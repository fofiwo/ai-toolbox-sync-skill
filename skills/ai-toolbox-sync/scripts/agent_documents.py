"""Whole-document snapshots and exact local bindings. Git transport stays with Skillshare."""
import argparse
import copy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import uuid
from sync_integrity import git


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def identifier(value):
    if not isinstance(value, str) or str(uuid.UUID(value)) != value:
        raise ValueError("Expected canonical UUID")
    return value


def repository(value):
    if not isinstance(value, str) or not re.fullmatch(r"https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", value):
        raise ValueError("Expected credential-free GitHub repository URL")
    return value.removesuffix(".git")


def regular(value, suffix):
    path = Path(value)
    if not path.is_absolute() or path.suffix.lower() != suffix or ".." in path.parts:
        raise ValueError("Expected explicit absolute file path")
    for p in (path, *path.parents):
        if p.name.lower().startswith(".env") or p.is_symlink() or (hasattr(p, "is_junction") and p.is_junction()):
            raise ValueError("Sensitive path or redirected path")
    if path.exists() and (not path.is_file() or path.stat().st_nlink != 1):
        raise ValueError("Expected independent regular file")
    return path


def raw_at(path):
    return path.read_bytes() if path.exists() else None


def checked(raw, expected):
    actual = digest(raw) if raw is not None else "missing"
    if actual != expected:
        raise ValueError("File changed since review")


def write(path, raw, expected):
    checked(raw_at(path), expected)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        regular(str(path), path.suffix)
        checked(raw_at(path), expected)
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def content(doc):
    lines = doc["content"]
    if not isinstance(lines, list) or any(not isinstance(line, str) for line in lines):
        raise ValueError("Invalid document content")
    return "".join(lines).encode("utf-8")


def reference(ref):
    if not isinstance(ref, dict) or set(ref) != {"repository", "commit", "documentId", "revision", "sha256", "agent"}:
        raise ValueError("Incomplete provenance reference")
    repository(ref["repository"])
    identifier(ref["documentId"])
    if not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", ref["commit"]) or not re.fullmatch(r"[0-9a-f]{64}", ref["sha256"]):
        raise ValueError("Provenance must pin a real revision and content hash")
    if type(ref["revision"]) is not int or ref["revision"] < 1 or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", ref["agent"]):
        raise ValueError("Invalid provenance version or agent")


def validate(doc):
    if doc.get("schemaVersion") != 1 or doc.get("kind") != "agent-document":
        raise ValueError("Invalid document schema")
    identifier(doc["documentId"])
    identifier(doc["installationId"])
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", doc["agent"]):
        raise ValueError("Invalid agent name")
    repository(doc["repository"])
    if type(doc["revision"]) is not int or doc["revision"] < 1 or digest(content(doc)) != doc["sha256"]:
        raise ValueError("Invalid document revision or checksum")
    history = doc["history"]
    if not isinstance(history, list) or len(history) != doc["revision"]:
        raise ValueError("Incomplete revision history")
    previous = None
    for number, event in enumerate(history, 1):
        if event["revision"] != number or event["previousSha256"] != previous or not re.fullmatch(r"[0-9a-f]{64}", event["sha256"]):
            raise ValueError("Broken revision history")
        if datetime.fromisoformat(event["at"]).utcoffset() is None:
            raise ValueError("Timestamp must include timezone")
        previous = event["sha256"]
    if previous != doc["sha256"] or doc["strategy"] not in ("original", "overwrite", "reorganize", "append", "insert"):
        raise ValueError("Invalid document history or import strategy")
    if doc["parent"] is None:
        if doc["root"] is not None or doc["strategy"] != "original":
            raise ValueError("Root document must have explicit original provenance")
    else:
        reference(doc["parent"])
        reference(doc["root"])
        if doc["strategy"] == "original" or doc["documentId"] in (doc["parent"]["documentId"], doc["root"]["documentId"]):
            raise ValueError("Fork must have a distinct identity")
    return doc


def revision(doc, raw):
    result = copy.deepcopy(doc)
    old = result.get("sha256")
    result["content"] = raw.decode("utf-8").splitlines(keepends=True)
    result["sha256"] = digest(raw)
    result["revision"] = result.get("revision", 0) + 1
    result.setdefault("history", []).append(dict(revision=result["revision"], at=datetime.now(timezone.utc).isoformat(),
                                                  sha256=result["sha256"], previousSha256=old))
    return validate(result)


def parent_snapshot(request):
    source = request["parent"]
    reference(source)
    checkout = Path(request["parentCheckout"])
    if repository(git(checkout, "remote", "get-url", "origin").decode().strip()) != repository(source["repository"]):
        raise ValueError("Parent checkout repository mismatch")
    path = "agent-documents/" + source["documentId"] + ".json"
    doc = validate(json.loads(git(checkout, "show", source["commit"] + ":" + path)))
    if any(doc[key] != source[key] for key in ("documentId", "revision", "sha256", "agent")) or repository(doc["repository"]) != repository(source["repository"]):
        raise ValueError("Parent reference differs from pinned Git snapshot")
    return source, doc["root"] or source


def paths(binding, state_path):
    if binding.get("schemaVersion") != 1 or binding.get("kind") != "agent-document" or not binding.get("authorizationEvidence"):
        raise ValueError("Explicit document binding and authorization evidence required")
    identifier(binding["documentId"])
    identifier(binding["installationId"])
    repo = Path(binding["gitRoot"])
    target = regular(binding["installedPath"], ".md")
    source = regular(str(repo / "agent-documents" / (binding["documentId"] + ".json")), ".json")
    if not repo.is_absolute() or not repo.samefile(Path(git(repo, "rev-parse", "--show-toplevel").decode().strip())):
        raise ValueError("Binding must name actual Git root")
    if repository(git(repo, "remote", "get-url", "origin").decode().strip()) != repository(binding["repository"]):
        raise ValueError("Repository binding changed")
    if git(repo, "branch", "--show-current").decode().strip() != binding["branch"]:
        raise ValueError("Branch binding changed")
    if target.is_relative_to(repo) or state_path.is_relative_to(repo) or target == state_path:
        raise ValueError("Installation and local records must remain outside shared repository")
    return source, target


def identity(binding, doc):
    for key in ("documentId", "installationId", "agent", "repository"):
        if binding[key] != doc[key]:
            raise ValueError("Document does not belong to this installation")


def workflow(journal, binding):
    if journal.is_relative_to(Path(binding["gitRoot"])):
        raise ValueError("Journal must remain outside repository")
    state = json.loads(journal.read_bytes()) if journal.exists() else {}
    if not isinstance(state, dict) or (state and state.get("schemaVersion") != 1):
        raise ValueError("Unknown workflow journal schema")
    if state.get("pending") and state.get("observation", {}).get("resourceId") != "agent-document:" + binding["documentId"]:
        raise ValueError("Reconcile the existing resource operation first")


def operate(state_path, request):
    state_path = regular(str(state_path), ".json")
    action = request["operation"]
    # 所有文件写入共用现有仓库流程锁；本地锁只保护这一份绑定。
    journal = regular(request["journalPath"], ".json")
    flow = journal.with_suffix(".flow.lock")
    regular(str(flow), ".lock")
    held = json.loads(flow.read_bytes())
    if not request.get("owner") or held.get("owner") != request["owner"]:
        raise ValueError("Acquire the existing sync-session workflow lock first")
    if (not held.get("repoLock") or json.loads(Path(held["repoLock"]).read_bytes()) != held
            or held.get("sessionId") != json.loads(journal.read_bytes()).get("session", {}).get("id")):
        raise ValueError("Workflow repository lock or session changed")
    lock = state_path.with_suffix(".lock")
    pending = state_path.with_suffix(".pending.json")
    regular(str(lock), ".lock")
    regular(str(pending), ".json")
    fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(fd)
    try:
        current = raw_at(state_path)
        checked(current, request["expectedBindingSha256"])
        if pending.exists():
            if action != "recover":
                raise ValueError("Unfinished operation; inspect and recover before continuing")
            operation = json.loads(pending.read_bytes())
            binding = operation["binding"]
            source, target = paths(binding, state_path)
            workflow(journal, binding)
            if str(journal) != binding["journalPath"]:
                raise ValueError("Workflow journal binding mismatch")
            checked(raw_at(source), operation["sourceSha256"])
            checked(raw_at(target), operation["targetSha256"])
            doc = validate(json.loads(source.read_bytes()))
            identity(binding, doc)
            if digest(content(doc)) != binding["baselineContentSha256"]:
                raise ValueError("Recovery content mismatch")
            if current not in (None, encoded(binding)) and digest(current) != operation["beforeBindingSha256"]:
                raise ValueError("Binding changed during interrupted operation")
            write(state_path, encoded(binding), request["expectedBindingSha256"])
            pending.unlink()
            return {"saved": True, "recovered": True, "documentId": binding["documentId"]}
        if action == "recover":
            raise ValueError("No unfinished operation")
        if action == "register":
            if current is not None or request.get("reviewed") is not True:
                raise ValueError("Registration needs a new binding and reviewed final whole document")
            binding = copy.deepcopy(request["binding"])
            binding.update(schemaVersion=1, kind="agent-document", documentId=str(uuid.uuid4()), installationId=str(uuid.uuid4()))
            source, target = paths(binding, state_path)
            workflow(journal, binding)
            binding["journalPath"] = str(journal)
            raw = target.read_bytes()
            checked(raw, request["expectedInstalledSha256"])
            parent, root = parent_snapshot(request) if request.get("parent") else (None, None)
            doc = revision(dict(schemaVersion=1, kind="agent-document", documentId=binding["documentId"],
                                installationId=binding["installationId"], agent=binding["agent"], repository=binding["repository"],
                                parent=parent, root=root, strategy=request["strategy"]), raw)
            source.parent.mkdir(exist_ok=True)
            expected_source = "missing"
            source_raw = encoded(doc)
            changed, payload, expected = source, source_raw, expected_source
        else:
            if current is None or action not in ("collect", "apply", "inspect"):
                raise ValueError("Unknown operation or missing binding")
            binding = json.loads(current)
            source, target = paths(binding, state_path)
            workflow(journal, binding)
            if str(journal) != binding["journalPath"]:
                raise ValueError("Workflow journal binding mismatch")
            source_raw, raw = source.read_bytes(), target.read_bytes()
            doc = validate(json.loads(source_raw))
            identity(binding, doc)
            if action == "inspect":
                return dict(documentId=binding["documentId"], installedDigest=digest(raw), sourceDigest=doc["sha256"],
                            bundleDigest=digest(source_raw), bindingDigest=digest(current), revision=doc["revision"])
            checked(source_raw, request["expectedSourceSha256"])
            checked(raw, request["expectedInstalledSha256"])
            if request.get("reviewed") is not True:
                raise ValueError("Review full document and provenance before transfer")
            if action == "collect":
                if digest(source_raw) != binding["baselineSourceSha256"]:
                    raise ValueError("Source changed; do not overwrite remote edits")
                if digest(raw) == doc["sha256"]:
                    return {"saved": False, "unchanged": True}
                doc = revision(doc, raw)
                changed, payload, expected = source, encoded(doc), digest(source_raw)
                source_raw = payload
            else:
                if request.get("inUse") is not False:
                    raise ValueError("Defer applying an in-use Agent document")
                if digest(raw) != binding["baselineContentSha256"]:
                    raise ValueError("Local edits conflict; preserve both versions")
                previous = binding["baselineRevision"]
                if doc["revision"] < previous or doc["history"][:previous] != binding["baselineHistory"]:
                    raise ValueError("Remote rewrote this installation's history")
                if digest(source_raw) == binding["baselineSourceSha256"]:
                    return {"saved": False, "unchanged": True}
                changed, payload, expected = target, content(doc), digest(raw)
                raw = payload
        binding.update(baselineContentSha256=doc["sha256"], baselineSourceSha256=digest(source_raw),
                       baselineRevision=doc["revision"], baselineHistory=doc["history"])
        if action != "register" and any(json.loads(current)[k] != doc[k] for k in ("parent", "root", "strategy") if k in json.loads(current)):
            raise ValueError("Immutable provenance changed")
        binding.update({k: doc[k] for k in ("parent", "root", "strategy")})
        before_target = raw_at(target)
        checked(before_target, request["expectedInstalledSha256"])
        checked(raw_at(source), expected_source if action == "register" else request["expectedSourceSha256"])
        backup = state_path.parent / (state_path.stem + ".backup-" + str(uuid.uuid4()))
        backup.mkdir()
        for name, data in (("binding.json", current), ("document.md", before_target), ("source.json", raw_at(source))):
            if data is not None:
                (backup / name).write_bytes(data)
        intent = dict(binding=binding, beforeBindingSha256=request["expectedBindingSha256"],
                      sourceSha256=digest(source_raw), targetSha256=digest(raw), backup=str(backup))
        write(pending, encoded(intent), "missing")
        write(changed, payload, expected)
        checked(raw_at(source), intent["sourceSha256"])
        checked(raw_at(target), intent["targetSha256"])
        write(state_path, encoded(binding), request["expectedBindingSha256"])
        pending.unlink()
        return dict(saved=True, documentId=doc["documentId"], revision=doc["revision"], sha256=doc["sha256"],
                    sourcePath=str(source), backup=str(backup), sync="pending")
    finally:
        lock.unlink()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binding", required=True, type=Path)
    parser.add_argument("--request", required=True, type=Path)
    args = parser.parse_args()
    try:
        request = json.loads(regular(str(args.request), ".json").read_bytes())
        print(json.dumps(operate(args.binding, request), ensure_ascii=False))
        return 0
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        print('{"saved":false,"error":"绑定、锁、来源或内容基线不一致；保留现场和 pending，不盲重试"}')
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
