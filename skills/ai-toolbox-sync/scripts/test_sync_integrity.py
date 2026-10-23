"""Regression tests for incomplete commits, stale evidence and recoverable sessions."""
import copy
import sys
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch
import sync_integrity as integrity
import sync_session as m


class IntegrityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='toolbox-integrity-')
        self.root = Path(self.tmp.name)
        self.env_patch = patch.dict(os.environ, dict(GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull,
            GIT_ALLOW_PROTOCOL='file', GIT_AUTHOR_NAME='Fixture', GIT_AUTHOR_EMAIL='fixture@example.invalid',
            GIT_COMMITTER_NAME='Fixture', GIT_COMMITTER_EMAIL='fixture@example.invalid',
            GIT_CONFIG_COUNT='1', GIT_CONFIG_KEY_0='core.autocrlf', GIT_CONFIG_VALUE_0='false'))
        self.env_patch.start()
        self.repo, self.remote = self.root/'repo', self.root/'remote.git'
        self.repo.mkdir()
        self.git(self.root, 'init', '--bare', '--initial-branch=main', str(self.remote))
        self.git(self.repo, 'init', '--initial-branch=main')
        self.git(self.repo, 'remote', 'add', 'origin', str(self.remote))
        self.source, self.installed = self.repo/'skills/example', self.root/'installed'
        self.source.mkdir(parents=True)
        (self.source/'SKILL.md').write_text('fixture', encoding='utf-8')
        self.commit()
        self.git(self.repo, 'push', 'origin', 'main')
        shutil.copytree(self.source, self.installed)
        self.state_path, self.binding = self.root/'journal.json', self.root/'binding.json'
        self.bound = dict(paths=dict(gitRoot=str(self.repo)),
            authorization=dict(status='granted', repository=str(self.remote), branch='main',resourceIds=['fixture']),
            taskSync=dict(enabled=True,journalPath=str(self.state_path),resources=[dict(id='fixture',
                sourcePath=str(self.source),installedPath=str(self.installed),runtimeExclusions=[])]))
        self.binding.write_text(json.dumps(self.bound))
        self.call('begin', binding=str(self.binding))

    def tearDown(self):
        if self.state_path.with_suffix('.flow.lock').exists():
            self.call('release')
        self.env_patch.stop()
        self.tmp.cleanup()

    def git(self, repo, *args):
        return subprocess.check_output(['git','-C',str(repo),*args],env=dict(os.environ),stderr=subprocess.PIPE,text=True).strip()

    def commit(self):
        self.git(self.repo,'add','-A')
        self.git(self.repo,'commit','-m','fixture')
        return self.git(self.repo,'rev-parse','HEAD')

    def call(self, operation, **fields):
        return m.operate(self.state_path,dict(operation=operation,owner='fixture-task',**fields))

    def observe(self, **fields):
        probe = self.call('probe',repo=str(self.repo),remote=str(self.remote),branch='main',strict=True,endPush=True)
        value = dict(resourceId='fixture',sourceDigest=m.fingerprint(self.source),installedDigest=m.fingerprint(self.installed),
            head=self.git(self.repo,'rev-parse','HEAD'),remoteTip=probe['head'],localPaths=[],remotePaths=[],
            remoteAvailable=True,scopeReviewed=True,inUse=False)
        value.update(fields)
        self.call('observe',observation=value)
        return value

    def test_real_commit_confirmation_and_interrupted_work_recovery(self):
        self.call('mark-dirty',resourceId='fixture')
        self.call('release')
        resumed = self.call('begin')
        self.assertEqual(resumed['workItems']['fixture-task']['fixture']['status'],'pending')
        self.observe()
        self.assertEqual(self.call('confirm')['status'],'confirmed')
        self.call('complete-work',previousCommandFinished=True)
        doc=json.loads(self.state_path.read_text())
        self.assertEqual(doc['workItems']['fixture-task']['fixture']['status'],'complete')
        self.assertEqual(doc['integrity']['fileCount'],1)

    def test_locator_and_empty_windows_git_setting(self):
        pointer=self.root/'.agents/ai-toolbox-sync/binding-pointer.json'
        pointer.parent.mkdir(parents=True)
        pointer.write_text(json.dumps(dict(schemaVersion=1,bindingPath=str(self.binding))))
        with patch.object(Path,'home',return_value=self.root):
            self.assertEqual(m.locate_binding(),(self.binding,self.state_path))
        with patch.dict(os.environ,dict(GIT_CONFIG_COUNT='1',GIT_CONFIG_KEY_0='credential.helper',GIT_CONFIG_VALUE_0='')):
            self.observe()
            self.assertEqual(self.call('confirm')['status'],'confirmed')

    def test_ignored_required_asset_blocks_confirm(self):
        (self.repo/'.gitignore').write_text('skills/example/assets/\n')
        self.commit(); self.git(self.repo,'push','origin','main')
        for folder in (self.source,self.installed):
            (folder/'assets').mkdir(); (folder/'assets/required.txt').write_text('needed')
        self.assertEqual(self.git(self.repo,'status','--porcelain'),'')
        self.observe()
        with self.assertRaisesRegex(ValueError,'coverage mismatch'):
            self.call('confirm')
        self.assertNotEqual(json.loads(self.state_path.read_text())['status'],'confirmed')

    def test_post_observe_edit_and_committed_extra_file_are_blocked(self):
        self.observe()
        (self.source/'SKILL.md').write_text('changed')
        with self.assertRaisesRegex(ValueError,'Committed content differs'):
            self.call('confirm')
        (self.source/'SKILL.md').unlink()
        with self.assertRaisesRegex(ValueError,'coverage mismatch'):
            self.call('confirm')

    def test_scan_error_propagates(self):
        real_walk=integrity.os.walk
        def failing(top, *args, **kwargs):
            yield next(real_walk(top))
            kwargs['onerror'](PermissionError('synthetic scandir failure'))
        with patch.object(integrity.os,'walk',failing), self.assertRaises(PermissionError):
            m.fingerprint(self.source)

    def test_new_session_cannot_reuse_old_live_or_missing_probe(self):
        old=self.observe()
        self.call('confirm'); self.call('release'); self.call('begin')
        with self.assertRaisesRegex(ValueError,'Fresh live evidence'):
            self.call('observe',observation=old)
        with self.assertRaises(ValueError):
            self.call('confirm')

    def test_expired_live_and_cached_probe_cannot_confirm(self):
        self.observe()
        with patch.object(m.time,'time',return_value=time.time()+301), self.assertRaisesRegex(ValueError,'Fresh live evidence'):
            self.call('confirm')
        hit=self.call('probe',repo=str(self.repo),remote=str(self.remote),branch='main')
        self.assertEqual(hit['status'],'cached-not-live')
        with self.assertRaisesRegex(ValueError,'Fresh live evidence'):
            self.call('confirm')

    def test_repository_lock_blocks_second_journal_and_preserves_owner(self):
        other_path, other_binding=self.root/'other.json',self.root/'other-binding.json'
        bound=copy.deepcopy(self.bound);bound['taskSync']['journalPath']=str(other_path)
        other_binding.write_text(json.dumps(bound))
        with self.assertRaises(FileExistsError):
            m.operate(other_path,dict(operation='begin',owner='other',binding=str(other_binding)))
        self.assertFalse(other_path.with_suffix('.flow.lock').exists())
        self.assertEqual(json.loads(self.state_path.with_suffix('.flow.lock').read_text())['owner'],'fixture-task')

    def test_binding_changes_and_wrong_remote_are_rejected(self):
        with self.assertRaisesRegex(ValueError,'Probe differs'):
            self.call('probe',repo=str(self.repo),remote=str(self.root/'wrong.git'),branch='main')
        changed=copy.deepcopy(self.bound);changed['taskSync']['resources'][0]['runtimeExclusions']=['SKILL.md']
        self.binding.write_text(json.dumps(changed))
        with self.assertRaisesRegex(ValueError,'Binding changed'):
            self.call('mark-dirty',resourceId='fixture')

    def test_builtin_newline_normalization_and_custom_filter_rejection(self):
        (self.repo/'.gitattributes').write_text('*.md text eol=lf\n')
        (self.source/'SKILL.md').write_bytes(b'line\r\n')
        head=self.commit()
        self.assertEqual(integrity.verify_commit(self.repo,self.source,head)['fileCount'],1)
        (self.repo/'.gitattributes').write_text('*.md filter=untrusted\n')
        with self.assertRaisesRegex(ValueError,'Custom filter'):
            integrity.verify_commit(self.repo,self.source,head)

    def test_sensitive_file_is_rejected_before_read(self):
        (self.source/'.ENV.fixture').touch()
        with patch.object(Path,'read_bytes',side_effect=AssertionError('must not read')), self.assertRaisesRegex(ValueError,'Sensitive'):
            m.fingerprint(self.source)

    def test_atomic_failure_preserves_journal_and_lock_cleanup(self):
        self.call('release')
        original=self.state_path.read_bytes()
        with patch.object(m,'atomic_json',side_effect=OSError('disk full')),self.assertRaises(OSError):
            self.call('begin')
        self.assertEqual(self.state_path.read_bytes(),original)
        self.assertFalse(self.state_path.with_suffix('.flow.lock').exists())
        self.assertFalse((self.repo/'.git/ai-toolbox-sync.flow.lock').exists())

    def test_real_push_lost_ack_recovery_keeps_evidence(self):
        self.call('mark-dirty',resourceId='fixture')
        for folder in (self.source,self.installed):
            (folder/'SKILL.md').write_text('updated')
        head=self.commit()
        self.observe(localPaths=['skills/example/SKILL.md'])
        self.call('intent',action='push',head=head)
        self.git(self.repo,'push','origin','main')
        self.call('release'); self.call('begin')
        value=self.observe()
        self.assertEqual(self.call('resolve',observation=value)['status'],'confirmed')
        self.call('complete-work',previousCommandFinished=True)


    def test_release_with_corrupt_journal(self):
        self.state_path.write_text('{broken')
        self.assertTrue(self.call('release')['released'])
        self.assertEqual(self.state_path.read_text(), '{broken')

    def test_release_retry_after_second_unlink_failure(self):
        original = Path.unlink
        lock = self.state_path.with_suffix('.flow.lock')
        def fail(path, *args, **kwargs):
            if path == lock: raise PermissionError('injected')
            return original(path, *args, **kwargs)
        with patch.object(Path, 'unlink', fail), self.assertRaises(PermissionError):
            self.call('release')
        self.assertTrue(self.call('release')['released'])

    def test_pending_work_forces_live_probe(self):
        self.observe()
        self.call('mark-dirty', resourceId='fixture')
        result = self.call('probe', repo=str(self.repo), remote=str(self.remote), branch='main')
        self.assertEqual(result['status'], 'live')

    def test_complete_work_rechecks_freshness_after_scan(self):
        self.call('mark-dirty', resourceId='fixture')
        self.observe(); self.call('confirm')
        now = m.time.time()
        original = m.check_integrity
        def slow(state, obs):
            original(state, obs)
            state['remoteObservation']['checkedAt'] = now - 301
        with patch.object(m, 'check_integrity', slow), self.assertRaisesRegex(ValueError, 'Fresh live evidence'):
            self.call('complete-work', previousCommandFinished=True)
        self.assertEqual(json.loads(self.state_path.read_text())['workItems']['fixture-task']['fixture']['status'], 'pending')


    def test_repository_only_lock_recovery_requires_matching_owner_and_binding(self):
        self.state_path.with_suffix('.flow.lock').unlink()
        with self.assertRaisesRegex(ValueError, 'another task'):
            m.operate(self.state_path, dict(operation='release', owner='wrong', binding=str(self.binding)))
        request = self.root/'request.json'
        request.write_text(json.dumps(dict(operation='release', owner='fixture-task')))
        with patch.object(sys, 'argv', ['sync_session', '--binding', str(self.binding), '--request', str(request)]), patch('builtins.print'):
            self.assertEqual(m.main(), 0)
        self.assertFalse((self.repo/'.git/ai-toolbox-sync.flow.lock').exists())

    def test_git_timeout_returns_structured_cli_failure(self):
        request = self.root/'request.json'
        request.write_text(json.dumps(dict(operation='probe', owner='fixture-task')))
        with patch.object(sys, 'argv', ['sync_session', '--state', str(self.state_path), '--request', str(request)]), patch.object(m, 'operate', side_effect=subprocess.TimeoutExpired('git', 30)), patch('builtins.print') as output:
            self.assertEqual(m.main(), 1)
            self.assertFalse(json.loads(output.call_args.args[0])['saved'])

    def test_missing_repository_lock_blocks_work(self):
        (self.repo/'.git/ai-toolbox-sync.flow.lock').unlink()
        with self.assertRaises(OSError):
            self.call('mark-dirty', resourceId='fixture')


    def test_exact_committed_bytes_survive_autocrlf_change(self):
        content = b'first\r\nsecond\r\n'
        (self.source/'SKILL.md').write_bytes(content)
        head = self.commit()
        with patch.dict(os.environ, {'GIT_CONFIG_VALUE_0': 'true'}):
            self.assertEqual(integrity.verify_commit(self.repo, self.source, head)['fileCount'], 1)
            self.assertEqual(integrity.verify_file(self.repo, self.source/'SKILL.md', head), content)

    def test_real_git_timeout_closes_transport_process(self):
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            listener.listen()
            listener.settimeout(5)
            remote = 'git://127.0.0.1:%d/stalled.git' % listener.getsockname()[1]
            started = time.monotonic()
            with patch.dict(os.environ, {'GIT_ALLOW_PROTOCOL': 'file:git'}), self.assertRaises(subprocess.TimeoutExpired):
                integrity.git(self.repo, 'ls-remote', remote, timeout=3)
            self.assertLess(time.monotonic() - started, 13)
            connection, _ = listener.accept()
            with connection:
                connection.settimeout(5)
                try:
                    while connection.recv(4096):
                        pass
                except ConnectionResetError:
                    pass  # Windows 终止 Git 时可发送 RST；同样证明连接已关闭。


if __name__=='__main__':
    unittest.main(verbosity=2)
