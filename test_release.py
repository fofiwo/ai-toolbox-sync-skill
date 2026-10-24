import copy
import json
import os
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

    def test_independent_distribution_retires_only_exact_dependency_files(self):
        files = {p: b for p, b in self.files.items() if p not in release.RETIRED}
        files['skills/ai-toolbox-sync/references/git-workflow.md'] = b'# native git'
        files['skills/ai-toolbox-sync/scripts/test_native_git.py'] = b'# fixture'
        release.validate(files, manifest=False)
        files.pop('skills/ai-toolbox-sync/UPSTREAM.json')
        with self.assertRaisesRegex(ValueError, 'Required distribution'):
            release.validate(files, manifest=False)

    def test_independent_distribution_rejects_dependency_reintroduction(self):
        files = dict(self.files)
        files['skills/ai-toolbox-sync/references/git-workflow.md'] = b'# native git'
        files['skills/ai-toolbox-sync/scripts/test_native_git.py'] = b'# fixture'
        with self.assertRaisesRegex(ValueError, 'Retired dependency'):
            release.validate(files, manifest=False)

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

    def test_push_pins_checked_sha_and_one_version_tag(self):
        head = 'a' * 40
        previous = 'b' * 40
        tag = 'refs/tags/v1.2.4-draft'
        def command(*args):
            return {'symbolic-ref': b'main\n', 'merge-base': previous.encode(),
                    'for-each-ref': b'', 'rev-parse': head.encode(), 'status': b'', '-c': b''}[args[0]]
        with patch.object(release, 'inspect', return_value={'local': head, 'remote': previous, 'status': 'local-ahead'}), \
             patch.object(release, 'check', return_value=head), \
             patch.object(release, 'committed_version', side_effect=lambda rev: '1.2.4-draft' if rev == head else '1.2.3-draft'), \
             patch.object(release, 'remote_refs', side_effect=[{'refs/heads/main': previous}, {'refs/heads/main': head, tag: head}]), \
             patch.object(release, 'git', side_effect=command) as git_command, \
             patch.object(release.sys, 'argv', ['release.py', 'push']):
            release.main()
            self.assertEqual(git_command.call_args.args, ('-c', 'push.followTags=false', '-c',
                'remote.origin.mirror=false', 'push', '--atomic', release.REMOTE,
                head + ':refs/heads/main', head + ':' + tag))


class VersionTests(unittest.TestCase):
    def test_semver_order_and_invalid_versions(self):
        ordered = ['1.0.0-alpha', '1.0.0-alpha.1', '1.0.0-alpha.beta', '1.0.0-beta',
                   '1.0.0-beta.2', '1.0.0-beta.11', '1.0.0-rc.1', '1.0.0', '1.0.1', '1.1.0', '2.0.0']
        self.assertEqual(sorted(reversed(ordered), key=release.version_key), ordered)
        self.assertEqual(release.version_key('1.2.3+build.1'), release.version_key('1.2.3+build.2'))
        for value in ['01.2.3', '1.2', 'v1.2.3', '1.2.3-draft.01', '1.2.3-', '1.2.3\n', '../v1.2.3']:
            with self.subTest(value=value), self.assertRaises(ValueError):
                release.semver(value)

    def test_bump_levels_and_prereleases(self):
        for level, expected in [('patch', '1.2.4-draft'), ('minor', '1.3.0-draft'),
                                ('major', '2.0.0-draft'), ('final', '1.2.3'), ('prerelease', '1.2.3-draft.1')]:
            self.assertEqual(release.next_version('1.2.3-draft', level), expected)
        self.assertEqual(release.next_version('1.2.3-rc.9', 'prerelease'), '1.2.3-rc.10')
        self.assertEqual(release.next_version('1.2.3+build.4', 'patch'), '1.2.4')
        with self.assertRaises(ValueError):
            release.next_version('1.2.3', 'final')


class VersionWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo, self.remote = self.root / 'repo', self.root / 'remote.git'
        self.repo.mkdir()
        environment = dict(GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull,
                           GIT_CONFIG_COUNT='0', GIT_ALLOW_PROTOCOL='file',
                           GIT_AUTHOR_NAME='Fixture', GIT_AUTHOR_EMAIL='fixture@example.invalid',
                           GIT_COMMITTER_NAME='Fixture', GIT_COMMITTER_EMAIL='fixture@example.invalid')
        self.env = patch.dict(os.environ, environment)
        self.env.start(); self.addCleanup(self.env.stop)
        self.git('init', '--bare', '--initial-branch=main', str(self.remote))
        self.git('init', '--initial-branch=main')
        self.git('remote', 'add', 'origin', str(self.remote))
        files = {release.VERSION: b'1.2.3-draft\n', release.SKILL: b'---\nmetadata:\n  version: 1.2.3-draft\n---\n',
                 'README.md': '公开分发版本：1.2.3-draft；fixture'.encode(),
                 release.INDEX: '个人 AI 工具箱 / 1.2.3-draft<span>fixture</span>'.encode(),
                 release.DATA: b'window.TOOLBOX_DATA = {"exampleOnly":false,"resources":[]};',
                 release.DISCOVERY: b'window.TOOLBOX_DISCOVERY = null;'}
        for name, raw in release.with_manifest(files).items():
            path = self.repo / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
        self.commit('fixture baseline')
        self.base = self.git('rev-parse', 'HEAD')
        self.git('push', 'origin', 'HEAD:refs/heads/main')
        self.settings = patch.multiple(release, ROOT=self.repo, BASE=self.base, REMOTE=str(self.remote))
        self.settings.start(); self.addCleanup(self.settings.stop)

    def git(self, *args):
        return subprocess.check_output(['git', *args], cwd=self.repo, stderr=subprocess.PIPE).decode().strip()

    def stage(self):
        paths = [p.relative_to(self.repo).as_posix() for p in self.repo.rglob('*')
                 if p.is_file() and '.git' not in p.parts]
        self.git('--literal-pathspecs', 'add', '--', *paths)

    def commit(self, message):
        self.stage()
        self.git('commit', '-m', message)
        return self.git('rev-parse', 'HEAD')

    def start(self, **options):
        options.setdefault('source_only', True)
        return release.start(**options)

    def test_bump_updates_all_surfaces_and_manifest_without_uploading(self):
        result = release.bump('minor')
        self.assertEqual((result['previousVersion'], result['version']), ('1.2.3-draft', '1.3.0-draft'))
        files = release.working_files()
        release.validate(files)
        self.assertEqual(release.version_from(files, managed=True), '1.3.0-draft')
        self.assertEqual(self.git('ls-remote', str(self.remote), 'refs/heads/main').split()[0], self.base)
        self.assertEqual(self.git('tag', '--list'), '')

    def test_mismatched_display_refuses_bump_without_replacing_local_edits(self):
        path = self.repo / 'README.md'
        path.write_bytes(path.read_bytes().replace(b'1.2.3-draft', b'9.9.9'))
        before = {n: (self.repo / n).read_bytes() for n in release.VERSION_FIELDS}
        with self.assertRaisesRegex(ValueError, 'Version mismatch'):
            release.bump('patch')
        self.assertEqual({n: (self.repo / n).read_bytes() for n in before}, before)

    def test_managed_version_cannot_disappear_from_checked_head(self):
        self.git('rm', '--', release.VERSION)
        before = release.working_files()
        release.write_reviewed(before, release.with_manifest(before))
        self.git('add', '--', 'SHA256SUMS.json')
        self.git('commit', '-m', 'fixture missing version')
        with self.assertRaisesRegex(ValueError, 'Managed VERSION'):
            release.check()

    def test_changed_release_cannot_reuse_published_version(self):
        path = self.repo / 'README.md'
        path.write_bytes(path.read_bytes() + b' changed content')
        release.write_reviewed(release.working_files(), release.with_manifest(release.working_files()))
        self.commit('fixture unchanged version')
        with self.assertRaisesRegex(ValueError, 'increase the published version'):
            release.publish()
        self.assertEqual(self.git('ls-remote', str(self.remote), 'refs/heads/main').split()[0], self.base)
        self.assertEqual(self.git('tag', '--list'), '')

    def test_real_atomic_release_and_retry_are_idempotent(self):
        release.bump('patch')
        head = self.commit('fixture version bump')
        result = release.publish()
        self.assertEqual(result['tag'], 'v1.2.4-draft')
        self.assertEqual(self.git('rev-parse', 'refs/tags/v1.2.4-draft'), head)
        self.assertEqual(self.git('ls-remote', str(self.remote), 'refs/tags/v1.2.4-draft').split()[0], head)
        self.assertTrue(release.publish()['alreadyPublished'])
        self.assertEqual(self.git('rev-parse', 'HEAD'), head)

    def test_conflicting_remote_and_local_tags_preserve_main(self):
        release.bump('patch')
        self.commit('fixture version bump')
        self.git('tag', 'v1.2.4-draft', self.base)
        with self.assertRaisesRegex(ValueError, 'Local version tag conflicts'):
            release.publish()
        self.git('push', 'origin', 'refs/tags/v1.2.4-draft:refs/tags/v1.2.4-draft')
        with self.assertRaisesRegex(ValueError, 'Version tag already exists'):
            release.publish()
        self.assertEqual(self.git('ls-remote', str(self.remote), 'refs/heads/main').split()[0], self.base)

    def test_higher_remote_tag_blocks_downgrade(self):
        self.git('tag', 'v9.0.0', self.base)
        self.git('push', 'origin', 'refs/tags/v9.0.0:refs/tags/v9.0.0')
        release.bump('minor')
        self.commit('fixture lower version')
        with self.assertRaisesRegex(ValueError, 'newer version tag'):
            release.publish()

    def test_atomic_tag_race_cannot_partially_publish_main(self):
        self.git('tag', 'v1.2.4-draft', self.base)
        self.git('push', 'origin', 'refs/tags/v1.2.4-draft:refs/tags/v1.2.4-draft')
        # Remove only this fixture's local reference; retain a conflicting remote tag.
        self.git('tag', '-d', 'v1.2.4-draft')
        release.bump('patch')
        self.commit('fixture version bump')
        with patch.object(release, 'remote_refs', return_value={'refs/heads/main': self.base}):
            with self.assertRaises(subprocess.CalledProcessError):
                release.publish()
        self.assertEqual(self.git('ls-remote', str(self.remote), 'refs/heads/main').split()[0], self.base)
        self.assertEqual(self.git('ls-remote', str(self.remote), 'refs/tags/v1.2.4-draft').split()[0], self.base)

    def test_server_without_atomic_support_keeps_branch_and_remote_tags(self):
        self.git('--git-dir', str(self.remote), 'config', 'receive.advertiseAtomic', 'false')
        release.bump('patch')
        head = self.commit('fixture version bump')
        with self.assertRaises(subprocess.CalledProcessError):
            release.publish()
        self.assertEqual(self.git('ls-remote', str(self.remote), 'refs/heads/main').split()[0], self.base)
        self.assertEqual(self.git('ls-remote', str(self.remote), 'refs/tags/v1.2.4-draft'), '')
        self.assertEqual(self.git('rev-parse', 'refs/tags/v1.2.4-draft'), head)

    def advance_peer(self, lower=False):
        self.git('checkout', '-b', 'peer', self.base)
        release.bump('patch')
        if lower:
            files = release.working_files()
            for name in (release.VERSION, *release.VERSION_FIELDS):
                files[name] = files[name].replace(b'1.2.4-draft', b'1.0.0-draft')
                (self.repo / name).write_bytes(files[name])
            release.write_reviewed(release.working_files(), release.with_manifest(release.working_files()))
        head = self.commit('peer changes')
        self.git('push', 'origin', 'HEAD:refs/heads/main')
        self.git('checkout', 'main')
        return head

    def test_start_clean_and_safe_fast_forward_do_not_install_or_upload(self):
        self.assertTrue(self.start()['readyToEdit'])
        peer = self.advance_peer()
        with self.assertRaisesRegex(ValueError, 'Remote is ahead'):
            self.start(restart=True)
        self.assertEqual(self.git('rev-parse', 'HEAD'), self.base)
        result = self.start(align=True, restart=True)
        self.assertTrue(result['readyToEdit'])
        self.assertFalse(result['installationUpdated'])
        self.assertEqual(self.git('rev-parse', 'HEAD'), peer)
        self.assertEqual(self.git('status', '--porcelain'), '')
        self.assertEqual(self.git('ls-remote', str(self.remote), 'refs/heads/main').split()[0], peer)

    def test_start_local_edits_require_explicit_review_and_preserve_index(self):
        path = self.repo / 'README.md'
        path.write_bytes(path.read_bytes() + b' staged')
        self.git('add', '--', 'README.md')
        path.write_bytes(path.read_bytes() + b' unstaged')
        before = (path.read_bytes(), self.git('show', ':README.md'))
        with self.assertRaisesRegex(ValueError, 'Existing local changes'):
            self.start()
        self.assertTrue(self.start(accept_local=True)['readyToEdit'])
        with self.assertRaisesRegex(ValueError, 'Local edits exist'):
            self.start(align=True, accept_local=True)
        self.assertEqual((path.read_bytes(), self.git('show', ':README.md')), before)

    def test_alignment_preserves_untracked_and_local_commits(self):
        path = self.repo / 'local.txt'
        path.write_text('keep this local work')
        with self.assertRaisesRegex(ValueError, 'Local edits exist'):
            self.start(align=True)
        self.assertEqual(path.read_text(), 'keep this local work')
        path.unlink()
        release.bump('minor')
        local = self.commit('local change')
        with self.assertRaisesRegex(ValueError, 'Existing local changes'):
            self.start()
        with self.assertRaisesRegex(ValueError, 'Local commits exist'):
            self.start(align=True)
        self.assertTrue(self.start(accept_local=True)['readyToEdit'])
        self.assertEqual(self.git('rev-parse', 'HEAD'), local)

    def test_divergence_blocks_even_with_higher_local_version(self):
        self.start()
        release.bump('major')
        local = self.commit('higher local version')
        self.advance_peer()
        for settings in ({}, {'align': True}, {'accept_local': True}):
            with self.assertRaisesRegex(ValueError, 'Both sides changed'):
                self.start(restart=True, **settings)
        path = self.repo / 'README.md'
        path.write_bytes(path.read_bytes() + b' preserve local progress after divergence')
        release.write_reviewed(release.working_files(), release.with_manifest(release.working_files()))
        self.stage()
        result = release.finish()
        self.assertTrue(result['readyToCommit'])
        self.assertEqual(result['remoteStatus'], 'diverged')
        self.assertFalse(result['publicationReady'])
        self.assertEqual(self.git('rev-parse', 'HEAD'), local)

    def test_alignment_rejects_remote_version_regression(self):
        self.advance_peer(lower=True)
        with self.assertRaisesRegex(ValueError, 'version goes backwards'):
            self.start(align=True)
        self.assertEqual(self.git('rev-parse', 'HEAD'), self.base)

    def test_finish_rechecks_remote_after_start_and_retains_work(self):
        self.start()
        self.advance_peer()
        release.bump('minor')
        before = release.working_files()
        self.stage()
        result = release.finish()
        self.assertEqual(result['remoteStatus'], 'remote-ahead')
        self.assertTrue(result['readyToCommit'])
        self.assertFalse(result['publicationReady'])
        self.assertEqual(release.working_files(), before)
        self.assertEqual(self.git('rev-parse', 'HEAD'), self.base)

    def test_finish_checks_version_and_manifest_without_committing(self):
        self.start()
        path = self.repo / 'README.md'
        path.write_bytes(path.read_bytes() + b' reviewed')
        self.stage()
        with self.assertRaisesRegex(ValueError, 'Manifest mismatch'):
            release.finish()
        release.write_reviewed(release.working_files(), release.with_manifest(release.working_files()))
        self.stage()
        result = release.finish()
        self.assertEqual(result['version'], '1.2.3-draft')
        self.assertTrue(result['readyToCommit'])
        self.assertFalse(result['publicationReady'])
        release.bump('minor')
        self.stage()
        result = release.finish()
        self.assertTrue(result['readyToCommit'])
        self.assertFalse(result['committed'])
        self.assertFalse(result['published'])
        self.assertEqual(result['version'], '1.3.0-draft')
        self.assertEqual(self.git('rev-parse', 'HEAD'), self.base)
        self.assertNotEqual(self.git('diff', '--cached', '--name-only'), '')

    def test_in_progress_git_operation_blocks_maintenance(self):
        self.start()
        merge_head = self.repo / '.git' / 'MERGE_HEAD'
        merge_head.write_text(self.base)
        for operation in (self.start, release.finish):
            with self.assertRaisesRegex(ValueError, 'Unfinished Git operation'):
                operation()
        self.assertEqual(merge_head.read_text(), self.base)

    def test_remote_race_before_fast_forward_preserves_local_head(self):
        self.advance_peer()
        with patch.object(release, 'remote_refs', return_value={'refs/heads/main': 'a' * 40}):
            with self.assertRaisesRegex(ValueError, 'Remote changed before alignment'):
                self.start(align=True)
        self.assertEqual(self.git('rev-parse', 'HEAD'), self.base)

    def test_finish_remote_race_during_check_is_rejected(self):
        self.start()
        release.bump('minor')
        self.stage()
        with patch.object(release, 'remote_refs', return_value={'refs/heads/main': 'a' * 40}):
            result = release.finish()
            self.assertEqual(result['remoteStatus'], 'changed-during-check')
            self.assertFalse(result['publicationReady'])
            self.assertTrue(result['readyToCommit'])
        self.assertEqual(self.git('rev-parse', 'HEAD'), self.base)

    def test_fast_forward_cannot_replace_an_ignored_local_file(self):
        self.git('checkout', '-b', 'peer', self.base)
        path = self.repo / 'AGENTS.md'
        path.write_text('public instructions')
        release.bump('patch')
        self.commit('peer adds instructions')
        self.git('push', 'origin', 'HEAD:refs/heads/main')
        self.git('checkout', 'main')
        (self.repo / '.git/info/exclude').write_text('AGENTS.md\n')
        path.write_text('preserve local ignored instructions')
        with self.assertRaises(subprocess.CalledProcessError):
            self.start(align=True)
        self.assertEqual(path.read_text(), 'preserve local ignored instructions')
        self.assertEqual(self.git('rev-parse', 'HEAD'), self.base)

    def test_fast_forward_rejects_invalid_remote_manifest(self):
        self.git('checkout', '-b', 'peer', self.base)
        path = self.repo / 'README.md'
        path.write_bytes(path.read_bytes() + b' invalid remote edit')
        self.commit('peer forgets manifest')
        self.git('push', 'origin', 'HEAD:refs/heads/main')
        self.git('checkout', 'main')
        with self.assertRaisesRegex(ValueError, 'Manifest mismatch'):
            self.start(align=True)
        self.assertEqual(self.git('rev-parse', 'HEAD'), self.base)

    def test_failed_network_blocks_start_but_allows_explicit_local_checkpoint(self):
        with patch.object(release, 'inspect', side_effect=subprocess.CalledProcessError(1, 'git fetch')):
            with self.assertRaises(subprocess.CalledProcessError):
                self.start()
        self.start()
        release.bump('minor')
        self.stage()
        with patch.object(release, 'inspect', side_effect=subprocess.CalledProcessError(1, 'git fetch')):
            result = release.finish()
        self.assertEqual(result['remoteStatus'], 'unverified')
        self.assertTrue(result['readyToCommit'])
        self.assertFalse(result['publicationReady'])
        self.assertEqual(self.git('rev-parse', 'HEAD'), self.base)

    def installed_fixture(self):
        root = self.root / 'installed'
        root.mkdir()
        for source, name in ((release.SKILL, 'SKILL.md'), (release.VERSION, 'VERSION')):
            (root / name).write_bytes((self.repo / source).read_bytes())
        receipt = self.root / 'installation.json'
        receipt.write_text(json.dumps({'source': release.REMOTE,
            'installedFilesSHA256': release.hashes({p.name: p.read_bytes() for p in root.iterdir()})}))
        return {'source_only': False, 'installed': str(root), 'receipt': str(receipt)}

    def test_partial_staging_is_rejected_without_changing_either_copy(self):
        self.start()
        path = self.repo / 'README.md'
        path.write_bytes(path.read_bytes() + b' staged earlier')
        self.git('add', '--', 'README.md')
        release.bump('minor')
        before = (path.read_bytes(), self.git('show', ':README.md'))
        with self.assertRaisesRegex(ValueError, 'Staged files differ'):
            release.finish()
        self.assertEqual((path.read_bytes(), self.git('show', ':README.md')), before)
        self.assertFalse(release.local_path('ai-toolbox-stage.json').exists())

    def test_actual_staged_manifest_is_checked_before_commit(self):
        self.start()
        path = self.repo / 'README.md'
        path.write_bytes(path.read_bytes() + b' staged without its manifest')
        self.git('add', '--', 'README.md')
        release.write_reviewed(release.working_files(), release.with_manifest(release.working_files()))
        with self.assertRaisesRegex(ValueError, 'Manifest mismatch'):
            release.finish()
        self.assertEqual(self.git('rev-parse', 'HEAD'), self.base)

    def test_staged_head_cannot_drop_managed_version(self):
        self.git('rm', '--', release.VERSION)
        release.write_reviewed(release.working_files(), release.with_manifest(release.working_files()))
        self.stage()
        with self.assertRaisesRegex(ValueError, 'Managed VERSION'):
            release.stage_check()
        self.assertEqual(self.git('rev-parse', 'HEAD'), self.base)

    def test_offline_checkpoint_same_version_then_exact_commit_verification(self):
        path = self.repo / 'README.md'
        path.write_bytes(path.read_bytes() + b' local development')
        release.write_reviewed(release.working_files(), release.with_manifest(release.working_files()))
        self.stage()
        with patch.object(release, 'inspect', side_effect=AssertionError('must stay offline')):
            result = release.stage_check()
        self.assertTrue(result['checkpointOnly'])
        self.assertEqual(result['version'], '1.2.3-draft')
        self.git('commit', '-m', 'offline checkpoint')
        verified = release.verify_commit()
        self.assertTrue(verified['commitVerified'])
        self.assertEqual(release.check(), verified['commit'])
        self.assertEqual(self.git('ls-remote', str(self.remote), 'refs/heads/main').split()[0], self.base)
        self.assertEqual(self.git('tag', '--list'), '')

    def test_commit_changed_after_preparation_is_not_verified_or_published(self):
        self.start()
        release.bump('minor')
        self.stage()
        release.finish()
        path = self.repo / 'README.md'
        path.write_bytes(path.read_bytes() + b' changed after review')
        release.write_reviewed(release.working_files(), release.with_manifest(release.working_files()))
        self.commit('different tree')
        with self.assertRaisesRegex(ValueError, 'differs from reviewed tree'):
            release.verify_commit()
        with self.assertRaisesRegex(ValueError, 'not verified at HEAD'):
            release.publish()
        self.assertEqual(self.git('ls-remote', str(self.remote), 'refs/heads/main').split()[0], self.base)

    def test_maintenance_on_development_branch_publish_only_main(self):
        self.git('checkout', '-b', 'development')
        self.start()
        release.bump('minor')
        self.stage()
        release.finish()
        self.git('commit', '-m', 'development change')
        self.assertTrue(release.verify_commit()['commitVerified'])
        with self.assertRaisesRegex(ValueError, 'Publish only main'):
            release.publish()

    def test_missing_baseline_cannot_claim_full_finish(self):
        release.bump('minor')
        self.stage()
        with self.assertRaisesRegex(ValueError, 'Missing maintenance baseline'):
            release.finish()
        self.assertTrue(release.stage_check()['readyToCommit'])
        with self.assertRaisesRegex(ValueError, 'Choose --source-only'):
            release.start()

    def test_resumption_retains_original_baseline(self):
        first = self.start()
        original = release.local_path('ai-toolbox-maintenance.json').read_bytes()
        release.bump('minor')
        second = self.start(accept_local=True)
        self.assertEqual(second['sessionId'], first['sessionId'])
        self.assertEqual(release.local_path('ai-toolbox-maintenance.json').read_bytes(), original)

    def test_restart_retains_previous_record_after_remote_update(self):
        self.start()
        old = release.local_path('ai-toolbox-maintenance.json').read_bytes()
        self.advance_peer()
        with self.assertRaisesRegex(ValueError, 'Existing baseline changed'):
            self.start()
        self.start(align=True, restart=True)
        archives = list((self.repo / '.git').glob('ai-toolbox-maintenance.*.json'))
        self.assertEqual(len(archives), 1)
        self.assertEqual(archives[0].read_bytes(), old)

    def test_staged_scope_is_enforced(self):
        self.start(paths=['README.md'])
        release.bump('minor')
        self.stage()
        with self.assertRaisesRegex(ValueError, 'outside the approved maintenance scope'):
            release.finish()

    def test_installed_customization_requires_its_own_choice(self):
        options = self.installed_fixture()
        path = Path(options['installed']) / 'SKILL.md'
        path.write_bytes(path.read_bytes() + b' custom local instructions')
        with self.assertRaisesRegex(ValueError, 'Installed customizations'):
            self.start(accept_local=True, **options)
        result = self.start(accept_installed=True, **options)
        self.assertEqual(result['installationChanges'], {'SKILL.md': 'modified'})
        self.assertTrue(result['installationVerified'])
        self.assertFalse(result['installationUpdated'])
        self.assertIn(b'custom local instructions', path.read_bytes())

    def test_installed_baseline_is_checked_through_exact_commit_verification(self):
        options = self.installed_fixture()
        start = self.start(**options)
        self.assertTrue(start['installationVerified'])
        self.assertFalse(start['installationSourceAligned'])
        release.bump('minor')
        self.stage()
        result = release.finish()
        self.assertTrue(result['installationVerified'])
        self.git('commit', '-m', 'reviewed source with unchanged installed baseline')
        self.assertTrue(release.verify_commit()['commitVerified'])

    def test_installation_or_receipt_changed_after_start_blocks_full_finish(self):
        options = self.installed_fixture()
        self.start(**options)
        release.bump('minor')
        self.stage()
        path = Path(options['installed']) / 'SKILL.md'
        original = path.read_bytes()
        path.write_bytes(original + b' concurrent installation edit')
        with self.assertRaisesRegex(ValueError, 'Installed files or receipt changed'):
            release.finish()
        path.write_bytes(original)
        record = Path(options['receipt'])
        record.write_text(record.read_text() + '\n')
        with self.assertRaisesRegex(ValueError, 'Installed files or receipt changed'):
            release.finish()
        self.assertTrue(release.stage_check()['checkpointOnly'])

    def test_installed_sensitive_path_is_rejected_before_reading(self):
        options = self.installed_fixture()
        path = Path(options['installed']) / '.env.local'
        path.write_text('synthetic-no-secrets')
        with self.assertRaisesRegex(ValueError, 'content not read'):
            self.start(accept_installed=True, **options)

    def future_update(self):
        name = 'skills/ai-toolbox-sync/scripts/future_feature.py'
        self.git('checkout', '-b', 'peer', self.base)
        target = self.repo / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text('# synthetic reviewed feature\n')
        (self.repo / 'release.py').write_text('raise AssertionError("remote validator must never execute during approval")\n')
        with patch.object(release, 'EXTRA', release.EXTRA | {name}):
            release.bump('minor')
            head = self.commit('reviewed new public file')
        self.git('push', 'origin', 'HEAD:refs/heads/main')
        self.git('checkout', 'main')
        return head, name

    def test_new_path_requires_exact_fixed_update_review_without_running_remote_code(self):
        head, name = self.future_update()
        with self.assertRaisesRegex(ValueError, 'Unexpected committed paths'):
            self.start(align=True)
        plan = release.update_review(head)
        self.assertEqual(plan['newPaths'], [name])
        for paths in ([], ['skills/ai-toolbox-sync/scripts/*'], [name, 'unreviewed.py']):
            with self.assertRaisesRegex(ValueError, 'every new path exactly'):
                release.update_review(head, paths)
        self.assertTrue(release.update_review(head, [name])['approved'])
        result = self.start(align=True)
        self.assertTrue(result['readyToEdit'])
        self.assertEqual(self.git('rev-parse', 'HEAD'), head)
        self.assertTrue((self.repo / name).exists())
        self.assertFalse(result['installationUpdated'])

    def test_update_approval_cannot_transfer_to_different_remote_commit(self):
        head, name = self.future_update()
        release.update_review(head, [name])
        self.git('checkout', 'peer')
        with patch.object(release, 'EXTRA', release.EXTRA | {name}):
            release.bump('patch')
            self.commit('peer changes again')
        self.git('push', 'origin', 'HEAD:refs/heads/main')
        self.git('checkout', 'main')
        with self.assertRaisesRegex(ValueError, 'Unexpected committed paths'):
            self.start(align=True)
        self.assertEqual(self.git('rev-parse', 'HEAD'), self.base)

    def test_baseline_record_lock_and_cas_preserve_other_writer(self):
        path = release.local_path('test-local-record.json')
        release.save_local(path, {'other': True}, None)
        old = path.read_bytes()
        with self.assertRaisesRegex(ValueError, 'Local record changed'):
            release.save_local(path, {'overwrite': True}, None)
        self.assertEqual(path.read_bytes(), old)
        lock = path.with_name(path.name + '.lock')
        lock.write_text('another owner')
        with self.assertRaises(FileExistsError):
            release.save_local(path, {'overwrite': True}, old)
        self.assertEqual(lock.read_text(), 'another owner')
        self.assertEqual(path.read_bytes(), old)


if __name__ == '__main__':
    unittest.main()
