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
            {'id': 'demo-stable', 'ownership': 'self', 'contentPath': 'skills/demo'}]}), encoding='utf-8')
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
                               resourceIds=['demo-stable']),
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


if __name__ == '__main__':
    unittest.main()
