"""Real local Git lifecycle and legacy binding compatibility, without another manager."""
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import sync_session as session


class NativeGitTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='toolbox-native-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.environment = patch.dict(os.environ, {
            'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': os.devnull,
            'GIT_ALLOW_PROTOCOL': 'file', 'GIT_AUTHOR_NAME': 'Fixture',
            'GIT_AUTHOR_EMAIL': 'fixture@example.invalid',
            'GIT_COMMITTER_NAME': 'Fixture', 'GIT_COMMITTER_EMAIL': 'fixture@example.invalid',
            'GIT_CONFIG_COUNT': '2', 'GIT_CONFIG_KEY_0': 'core.autocrlf',
            'GIT_CONFIG_VALUE_0': 'false', 'GIT_CONFIG_KEY_1': 'core.hooksPath',
            'GIT_CONFIG_VALUE_1': str(self.root / 'no-hooks'),
        })
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.repo, self.remote = self.root / 'repo', self.root / 'remote.git'
        self.repo.mkdir()
        self.git(self.root, 'init', '--bare', '--initial-branch=main', str(self.remote))
        self.git(self.repo, 'init', '--initial-branch=main')
        self.git(self.repo, 'remote', 'add', 'origin', str(self.remote))
        self.source = self.repo / 'skills/demo'
        self.source.mkdir(parents=True)
        (self.source / 'SKILL.md').write_text('base\n', encoding='utf-8')
        self.manifest = self.repo / 'toolbox.json'
        self.manifest.write_text(json.dumps({'schemaVersion': 1, 'resources': [
            {'id': 'demo-stable', 'kind': 'skill', 'name': 'demo', 'sourceIdentity': 'self:demo',
             'ownership': 'self', 'contentPath': 'skills/demo'}]}), encoding='utf-8')
        self.git(self.repo, '--literal-pathspecs', 'add', '--', 'toolbox.json', 'skills/demo/SKILL.md')
        self.git(self.repo, 'commit', '-m', 'fixture base')
        self.base = self.git(self.repo, 'rev-parse', 'HEAD')
        self.push(self.repo, self.base)
        self.installed = self.root / 'installed'
        shutil.copytree(self.source, self.installed)
        self.journal, self.binding_path = self.root / 'journal.json', self.root / 'binding.json'
        self.binding = dict(schemaVersion=1, runtime=dict(gitPath=shutil.which('git')),
            paths=dict(gitRoot=str(self.repo)),
            authorization=dict(status='granted', repository=str(self.remote), branch='main',
                               resourceIds=['demo-stable'], operations=['collect', 'commit', 'pull', 'push']),
            taskSync=dict(enabled=True, journalPath=str(self.journal), resources=[dict(
                id='demo-stable', sourcePath=str(self.source), installedPath=str(self.installed),
                runtimeExclusions=[], applicationMode='reviewed-files')]))
        self.binding_path.write_text(json.dumps(self.binding), encoding='utf-8')

    def git(self, directory, *args):
        return subprocess.check_output(['git', '-C', str(directory), *args],
            env=dict(os.environ), stderr=subprocess.PIPE, text=True, timeout=30).strip()

    def push(self, directory, head):
        return self.git(directory, '-c', 'push.followTags=false', '-c',
            'remote.origin.mirror=false', 'push', '--', str(self.remote), head + ':refs/heads/main')

    def call(self, operation, **fields):
        return session.operate(self.journal, dict(operation=operation, owner='native-fixture', **fields))

    def observation(self, local_paths):
        probe = self.call('probe', repo=str(self.repo), remote=str(self.remote),
                          branch='main', strict=True, endPush=True)
        return dict(resourceId='demo-stable', sourceDigest=session.fingerprint(self.source),
            installedDigest=session.fingerprint(self.installed), remoteTip=probe['head'],
            head=self.git(self.repo, 'rev-parse', 'HEAD'), localPaths=local_paths, remotePaths=[],
            remoteAvailable=True, scopeReviewed=True, inUse=False)

    def test_native_commit_push_and_session_confirmation(self):
        before_manifest = self.manifest.read_bytes()
        before_binding = self.binding_path.read_bytes()
        self.call('begin', binding=str(self.binding_path))
        try:
            self.call('mark-dirty', resourceId='demo-stable')
            for directory in (self.source, self.installed):
                (directory / 'entry[1].txt').write_text('selected\n', encoding='utf-8')
                (directory / 'SKILL.md').write_text('selected update\n', encoding='utf-8')
            self.git(self.repo, '--literal-pathspecs', 'add', '--',
                     'skills/demo/entry[1].txt', 'skills/demo/SKILL.md')
            self.git(self.repo, 'commit', '-m', 'selected files')
            head = self.git(self.repo, 'rev-parse', 'HEAD')
            changed = ['skills/demo/entry[1].txt', 'skills/demo/SKILL.md']
            value = self.observation(changed)
            self.call('observe', observation=value)
            self.call('intent', action='push', head=head)
            self.push(self.repo, head)
            self.assertEqual(self.git(self.repo, 'ls-remote', str(self.remote), 'refs/heads/main').split()[0], head)
            value = self.observation([])
            self.call('resolve', observation=value, previousCommandFinished=True, applicationVerified=True)
            self.call('complete-work', previousCommandFinished=True)
            saved = json.loads(self.journal.read_bytes())
            self.assertEqual(saved['status'], 'confirmed')
            self.assertEqual(saved['workItems']['native-fixture']['demo-stable']['status'], 'complete')
            self.assertEqual(self.manifest.read_bytes(), before_manifest)
            self.assertEqual(self.binding_path.read_bytes(), before_binding)
        finally:
            self.call('release')

    def test_exact_paths_do_not_stage_unrelated_content(self):
        (self.source / 'entry[1].txt').write_text('chosen', encoding='utf-8')
        (self.source / 'entry1.txt').write_text('not chosen', encoding='utf-8')
        (self.repo / 'unrelated.txt').write_text('local only', encoding='utf-8')
        self.git(self.repo, '--literal-pathspecs', 'add', '--', 'skills/demo/entry[1].txt')
        self.assertEqual(self.git(self.repo, 'diff', '--cached', '--name-only'), 'skills/demo/entry[1].txt')
        self.assertIn('unrelated.txt', self.git(self.repo, 'ls-files', '--others', '--exclude-standard'))

    def test_legacy_binding_metadata_remains_untouched(self):
        legacy = copy.deepcopy(self.binding)
        legacy['cli'] = {'path': str(self.root / 'absent-legacy-cli'), 'expectedVersion': 'historical'}
        legacy['paths'].update(xdgConfigHome=str(self.root / 'old-config'),
                               skillshareConfig=str(self.root / 'absent-legacy-config'))
        self.binding_path.write_text(json.dumps(legacy), encoding='utf-8')
        before = self.binding_path.read_bytes()
        self.call('begin', binding=str(self.binding_path))
        try:
            self.call('observe', observation=self.observation([]))
            self.assertEqual(self.call('confirm')['status'], 'confirmed')
            self.assertEqual(self.binding_path.read_bytes(), before)
            saved = json.loads(self.journal.read_bytes())
            self.assertEqual(saved['baselines']['demo-stable']['resourceId'], 'demo-stable')
        finally:
            self.call('release')

    def test_fetch_does_not_apply_and_divergence_is_rejected(self):
        receiver = self.root / 'receiver'
        self.git(self.root, 'clone', '--no-checkout', '--no-tags', '--', str(self.remote), str(receiver))
        self.assertFalse((receiver / 'toolbox.json').exists())
        self.git(receiver, 'checkout', 'main')
        (self.source / 'SKILL.md').write_text('remote change\n', encoding='utf-8')
        self.git(self.repo, '--literal-pathspecs', 'add', '--', 'skills/demo/SKILL.md')
        self.git(self.repo, 'commit', '-m', 'remote update')
        remote_head = self.git(self.repo, 'rev-parse', 'HEAD')
        self.push(self.repo, remote_head)
        self.git(receiver, 'fetch', '--no-tags', '--no-write-fetch-head', '--', str(self.remote), 'refs/heads/main')
        self.assertEqual(self.git(receiver, 'rev-parse', 'HEAD'), self.base)
        self.assertEqual((receiver / 'skills/demo/SKILL.md').read_text(), 'base\n')
        (receiver / 'local.txt').write_text('preserve local history', encoding='utf-8')
        self.git(receiver, '--literal-pathspecs', 'add', '--', 'local.txt')
        self.git(receiver, 'commit', '-m', 'local change')
        local_head = self.git(receiver, 'rev-parse', 'HEAD')
        with self.assertRaises(subprocess.CalledProcessError):
            self.git(receiver, 'merge', '--ff-only', remote_head)
        with self.assertRaises(subprocess.CalledProcessError):
            self.push(receiver, local_head)
        self.assertEqual(self.git(receiver, 'rev-parse', 'HEAD'), local_head)
        self.assertTrue((receiver / 'local.txt').exists())
        self.assertEqual(self.git(self.repo, 'ls-remote', str(self.remote), 'refs/heads/main').split()[0], remote_head)

    def sync(self, **options):
        return session.collection_sync(self.binding_path, **options)

    def other(self):
        path = self.root / 'other'
        self.git(self.root, 'clone', '--', str(self.remote), str(path))
        return path

    def update(self, path, name, content, message='fixture change'):
        file = path / name
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(content, encoding='utf-8')
        self.git(path, '--literal-pathspecs', 'add', '--', name)
        self.git(path, 'commit', '-m', message)
        return self.git(path, 'rev-parse', 'HEAD')

    def test_status_is_local_and_does_not_write_journal(self):
        before = self.binding_path.read_bytes()
        with patch.object(session, 'collection_network', side_effect=AssertionError('unexpected network')):
            status = session.collection_status(self.binding_path)
        self.assertEqual(status['remoteVerification'], 'not-queried')
        self.assertEqual(status['resources'][0]['status'], 'equal')
        self.assertEqual(self.binding_path.read_bytes(), before)
        self.assertFalse(self.journal.exists())

    def test_dry_run_does_not_commit_stage_or_install(self):
        for directory in (self.source, self.installed):
            (directory / 'entry[1].txt').write_text('new source\n', encoding='utf-8')
        before = self.git(self.repo, 'write-tree')
        result = self.sync(dry_run=True)
        self.assertEqual(result['status'], 'planned')
        self.assertEqual(self.git(self.repo, 'rev-parse', 'HEAD'), self.base)
        self.assertEqual(self.git(self.repo, 'write-tree'), before)
        self.assertEqual(self.git(self.repo, 'ls-remote', str(self.remote), 'refs/heads/main').split()[0], self.base)
        self.assertFalse(self.journal.with_suffix('.flow.lock').exists())

    def test_sync_commits_uploads_and_is_idempotent(self):
        for directory in (self.source, self.installed):
            (directory / 'entry[1].txt').write_text('selected\n', encoding='utf-8')
        result = self.sync()
        self.assertEqual(result['status'], 'synced')
        self.assertNotEqual(result['head'], self.base)
        self.assertEqual(result['head'], self.git(self.remote, 'rev-parse', 'main'))
        self.assertEqual(self.sync()['head'], result['head'])
        self.assertFalse(self.git(self.repo, 'status', '--porcelain'))

    def test_legacy_crlf_index_and_mixed_worktree_match_planned_tree(self):
        name = 'skills/demo/entry[1].txt'
        raw = b'old\r\nsecond\r\n'
        (self.repo / name).write_bytes(raw)
        self.git(self.repo, 'config', 'core.autocrlf', 'false')
        self.git(self.repo, '--literal-pathspecs', 'add', '--', name)
        self.git(self.repo, 'commit', '-m', 'legacy CRLF index')
        self.push(self.repo, self.git(self.repo, 'rev-parse', 'HEAD'))
        self.git(self.repo, 'config', 'core.autocrlf', 'true')
        for directory in (self.source, self.installed):
            (directory / 'entry[1].txt').write_bytes(b'new\r\nsecond\n')
        result = self.sync()
        self.assertEqual(result['status'], 'synced')
        self.assertEqual(self.sync()['head'], result['head'])

    def test_remote_only_fast_forwards_without_installing(self):
        other = self.other()
        head = self.update(other, 'skills/demo/new.txt', 'remote\n')
        self.push(other, head)
        result = self.sync()
        self.assertEqual(result['head'], head)
        self.assertTrue((self.source / 'new.txt').exists())
        self.assertFalse((self.installed / 'new.txt').exists())
        self.assertEqual(result['installations']['demo-stable']['status'], 'source-only')
        self.assertEqual(self.sync()['head'], head)

    def test_git_merges_different_changes_in_same_file(self):
        text = ''.join(str(i) + '\n' for i in range(20))
        head = self.update(self.repo, 'skills/demo/SKILL.md', text)
        (self.installed / 'SKILL.md').write_text(text, encoding='utf-8')
        self.push(self.repo, head)
        other = self.other()
        tip = self.update(other, 'skills/demo/SKILL.md', text.replace('19\n', 'remote\n'))
        self.push(other, tip)
        for directory in (self.source, self.installed):
            (directory / 'SKILL.md').write_text(text.replace('0\n', 'local\n', 1), encoding='utf-8')
        result = self.sync()
        self.assertEqual(result['status'], 'synced')
        self.assertEqual((self.source / 'SKILL.md').read_text(), text.replace('0\n', 'local\n', 1).replace('19\n', 'remote\n'))
        self.assertEqual(len(self.git(self.repo, 'rev-list', '--parents', '-n', '1', 'HEAD').split()), 3)
        self.assertNotIn('remote', (self.installed / 'SKILL.md').read_text())

    def test_real_conflict_keeps_working_copy_and_history(self):
        other = self.other()
        tip = self.update(other, 'skills/demo/SKILL.md', 'remote\n')
        self.push(other, tip)
        for directory in (self.source, self.installed):
            (directory / 'SKILL.md').write_text('local\n', encoding='utf-8')
        result = self.sync()
        self.assertEqual(result['status'], 'conflict-review')
        self.assertEqual(result['conflicts'], ['skills/demo/SKILL.md'])
        self.assertEqual(self.git(self.repo, 'rev-parse', 'HEAD'), self.base)
        self.assertEqual((self.source / 'SKILL.md').read_text(), 'local\n')
        self.assertFalse(self.git(self.repo, 'diff', '--cached', '--name-only'))

    def test_manifest_merges_independent_resource_additions_by_id(self):
        other = self.other()
        def add(path, identity):
            doc = json.loads((path / 'toolbox.json').read_bytes())
            doc['resources'].append(dict(id=identity, kind='mcp', name=identity,
                sourceIdentity='third-party:' + identity, ownership='third-party', source='https://example.invalid/' + identity))
            return json.dumps(doc, indent=2) + '\n'
        tip = self.update(other, 'toolbox.json', add(other, 'remote-index'))
        self.push(other, tip)
        self.manifest.write_text(add(self.repo, 'local-index'), encoding='utf-8')
        result = self.sync()
        self.assertEqual(result['status'], 'synced')
        self.assertEqual({r['id'] for r in json.loads(self.manifest.read_bytes())['resources']},
                         {'demo-stable', 'remote-index', 'local-index'})
        self.assertEqual(self.sync()['head'], result['head'])

    def test_manifest_reordering_is_stable_and_real_order_conflicts_stop(self):
        rows = [dict(id=n, kind='mcp', name=n, ownership='third-party', sourceIdentity='upstream:' + n) for n in 'abc']
        def doc(order):
            return json.dumps(dict(schemaVersion=1, resources=[rows[i] for i in order])).encode()
        base, remote = doc([0, 1, 2]), doc([2, 1, 0])
        self.assertEqual(session.collection_merge_manifest(base, base, remote, set()), remote)
        with self.assertRaises(ValueError):
            session.collection_merge_manifest(base, doc([1, 0, 2]), doc([0, 2, 1]), set())

    def test_modify_delete_and_identity_changes_are_not_auto_merged(self):
        base = self.manifest.read_bytes()
        changed = json.loads(base)
        changed['resources'][0]['description'] = 'local change'
        empty = json.dumps(dict(schemaVersion=1, resources=[])).encode()
        with self.assertRaises(ValueError):
            session.collection_merge_manifest(base, json.dumps(changed).encode(), empty, {'demo-stable'})
        changed['resources'][0]['sourceIdentity'] = 'different'
        with self.assertRaises(ValueError):
            session.collection_merge_manifest(base, json.dumps(changed).encode(), base, set())

    def test_installed_only_uses_trusted_baseline_and_keeps_backup(self):
        self.call('begin', binding=str(self.binding_path))
        self.call('observe', observation=self.observation([]))
        self.call('confirm')
        self.call('release')
        (self.installed / 'SKILL.md').write_text('installed edit\n', encoding='utf-8')
        result = self.sync()
        self.assertEqual(result['status'], 'synced')
        self.assertEqual((self.source / 'SKILL.md').read_text(), 'installed edit\n')
        backups = list((self.root / 'sync-runs').glob('*/SKILL.md'))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_text(), 'base\n')

    def test_unknown_installation_drift_does_not_collect(self):
        (self.installed / 'SKILL.md').write_text('unknown change\n', encoding='utf-8')
        with self.assertRaises(ValueError):
            self.sync()
        self.assertEqual((self.source / 'SKILL.md').read_text(), 'base\n')
        self.assertEqual(self.git(self.repo, 'rev-parse', 'HEAD'), self.base)

    def test_delete_requires_exact_approval(self):
        for directory in (self.source, self.installed):
            (directory / 'SKILL.md').unlink()
        with self.assertRaises(ValueError):
            self.sync()
        result = self.sync(allow_delete=['skills/demo/SKILL.md'])
        self.assertEqual(result['status'], 'synced')
        self.assertNotIn('skills/demo/SKILL.md', self.git(self.remote, 'ls-tree', '-r', '--name-only', 'main'))

    def test_unknown_staged_and_sensitive_files_are_preserved(self):
        (self.repo / 'outside.txt').write_text('unrelated', encoding='utf-8')
        self.git(self.repo, 'add', '--', 'outside.txt')
        index = self.git(self.repo, 'write-tree')
        with self.assertRaises(ValueError):
            self.sync()
        self.assertEqual(self.git(self.repo, 'write-tree'), index)
        (self.source / '.ENV.private').write_text('never read', encoding='utf-8')
        with self.assertRaises(ValueError):
            session.collection_status(self.binding_path)

    def test_temporary_unapproved_history_cannot_be_uploaded(self):
        self.update(self.repo, 'private-note.txt', 'do not upload')
        self.git(self.repo, 'rm', '--', 'private-note.txt')
        self.git(self.repo, 'commit', '-m', 'remove private note')
        head = self.git(self.repo, 'rev-parse', 'HEAD')
        with self.assertRaises(ValueError):
            self.sync()
        self.assertEqual(self.git(self.repo, 'rev-parse', 'HEAD'), head)
        self.assertEqual(self.git(self.remote, 'rev-parse', 'main'), self.base)

    def test_uncertain_push_is_verified_on_resume_without_duplicate_commit(self):
        for directory in (self.source, self.installed):
            (directory / 'new.txt').write_text('selected\n', encoding='utf-8')
        original = session.collection_network
        def uncertain(repo, *args):
            value = original(repo, *args)
            if args[0] == 'push':
                raise ValueError('Synthetic lost response after successful push')
            return value
        with patch.object(session, 'collection_network', side_effect=uncertain), self.assertRaises(ValueError):
            self.sync()
        head = self.git(self.repo, 'rev-parse', 'HEAD')
        receipts = [json.loads(p.read_bytes()) for p in (self.root / 'sync-runs').glob('*.json')]
        self.assertTrue(any(p['phase'] == 'push-pending' and p['head'] == head for p in receipts))
        self.assertEqual(self.sync()['head'], head)

    def test_remote_advance_retains_local_commit_then_merges_on_resume(self):
        other = self.other()
        for directory in (self.source, self.installed):
            (directory / 'local.txt').write_text('local\n', encoding='utf-8')
        original = session.collection_network
        probes = []
        def moving(repo, *args):
            if args[0] == 'ls-remote':
                probes.append(1)
                if len(probes) == 3:
                    tip = self.update(other, 'skills/demo/remote.txt', 'remote\n')
                    self.push(other, tip)
            return original(repo, *args)
        with patch.object(session, 'collection_network', side_effect=moving):
            result = self.sync()
        self.assertEqual(result['status'], 'remote-advanced')
        self.assertNotEqual(result['head'], self.base)
        self.assertEqual(self.sync()['status'], 'synced')
        self.assertTrue((self.source / 'local.txt').exists())
        self.assertTrue((self.source / 'remote.txt').exists())

    def test_existing_workflow_lock_is_not_stolen(self):
        self.call('begin', binding=str(self.binding_path))
        try:
            with self.assertRaises(FileExistsError):
                self.sync()
            self.assertEqual(json.loads(self.journal.with_suffix('.flow.lock').read_bytes())['owner'], 'native-fixture')
        finally:
            self.call('release')

    def test_push_url_mismatch_and_ignored_source_stop_before_commit(self):
        self.git(self.repo, 'remote', 'set-url', '--push', 'origin', str(self.root / 'unapproved.git'))
        with self.assertRaises(ValueError):
            session.collection_status(self.binding_path)
        self.git(self.repo, 'remote', 'set-url', '--push', 'origin', str(self.remote))
        self.update(self.repo, '.gitignore', '*.cache\n')
        head = self.git(self.repo, 'rev-parse', 'HEAD')
        self.push(self.repo, head)
        for directory in (self.source, self.installed):
            (directory / 'needed.cache').write_text('required source\n', encoding='utf-8')
        with self.assertRaises(ValueError):
            self.sync(dry_run=True)
        self.assertEqual(self.git(self.repo, 'rev-parse', 'HEAD'), head)

    def test_transport_failure_switches_once_but_authentication_does_not(self):
        attempts = []
        def transport(repo, *args, **kwargs):
            if args[0] == 'config':
                return subprocess.CompletedProcess(args, 1, b'', b'')
            attempts.append(args)
            return subprocess.CompletedProcess(args, 128 if len(attempts) == 1 else 0,
                                               b'checked', b'Could not resolve host')
        with patch.object(session, 'collection_git', side_effect=transport):
            self.assertEqual(session.collection_network(self.repo, 'ls-remote', 'https://example.invalid/repo', 'refs/heads/main'), b'checked')
        self.assertEqual(len(attempts), 2)
        self.assertEqual(attempts[1][0], '-c')
        attempts.clear()
        def authentication(repo, *args, **kwargs):
            if args[0] == 'config':
                return subprocess.CompletedProcess(args, 1, b'', b'')
            attempts.append(args)
            return subprocess.CompletedProcess(args, 128, b'', b'could not read Username')
        with patch.object(session, 'collection_git', side_effect=authentication), self.assertRaises(ValueError):
            session.collection_network(self.repo, 'ls-remote', 'https://example.invalid/repo', 'refs/heads/main')
        self.assertEqual(len(attempts), 1)


if __name__ == '__main__':
    unittest.main()
