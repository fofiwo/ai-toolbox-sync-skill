"""Workspace regression checks use synthetic metadata, never the user's inventory."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
import subprocess
import sys

from build_workspace import build_workspace, pending_snapshot
from build_catalog import export


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.snapshot = dict(schemaVersion=1, snapshotType='discovery-not-collection', generatedAt='2026-10-23T00:00:00Z', scopes=[], warnings=[], groups=[
            dict(id='group', name='source', source=None, identityStatus='unknown', components=[
                dict(id='component', name='same', kind='skill', installations=[dict(path=str(self.root / 'skill'), status='files-present')])])])
        self.manifest = dict(schemaVersion=1, resources=[dict(id='skill:one', name='same', kind='skill', management='managed')])
        self.records = [dict(id='skill:one', state=dict(collection='collected'))]
        self.binding = dict(taskSync=dict(resources=[dict(id='skill:one', installedPath=str(self.root / 'skill'))]))

    def tearDown(self):
        self.temp.cleanup()

    def test_only_explicit_collected_binding_is_excluded(self):
        original = copy.deepcopy(self.snapshot)
        self.assertEqual(pending_snapshot(self.snapshot, [], self.binding)['groups'], self.snapshot['groups'])
        self.assertEqual(pending_snapshot(self.snapshot, self.records)['groups'], self.snapshot['groups'])
        self.assertEqual(pending_snapshot(self.snapshot, self.records, self.binding)['groups'], [])
        self.assertEqual(self.snapshot, original)

    def test_partial_binding_and_shared_mcp_path_are_retained(self):
        component = self.snapshot['groups'][0]['components'][0]
        component['installations'].append(dict(path=str(self.root / 'other'), status='cache-only'))
        self.assertEqual(len(pending_snapshot(self.snapshot, self.records, self.binding)['groups']), 1)
        component['installations'].pop()
        component['kind'] = 'mcp'
        self.assertEqual(len(pending_snapshot(self.snapshot, self.records, self.binding)['groups']), 1)

    def test_separate_data_complete_assets_and_no_overwrite(self):
        self.snapshot['groups'][0]['name'] = '</script><script>alert(1)</script>'
        output = self.root / 'workspace'
        result = build_workspace(self.manifest, self.snapshot, output)
        self.assertEqual((result['collected'], result['pending']), (1, 1))
        public = (output / 'data.js').read_text(encoding='utf-8')
        private = (output / 'discovery-data.js').read_text(encoding='utf-8')
        self.assertNotIn(str(self.root), public)
        self.assertNotIn('</script>', private)
        self.assertIn('\\u003c/script', private)
        import re
        for name in re.findall(r'(?:src|href)="([^"#]+)"', (output / 'index.html').read_text(encoding='utf-8')):
            self.assertTrue((output / name).is_file(), name)
        before = (output / 'discovery-data.js').read_bytes()
        with self.assertRaises(FileExistsError):
            build_workspace(self.manifest, self.snapshot, output)
        self.assertEqual((output / 'discovery-data.js').read_bytes(), before)

    def test_git_repository_output_and_wrong_snapshot_are_rejected(self):
        (self.root / '.git').mkdir()
        with self.assertRaises(ValueError):
            build_workspace(self.manifest, self.snapshot, self.root / 'workspace')
        self.assertFalse((self.root / 'workspace').exists())
        self.snapshot['snapshotType'] = 'collection'
        with self.assertRaises(ValueError):
            pending_snapshot(self.snapshot, [])

    def test_legacy_collection_and_machine_records_survive_new_workspace(self):
        # A code update reads the old formats without rewriting the collection or its binding.
        manifest = dict(schemaVersion=1, customField={'keep': True}, resources=[
            dict(id='skill:stable', name='Renamed', kind='skill', ownership='self',
                 sourceIdentity='self:stable', management='managed', parentId='bundle:stable'),
            dict(id='mcp:official', name='Third party', kind='mcp', ownership='third-party',
                 sourceIdentity='https://example.invalid/official', version='old-shared',
                 state=dict(collection='collected'))])
        records = [dict(id='skill:stable', kind='skill', sourceIdentity='self:stable',
                        parentId='bundle:stable', state=dict(collection='collected', installation='installed', sync='failed')),
                   dict(id='mcp:official', kind='mcp', sourceIdentity='https://example.invalid/official',
                        revision='verified-local', state=dict(collection='collected', installation='installed'))]
        binding = dict(taskSync=dict(resources=[dict(id='skill:stable', installedPath=str(self.root / 'skill'))]))
        inputs = {'toolbox.json': manifest, 'decisions.json': {'schemaVersion': 1, 'records': records},
                  'binding.json': binding, 'journal.json': {'pending': {'preserve': True}}}
        for name, data in inputs.items():
            (self.root / name).write_text(json.dumps(data), encoding='utf-8')
        before = {name: (self.root / name).read_bytes() for name in inputs}
        old = export(manifest, records=records)
        result = build_workspace(manifest, self.snapshot, self.root / 'upgraded', records, binding)
        generated = (self.root / 'upgraded/data.js').read_text(encoding='utf-8')
        self.assertEqual(json.loads(generated.split('=', 1)[1].rstrip(';\n')), old)
        self.assertEqual([row['id'] for row in old['resources']], ['skill:stable', 'mcp:official'])
        self.assertEqual(old['resources'][0]['state']['sync'], 'failed')
        self.assertEqual(old['resources'][0]['state']['collection'], 'collected')
        self.assertEqual(old['resources'][1]['version'], 'verified-local')
        self.assertEqual((result['collected'], result['pending']), (2, 0))
        for name in inputs:
            self.assertEqual((self.root / name).read_bytes(), before[name], name)
        # Missing optional records are not a request to erase the old collection.
        plain = build_workspace(manifest, None, self.root / 'collection-only')
        self.assertEqual((plain['collected'], plain['pending']), (2, 0))
        self.assertEqual((self.root / 'collection-only/discovery-data.js').read_text(encoding='utf-8').strip(),
                         'window.TOOLBOX_DISCOVERY = null;')

    def test_identity_conflict_leaves_existing_workspace_and_inputs_untouched(self):
        manifest = copy.deepcopy(self.manifest)
        manifest['resources'][0]['sourceIdentity'] = 'self:one'
        records = [dict(id='skill:one', sourceIdentity='self:other', state=dict(collection='collected'))]
        output = self.root / 'conflict'
        with self.assertRaisesRegex(ValueError, 'identity'):
            build_workspace(manifest, self.snapshot, output, records)
        self.assertFalse(output.exists())

    def test_real_catalog_cannot_replace_a_tracked_template(self):
        source = self.root / 'manifest.json'
        source.write_text(json.dumps(self.manifest), encoding='utf-8')
        target_root = self.root / 'repository'
        (target_root / '.git').mkdir(parents=True)
        target = target_root / 'data.js'
        target.write_bytes(b'original template')
        script = Path(__file__).parent / 'build_catalog.py'
        result = subprocess.run([sys.executable, '-B', str(script), str(source), str(target)], capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(target.read_bytes(), b'original template')


if __name__ == '__main__':
    unittest.main(verbosity=2)
