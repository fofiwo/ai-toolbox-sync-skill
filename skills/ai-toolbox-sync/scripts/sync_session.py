"""Cooperative sync journal and read-only remote probe; no Git mutations or installation."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import tempfile
import subprocess
import time
import uuid
from sync_integrity import snapshot, digest as snapshot_digest, verify_commit, verify_file, git, linked


def remote_probe(repo, remote, branch, cache=None, *, strict=False, force=False,
                 dirty=False, pending=False, end_push=False, known_tip=None, now=None, query=None):
    now = time.time() if now is None else now
    if not isinstance(remote, str) or not (Path(remote).is_absolute() or "://" in remote or remote.startswith("git@")):
        raise ValueError("Use the verified actual remote URL, not a mutable alias")
    identity = [str(Path(repo).resolve()), remote, branch]
    cache = cache if isinstance(cache, dict) else {}
    fetched = cache.get("checkedAt")
    expires = cache.get("cache_expire_at")
    valid = (cache.get("identity") == identity and type(fetched) in (int, float)
             and type(expires) in (int, float) and fetched <= now < expires
             and 0 < expires - fetched <= 86400
             and isinstance(cache.get("remote_head_cached"), str)
             and len(cache["remote_head_cached"]) in (40, 64)
             and all(c in "0123456789abcdef" for c in cache["remote_head_cached"]))
    if valid and not (strict or force or dirty or pending or end_push):
        return {"status": "cached-not-live", "head": cache["remote_head_cached"], "fetchRequired": known_tip != cache["remote_head_cached"], "cache": cache}
    try:
        if query is None:
            # Windows 默认继承会丢失空的 Git helper 重置项，显式传环境保留它。
            lines = git(repo, "ls-remote", remote, "refs/heads/" + branch, timeout=20).decode().splitlines()
            matches = [line.split()[0] for line in lines if len(line.split()) == 2 and line.split()[1] == "refs/heads/" + branch]
            if len(matches) != 1:
                raise ValueError("Branch missing or ambiguous")
            head = matches[0]
        else:
            head = query()
        if len(head) not in (40, 64) or any(c not in "0123456789abcdef" for c in head):
            raise ValueError("Invalid remote revision")
    except (OSError, ValueError, subprocess.SubprocessError):
        return {"status": "network-pending", "head": "unknown", "fetchRequired": False, "cache": cache}
    updated = {"identity": identity, "remote_head_cached": head, "checkedAt": now, "cache_expire_at": now + 86400}
    return {"status": "live", "head": head, "fetchRequired": known_tip != head, "cache": updated}


def atomic_json(path, value):
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write((json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def fingerprint(root, excluded=(), expected_root=None):
    return snapshot_digest(snapshot(root, excluded, expected_root))


def require_live(state, observation, end_push=False):
    probe = state.get("remoteObservation", {})
    session = state.get("session", {})
    checked = probe.get("checkedAt")
    if (not session.get("id") or probe.get("sessionId") != session["id"]
            or probe.get("identity") != session.get("identity")
            or probe.get("status") != "live" or probe.get("head") != observation.get("remoteTip")
            or type(checked) not in (int, float) or not 0 <= time.time() - checked <= 300
            or (end_push and probe.get("endPush") is not True)):
        raise ValueError("Fresh live evidence from this repository session is required")


def require_integrity(state, observation):
    proof = state.get("integrity", {})
    if (proof.get("sessionId") != state.get("session", {}).get("id")
            or proof.get("resourceId") != observation.get("resourceId")
            or proof.get("head") != observation.get("head")
            or proof.get("sourceDigest") != observation.get("sourceDigest")
            or proof.get("installedDigest") != observation.get("installedDigest")
            or not isinstance(proof.get("files"), dict)):
        raise ValueError("Verified commit coverage and current installed content are required")


def classify(observation):
    local = set(observation["localPaths"])
    remote = set(observation["remotePaths"])
    if observation["installedDigest"] != observation["sourceDigest"]:
        return "installed-drift"
    if not observation["remoteAvailable"]:
        return "network-pending"
    if not observation["scopeReviewed"]:
        return "scope-blocked"
    if remote and observation["inUse"]:
        return "application-deferred"
    if local & remote:
        return "conflict-review"
    if local and remote:
        return "mergeable"
    if remote:
        return "remote-only"
    if local:
        return "local-only"
    return "unchanged"


def validate_observation(value):
    required = {"resourceId", "sourceDigest", "installedDigest", "remoteTip", "head", "localPaths", "remotePaths", "remoteAvailable", "scopeReviewed", "inUse"}
    if not isinstance(value, dict) or set(value) != required:
        raise ValueError("Observation fields do not match contract")
    if not isinstance(value["resourceId"], str) or not value["resourceId"]:
        raise ValueError("Missing stable identity")
    for key in ("sourceDigest", "installedDigest", "remoteTip", "head"):
        v = value[key]
        if not isinstance(v, str) or (v != "unknown" and (len(v) not in (40, 64) or any(c not in "0123456789abcdef" for c in v))):
            raise ValueError("Invalid digest or revision")
    for key in ("localPaths", "remotePaths"):
        if not isinstance(value[key], list) or any(not isinstance(p, str) or not p or Path(p).is_absolute() or ".." in Path(p).parts for p in value[key]):
            raise ValueError("Invalid changed paths")
    for key in ("remoteAvailable", "scopeReviewed", "inUse"):
        if type(value[key]) is not bool:
            raise ValueError("Invalid observation flag")
    if value["sourceDigest"] == "unknown" or value["installedDigest"] == "unknown":
        raise ValueError("Missing content evidence")
    if value["remoteAvailable"] and (value["remoteTip"] == "unknown" or value["head"] == "unknown"):
        raise ValueError("Missing remote evidence")


def transition(state, request):
    operation = request["operation"]
    if operation in ("intent", "application", "resolve", "confirm") and not (operation == "intent" and request.get("action") == "collect"):
        evidence = request.get("observation", state.get("observation", {}))
        require_live(state, evidence, end_push=operation == "intent" and request.get("action") == "push")
    if operation == "confirm" or (operation == "intent" and request.get("action") == "push"):
        require_integrity(state, state.get("observation", {}))
    if operation == "observe":
        observation = request["observation"]
        validate_observation(observation)
        if observation["remoteAvailable"]:
            require_live(state, observation)
        if state.get("pending") and state["observation"]["resourceId"] != observation["resourceId"]:
            raise ValueError("Reconcile the original resource first")
        key = hashlib.sha256(json.dumps(observation, sort_keys=True).encode()).hexdigest()
        status = classify(observation)
        baseline = state.get("baselines", {}).get(observation["resourceId"], state.get("baseline", {}))
        if (status == "installed-drift" and baseline.get("resourceId") == observation["resourceId"]
                and baseline.get("sourceDigest") == observation["sourceDigest"]):
            status = "installed-only"
        elif (status == "installed-drift" and baseline.get("resourceId") == observation["resourceId"]
                and baseline.get("installedDigest") == observation["installedDigest"]):
            status = "application-deferred" if observation["inUse"] else "source-only"
        state["observation"] = observation
        state["key"] = key
        if state.get("pending"):
            status = "reconcile-required"
        elif status == "unchanged" and state.get("confirmedKeys", {}).get(observation["resourceId"], state.get("confirmedKey")) == key:
            status = "duplicate"
        state["status"] = status
    elif operation == "intent":
        action = request["action"]
        if state.get("pending") or action not in ("pull", "push", "merge", "collect", "apply"):
            raise ValueError("Pending operation or invalid action")
        allowed = {"pull": {"remote-only"}, "merge": {"mergeable"}, "push": {"local-only"}, "collect": {"installed-only"}, "apply": {"source-only"}}
        if state.get("status") not in allowed[action]:
            raise ValueError("Observation does not permit this intent")
        if not state["observation"]["scopeReviewed"] or (action != "collect" and not state["observation"]["remoteAvailable"]):
            raise ValueError("Scope review and live remote evidence required")
        if state["observation"]["head"] != request["head"]:
            raise ValueError("HEAD changed; inspect again before intent")
        state["pending"] = {"action": action, "head": request["head"], "remoteTip": state["observation"]["remoteTip"], "key": state["key"]}
        state["status"] = "pending"
    elif operation == "application":
        pending = state.get("pending", {})
        observation = request["observation"]
        validate_observation(observation)
        baseline = state.get("baselines", {}).get(observation["resourceId"], state.get("baseline", {}))
        if (pending.get("action") != "pull" or observation["resourceId"] != state["observation"]["resourceId"]
                or not observation["remoteAvailable"] or not observation["scopeReviewed"] or observation["inUse"]
                or baseline.get("installedDigest") != observation["installedDigest"]
                or observation["head"] != observation["remoteTip"] or observation["remoteTip"] != pending["remoteTip"]
                or observation["localPaths"] or observation["remotePaths"] or request.get("previousCommandFinished") is not True):
            raise ValueError("Pull application requires a safe unchanged host and verified completed pull")
        pending["stage"] = "apply"
        state["observation"] = observation
        state["status"] = "application-ready"
    elif operation == "resolve":
        # A failed/unknown CLI result is never evidence that a push did not happen.
        pending = state.get("pending")
        if not pending:
            raise ValueError("No operation to reconcile")
        observation = request["observation"]
        validate_observation(observation)
        if not observation["remoteAvailable"] or not observation["scopeReviewed"]:
            raise ValueError("Fresh remote and scope evidence required")
        if observation["resourceId"] != state["observation"]["resourceId"]:
            raise ValueError("Resource identity changed")
        if (pending["action"] in ("merge", "collect", "apply") and request.get("previousCommandFinished") is True
                and request.get("applicationVerified") is True and classify(observation) == "local-only"):
            state.pop("pending")
            transition(state, {"operation": "observe", "observation": observation})
            return state
        if pending["action"] == "push" and observation["remoteTip"] != pending["head"]:
            if (observation["remoteTip"] == pending["remoteTip"] and observation["head"] == pending["head"]
                    and request.get("previousCommandFinished") is True and classify(observation) == "local-only"):
                state.pop("pending")
                transition(state, {"operation": "observe", "observation": observation})
                return state
            raise ValueError("Remote is not the intended commit; retain pending for explicit review")
        if classify(observation) != "unchanged" or observation["head"] != observation["remoteTip"]:
            raise ValueError("Synchronization not yet verified")
        require_integrity(state, observation)
        state.pop("pending")
        transition(state, {"operation": "observe", "observation": observation})
        state["confirmedKey"] = state["key"]
        state["status"] = "confirmed"
        state.setdefault("baselines", {})[observation["resourceId"]] = {k: observation[k] for k in ("resourceId", "sourceDigest", "installedDigest")}
        state.setdefault("confirmedKeys", {})[observation["resourceId"]] = state["key"]
    elif operation == "confirm":
        if state.get("pending") or state.get("status") not in ("unchanged", "duplicate"):
            raise ValueError("Cannot confirm unverified work")
        if state["observation"]["head"] != state["observation"]["remoteTip"]:
            raise ValueError("Local and remote revisions differ")
        state["confirmedKey"] = state["key"]
        state["status"] = "confirmed"
        observation = state["observation"]
        state.setdefault("baselines", {})[observation["resourceId"]] = {k: observation[k] for k in ("resourceId", "sourceDigest", "installedDigest")}
        state.setdefault("confirmedKeys", {})[observation["resourceId"]] = state["key"]
    else:
        raise ValueError("Unknown journal operation")
    return state


def load_binding(path, binding_path):
    binding_path = Path(binding_path)
    if binding_path.suffix != ".json" or binding_path.name.lower().startswith(".env") or linked(binding_path):
        raise ValueError("Expected non-sensitive local binding JSON")
    binding = json.loads(binding_path.read_text(encoding="utf-8-sig"))
    task = binding["taskSync"]
    repo = Path(binding["paths"]["gitRoot"]).resolve()
    if not task.get("enabled") or Path(task["journalPath"]).resolve() != path.resolve():
        raise ValueError("Journal must match enabled binding")
    if Path(git(repo, "rev-parse", "--show-toplevel").decode().strip()).resolve() != repo:
        raise ValueError("Binding is not the actual Git root")
    remote = git(repo, "remote", "get-url", "origin").decode().strip()
    authorization = binding["authorization"]
    if authorization.get("status") != "granted" or remote.removesuffix(".git") != authorization["repository"].removesuffix(".git"):
        raise ValueError("Remote differs from authorized binding")
    branch = authorization["branch"]
    if git(repo, "branch", "--show-current").decode().strip() != branch:
        raise ValueError("Branch differs from binding")
    resources = {}
    for resource in task["resources"]:
        if resource["id"] not in authorization["resourceIds"] or resource["id"] in resources:
            raise ValueError("Unknown or duplicate resource binding")
        Path(resource["sourcePath"]).resolve().relative_to(repo)
        resources[resource["id"]] = resource
    return [str(repo), remote, branch], resources


def locate_binding(explicit=None):
    if explicit:
        binding_path = Path(explicit)
    else:
        pointer = Path.home() / ".agents/ai-toolbox-sync/binding-pointer.json"
        if linked(pointer):
            raise ValueError("Binding pointer must be a regular local file")
        value = json.loads(pointer.read_text(encoding="utf-8"))
        if value.get("schemaVersion") != 1:
            raise ValueError("Unknown binding pointer schema")
        binding_path = Path(value["bindingPath"])
        if not binding_path.is_absolute():
            raise ValueError("Binding pointer must use an absolute local path")
    if linked(binding_path) or binding_path.suffix != ".json" or binding_path.name.lower().startswith(".env"):
        raise ValueError("Expected non-sensitive local binding JSON")
    binding = json.loads(binding_path.read_text(encoding="utf-8-sig"))
    journal = Path(binding["taskSync"]["journalPath"])
    load_binding(journal, binding_path)
    return binding_path, journal


def check_integrity(state, observation):
    validate_observation(observation)
    resource = state["session"]["resources"][observation["resourceId"]]
    source, installed = Path(resource["sourcePath"]), Path(resource["installedPath"])
    excluded = resource.get("runtimeExclusions", [])
    repo = state["session"]["identity"][0]
    if resource.get("kind") == "agent-document":
        import agent_documents as documents
        binding_path = documents.regular(resource["documentBindingPath"], ".json")
        raw_binding = binding_path.read_bytes()
        binding = json.loads(raw_binding)
        bound_source, bound_target = documents.paths(binding, binding_path)
        if (bound_source.resolve() != source.resolve() or bound_target.resolve() != installed.resolve()
                or Path(binding["gitRoot"]).resolve() != Path(repo).resolve()
                or resource["id"] != "agent-document:" + binding["documentId"]
                or binding.get("pending") or excluded):
            raise ValueError("Document binding differs or has unfinished local operation")
        bundle = verify_file(repo, source, observation["head"])
        doc = documents.validate(json.loads(bundle))
        documents.identity(binding, doc)
        actual = installed.read_bytes()
        proof = dict(head=observation["head"], sourceDigest=doc["sha256"],
                     installedDigest=hashlib.sha256(actual).hexdigest(), fileCount=1,
                     files={source.relative_to(repo).as_posix(): hashlib.sha256(bundle).hexdigest()})
        if source.read_bytes() != bundle or installed.read_bytes() != actual or binding_path.read_bytes() != raw_binding:
            raise ValueError("Document evidence changed during verification")
    else:
        proof = verify_commit(repo, source, observation["head"], excluded)
        proof["installedDigest"] = fingerprint(installed, excluded, resource.get("expectedInstalledRoot"))
    if proof["sourceDigest"] != observation["sourceDigest"] or proof["installedDigest"] != observation["installedDigest"]:
        raise ValueError("Observation no longer matches real files")
    proof.update(resourceId=observation["resourceId"], sessionId=state["session"]["id"])
    state["integrity"] = proof


def operate(path, request):
    path = Path(path)
    if path.suffix != ".json" or path.name.lower().startswith(".env") or linked(path):
        raise ValueError("Expected local regular JSON journal")
    owner = request.get("owner")
    if not isinstance(owner, str) or not owner.strip() or len(owner) > 200:
        raise ValueError("Explicit task owner required")
    lock = path.with_suffix(".flow.lock")
    operation = request["operation"]
    if operation == "release":
        # 释放只依赖锁身份，损坏的业务日志必须原样保留。
        if lock.exists():
            held = json.loads(lock.read_text(encoding="utf-8"))
        else:
            if not request.get("binding"):
                raise ValueError("Repository-only lock recovery requires explicit binding")
            identity, _ = load_binding(path, request["binding"])
            common = git(identity[0], "rev-parse", "--path-format=absolute", "--git-common-dir").decode().strip()
            held = json.loads((Path(common) / "ai-toolbox-sync.flow.lock").read_text(encoding="utf-8"))
            if held.get("journal") != str(path.resolve()):
                raise ValueError("Repository lock belongs to another journal")
        if held.get("owner") != owner:
            raise ValueError("Lock belongs to another task")
        if held.get("repoLock"):
            repo_lock = Path(held["repoLock"])
            if repo_lock.exists():
                if json.loads(repo_lock.read_text(encoding="utf-8")) != held:
                    raise ValueError("Repository lock identity changed")
                repo_lock.unlink()
        lock.unlink(missing_ok=True)
        return {"released": True}
    state = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"schemaVersion": 1}
    if not isinstance(state, dict) or state.get("schemaVersion") != 1:
        raise ValueError("Unknown journal schema")
    if operation == "begin":
        binding_path = request.get("binding", state.get("bindingPath"))
        if not binding_path:
            raise ValueError("First begin requires the verified local binding path")
        identity, resources = load_binding(path, binding_path)
        common = git(identity[0], "rev-parse", "--path-format=absolute", "--git-common-dir").decode().strip()
        repo_lock = Path(common) / "ai-toolbox-sync.flow.lock"
        acquired = []
        session_id = uuid.uuid4().hex
        try:
            for candidate in (repo_lock, lock):
                fd = os.open(candidate, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                acquired.append(candidate)
                with os.fdopen(fd, "w", encoding="utf-8") as stream:
                    json.dump({"owner": owner, "sessionId": session_id, "journal": str(path.resolve()), "repoLock": str(repo_lock)}, stream)
                    stream.flush()
                    os.fsync(stream.fileno())
            state = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"schemaVersion": 1}
            if not isinstance(state, dict) or state.get("schemaVersion") != 1:
                raise ValueError("Unknown journal schema")
            # 保留旧 pending/基线；成功状态与 live 证据不能继承到新事务。
            state["bindingPath"] = str(Path(binding_path).resolve())
            state["session"] = dict(id=session_id, identity=identity, resources=resources, owner=owner)
            state.pop("remoteObservation", None)
            state.pop("integrity", None)
            state["status"] = "reconcile-required" if state.get("pending") else "inspection-required"
            atomic_json(path, state)
            return {"locked": True, "pending": bool(state.get("pending")), "workItems": state.get("workItems", {})}
        except BaseException:
            for candidate in reversed(acquired):
                candidate.unlink(missing_ok=True)
            raise
    held = json.loads(lock.read_text(encoding="utf-8"))
    if held["owner"] != owner:
        raise ValueError("Lock belongs to another task")
    if not held.get("repoLock") or json.loads(Path(held["repoLock"]).read_text(encoding="utf-8")) != held:
        raise ValueError("Repository lock identity changed")
    if held.get("sessionId") != state.get("session", {}).get("id"):
        raise ValueError("Start a new bound session before using the upgraded protocol")
    current_identity, current_resources = load_binding(path, state["bindingPath"])
    if current_identity != state["session"]["identity"] or current_resources != state["session"]["resources"]:
        raise ValueError("Binding changed; release and inspect again")
    if operation == "mark-dirty":
        resource_id = request["resourceId"]
        if resource_id not in state["session"]["resources"]:
            raise ValueError("Resource outside binding")
        state.setdefault("workItems", {}).setdefault(owner, {})[resource_id] = dict(status="pending", markedAt=time.time())
        state["status"] = "work-pending"
        atomic_json(path, state)
        return {"saved": True, "status": "work-pending"}
    if operation == "probe":
        if any(type(request.get(key, False)) is not bool for key in ("strict", "force", "dirty", "endPush")):
            raise ValueError("Probe flags must be boolean")
        identity = [str(Path(request["repo"]).resolve()), request["remote"], request["branch"]]
        if identity != state["session"]["identity"]:
            raise ValueError("Probe differs from bound session")
        result = remote_probe(*identity, state.get("remoteCache"),
                              strict=request.get("strict", False), force=request.get("force", False),
                              dirty=request.get("dirty", False), pending=bool(state.get("pending")) or any(
                                  item.get("status") == "pending" for items in state.get("workItems", {}).values() for item in items.values()),
                              end_push=request.get("endPush", False), known_tip=request.get("knownTip"))
        state["remoteCache"] = result.pop("cache")
        result.update(sessionId=state["session"]["id"], identity=identity,
                      checkedAt=state["remoteCache"].get("checkedAt"), endPush=request.get("endPush", False))
        state["remoteObservation"] = result
        atomic_json(path, state)
        return result
    if operation == "complete-work":
        work_owner = request.get("workOwner", owner)
        observation = state.get("observation", {})
        if state.get("status") != "confirmed" or state.get("pending") or request.get("previousCommandFinished") is not True:
            raise ValueError("Work can finish only after verified synchronization and command completion")
        require_live(state, observation)
        check_integrity(state, observation)
        require_live(state, observation)
        item = state["workItems"][work_owner][observation["resourceId"]]
        item.update(status="complete", completedAt=time.time(), head=observation["head"])
        atomic_json(path, state)
        return {"saved": True, "status": "complete"}
    observation = request.get("observation", state.get("observation", {}))
    if observation.get("resourceId") not in state["session"]["resources"]:
        raise ValueError("Observation resource is outside the verified binding")
    if operation == "verify" or operation == "confirm" or (operation == "intent" and request.get("action") == "push") or (operation == "resolve" and classify(observation) == "unchanged"):
        check_integrity(state, observation)
    if operation == "verify":
        atomic_json(path, state)
        return {"saved": True, "fileCount": state["integrity"]["fileCount"]}
    result = transition(state, request)
    atomic_json(path, result)
    return {"saved": True, "status": result["status"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", type=Path)
    parser.add_argument("--request", type=Path)
    parser.add_argument("--binding", type=Path)
    parser.add_argument("--locate", action="store_true")
    args = parser.parse_args()
    if not args.locate and (not args.request or args.request.suffix != ".json" or args.request.name.lower().startswith(".env") or args.request.is_symlink()):
        parser.error("Expected regular JSON request")
    try:
        if args.locate or not args.state or args.binding:
            binding_path, journal = locate_binding(args.binding)
            if args.state and args.state.resolve() != journal.resolve():
                raise ValueError("Explicit journal differs from binding")
            args.state = journal
            if args.locate:
                print(json.dumps(dict(bindingPath=str(binding_path), journalPath=str(journal))))
                return 0
        request = json.loads(args.request.read_text(encoding="utf-8"))
        if request.get("operation") in ("begin", "release") and (args.binding or 'binding_path' in locals()):
            request["binding"] = str(binding_path)
        print(json.dumps(operate(args.state, request), ensure_ascii=False))
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        print('{"saved":false,"error":"锁、输入或状态不满足条件；保留现场并核实，不盲重试"}')
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
