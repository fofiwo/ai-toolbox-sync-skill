"""Real local Git + own file executor, with no external toolbox executable on PATH."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import resource_files as resources
import sync_session as sessions


class ResourceMigrationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="native-toolbox-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        git_path = Path(shutil.which("git")).parent
        system_path = Path(os.environ.get("SystemRoot", "/")) / "System32"
        environment = dict(PATH=os.pathsep.join([str(git_path), str(system_path)]),
            GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull,
            GIT_ALLOW_PROTOCOL="file", GIT_AUTHOR_NAME="Fixture",
            GIT_AUTHOR_EMAIL="fixture@example.invalid", GIT_COMMITTER_NAME="Fixture",
            GIT_COMMITTER_EMAIL="fixture@example.invalid", GIT_CONFIG_COUNT="1",
            GIT_CONFIG_KEY_0="core.autocrlf", GIT_CONFIG_VALUE_0="false")
        self.environment = patch.dict(os.environ, environment)
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.assertIsNone(shutil.which("skillshare"))
        self.repo, self.remote = self.root / "repo", self.root / "remote.git"
        self.repo.mkdir()
        self.git(self.root, "init", "--bare", "--initial-branch=main", str(self.remote))
        self.git(self.repo, "init", "--initial-branch=main")
        self.git(self.repo, "remote", "add", "origin", str(self.remote))
        self.source, self.installed = self.repo / "skills/example", self.root / "installed"
        self.source.mkdir(parents=True)
        (self.source / "SKILL.md").write_bytes(b"base resource")
        self.commit(self.repo, ["skills/example/SKILL.md"])
        self.push(self.repo)

    def git(self, repo, *args):
        return subprocess.check_output(["git", "-C", str(repo), *args],
            env=dict(os.environ), stderr=subprocess.PIPE).decode().strip()

    def commit(self, repo, names):
        self.git(repo, "--literal-pathspecs", "add", "--", *names)
        self.git(repo, "commit", "-m", "fixture selected resource")
        return self.git(repo, "rev-parse", "HEAD")

    def push(self, repo):
        head = self.git(repo, "rev-parse", "HEAD")
        self.git(repo, "-c", "push.followTags=false", "-c", "remote.origin.mirror=false",
                 "push", "--", str(self.remote), head + ":refs/heads/main")
        self.assertEqual(self.git(repo, "ls-remote", str(self.remote), "refs/heads/main").split()[0], head)

    def test_restore_collect_commit_push_and_existing_binding(self):
        resources.apply(resources.prepare(self.source, self.installed),
                        self.root / "restore.json", self.root / "restore-backup")
        (self.installed / "SKILL.md").write_bytes(b"selected local edit")
        resources.apply(resources.prepare(self.installed, self.source),
                        self.root / "collect.json", self.root / "collect-backup")
        (self.repo / "unrelated.txt").write_bytes(b"do not include")
        self.commit(self.repo, ["skills/example/SKILL.md"])
        self.assertNotIn("unrelated.txt", self.git(self.repo, "ls-tree", "-r", "--name-only", "HEAD"))
        self.push(self.repo)
        journal, binding = self.root / "journal.json", self.root / "binding.json"
        # Legacy optional fields must neither be required nor executed.
        bound = dict(paths=dict(gitRoot=str(self.repo), xdgConfigHome="unused legacy field"),
            cli=dict(path="unused-and-nonexistent.exe"),
            authorization=dict(status="granted", repository=str(self.remote), branch="main", resourceIds=["fixture"]),
            taskSync=dict(enabled=True, journalPath=str(journal), resources=[dict(id="fixture",
                sourcePath=str(self.source), installedPath=str(self.installed), runtimeExclusions=[])]))
        binding.write_text(json.dumps(bound), encoding="utf-8")
        binding_bytes = binding.read_bytes()
        def call(operation, **fields):
            return sessions.operate(journal, dict(owner="independent-test", operation=operation, **fields))
        call("begin", binding=str(binding))
        try:
            probe = call("probe", repo=str(self.repo), remote=str(self.remote), branch="main", strict=True)
            observation = dict(resourceId="fixture", sourceDigest=sessions.fingerprint(self.source),
                installedDigest=sessions.fingerprint(self.installed), remoteTip=probe["head"],
                head=self.git(self.repo, "rev-parse", "HEAD"), localPaths=[], remotePaths=[],
                remoteAvailable=True, scopeReviewed=True, inUse=False)
            call("observe", observation=observation)
            self.assertEqual(call("confirm")["status"], "confirmed")
        finally:
            call("release")
        self.assertEqual(binding.read_bytes(), binding_bytes)
        self.assertEqual((self.repo / "unrelated.txt").read_bytes(), b"do not include")




if __name__ == "__main__":
    unittest.main()
