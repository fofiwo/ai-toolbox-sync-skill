"""Cooperative local decision updates: exclusive lock, SHA precondition, atomic replace."""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile

VALUES = {
    "decision": {"pending", "approved", "declined", "deferred", "unknown"},
    "collection": {"not-collected", "collected", "failed", "unknown"},
    "installation": {"source-only", "configured", "installed", "failed", "uninstalled", "unknown"},
    "sync": {"not-requested", "pending", "synced", "failed", "unknown"},
    "catalog": {"pending", "current", "failed", "unknown"},
}
DEFAULT = dict(decision="pending", collection="not-collected", installation="unknown", sync="not-requested", catalog="pending")
FIELDS = {"name", "kind", "ownership", "sourceIdentity", "revision", "parentId", "prompted", "decisionEvidence", "state"}


def normalized_state(record):
    """Old fields are evidence hints only; new state fields take precedence."""
    old = record.get("decision", record.get("management", "unknown"))
    if not isinstance(old, str) or (old not in VALUES["decision"] and old != "managed"):
        old = "unknown"
    state = dict(decision="approved" if old == "managed" else old,
                 collection="collected" if old == "managed" or record.get("management") == "managed" else "unknown",
                 installation={"created": "source-only", "configured": "configured", "installed": "installed", "failed": "failed"}.get(record.get("outcome") if isinstance(record.get("outcome"), str) else "unknown", "unknown"),
                 sync="unknown", catalog="unknown")
    supplied = record.get("state", {})
    if not isinstance(supplied, dict):
        raise ValueError("state must be an object")
    for key, value in supplied.items():
        if key not in VALUES or not isinstance(value, str) or value not in VALUES[key]:
            raise ValueError("Invalid state field or value")
        state[key] = value
    return state


def management_view(state):
    if state["collection"] == "collected":
        return "managed"
    return state["decision"]


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def read_store(path):
    if path.name.lower().startswith(".env") or path.suffix != ".json" or path.is_symlink():
        raise ValueError("Expected a regular non-environment JSON record file")
    raw = path.read_bytes()
    doc = json.loads(raw.decode("utf-8-sig"))
    if not isinstance(doc, dict) or doc.get("schemaVersion") != 1 or not isinstance(doc.get("records"), list):
        raise ValueError("Expected schemaVersion 1 with records array")
    ids = []
    for record in doc["records"]:
        if not isinstance(record, dict) or not isinstance(record.get("id"), str) or not record["id"]:
            raise ValueError("Invalid legacy record; preserve and review manually")
        ids.append(record["id"])
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate record IDs; preserve and review manually")
    return raw, doc


def apply_update(doc, request):
    if not isinstance(request, dict) or set(request) != {"id", "patch"}:
        raise ValueError("Request requires id and patch only")
    identity, patch = request["id"], request["patch"]
    if not isinstance(identity, str) or not identity.strip() or len(identity) > 300 or not isinstance(patch, dict) or not patch or set(patch) - FIELDS:
        raise ValueError("Invalid ID or patch fields")
    for key, value in patch.items():
        if key == "state":
            if not isinstance(value, dict) or not value or set(value) - VALUES.keys():
                raise ValueError("Invalid state patch")
            for axis, status in value.items():
                if not isinstance(status, str) or status not in VALUES[axis]:
                    raise ValueError("Invalid state value")
        elif key == "prompted":
            if type(value) is not bool:
                raise ValueError("prompted must be boolean")
        elif not isinstance(value, str) or not value.strip() or len(value) > 2000:
            raise ValueError("Metadata must be nonempty short text")
    result = copy.deepcopy(doc)
    record = next((r for r in result["records"] if r["id"] == identity), None)
    if record is None:
        if not all(patch.get(k) for k in ("name", "kind", "sourceIdentity")):
            raise ValueError("New identity needs name, kind and confirmed sourceIdentity")
        record = {"id": identity, "state": DEFAULT.copy()}
        result["records"].append(record)
    for key in ("kind", "sourceIdentity", "parentId"):
        if key in patch and key in record and patch[key] != record[key]:
            raise ValueError("Stable identity cannot be changed by an update")
    if patch.get("kind", record.get("kind")) not in ("skill", "mcp", "plugin", "agent-document"):
        raise ValueError("Invalid resource kind")
    previous = normalized_state(record)
    state = {**previous, **patch.get("state", {})}
    if state["decision"] != previous["decision"] and state["decision"] in ("approved", "declined", "deferred") and not patch.get("decisionEvidence"):
        raise ValueError("A user decision needs explicit evidence in this request")
    if previous["collection"] == "collected" and state["collection"] != "collected":
        raise ValueError("This helper cannot remove an existing collection")
    if previous["collection"] != "collected" and state["collection"] == "collected" and state["decision"] != "approved":
        raise ValueError("Collection requires an approved user decision")
    if "history" in record and not isinstance(record["history"], list):
        raise ValueError("Unknown legacy history format; preserve and review manually")
    if previous != state:
        record.setdefault("history", []).append({"before":previous,"after":state.copy(),"decisionEvidence":patch.get("decisionEvidence")})
    record.update({k:v for k,v in patch.items() if k != "state"})
    record["state"] = state
    for other in result["records"]:
        if other is not record and record.get("sourceIdentity") and other.get("kind") == record.get("kind") and other.get("sourceIdentity") == record["sourceIdentity"]:
            raise ValueError("Source identity already exists; reuse its ID")
    return result


def update_store(path, expected, request):
    if len(expected) != 64 or any(c not in "0123456789abcdef" for c in expected):
        raise ValueError("Expected SHA-256 must be the inspected current file hash")
    lock = path.with_name(path.name + ".lock")
    # Only cooperating writers are protected; never steal a stale lock automatically.
    fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    temporary = None
    try:
        os.close(fd)
        raw, doc = read_store(path)
        if digest(raw) != expected:
            raise ValueError("Conflict: record file changed; inspect and rebase explicitly")
        result = apply_update(doc, request)
        payload = (json.dumps(result, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".decision-", suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        if path.read_bytes() != raw:
            raise ValueError("Conflict: noncooperating writer changed the file")
        os.replace(temporary, path)
        temporary = None
        return digest(payload)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        lock.unlink()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("inspect", "update"))
    parser.add_argument("--store", required=True, type=Path)
    parser.add_argument("--request", type=Path)
    parser.add_argument("--expected-sha256")
    args = parser.parse_args()
    try:
        if args.command == "inspect":
            raw, doc = read_store(args.store)
            print(json.dumps({"sha256":digest(raw),"recordCount":len(doc["records"])}, ensure_ascii=False))
        else:
            if not args.request or not args.expected_sha256 or args.request.name.lower().startswith(".env") or args.request.suffix != ".json":
                raise ValueError("update requires a non-environment JSON request and expected hash")
            request = json.loads(args.request.read_text(encoding="utf-8-sig"))
            new_hash = update_store(args.store, args.expected_sha256, request)
            print(json.dumps({"saved":True,"sha256":new_hash}))
    except (OSError, ValueError, TypeError):
        print("Update/read failed: invalid input, conflict, lock or filesystem failure; no success claimed. Inspect current records before retry.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
