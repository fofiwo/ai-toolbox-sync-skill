"""Workspace regression checks use synthetic metadata, never the user's inventory."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
import subprocess
import sys
import shutil
import io
from contextlib import redirect_stdout
from unittest.mock import patch

import build_workspace as workspace

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
        skill = Path(__file__).resolve().parent.parent
        version = re.search(r'^  version:\s*(\S+)', (skill / 'SKILL.md').read_text(encoding='utf-8'), re.M).group(1)
        self.assertIn('个人 AI 工具箱 / ' + version,
                      (output / 'index.html').read_text(encoding='utf-8'))
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


class WorkspaceCacheTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.skills = self.root / 'skills'
        self.skill = self.skills / 'demo' / 'SKILL.md'
        self.skill.parent.mkdir(parents=True)
        self.skill.write_text('---\nname: Demo\n---\n', encoding='utf-8')
        self.manifest = self.root / 'toolbox.json'
        self.manifest.write_text(json.dumps(dict(schemaVersion=1, resources=[])), encoding='utf-8')
        self.cache = self.root / 'cache'

    def refresh(self, **kwargs):
        return workspace.refresh_workspace(self.manifest, self.cache, [self.skills], **kwargs)

    def test_first_open_populates_and_unchanged_open_reuses_verified_cache(self):
        first = self.refresh()
        self.assertEqual((first['status'], first['pending']), ('updated', 1))
        page = Path(first['output'])
        before = {p.name: p.read_bytes() for p in page.parent.iterdir()}
        state = (self.cache / 'cache.json').read_bytes()
        second = self.refresh()
        self.assertEqual((second['status'], second['output'], second['generatedAt']),
                         ('cached', first['output'], first['generatedAt']))
        self.assertEqual((self.cache / 'cache.json').read_bytes(), state)
        self.assertEqual({p.name: p.read_bytes() for p in page.parent.iterdir()}, before)
        discovery = json.loads((page.parent / 'discovery-data.js').read_text(encoding='utf-8').split('=', 1)[1].rstrip(';\n'))
        self.assertEqual(discovery['groups'][0]['components'][0]['name'], 'Demo')
        self.assertEqual((self.cache / 'refresh.lock').read_bytes(), b'\0')

    def test_add_rename_remove_and_collection_changes_refresh_without_overwriting_old_page(self):
        first = self.refresh()
        old = Path(first['output']).read_bytes()
        self.skill.write_text('---\nname: Renamed\n---\n', encoding='utf-8')
        renamed = self.refresh()
        self.assertEqual(renamed['status'], 'updated')
        self.assertIn('Renamed', (Path(renamed['output']).parent / 'discovery-data.js').read_text(encoding='utf-8'))
        extra = self.skills / 'extra' / 'SKILL.md'
        extra.parent.mkdir()
        extra.write_text('---\nname: Extra\n---\n', encoding='utf-8')
        self.assertEqual(self.refresh()['pending'], 2)
        extra.unlink()
        self.assertEqual(self.refresh()['pending'], 1)
        self.manifest.write_text(json.dumps(dict(schemaVersion=1, resources=[dict(id='demo', kind='skill', name='Collected')])), encoding='utf-8')
        changed = self.refresh()
        self.assertEqual((changed['status'], changed['collected']), ('updated', 1))
        self.assertEqual(Path(first['output']).read_bytes(), old)

    def test_scan_failure_retains_last_good_cache_and_first_failure_cannot_claim_success(self):
        first = self.refresh()
        before = (self.cache / 'cache.json').read_bytes()
        with patch.object(workspace.Inventory, 'skills', side_effect=OSError('fixture access denied')):
            stale = self.refresh()
        self.assertEqual((stale['status'], stale['output']), ('stale-cache', first['output']))
        self.assertIn('未确认最新', stale['warning'])
        self.assertEqual((self.cache / 'cache.json').read_bytes(), before)
        with self.assertRaises(OSError):
            workspace.refresh_workspace(self.manifest, self.root / 'empty-cache', [self.root / 'missing'])
        self.assertEqual((self.cache / 'refresh.lock').read_bytes(), b'\0')

    def test_different_scope_cannot_fall_back_to_old_inventory(self):
        self.refresh()
        with self.assertRaises(OSError):
            workspace.refresh_workspace(self.manifest, self.cache, [self.root / 'missing'])

    def test_tampered_page_and_template_update_rebuild_cache(self):
        first = self.refresh()
        Path(first['output']).write_text('tampered', encoding='utf-8')
        repaired = self.refresh()
        self.assertEqual(repaired['status'], 'updated')
        self.assertNotEqual(repaired['output'], first['output'])
        assets = self.root / 'assets'
        shutil.copytree(workspace.ASSETS, assets)
        with (assets / 'style.css').open('a', encoding='utf-8') as stream:
            stream.write('\n/* updated template */\n')
        with patch.object(workspace, 'ASSETS', assets):
            updated = self.refresh()
        self.assertEqual(updated['status'], 'updated')
        self.assertIn('updated template', (Path(updated['output']).parent / 'style.css').read_text(encoding='utf-8'))

    def test_collection_records_and_binding_refresh_pending_exclusions(self):
        self.manifest.write_text(json.dumps(dict(schemaVersion=1, resources=[dict(id='demo', kind='skill', name='Demo')])), encoding='utf-8')
        records = self.root / 'decisions.json'
        records.write_text(json.dumps(dict(schemaVersion=1, records=[])), encoding='utf-8')
        binding = self.root / 'binding.json'
        binding.write_text(json.dumps(dict(taskSync=dict(resources=[dict(id='demo', installedPath=str(self.skill.parent))]))), encoding='utf-8')
        first = self.refresh(records=records, binding=binding)
        records.write_text(json.dumps(dict(schemaVersion=1, records=[dict(id='demo', state=dict(collection='collected'))])), encoding='utf-8')
        second = self.refresh(records=records, binding=binding)
        self.assertEqual((first['pending'], second['pending'], second['status']), (1, 0, 'updated'))

    def test_lock_invalid_inputs_and_unrelated_directory_are_preserved(self):
        self.refresh()
        lock = self.cache / 'refresh.lock'
        lock.write_text('other writer', encoding='ascii')
        with self.assertRaisesRegex(ValueError, 'Unknown workspace lock'):
            self.refresh()
        self.assertEqual(lock.read_text(encoding='ascii'), 'other writer')
        other = self.root / 'unrelated'
        other.mkdir()
        (other / 'keep.txt').write_text('keep', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'unrelated'):
            workspace.refresh_workspace(self.manifest, other, [self.skills])
        with self.assertRaisesRegex(ValueError, 'regular JSON'):
            workspace.refresh_workspace(self.root / '.env', self.root / 'unused', [self.skills])
        self.assertFalse((self.root / 'unused').exists())

    def test_open_entry_uses_checked_cache_and_reports_stale_fallback(self):
        first = self.refresh()
        argv = ['build_workspace.py', '--refresh', '--manifest', str(self.manifest),
                '--skill-root', str(self.skills), '--output', str(self.cache), '--open']
        with patch.object(sys, 'argv', argv), patch('webbrowser.open') as opened, redirect_stdout(io.StringIO()) as output:
            self.assertEqual(workspace.main(), 0)
        self.assertEqual(json.loads(output.getvalue())['status'], 'cached')
        opened.assert_called_once_with(json.loads(output.getvalue())['url'])
        with patch.object(sys, 'argv', argv), patch('webbrowser.open') as opened, \
                patch.object(workspace.Inventory, 'skills', side_effect=OSError('fixture unavailable')), \
                redirect_stdout(io.StringIO()) as output:
            self.assertEqual(workspace.main(), 2)
        self.assertEqual(json.loads(output.getvalue())['status'], 'stale-cache')
        opened.assert_called_once_with(json.loads(output.getvalue())['url'])
        self.assertIn('toolbox-check=stale-cache', opened.call_args.args[0])

    def test_native_lock_blocks_concurrent_writer_and_recovers_after_crash(self):
        self.refresh()
        lock = self.cache / 'refresh.lock'
        script = 'import sys,time; from pathlib import Path; from build_workspace import workspace_lock\nwith workspace_lock(Path(sys.argv[1])):\n print("locked",flush=True)\n time.sleep(30)'
        child = subprocess.Popen([sys.executable, '-B', '-c', script, str(lock)],
                                 cwd=Path(workspace.__file__).parent, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            self.assertEqual(child.stdout.readline().strip(), b'locked')
            with self.assertRaises(OSError):
                self.refresh()
        finally:
            child.kill()
            child.communicate(timeout=10)
        self.assertEqual(self.refresh()['status'], 'cached')
        # A crash before the first cache marker was written also remains recoverable.
        fresh = self.root / 'interrupted'
        fresh.mkdir()
        (fresh / 'refresh.lock').write_bytes(b'\0')
        self.assertEqual(workspace.refresh_workspace(self.manifest, fresh, [self.skills])['status'], 'updated')

    def test_input_change_during_scan_or_build_never_claims_fresh_or_replaces_cache(self):
        self.refresh()
        before = (self.cache / 'cache.json').read_bytes()
        original = self.manifest.read_bytes()
        scan = workspace.Inventory.skills
        def changed(inv, root):
            scan(inv, root)
            self.manifest.write_text(json.dumps(dict(schemaVersion=1, resources=[dict(id='new', kind='skill', name='New')])), encoding='utf-8')
        with patch.object(workspace.Inventory, 'skills', changed), self.assertRaisesRegex(ValueError, 'inputs changed'):
            self.refresh()
        self.assertEqual((self.cache / 'cache.json').read_bytes(), before)
        self.manifest.write_bytes(original)
        build = workspace.build_workspace
        def changed_build(*args, **kwargs):
            result = build(*args, **kwargs)
            self.manifest.write_text('{"schemaVersion":1,"resources":[{"id":"new","kind":"skill"}]}', encoding='utf-8')
            return result
        self.skill.write_text('---\nname: Changed\n---', encoding='utf-8')
        with patch.object(workspace, 'build_workspace', changed_build), self.assertRaisesRegex(ValueError, 'inputs changed'):
            self.refresh()
        self.assertEqual((self.cache / 'cache.json').read_bytes(), before)

    def test_browser_open_failure_is_not_success(self):
        argv = ['build_workspace.py', '--refresh', '--manifest', str(self.manifest),
                '--skill-root', str(self.skills), '--output', str(self.cache), '--open']
        with patch.object(sys, 'argv', argv), patch('webbrowser.open', return_value=False), redirect_stdout(io.StringIO()):
            self.assertEqual(workspace.main(), 1)

    def test_failed_cache_publish_keeps_previous_pointer_and_old_page(self):
        first = self.refresh()
        state = (self.cache / 'cache.json').read_bytes()
        page = Path(first['output']).read_bytes()
        self.skill.write_text('---\nname: Changed\n---', encoding='utf-8')
        with patch.object(workspace, 'atomic', side_effect=OSError('fixture disk full')):
            result = self.refresh()
        self.assertEqual((result['status'], result['output']), ('stale-cache', first['output']))
        self.assertEqual((self.cache / 'cache.json').read_bytes(), state)
        self.assertEqual(Path(first['output']).read_bytes(), page)
        self.assertEqual(self.refresh()['status'], 'updated')

    def test_process_exit_during_first_atomic_write_recovers_without_removing_debris(self):
        script = ('import sys,os;from pathlib import Path;import build_workspace as w\n'
                  'def interrupted(p,b):\n (p.parent/"tmp-interrupted").write_bytes(b)\n os._exit(99)\n'
                  'w.atomic=interrupted\nw.refresh_workspace(Path(sys.argv[1]),Path(sys.argv[2]),[Path(sys.argv[3])])')
        child = subprocess.run([sys.executable, '-B', '-c', script, str(self.manifest), str(self.cache), str(self.skills)],
                               cwd=Path(workspace.__file__).parent, capture_output=True, timeout=10)
        self.assertEqual(child.returncode, 99)
        self.assertFalse((self.cache / 'cache.json').exists())
        debris = (self.cache / 'tmp-interrupted').read_bytes()
        self.assertEqual(self.refresh()['status'], 'updated')
        self.assertEqual((self.cache / 'tmp-interrupted').read_bytes(), debris)

    def test_corrupt_cache_or_invalid_collection_never_opens_as_success(self):
        self.refresh()
        state = (self.cache / 'cache.json').read_bytes()
        for bad in ('not json', '{"schemaVersion":99}', '{"schemaVersion":1,"cacheType":"local-workspace","generation":"../escape"}'):
            with self.subTest(bad=bad):
                (self.cache / 'cache.json').write_text(bad, encoding='utf-8')
                with self.assertRaises(ValueError):
                    self.refresh()
        (self.cache / 'cache.json').write_bytes(state)
        self.manifest.write_text('{"schemaVersion":1,"resources":"invalid"}', encoding='utf-8')
        with self.assertRaises(ValueError):
            self.refresh()
        self.assertEqual((self.cache / 'cache.json').read_bytes(), state)


if __name__ == '__main__':
    unittest.main(verbosity=2)
