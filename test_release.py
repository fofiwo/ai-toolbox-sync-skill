import copy
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import release


class ReleaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.files = release.tree(release.BASE)

    def test_clean_baseline(self):
        release.validate(self.files)

    def test_private_files_rejected_even_with_updated_manifest(self):
        for name in ['toolbox.json', 'binding.json', 'decisions.json',
                     'task-sync-journal.json', 'skills/ai-toolbox-sync/assets/notes.json']:
            files = dict(self.files, **{name: b'{}'})
            with self.assertRaises(ValueError):
                release.validate(files, manifest=False)

    def test_collections_rejected(self):
        files = copy.copy(self.files)
        files[release.DATA] = b'window.TOOLBOX_DATA = {"exampleOnly":false,"resources":[{"id":"synthetic"}]};'
        with self.assertRaisesRegex(ValueError, 'empty'):
            release.validate(files, manifest=False)

    def test_missing_file(self):
        files = dict(self.files)
        del files['skills/ai-toolbox-sync/SKILL.md']
        with self.assertRaises(ValueError):
            release.validate(files)

    def test_machine_discovery_rejected(self):
        files = dict(self.files)
        files[release.DISCOVERY] = b'window.TOOLBOX_DISCOVERY = null;'
        release.validate(files, manifest=False)
        for payload in [b'{}', b'window.TOOLBOX_DISCOVERY = {"groups":[]};',
                        b'window.TOOLBOX_DISCOVERY = null; additionalCode()']:
            files[release.DISCOVERY] = payload
            with self.assertRaisesRegex(ValueError, 'discovery'):
                release.validate(files, manifest=False)

    def test_workspace_distribution_requires_empty_discovery(self):
        files = dict(self.files)
        files['skills/ai-toolbox-sync/scripts/build_workspace.py'] = b'# synthetic'
        with self.assertRaisesRegex(ValueError, 'Discovery template missing'):
            release.validate(files, manifest=False)

    def test_tampered_file(self):
        files = dict(self.files)
        files['README.md'] += b'changed'
        with self.assertRaisesRegex(ValueError, 'Manifest'):
            release.validate(files)

    def test_credential_pattern(self):
        files = dict(self.files)
        files['README.md'] += b'ghp_' + b'x' * 36
        with self.assertRaisesRegex(ValueError, 'Credential'):
            release.validate(files, manifest=False)

    def test_removed_private_file_still_blocked_in_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            subprocess.run(['git', 'clone', '--quiet', '--no-hardlinks', str(release.ROOT), tmp], check=True)
            def git(*args):
                return subprocess.check_output(['git', '-c', 'user.name=Fixture', '-c',
                    'user.email=fixture@example.invalid', *args], cwd=tmp)
            path = Path(tmp) / 'toolbox.json'
            path.write_text('{"synthetic":true}')
            git('add', 'toolbox.json'); git('commit', '-qm', 'synthetic private state')
            path.unlink()
            git('add', '-u'); git('commit', '-qm', 'remove state')
            with patch.object(release, 'ROOT', Path(tmp)):
                with self.assertRaisesRegex(ValueError, 'Unexpected committed paths'):
                    release.check()

    def test_wrong_remote_never_pushes(self):
        with patch.object(release, 'check', return_value='a' * 40), \
             patch.object(release, 'git', return_value=b'https://example.invalid/private.git\n') as command, \
             patch.object(release.sys, 'argv', ['release.py', 'push']):
            with self.assertRaisesRegex(ValueError, 'push targets'):
                release.main()
            self.assertEqual(command.call_count, 1)

    def test_real_git_comparison(self):
        with tempfile.TemporaryDirectory() as tmp:
            def run(*args):
                return subprocess.check_output(['git', '-c', 'user.name=Fixture', '-c',
                    'user.email=fixture@example.invalid', *args], cwd=tmp).decode().strip()
            run('init', '-q')
            p = Path(tmp) / 'sample.txt'
            p.write_text('base')
            run('add', '.'); run('commit', '-qm', 'base')
            base = run('rev-parse', 'HEAD')
            p.write_text('local')
            run('commit', '-qam', 'local')
            local = run('rev-parse', 'HEAD')
            run('checkout', '-qb', 'other', base)
            p.write_text('remote')
            run('commit', '-qam', 'remote')
            remote = run('rev-parse', 'HEAD')
            p.write_text('staged'); run('add', '.')
            p.write_text('unstaged')
            (Path(tmp) / 'new.txt').write_text('new')
            with patch.object(release, 'ROOT', Path(tmp)):
                self.assertEqual(release.compare(base, base)['status'], 'aligned')
                self.assertEqual(release.compare(local, base)['status'], 'local-ahead')
                self.assertEqual(release.compare(base, remote)['status'], 'remote-ahead')
                result = release.compare(local, remote)
                self.assertEqual(result['status'], 'diverged')
                for field in ['localChanges', 'remoteChanges', 'staged', 'unstaged']:
                    self.assertIn('sample.txt', result[field])
                self.assertIn('new.txt', result['untracked'])

    def test_push_uses_checked_sha_and_no_tags(self):
        head = 'a' * 40
        previous = 'b' * 40
        replies = [b'main\n',
                   (previous + '\trefs/heads/main\n').encode(), previous.encode(), b'']
        with patch.object(release, 'inspect', return_value={'local': head, 'status': 'local-ahead'}), \
             patch.object(release, 'check', return_value=head), \
             patch.object(release, 'git', side_effect=replies) as command, \
             patch.object(release.sys, 'argv', ['release.py', 'push']):
            release.main()
            self.assertEqual(command.call_args.args, ('-c', 'push.followTags=false', '-c',
                'remote.origin.mirror=false', 'push', release.REMOTE, head + ':refs/heads/main'))


if __name__ == '__main__':
    unittest.main()
