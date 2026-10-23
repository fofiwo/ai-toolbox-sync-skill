"""Export an audited toolbox manifest to an offline, read-only catalog snapshot."""
import argparse
import json
import re
import os
import tempfile
from pathlib import Path
from urllib.parse import urlsplit
from record_decision import normalized_state, management_view, read_store

FIELDS = ("id", "name", "description", "version", "resolvedCommit", "license", "ownership", "management", "verification")

def safe_text(value):
    if not isinstance(value, str):
        return "unknown"
    if any(safe_url(url) is None for url in re.findall(r"https?://[^\s<>]+", value, re.IGNORECASE)):
        return "[已隐藏敏感内容]"
    # shortcut: reject common sensitive patterns; the manifest still requires human review.
    if re.search(r"(?i)((?<![a-z0-9])[a-z]:[\\/]|\\\\|/(?:home|users|etc|root)/|bearer\s|(?:token|password|secret|api[_-]?key)\s*[:=]|sk-[a-z0-9]{12})", value):
        return "[已隐藏敏感内容]"
    return value[:2000]

def safe_url(value):
    if not isinstance(value, str) or re.search(r"[\s\\]", value):
        return None
    try:
        u = urlsplit(value)
        return value if u.scheme in ("http", "https") and u.hostname and not (u.username or u.password or u.query or u.fragment) else None
    except ValueError:
        return None

def export(data, demo=False, records=None):
    if not isinstance(data, dict) or data.get("schemaVersion") != 1 or not isinstance(data.get("resources"), list):
        raise ValueError("Expected schemaVersion 1 and resources array")
    if bool(data.get("exampleOnly")) != demo:
        raise ValueError("Example manifests require --demo; production manifests must not be examples")
    record_map = {}
    for record in records or []:
        if not isinstance(record, dict) or not isinstance(record.get("id"),str) or not record["id"] or record["id"] in record_map:
            raise ValueError("Invalid or duplicate local record identity")
        normalized_state(record)
        record_map[record["id"]] = record
    rows=[]
    ids=set()
    for item in data["resources"]:
        if not isinstance(item, dict) or item.get("kind") not in ("skill", "mcp", "plugin", "agent-document"):
            raise ValueError("Invalid resource kind")
        if not isinstance(item.get("id"), str) or not item["id"] or item["id"] in ids or not isinstance(item.get("name"), str) or not item["name"].strip():
            raise ValueError("Each resource needs a unique id and nonempty name")
        if safe_text(item["id"]) != item["id"] or not item["id"].strip():
            raise ValueError("Resource id must remain unchanged in the public snapshot")
        ids.add(item["id"])
        row={key:safe_text(item.get(key)) for key in FIELDS}
        if row["management"] not in ("pending", "approved", "managed", "declined", "deferred"):
            row["management"] = "unknown"
        categories = item.get("categories", [])
        if not isinstance(categories, list) or len(categories)>3 or any(not isinstance(c,str) or not c.strip() or len(c)>30 or c.strip() in ("all", "未分类") or safe_text(c)!=c for c in categories):
            raise ValueError("categories must contain up to 3 short, safe capability labels")
        row["categories"] = list(dict.fromkeys(c.strip() for c in categories))
        summary = item.get("summary", item.get("description", ""))
        prompt = item.get("triggerPrompt", "") if item["kind"] in ("skill", "agent-document") else ""
        if not isinstance(summary,str) or not isinstance(prompt,str) or len(summary)>2000 or len(prompt)>2000:
            raise ValueError("summary and triggerPrompt must be strings up to 2000 characters")
        row["summary"] = safe_text(summary)
        row["triggerPrompt"] = safe_text(prompt)
        row["state"] = normalized_state(item)
        if item["id"] in record_map:
            local_record = record_map[item["id"]]
            for key in ("kind", "sourceIdentity", "parentId"):
                if key in item and key in local_record and item[key] != local_record[key]:
                    raise ValueError("Local record identity does not match manifest")
            row["state"].update({k:v for k,v in normalized_state(local_record).items() if v != "unknown"})
            row["state"].update(local_record.get("state", {}))
        if item.get("ownership") == "third-party":
            local = record_map.get(item["id"], {})
            row["version"] = safe_text(local.get("revision")) if row["state"]["installation"] == "installed" else "unknown"
        row["management"] = management_view(row["state"])
        row["kind"]=item["kind"]
        if item["kind"] == "agent-document":
            row["agent"] = safe_text(item.get("agent"))
            row["documentId"] = safe_text(item.get("documentId"))
            for key in ("parent", "root"):
                ref = item.get(key)
                row[key] = ({k: safe_text(ref.get(k)) for k in ("documentId", "agent", "commit")}
                            | {"repository": safe_url(ref.get("repository"))}) if isinstance(ref, dict) else None
        row["projectUrl"]=safe_url(item.get("projectUrl") or item.get("source"))
        rows.append(row)
    return {"exampleOnly":demo,"resources":rows}

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest",type=Path)
    parser.add_argument("output",type=Path)
    parser.add_argument("--demo",action="store_true")
    parser.add_argument("--records",type=Path,help="Explicitly authorized local decisions JSON; export only matching state axes")
    args=parser.parse_args()
    if args.manifest.name.lower().startswith(".env"):
        parser.error("Environment files are not manifests")
    if args.output.name != ("demo-data.js" if args.demo else "data.js"):
        parser.error("Output must be demo-data.js or data.js matching mode")
    if args.output.is_symlink() or args.output.resolve() == args.manifest.resolve() or (args.records and args.output.resolve() == args.records.resolve()):
        parser.error("Output must not be a symbolic link or replace an input file")
    records = read_store(args.records)[1]["records"] if args.records else None
    result=export(json.loads(args.manifest.read_text(encoding="utf-8-sig")),args.demo,records)
    payload=json.dumps(result,ensure_ascii=False,indent=2).replace("<","\\u003c").replace("\u2028","\\u2028").replace("\u2029","\\u2029")
    content = "// Generated from the audited manifest; do not edit.\nwindow."+("TOOLBOX_DEMO" if args.demo else "TOOLBOX_DATA")+" = "+payload+";\n"
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=args.output.parent, prefix=".catalog-", suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(content.encode("utf-8"))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, args.output)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)

if __name__ == "__main__":
    main()
