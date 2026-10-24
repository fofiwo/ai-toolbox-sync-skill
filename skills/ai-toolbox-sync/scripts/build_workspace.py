"""Build a machine-local, offline workspace with separate catalog and discovery panels."""
import argparse
import copy
import json
import os
from pathlib import Path
import shutil

from build_catalog import export
from inventory import linked, read_json, write_new
from record_decision import read_store


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


def build_workspace(manifest, snapshot, output, records=None, binding=None):
    records = records or []
    catalog = export(manifest, records=records)
    managed_ids = {row['id'] for row in catalog['resources']}
    pending = pending_snapshot(snapshot, [r for r in records if r['id'] in managed_ids], binding) if snapshot is not None else None
    output = Path(output).absolute()
    if any(linked(parent) for parent in (output, *output.parents)):
        raise ValueError('Workspace output must not traverse links')
    output = output.resolve()
    assets = Path(__file__).resolve().parent.parent / 'catalog'
    if output.is_relative_to(assets.parent) or any((parent / '.git').exists() for parent in (output, *output.parents)):
        raise ValueError('Machine discovery must stay outside the installed/shared skill')
    # Never replace an earlier workspace or its still-selected resources.
    output.mkdir(parents=True, exist_ok=False)
    for name in ('index.html', 'style.css', 'model.js', 'app.js', 'demo-data.js', 'inventory-model.js', 'inventory-app.js'):
        shutil.copyfile(assets / name, output / name)
    for name, variable, data in (('data.js', 'TOOLBOX_DATA', catalog), ('discovery-data.js', 'TOOLBOX_DISCOVERY', pending)):
        payload = json.dumps(data, ensure_ascii=False).replace('<', '\\u003c').replace('\u2028', '\\u2028').replace('\u2029', '\\u2029')
        write_new(output / name, 'window.' + variable + ' = ' + payload + ';\n')
    return dict(output=str(output.resolve() / 'index.html'), collected=len(catalog['resources']),
                pending=sum(len(g['components']) for g in pending['groups']) if pending else 0,
                generatedAt=pending['generatedAt'] if pending else None)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--manifest', type=Path, required=True)
    p.add_argument('--snapshot', type=Path, help='Optional explicit inventory; omission does not scan the machine')
    p.add_argument('--records', type=Path)
    p.add_argument('--binding', type=Path)
    p.add_argument('--output', type=Path, required=True, help='New machine-local directory outside any sync repository')
    a = p.parse_args()
    # Reject sensitive input names before reading bytes, including optional metadata.
    for source in (a.manifest, a.snapshot, a.records, a.binding):
        if source and (source.name.lower().startswith('.env') or linked(source)):
            p.error('Expected explicit regular JSON inputs, never environment files or links')
    records = read_store(a.records)[1]['records'] if a.records else []
    print(json.dumps(build_workspace(read_json(a.manifest), read_json(a.snapshot) if a.snapshot else None, a.output, records,
                                     read_json(a.binding) if a.binding else None), ensure_ascii=False))


if __name__ == '__main__':
    main()
