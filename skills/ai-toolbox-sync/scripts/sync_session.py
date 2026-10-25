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
from contextlib import contextmanager
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
        if Path(resource["installedPath"]).resolve() == Path(__file__).resolve().parent.parent:
            raise ValueError("The manager uses public source maintenance, not private resource sync; review self-maintenance.md")
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


def collection_path(name):
    """Validate names before reading working files or Git blobs."""
    from sync_integrity import safe_relative
    if (not isinstance(name, str) or "\\" in name or safe_relative(name) != name
            or any(part.lower().startswith('.env') or part.lower() == '.git'
                   for part in Path(name).parts)
            or Path(name).suffix.lower() in {'.pem', '.pfx', '.p12', '.key'}
            or Path(name).name.lower() in {'id_rsa', 'id_ed25519', '.gitmodules', '.lfsconfig'}):
        raise ValueError('Sensitive or unsupported collection path')
    return name


def collection_git(repo, *args, input=None, env=None, accepted=(0,)):
    settings = dict(os.environ, GIT_TERMINAL_PROMPT='0', GCM_INTERACTIVE='Never')
    settings.update(env or {})
    hooks = Path(repo) / '.git' / 'toolbox-no-hooks'
    if hooks.exists():
        raise ValueError('Reserved empty hooks location must not contain user files')
    return git(repo, '-c', 'core.fsmonitor=false', '-c', 'core.hooksPath=' + str(hooks),
        '-c', 'push.followTags=false', '-c', 'remote.origin.mirror=false',
        '-c', 'submodule.recurse=false', '-c', 'rerere.enabled=false', *args,
        input=input, env=settings, timeout=30, accepted=accepted, return_result=True)


def collection_network(repo, *args):
    """Retry only transport failures, once, with the host's alternate route."""
    import re
    remote = args[1] if args[0] == 'ls-remote' else args[args.index('--') + 1]
    if Path(remote).is_absolute() or remote.startswith('file://'):
        return collection_git(repo, *args).stdout
    current = collection_git(repo, 'config', '--get-urlmatch', 'http.proxy', remote, accepted=(0, 1)).stdout.strip()
    current = current or os.environ.get('HTTPS_PROXY', '').encode()
    for attempt in range(2):
        route = () if attempt == 0 else ('-c', 'http.proxy=' + ('' if current else 'http://127.0.0.1:10808'))
        try:
            result = collection_git(repo, *route, *args, accepted=tuple(range(256)))
        except subprocess.TimeoutExpired:
            if attempt == 0:
                continue
            raise ValueError('Network timeout on both routes; synchronization remains pending')
        if result.returncode == 0:
            return result.stdout
        error = result.stderr.decode('utf-8', errors='replace')
        if re.search(r'(?i)(authentication|could not read username|cannot prompt|permission denied|repository not found|403|401)', error):
            raise ValueError('Repository authentication/permission failed; reuse an authorized credential helper')
        if attempt or not re.search(r'(?i)(resolve host|connect to|connection|timed out|timeout|SSL|TLS|recv failure|HTTP/2)', error):
            raise ValueError('Remote operation failed or result uncertain; inspect retained state before retry')
    raise ValueError('Remote operation did not finish')


def collection_tree(repo, revision):
    result = {}
    for entry in collection_git(repo, 'ls-tree', '-r', '-z', revision).stdout.split(b'\0'):
        if not entry:
            continue
        meta, raw_name = entry.split(b'\t', 1)
        mode, kind, oid = meta.decode('ascii').split()
        name = collection_path(raw_name.decode('utf-8'))
        if mode not in ('100644', '100755') or kind != 'blob':
            raise ValueError('Links/submodules require separate review')
        if name.casefold() in {p.casefold() for p in result}:
            raise ValueError('Case-colliding collection paths')
        result[name] = (mode, oid)
    return result


def collection_content(raw, private_paths=()):
    import re
    if re.search(rb'-----BEGIN (?:[A-Z]+ )?PRIVATE KEY-----|(?:gh[pousr]_|github_pat_)[A-Za-z0-9_]{20,}|AKIA[A-Z0-9]{16}|sk-(?:proj-)?[A-Za-z0-9_-]{32,}', raw):
        raise ValueError('Credential signature in proposed collection content')
    folded = raw.lower().replace(b'\\\\', b'\\').replace(b'/', b'\\')
    if any(str(p).encode('utf-8').lower().replace(b'/', b'\\') in folded for p in private_paths):
        raise ValueError('Machine-specific path in proposed collection content')


def collection_manifest(raw):
    from build_catalog import export
    from sync_integrity import safe_relative
    value = json.loads(raw.decode('utf-8-sig'))
    export(value)
    identities, paths = set(), []
    for item in value['resources']:
        identity = (item['kind'], item.get('sourceIdentity'))
        if not identity[1] or identity in identities:
            raise ValueError('Missing or duplicate stable source identity')
        identities.add(identity)
        if item.get('ownership') == 'self':
            name = collection_path(item['contentPath'])
            if safe_relative(name) != name or name == '.' or any(name == p or name.startswith(p + '/') or p.startswith(name + '/') for p in paths):
                raise ValueError('Overlapping resource paths')
            paths.append(name)
        elif item.get('contentPath'):
            raise ValueError('Third-party/unknown resource source must not enter the collection')
        if item.get('name') == 'ai-toolbox-sync' or item.get('contentPath') == 'skills/ai-toolbox-sync':
            raise ValueError('Manager maintenance belongs to its public source')
    return value


def collection_merge_manifest(base, ours, theirs, allow_remove):
    missing = object()

    def merge(b, o, t):
        if o == t or t == b:
            return o
        if o == b:
            return t
        if all(isinstance(v, dict) for v in (b, o, t)):
            result = {}
            for key in dict.fromkeys([*b, *o, *t]):
                value = merge(b.get(key, missing), o.get(key, missing), t.get(key, missing))
                if value is not missing:
                    result[key] = value
            return result
        raise ValueError('Manifest semantic conflict; preserve both versions')

    values = [json.loads(raw.decode('utf-8-sig')) for raw in (base, ours, theirs)]
    maps = [{r['id']: r for r in v['resources']} for v in values]
    if any(len(m) != len(v['resources']) for m, v in zip(maps, values)):
        raise ValueError('Duplicate resource identity')
    common = set(maps[0]) & set(maps[1]) & set(maps[2])
    orders = [[key for key in m if key in common] for m in maps]
    if orders[1] != orders[0] and orders[2] != orders[0] and orders[1] != orders[2]:
        raise ValueError('Both sides reordered existing resources differently')
    preferred = maps[2] if values[1] == values[0] or orders[1] == orders[0] != orders[2] else maps[1]
    rows = []
    for identity in dict.fromkeys([*preferred, *maps[1], *maps[2], *maps[0]]):
        b, o, t = (m.get(identity, missing) for m in maps)
        if b is not missing:
            for item in (o, t):
                if item is not missing and any(item.get(k) != b.get(k) for k in ('kind', 'sourceIdentity', 'ownership', 'contentPath', 'parentId')):
                    raise ValueError('Resource identity changed; explicit migration required')
        value = merge(b, o, t)
        if value is missing:
            if identity not in allow_remove:
                raise ValueError('Resource removal needs explicit approval: ' + identity)
        else:
            rows.append(value)
    roots = [{k: v for k, v in doc.items() if k != 'resources'} for doc in values]
    result = {**merge(*roots), 'resources': rows}
    raw = next((r for r, v in zip((ours, theirs, base), (values[1], values[2], values[0])) if v == result), None)
    raw = raw if raw is not None else (json.dumps(result, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
    collection_manifest(raw)
    return raw


@contextmanager
def collection_index(repo, root, revision):
    with tempfile.TemporaryDirectory(prefix='toolbox-index-', dir=root) as directory:
        env = {'GIT_INDEX_FILE': str(Path(directory) / 'index')}
        collection_git(repo, 'read-tree', revision, env=env)
        yield env


def collection_attributes(repo, names, revision=None):
    if not names:
        return
    args = ('--source=' + revision,) if revision else ()
    values = collection_git(repo, 'check-attr', '-z', *args, 'filter', 'working-tree-encoding',
                            'merge', '--', *sorted(names)).stdout.split(b'\0')
    for index in range(0, len(values) - 1, 3):
        attribute, value = values[index + 1:index + 3]
        permitted = {b'unspecified', b'unset'} | ({b'text', b'binary', b'set'} if attribute == b'merge' else set())
        if value not in permitted:
            raise ValueError('Custom filter/encoding/merge driver requires separate review')


def collection_status(binding_path):
    binding_path, journal = locate_binding(binding_path)
    identity, resources = load_binding(journal, binding_path)
    repo, remote, branch = identity
    if '://' in remote:
        from urllib.parse import urlsplit
        url = urlsplit(remote)
        if url.username or url.password or url.query or url.fragment:
            raise ValueError('Credential-bearing or ambiguous remote URL is forbidden')
    binding = json.loads(binding_path.read_text(encoding='utf-8-sig'))
    for flags in (('--all',), ('--push', '--all')):
        urls = collection_git(repo, 'remote', 'get-url', *flags, 'origin').stdout.decode().splitlines()
        if len(urls) != 1 or urls[0].removesuffix('.git') != remote.removesuffix('.git'):
            raise ValueError('Read/push URLs differ from the approved binding')
    manifest = collection_manifest((Path(repo) / 'toolbox.json').read_bytes())
    managed = {item['id']: item for item in manifest['resources']}
    state = json.loads(journal.read_text(encoding='utf-8')) if journal.exists() else {}
    result = dict(binding=str(binding_path), journal=str(journal), repo=repo, remote=remote, branch=branch,
                  head=collection_git(repo, 'rev-parse', 'HEAD').stdout.decode().strip(),
                  remoteVerification='not-queried', resources=[],
                  worktree=collection_git(repo, 'status', '--porcelain=v1', '--untracked-files=all').stdout.decode())
    for resource in resources.values():
        item = managed.get(resource['id'])
        source = Path(resource['sourcePath'])
        if not item or item.get('ownership') != 'self' or source.resolve() != (Path(repo) / item['contentPath']).resolve():
            raise ValueError('Manifest and approved resource binding differ')
        excluded = resource.get('runtimeExclusions', [])
        source_files = snapshot(source, excluded)
        installed_files = snapshot(resource['installedPath'], excluded, resource.get('expectedInstalledRoot'))
        source_digest, installed_digest = snapshot_digest(source_files), snapshot_digest(installed_files)
        baseline = state.get('baselines', {}).get(resource['id'], {})
        previous = state.get('collectionSync', {}).get('installations', {}).get(resource['id'], {})
        status = 'equal' if source_digest == installed_digest else (
            'installed-only' if baseline.get('sourceDigest') == source_digest else
            'source-only' if installed_digest in (baseline.get('installedDigest'), previous.get('installedDigest')) else 'drift-review')
        result['resources'].append(dict(id=resource['id'], sourceDigest=source_digest,
            installedDigest=installed_digest, status=status, sourceFiles=source_files))
    result['pendingGitIntent'] = bool(state.get('pending'))
    result['operations'] = binding['authorization'].get('operations', [])
    return result


def collection_plan(status, remote_tip, extra_paths=(), allow_delete=(), allow_remove=()):
    repo, head = status['repo'], status['head']
    _, resources = load_binding(Path(status['journal']), status['binding'])
    base = collection_git(repo, 'merge-base', head, remote_tip).stdout.decode().strip()
    head_tree, remote_tree, base_tree = (collection_tree(repo, r) for r in (head, remote_tip, base))
    prefixes = [Path(r['sourcePath']).resolve().relative_to(Path(repo)).as_posix() + '/' for r in resources.values()]
    exact = {'toolbox.json', 'README.md'} | {collection_path(n) for n in extra_paths}
    permitted_deletions = {collection_path(n) for n in allow_delete}
    changed = set(collection_git(repo, 'diff', '--no-ext-diff', '--name-only', '-z', head).stdout.decode().strip('\0').split('\0')) - {''}
    changed.update(filter(None, collection_git(repo, 'ls-files', '--others', '--exclude-standard', '-z').stdout.decode().split('\0')))
    overrides, collect = {}, []
    for item in status['resources']:
        resource = resources[item['id']]
        prefix = Path(resource['sourcePath']).resolve().relative_to(Path(repo)).as_posix()
        if item['status'] == 'drift-review':
            raise ValueError('Installation/source have no safe common baseline: ' + item['id'])
        if item['status'] == 'installed-only':
            from resource_files import prepare
            plan = prepare(resource['installedPath'], resource['sourcePath'], resource.get('runtimeExclusions', []))
            collect.append(dict(id=item['id'], plan=plan))
            for change in plan['changes']:
                name = prefix + '/' + change['path']
                changed.add(name)
                overrides[name] = None if change['after'] is None else Path(resource['installedPath']) / change['path']
        changed.update(prefix + '/' + name for name in item['sourceFiles'] if prefix + '/' + name not in head_tree)
    incoming = {n for n in base_tree.keys() | remote_tree.keys() if base_tree.get(n) != remote_tree.get(n)}
    outgoing = {n for n in base_tree.keys() | head_tree.keys() if base_tree.get(n) != head_tree.get(n)}
    for name in changed | incoming | outgoing:
        collection_path(name)
        working = overrides.get(name, Path(repo) / name)
        deleting = ((name in changed and (working is None or not working.exists()))
                    or name in incoming and name not in remote_tree or name in outgoing and name not in head_tree)
        if deleting and name not in permitted_deletions:
            raise ValueError('File deletion needs explicit approval: ' + name)
        if name not in exact and not any(name.startswith(p) for p in prefixes) and not (deleting and name in permitted_deletions):
            raise ValueError('Change outside selected collection scope: ' + name)
    names = set(head_tree) | set(remote_tree) | changed
    collection_attributes(repo, names)
    collection_attributes(repo, names, remote_tip)
    new_names = [n for n in sorted(changed) if n not in head_tree]
    if new_names and collection_git(repo, 'check-ignore', '--no-index', '-z', '--stdin',
            input=b'\0'.join(n.encode() for n in new_names) + b'\0', accepted=(0, 1)).stdout.strip(b'\0'):
        raise ValueError('Required source file is ignored; review its collection policy before syncing')
    private_paths = (Path.home(), Path(status['journal']).parent, Path(__file__).resolve().parent.parent)
    raw_hashes = {}
    with collection_index(repo, Path(status['journal']).parent, head) as env:
        for name in sorted(changed):
            path = overrides.get(name, Path(repo) / name)
            if path is None or not path.exists():
                collection_git(repo, '--literal-pathspecs', 'update-index', '--force-remove', '--', name, env=env)
                raw_hashes[name] = None
                continue
            if any(linked(p) for p in (path, *path.parents)) or not path.is_file():
                raise ValueError('Linked/nonregular working file')
            raw = path.read_bytes()
            collection_content(raw, private_paths)
            raw_hashes[name] = hashlib.sha256(raw).hexdigest()
            oid = collection_git(repo, 'hash-object', '-w', '--path=' + name, '--stdin', input=raw).stdout.decode().strip()
            collection_git(repo, '--literal-pathspecs', 'update-index', '--add', '--cacheinfo',
                head_tree.get(name, ('100644',))[0], oid, name, env=env)
        local_tree = collection_git(repo, 'write-tree', env=env).stdout.decode().strip()
    for revision in collection_git(repo, 'rev-list', head + '...' + remote_tip).stdout.decode().splitlines():
        tree = collection_tree(repo, revision)
        collection_attributes(repo, set(tree), revision)
        collection_manifest(collection_git(repo, 'show', revision + ':toolbox.json').stdout)
        for name in collection_git(repo, 'diff-tree', '--root', '-m', '--no-commit-id', '--name-only', '-r', revision).stdout.decode().splitlines():
            collection_path(name)
            if name not in exact and not any(name.startswith(p) for p in prefixes) and not (name not in tree and name in permitted_deletions):
                raise ValueError('Unreviewed file in pending Git history: ' + name)
            if name in tree:
                collection_content(collection_git(repo, 'cat-file', 'blob', tree[name][1]).stdout, private_paths)
    result = collection_git(repo, 'merge-tree', '--write-tree', '--name-only', '-z',
        '--merge-base=' + base, local_tree, remote_tip, accepted=(0, 1))
    parts = result.stdout.split(b'\0')
    merged_tree = parts[0].decode().strip()
    conflicts = []
    if result.returncode:
        for name in parts[1:]:
            if not name:
                break
            conflicts.append(collection_path(name.decode()))
    def blob(tree, name):
        return collection_git(repo, 'show', tree + ':' + name).stdout
    merged_manifest = collection_merge_manifest(blob(base, 'toolbox.json'), blob(local_tree, 'toolbox.json'),
                                              blob(remote_tip, 'toolbox.json'), set(allow_remove))
    conflicts = [n for n in conflicts if n != 'toolbox.json']
    if not conflicts:
        with collection_index(repo, Path(status['journal']).parent, merged_tree) as env:
            oid = collection_git(repo, 'hash-object', '-w', '--path=toolbox.json', '--stdin', input=merged_manifest).stdout.decode().strip()
            collection_git(repo, 'update-index', '--cacheinfo', '100644', oid, 'toolbox.json', env=env)
            merged_tree = collection_git(repo, 'write-tree', env=env).stdout.decode().strip()
        merged = collection_tree(repo, merged_tree)
        for name in merged:
            collection_content(blob(merged_tree, name), private_paths)
    return dict(head=head, remoteTip=remote_tip, base=base, localTree=local_tree, mergedTree=merged_tree,
        localChanges=sorted(changed | outgoing), remoteChanges=sorted(incoming), conflicts=conflicts,
        workingHashes=raw_hashes, collect=collect, manifest=merged_manifest.decode('utf-8-sig'))


def collection_sync(binding_path=None, *, dry_run=False, extra_paths=(), allow_delete=(), allow_remove=(), owner=None):
    owner = owner or 'collection-sync-' + uuid.uuid4().hex
    binding_path, journal = locate_binding(binding_path)
    begin = operate(journal, dict(operation='begin', owner=owner, binding=str(binding_path)))
    run_path = None
    try:
        if begin['pending']:
            raise ValueError('Reconcile the existing Git intent before collection sync')
        status = collection_status(binding_path)
        repo, remote, branch = status['repo'], status['remote'], status['branch']
        if not dry_run and not {'commit', 'push', 'pull'} <= set(status['operations']):
            raise ValueError('Binding does not authorize this collection sync')
        if collection_git(repo, 'diff', '--cached', '--name-only').stdout.strip():
            raise ValueError('Existing staged files require separate review')
        if collection_git(repo, 'ls-files', '--unmerged').stdout.strip() or (Path(repo) / '.git' / 'MERGE_HEAD').exists():
            raise ValueError('An existing merge must be resolved first')
        def probe():
            lines = collection_network(repo, 'ls-remote', remote, 'refs/heads/' + branch).decode().splitlines()
            matches = [line.split()[0] for line in lines if line.split()[1] == 'refs/heads/' + branch]
            if len(matches) != 1 or len(matches[0]) not in (40, 64):
                raise ValueError('Authorized remote branch missing or ambiguous')
            return matches[0]
        tip = probe()
        collection_network(repo, 'fetch', '--no-tags', '--no-write-fetch-head', '--', remote, 'refs/heads/' + branch)
        if probe() != tip:
            raise ValueError('Remote changed during fetch; compare again')
        plan = collection_plan(status, tip, extra_paths, allow_delete, allow_remove)
        if dry_run or plan['conflicts']:
            return dict(status='conflict-review' if plan['conflicts'] else 'planned', dryRun=dry_run,
                head=plan['head'], remoteTip=tip, localChanges=plan['localChanges'],
                remoteChanges=plan['remoteChanges'], conflicts=plan['conflicts'], resources=status['resources'])
        run_dir = journal.parent / 'sync-runs'
        from resource_files import location, apply, atomic
        location(run_dir)
        if any((p / '.git').exists() for p in (run_dir, *run_dir.parents)):
            raise ValueError('Sync receipts must stay outside Git repositories')
        run_dir.mkdir(exist_ok=True)
        run_path = run_dir / (uuid.uuid4().hex + '.json')
        receipt = dict(schemaVersion=1, owner=owner, phase='prepared', plan=plan)
        def save(phase, **fields):
            receipt.update(phase=phase, **fields)
            atomic_json(run_path, receipt)
        save('prepared')
        for entry in plan['collect']:
            apply(entry['plan'], run_dir / (uuid.uuid4().hex + '.json'), run_dir / uuid.uuid4().hex,
                  allow_delete=all(Path(entry['plan']['target']).resolve().relative_to(repo).as_posix() + '/' + c['path'] in allow_delete
                                   for c in entry['plan']['changes'] if c['after'] is None))
        checked = collection_plan(collection_status(binding_path), tip, extra_paths, allow_delete, allow_remove)
        if checked['localTree'] != plan['localTree'] or checked['mergedTree'] != plan['mergedTree']:
            raise ValueError('Files changed after planning; nothing committed')
        if plan['localTree'] != collection_git(repo, 'rev-parse', 'HEAD^{tree}').stdout.decode().strip():
            names = sorted(set(plan['localChanges']) & set(plan['workingHashes']))
            collection_git(repo, '--literal-pathspecs', 'add', '--', *names)
            if collection_git(repo, 'write-tree').stdout.decode().strip() != plan['localTree']:
                raise ValueError('Actual index differs from the approved plan')
            save('committing')
            collection_git(repo, 'commit', '-m', 'Sync selected toolbox collection')
        head = collection_git(repo, 'rev-parse', 'HEAD').stdout.decode().strip()
        save('local-saved', head=head)
        if head != tip and collection_git(repo, 'merge-base', head, tip).stdout.decode().strip() != tip:
            save('merging')
            if plan['mergedTree'] == collection_git(repo, 'rev-parse', tip + '^{tree}').stdout.decode().strip():
                collection_git(repo, '-c', 'merge.autoStash=false', 'merge', '--ff-only', '--no-overwrite-ignore', tip)
            else:
                result = collection_git(repo, '-c', 'merge.autoStash=false', 'merge', '--no-commit', '--no-ff', '--no-overwrite-ignore', tip, accepted=(0, 1))
                unmerged = collection_git(repo, 'diff', '--name-only', '--diff-filter=U').stdout.decode().splitlines()
                if any(n != 'toolbox.json' for n in unmerged):
                    raise ValueError('Unexpected merge conflict retained; inspect before continuing')
                atomic(Path(repo) / 'toolbox.json', plan['manifest'].encode('utf-8'))
                collection_git(repo, '--literal-pathspecs', 'add', '--', 'toolbox.json')
                if collection_git(repo, 'write-tree').stdout.decode().strip() != plan['mergedTree']:
                    raise ValueError('Merge result differs from the reviewed tree')
                collection_git(repo, 'commit', '--no-edit')
        head = collection_git(repo, 'rev-parse', 'HEAD').stdout.decode().strip()
        if collection_git(repo, 'rev-parse', 'HEAD^{tree}').stdout.decode().strip() != plan['mergedTree']:
            raise ValueError('Final commit differs from the planned merge')
        final = collection_status(binding_path)
        if final['worktree'].strip():
            raise ValueError('Working files changed during sync; retained local commits')
        for item in final['resources']:
            before = next(r for r in status['resources'] if r['id'] == item['id'])
            if item['status'] == 'drift-review' and item['installedDigest'] == before['installedDigest']:
                item['status'] = 'source-only'
        audited = collection_plan(final, tip, extra_paths, allow_delete, allow_remove)
        if audited['conflicts'] or audited['mergedTree'] != plan['mergedTree']:
            raise ValueError('Outgoing history changed during synchronization')
        for resource in load_binding(journal, binding_path)[1].values():
            verify_commit(repo, resource['sourcePath'], head, resource.get('runtimeExclusions', []))
        if probe() != tip:
            save('remote-advanced', head=head)
            return dict(status='remote-advanced', head=head, receipt=str(run_path), retry='sync again to compare and merge; local commits retained')
        save('push-pending', head=head, remoteTip=tip)
        if head != tip:
            collection_network(repo, 'push', '--', remote, head + ':refs/heads/' + branch)
        verified_tip = probe()
        if verified_tip != head:
            raise ValueError('Remote result changed; retain receipt and verify ancestry before retry')
        final = collection_status(binding_path)
        if final['head'] != head or final['worktree'].strip():
            raise ValueError('Local state changed after upload; only the fixed commit was uploaded')
        for item in final['resources']:
            before = next(r for r in status['resources'] if r['id'] == item['id'])
            if item['status'] != 'equal' and item['installedDigest'] == before['installedDigest']:
                item['status'] = 'source-only'
        installations = {r['id']: {k: r[k] for k in ('sourceDigest', 'installedDigest', 'status')} for r in final['resources']}
        state = json.loads(journal.read_text(encoding='utf-8'))
        state['collectionSync'] = dict(head=head, remoteTip=verified_tip, checkedAt=time.time(),
                                      receipt=str(run_path), installations=installations)
        state['remoteObservation'] = dict(status='live', head=verified_tip, checkedAt=time.time(),
            sessionId=state['session']['id'], identity=state['session']['identity'], endPush=True)
        atomic_json(journal, state)
        for item in final['resources']:
            if item['status'] == 'equal':
                observation = dict(resourceId=item['id'], sourceDigest=item['sourceDigest'],
                    installedDigest=item['installedDigest'], head=head, remoteTip=verified_tip,
                    localPaths=[], remotePaths=[], remoteAvailable=True, scopeReviewed=True, inUse=True)
                operate(journal, dict(operation='observe', owner=owner, observation=observation))
                operate(journal, dict(operation='confirm', owner=owner))
        save('verified', head=head, remoteTip=verified_tip, installations=installations)
        return dict(status='synced', head=head, remoteTip=verified_tip, receipt=str(run_path),
                    installations=installations, pendingWorkPreserved=True)
    finally:
        operate(journal, dict(operation='release', owner=owner, binding=str(binding_path)))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', nargs='?', choices=('status', 'sync'))
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--paths', nargs='*', default=[])
    parser.add_argument('--allow-delete', nargs='*', default=[])
    parser.add_argument('--allow-remove', nargs='*', default=[])
    parser.add_argument("--state", type=Path)
    parser.add_argument("--request", type=Path)
    parser.add_argument("--binding", type=Path)
    parser.add_argument("--locate", action="store_true")
    args = parser.parse_args()
    if args.command:
        if args.request or args.state or args.locate or args.command == 'status' and (args.dry_run or args.paths or args.allow_delete or args.allow_remove):
            parser.error('Do not combine collection commands and legacy journal requests')
        try:
            result = collection_status(args.binding) if args.command == 'status' else collection_sync(
                args.binding, dry_run=args.dry_run, extra_paths=args.paths,
                allow_delete=args.allow_delete, allow_remove=args.allow_remove)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result.get('status', 'status') not in ('conflict-review', 'remote-advanced') else 2
        except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as exc:
            print(json.dumps(dict(status='stopped', error=str(exc) if isinstance(exc, ValueError) else type(exc).__name__,
                                  recovery='Local files, commits and sync-runs receipts are retained; inspect before retry'), ensure_ascii=False))
            return 1
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
