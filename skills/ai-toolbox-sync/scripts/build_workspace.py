"""Build a machine-local, offline workspace with separate catalog and discovery panels."""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from urllib.parse import urlencode

from build_catalog import export
from inventory import Inventory, linked, read_json, write_new
from record_decision import read_store
from resource_files import atomic

ASSETS = Path(__file__).resolve().parent.parent / 'catalog'
ASSET_NAMES = ('index.html', 'style.css', 'model.js', 'app.js', 'demo-data.js', 'inventory-model.js', 'inventory-app.js')


def pending_snapshot(snapshot, records, binding=None):
    if snapshot.get('schemaVersion') != 1 or snapshot.get('snapshotType') != 'discovery-not-collection' or not isinstance(snapshot.get('groups'), list):
        raise ValueError('Expected an inventory discovery snapshot')
    result = copy.deepcopy(snapshot)
    collected = {r['id'] for r in records if r.get('state', {}).get('collection') == 'collected'}
    paths = {os.path.normcase(str(Path(r['installedPath']).resolve()))
             for r in (binding or {}).get('taskSync', {}).get('resources', [])
             if r.get('id') in collected and r.get('installedPath') and r.get('kind', 'skill') == 'skill'}
    # Only explicit, collected installation bindings prove identity; names never do.
    removed = 0
    for group in result['groups']:
        components = []
        for component in group['components']:
            installations = component.get('installations', [])
            if component.get('kind') == 'skill' and installations and all(os.path.normcase(str(Path(i['path']).resolve())) in paths for i in installations):
                removed += 1
            else:
                components.append(component)
        group['components'] = components
    result['groups'] = [g for g in result['groups'] if g['components']]
    result.setdefault('warnings', []).append(f'按已收藏的本机精确绑定排除 {removed} 个组件；其余收藏状态未核对。')
    return result


def workspace_location(output):
    output = Path(output).absolute()
    if any(linked(parent) for parent in (output, *output.parents)):
        raise ValueError('Workspace output must not traverse links')
    output = output.resolve()
    if output.is_relative_to(Path(__file__).resolve().parent.parent) or any((parent / '.git').exists() for parent in (output, *output.parents)):
        raise ValueError('Machine discovery must stay outside the installed/shared skill')
    return output


def build_workspace(manifest, snapshot, output, records=None, binding=None):
    records = records or []
    catalog = export(manifest, records=records)
    managed_ids = {row['id'] for row in catalog['resources']}
    pending = pending_snapshot(snapshot, [r for r in records if r['id'] in managed_ids], binding) if snapshot is not None else None
    output = workspace_location(output)
    # Never replace an earlier workspace or its still-selected resources.
    output.mkdir(parents=True, exist_ok=False)
    for name in ASSET_NAMES:
        shutil.copyfile(ASSETS / name, output / name)
    for name, variable, data in (('data.js', 'TOOLBOX_DATA', catalog), ('discovery-data.js', 'TOOLBOX_DISCOVERY', pending)):
        payload = json.dumps(data, ensure_ascii=False).replace('<', '\\u003c').replace('\u2028', '\\u2028').replace('\u2029', '\\u2029')
        write_new(output / name, 'window.' + variable + ' = ' + payload + ';\n')
    return dict(output=str(output.resolve() / 'index.html'), collected=len(catalog['resources']),
                pending=sum(len(g['components']) for g in pending['groups']) if pending else 0,
                generatedAt=pending['generatedAt'] if pending else None)


@contextmanager
def workspace_lock(path):
    # The OS releases this lock on a crash; retain the file to avoid an unlink/reopen race.
    if linked(path) or (path.exists() and path.stat().st_size > 1):
        raise ValueError('Unknown workspace lock; preserve it for review')
    with path.open('a+b') as stream:
        stream.seek(0)
        if os.name == 'nt':
            import msvcrt
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        marker = stream.read(2)
        if marker not in (b'', b'\0'):
            raise ValueError('Unknown workspace lock; preserve it for review')
        if not marker:
            stream.write(b'\0')
            stream.flush()
        yield


def refresh_workspace(manifest, output, skill_roots, records=None, binding=None):
    """Check explicit local scopes on each invocation; retain previous generations on failure."""
    output = workspace_location(output)
    roots = [Path(root).absolute() for root in skill_roots]
    if any(linked(part) for root in roots for part in (root, *root.parents)):
        raise ValueError('Skill roots must not traverse links')
    if not roots or any(output.is_relative_to(root.resolve()) for root in roots):
        raise ValueError('Specify Skill roots and keep the cache outside them')
    for source in (manifest, records, binding):
        if source and (Path(source).suffix.lower() != '.json' or Path(source).name.lower().startswith('.env')
                       or any(linked(part) for part in (Path(source), *Path(source).parents))):
            raise ValueError('Expected regular JSON inputs without linked ancestors')
    inputs = dict(manifest=str(Path(manifest).resolve()), roots=[str(root) for root in roots],
                  records=str(Path(records).resolve()) if records else None,
                  binding=str(Path(binding).resolve()) if binding else None)
    expected = {*ASSET_NAMES, 'data.js', 'discovery-data.js', 'inventory.json'}
    output.mkdir(parents=True, exist_ok=True)
    state_path = output / 'cache.json'
    lock = output / 'refresh.lock'
    if not state_path.exists() and any(p.name != 'refresh.lock' for p in output.iterdir()):
        # A first atomic write can be interrupted before cache.json exists; preserve its debris.
        if linked(lock) or not lock.is_file() or lock.stat().st_size != 1 or lock.read_bytes() != b'\0':
            raise ValueError('Cache directory contains unrelated files; use a new location')
    with workspace_lock(lock):
        state = read_json(state_path) if state_path.exists() else dict(schemaVersion=1, cacheType='local-workspace', generation=None)
        if state.get('schemaVersion') != 1 or state.get('cacheType') != 'local-workspace':
            raise ValueError('Unknown workspace cache format')
        if not state_path.exists():
            atomic(state_path, (json.dumps(state) + '\n').encode('utf-8'))
        previous = None
        if state.get('generation'):
            generation = state['generation']
            if not isinstance(generation, str) or len(generation) != 32 or any(c not in '0123456789abcdef' for c in generation):
                raise ValueError('Invalid cached workspace generation')
            page = workspace_location(output / generation)
            hashes = state.get('filesSHA256', {})
            if (state.get('inputs') == inputs and set(hashes) == expected
                    and all(not linked(page / name) and (page / name).is_file()
                            and hashlib.sha256((page / name).read_bytes()).hexdigest() == digest
                            for name, digest in hashes.items())):
                previous = dict(state['result'], output=str(page / 'index.html'))
        checked = datetime.now(timezone.utc).isoformat()
        # Invalid collection inputs stop; they must not silently open an unrelated old catalog.
        collection = read_json(Path(manifest))
        local_records = read_store(Path(records))[1]['records'] if records else []
        local_binding = read_json(Path(binding)) if binding else None
        export(collection, records=local_records)

        def verify_inputs():
            current = (read_json(Path(manifest)), read_store(Path(records))[1]['records'] if records else [],
                       read_json(Path(binding)) if binding else None)
            if current != (collection, local_records, local_binding):
                raise ValueError('Workspace inputs changed during the check; retry without using this result')

        try:
            inventory = Inventory(strict=True)
            for root in roots:
                inventory.skills(root)
            snapshot = inventory.result()
            fingerprint_data = dict(collection=collection, records=local_records, binding=local_binding,
                                    discovery={k: v for k, v in snapshot.items() if k != 'generatedAt'},
                                    assets={name: hashlib.sha256((ASSETS / name).read_bytes()).hexdigest() for name in ASSET_NAMES},
                                    scripts={name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
                                             for name in ('build_workspace.py', 'inventory.py', 'build_catalog.py', 'record_decision.py')})
            fingerprint = hashlib.sha256(json.dumps(fingerprint_data, sort_keys=True, ensure_ascii=False).encode('utf-8')).hexdigest()
            if previous and fingerprint == state.get('fingerprint'):
                verify_inputs()
                return dict(previous, status='cached', checkedAt=checked)
            generation = uuid.uuid4().hex
            page = output / generation
            result = build_workspace(collection, snapshot, page, local_records, local_binding)
            write_new(page / 'inventory.json', json.dumps(snapshot, ensure_ascii=False, indent=2))
            state = dict(schemaVersion=1, cacheType='local-workspace', generation=generation, inputs=inputs,
                         fingerprint=fingerprint, result=result,
                         filesSHA256={name: hashlib.sha256((page / name).read_bytes()).hexdigest() for name in expected})
            verify_inputs()
            atomic(state_path, (json.dumps(state, ensure_ascii=False, indent=2) + '\n').encode('utf-8'))
            return dict(result, status='updated', checkedAt=checked)
        except (OSError, ValueError):
            if previous:
                verify_inputs()
                return dict(previous, status='stale-cache', checkedAt=checked,
                            warning='本次检查失败，继续显示上次成功快照；未确认最新状态。')
            raise


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--manifest', type=Path, required=True)
    p.add_argument('--snapshot', type=Path, help='Optional explicit inventory; omission does not scan the machine')
    p.add_argument('--records', type=Path)
    p.add_argument('--binding', type=Path)
    p.add_argument('--output', type=Path, required=True, help='New workspace, or persistent cache directory with --refresh')
    p.add_argument('--refresh', action='store_true', help='Check explicit Skill roots and reuse or refresh a local cache')
    p.add_argument('--skill-root', action='append', default=[], type=Path)
    p.add_argument('--open', action='store_true', help='Open the resulting offline page in the system browser')
    a = p.parse_args()
    if a.refresh and (a.snapshot or not a.skill_root) or a.skill_root and not a.refresh:
        p.error('--refresh requires --skill-root and cannot use a static --snapshot')
    # Reject sensitive input names before reading bytes, including optional metadata.
    for source in (a.manifest, a.snapshot, a.records, a.binding):
        if source and (source.name.lower().startswith('.env') or linked(source)):
            p.error('Expected explicit regular JSON inputs, never environment files or links')
    if a.refresh:
        result = refresh_workspace(a.manifest, a.output, a.skill_root, a.records, a.binding)
    else:
        records = read_store(a.records)[1]['records'] if a.records else []
        result = build_workspace(read_json(a.manifest), read_json(a.snapshot) if a.snapshot else None, a.output, records,
                                 read_json(a.binding) if a.binding else None)
    result['url'] = Path(result['output']).as_uri()
    if result.get('status'):
        result['url'] += '#' + urlencode({'toolbox-check': result['status'], 'checkedAt': result['checkedAt']})
    print(json.dumps(result, ensure_ascii=False))
    if a.open:
        import webbrowser
        if not webbrowser.open(result['url']):
            print('浏览器未能打开；请使用结果中的 url 手动打开。', file=sys.stderr)
            return 1
    return 2 if result.get('status') == 'stale-cache' else 0


if __name__ == '__main__':
    raise SystemExit(main())
