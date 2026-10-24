"""Review and apply one explicit resource with hash checks and local recovery receipts."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import tempfile

from sync_integrity import digest, linked, safe_relative, snapshot


def location(value):
    path = Path(value).absolute()
    if any(linked(part) for part in (path, *path.parents)):
        raise ValueError("Linked resource or ancestor requires separate review")
    return path.resolve()


def separate(a, b):
    if a == b or a in b.parents or b in a.parents:
        raise ValueError("Source, target and recovery locations must be separate")


def files(path, excluded):
    if not path.exists():
        return {}
    result = snapshot(path, excluded)
    if len({name.casefold() for name in result}) != len(result):
        raise ValueError("Resource contains case-colliding paths")
    return result


def prepare(source, target, excluded=()):
    source, target = location(source), location(target)
    separate(source, target)
    if not source.is_dir():
        raise ValueError("Source resource is missing")
    excluded = sorted({safe_relative(name) for name in excluded})
    before, after = files(target, excluded), files(source, excluded)
    # Match spelling aliases only when this filesystem resolves them to the same file.
    target_names = {name.casefold(): name for name in before}
    for name in after:
        previous = target_names.get(name.casefold())
        if previous is not None and previous != name:
            candidate = target / name
            if candidate.exists() and candidate.samefile(target / previous):
                before[name] = before.pop(previous)
    changes = [{"path": name, "before": before.get(name), "after": after.get(name)}
               for name in sorted(before.keys() | after.keys())
               if before.get(name) != after.get(name)]
    # An existing excluded file must not become an ancestor of new source files.
    for change in changes:
        path = target / change["path"]
        for parent in path.parents:
            if parent == target:
                break
            if parent.exists() and not parent.is_dir():
                raise ValueError("Target contains a file/directory shape conflict")
        if path.exists() and not path.is_file():
            raise ValueError("Target contains a file/directory shape conflict")
    return dict(schemaVersion=1, source=str(source), target=str(target),
                targetExists=target.exists(), excluded=excluded,
                sourceDigest=digest(after), targetDigest=digest(before), changes=changes)


def atomic(path, content):
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def save(path, value):
    atomic(path, (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


def current(path):
    if not path.exists():
        return None
    if not path.is_file() or linked(path):
        raise ValueError("Destination stopped being a regular file")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def apply(plan, receipt, backup, *, allow_delete=False):
    if plan.get("schemaVersion") != 1:
        raise ValueError("Unknown resource plan")
    source, target = location(plan["source"]), location(plan["target"])
    receipt, backup = location(receipt), location(backup)
    separate(source, target)
    for path in (receipt, backup):
        for resource in (source, target):
            separate(resource, path)
        if any((parent / ".git").exists() for parent in (path, *path.parents)):
            raise ValueError("Recovery artifacts must remain outside Git repositories")
    separate(receipt, backup)
    if receipt.exists() or backup.exists():
        raise ValueError("Recovery locations already exist; retain previous operation")
    if prepare(source, target, plan["excluded"]) != plan:
        raise ValueError("Resource changed since review; prepare and review again")
    if any(change["after"] is None for change in plan["changes"]) and not allow_delete:
        raise ValueError("Deletion requires explicit approval of listed paths")
    state = dict(schemaVersion=1, status="pending", plan=plan, completed=[], backup=str(backup))
    receipt.parent.mkdir(parents=True, exist_ok=True)
    backup.mkdir(parents=True, exist_ok=False)
    save(receipt, state)
    try:
        # Preserve every old file before starting replacements, for interrupted runs.
        for change in plan["changes"]:
            if change["before"] is not None:
                path = target / change["path"]
                location(path)
                content = path.read_bytes()
                if hashlib.sha256(content).hexdigest() != change["before"]:
                    raise ValueError("Destination changed before backup")
                saved = backup / change["path"]
                saved.parent.mkdir(parents=True, exist_ok=True)
                atomic(saved, content)
        if prepare(source, target, plan["excluded"]) != plan:
            raise ValueError("Resource changed while preparing recovery files")
        target.mkdir(parents=True, exist_ok=True)
        for change in plan["changes"]:
            path = target / change["path"]
            location(path)
            if current(path) != change["before"]:
                raise ValueError("Destination changed during application")
            if change["after"] is None:
                path.unlink()
            else:
                content = (source / change["path"]).read_bytes()
                if hashlib.sha256(content).hexdigest() != change["after"]:
                    raise ValueError("Source changed during application")
                path.parent.mkdir(parents=True, exist_ok=True)
                atomic(path, content)
            state["completed"].append(change["path"])
            save(receipt, state)
        verified = prepare(source, target, plan["excluded"])
        if (verified["sourceDigest"] != plan["sourceDigest"]
                or verified["targetDigest"] != plan["sourceDigest"]):
            raise ValueError("Final resource content differs from reviewed source")
        state["status"] = "applied"
        save(receipt, state)
        return state
    except BaseException:
        # Do not roll back over another writer. Leave the exact completed list and backups.
        state["status"] = "incomplete"
        save(receipt, state)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    review = commands.add_parser("plan")
    review.add_argument("--source", required=True)
    review.add_argument("--target", required=True)
    review.add_argument("--exclude", action="append", default=[])
    execute = commands.add_parser("apply")
    execute.add_argument("--plan", required=True)
    execute.add_argument("--receipt", required=True)
    execute.add_argument("--backup", required=True)
    execute.add_argument("--allow-delete", action="store_true")
    args = parser.parse_args()
    if args.command == "plan":
        result = prepare(args.source, args.target, args.exclude)
    else:
        plan_path = location(args.plan)
        if plan_path.name.lower().startswith(".env") or plan_path.suffix != ".json":
            raise ValueError("Expected a non-sensitive reviewed JSON plan")
        result = apply(json.loads(plan_path.read_text(encoding="utf-8")), args.receipt,
                       args.backup, allow_delete=args.allow_delete)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, KeyError) as exc:
        raise SystemExit("Resource operation stopped; retained recovery state: " + type(exc).__name__)
