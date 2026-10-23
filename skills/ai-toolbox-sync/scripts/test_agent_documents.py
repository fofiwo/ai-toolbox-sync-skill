"""Isolated whole-document lifecycle tests; never reads real Agent documents or networks."""
import copy
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import agent_documents as a
import sync_session as s
import build_catalog
import record_decision


class Documents(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.git("init", "-b", "main")
        self.git("config", "user.name", "Test")
        self.git("config", "user.email", "test@example.invalid")
        self.git("config", "core.autocrlf", "false")
        self.git("remote", "add", "origin", "https://github.com/example/toolbox")
        self.journal = self.root / "journal.json"
        self.owner = "documents-test"
        self.sync_binding = self.root / "sync-binding.json"
        self.sync_binding.write_text(json.dumps(dict(paths=dict(gitRoot=str(self.repo)),
            authorization=dict(status="granted", repository="https://github.com/example/toolbox",branch="main",resourceIds=[]),
            taskSync=dict(enabled=True,journalPath=str(self.journal),resources=[]))))
        s.operate(self.journal, dict(operation="begin", owner=self.owner,binding=str(self.sync_binding)))
        self.addCleanup(lambda: s.operate(self.journal, dict(operation="release", owner=self.owner)))
        self.target = self.root / "AGENTS.md"
        self.target.write_bytes(b"# Rules\r\nOriginal\r\n")
        self.state = self.root / "binding.json"

    def git(self, *args):
        return a.git(self.repo, *args).decode().strip()

    def request(self, operation, state=None, **extra):
        state = state or self.state
        raw = a.raw_at(state)
        result = dict(operation=operation, journalPath=str(self.journal), owner=self.owner,
                      expectedBindingSha256=a.digest(raw) if raw else "missing", reviewed=True)
        if raw:
            binding = json.loads(raw)
            source, target = a.paths(binding, state)
            result.update(expectedSourceSha256=a.digest(source.read_bytes()), expectedInstalledSha256=a.digest(target.read_bytes()))
        result.update(extra)
        return result

    def register(self, state=None, target=None, **extra):
        state, target = state or self.state, target or self.target
        request = self.request("register", state, strategy="original",
                               expectedInstalledSha256=a.digest(target.read_bytes()),
                               binding=dict(gitRoot=str(self.repo), repository="https://github.com/example/toolbox",
                                            branch="main", agent="codex", installedPath=str(target),
                                            authorizationEvidence="Isolated test only"))
        request.update(extra)
        result = a.operate(state, request)
        self.assertEqual(result["sync"], "pending")
        return json.loads(state.read_bytes()), Path(result["sourcePath"])

    def test_repository_lock_loss_blocks_document_write(self):
        self.register()
        before = self.state.read_bytes()
        (self.repo / '.git/ai-toolbox-sync.flow.lock').unlink()
        with self.assertRaises(OSError):
            a.operate(self.state, self.request('collect'))
        self.assertEqual(self.state.read_bytes(), before)

    def test_whole_document_collect_noop_and_exact_bytes(self):
        self.target.write_bytes(b"\xef\xbb\xbf# Rules\r\n" + "中文".encode() + b"\nend")
        binding, source = self.register()
        self.assertEqual(a.content(json.loads(source.read_bytes())), self.target.read_bytes())
        before = source.read_bytes()
        self.assertTrue(a.operate(self.state, self.request("collect"))["unchanged"])
        self.assertEqual(source.read_bytes(), before)
        self.target.write_bytes(self.target.read_bytes() + b"\nnew rule")
        result = a.operate(self.state, self.request("collect"))
        doc = json.loads(source.read_bytes())
        self.assertEqual(result["revision"], 2)
        self.assertEqual(doc["history"][1]["previousSha256"], binding["baselineContentSha256"])
        self.assertEqual(a.content(doc), self.target.read_bytes())
        self.assertTrue(Path(result["backup"]).joinpath("source.json").is_file())

    def test_three_generation_provenance_and_isolation(self):
        first, first_file = self.register()
        self.git("add", "agent-documents")
        self.git("commit", "-m", "Original")
        original = first_file.read_bytes()
        root_ref = None
        parent_file = first_file
        states = []
        for i, mode in enumerate(("append", "reorganize")):
            doc = json.loads(parent_file.read_bytes())
            ref = dict(repository=doc["repository"], commit=self.git("rev-parse", "HEAD"),
                       **{key: doc[key] for key in ("documentId", "revision", "sha256", "agent")})
            root_ref = root_ref or ref
            target, state = self.root / f"CLAUDE{i}.md", self.root / f"binding{i}.json"
            target.write_bytes(a.content(doc) + f"new computer {i}".encode())
            binding, parent_file = self.register(state, target, strategy=mode, parent=ref, parentCheckout=str(self.repo))
            derived = json.loads(parent_file.read_bytes())
            self.assertEqual(derived["parent"], ref)
            self.assertEqual(derived["root"], root_ref)
            self.assertNotEqual(derived["documentId"], first["documentId"])
            self.git("add", "agent-documents")
            self.git("commit", "-m", "Fork")
            states.append((state, target))
        state, target = states[-1]
        target.write_bytes(target.read_bytes() + b"\nmy edit")
        a.operate(state, self.request("collect", state))
        self.assertEqual(first_file.read_bytes(), original)
        self.assertEqual(self.target.read_bytes(), b"# Rules\r\nOriginal\r\n")
        self.assertNotIn("my edit", states[0][1].read_text())

    def test_all_import_modes_require_verified_parent(self):
        _, source = self.register()
        self.git("add", "agent-documents"); self.git("commit", "-m", "Root")
        doc = json.loads(source.read_bytes())
        ref = dict(repository=doc["repository"], commit=self.git("rev-parse", "HEAD"),
                   **{k: doc[k] for k in ("documentId", "revision", "sha256", "agent")})
        for mode in ("overwrite", "reorganize", "append", "insert"):
            target = self.root / (mode + ".md"); target.write_bytes(b"reviewed final whole document")
            state = self.root / (mode + ".json")
            _, path = self.register(state, target, strategy=mode, parent=ref, parentCheckout=str(self.repo))
            self.assertEqual(json.loads(path.read_bytes())["strategy"], mode)
        ref["sha256"] = "0" * 64
        with self.assertRaises(ValueError):
            self.register(self.root / "bad.json", strategy="append", parent=ref, parentCheckout=str(self.repo))

    def test_apply_only_own_bound_file(self):
        _, source = self.register()
        other = self.root / "OTHER.md"; other.write_bytes(b"do not touch")
        updated = a.revision(json.loads(source.read_bytes()), b"remote whole document\n")
        source.write_bytes(a.encoded(updated))
        a.operate(self.state, self.request("apply", inUse=False))
        self.assertEqual(self.target.read_bytes(), b"remote whole document\n")
        self.assertEqual(other.read_bytes(), b"do not touch")

    def test_in_use_and_local_remote_conflict(self):
        _, source = self.register()
        source.write_bytes(a.encoded(a.revision(json.loads(source.read_bytes()), b"remote")))
        with self.assertRaises(ValueError): a.operate(self.state, self.request("apply", inUse=True))
        self.target.write_bytes(b"local")
        with self.assertRaises(ValueError): a.operate(self.state, self.request("apply", inUse=False))
        with self.assertRaises(ValueError): a.operate(self.state, self.request("collect"))
        self.assertEqual(self.target.read_bytes(), b"local")
        self.assertEqual(a.content(json.loads(source.read_bytes())), b"remote")

    def test_stale_review_and_wrong_identity(self):
        _, source = self.register()
        request = self.request("collect")
        self.target.write_bytes(b"edit after review")
        with self.assertRaises(ValueError): a.operate(self.state, request)
        doc = json.loads(source.read_bytes()); doc["installationId"] = str(a.uuid.uuid4())
        source.write_bytes(a.encoded(doc))
        with self.assertRaises(ValueError): a.operate(self.state, self.request("inspect"))

    def test_unbound_remote_or_branch_rejected(self):
        self.register()
        self.git("remote", "set-url", "origin", "https://github.com/example/other")
        with self.assertRaises(ValueError): a.operate(self.state, self.request("inspect"))

    def test_other_resource_pending_cannot_be_bypassed(self):
        self.journal.write_text(json.dumps(dict(schemaVersion=1, pending={"action":"push"}, observation={"resourceId":"skill:other"})), encoding="utf-8")
        with self.assertRaises(ValueError): self.register()
        self.assertFalse(self.state.exists())

    def test_broken_parent_and_immutable_provenance_refused(self):
        _, source = self.register()
        doc = a.revision(json.loads(source.read_bytes()), b"new")
        fake = dict(repository=doc["repository"], commit="a"*40, documentId=str(a.uuid.uuid4()), revision=1, sha256="b"*64, agent="claude")
        doc.update(parent=fake, root=fake, strategy="append")
        source.write_bytes(a.encoded(doc))
        original = self.target.read_bytes()
        with self.assertRaises(ValueError): a.operate(self.state, self.request("apply", inUse=False))
        self.assertEqual(self.target.read_bytes(), original)

    def test_link_and_hardlink_refused_before_read(self):
        other = self.root / "hard.md"
        os.link(self.target, other)
        with self.assertRaises(ValueError): self.register()

    def test_binding_inside_repo_refused(self):
        with self.assertRaises(ValueError): self.register(self.repo / "binding.json")

    def test_git_preserves_empty_process_config(self):
        with patch.dict(os.environ, {"GIT_CONFIG_COUNT":"1", "GIT_CONFIG_KEY_0":"credential.helper", "GIT_CONFIG_VALUE_0":""}):
            self.register()

    def test_partial_write_recovery_no_false_success(self):
        _, source = self.register()
        self.target.write_bytes(b"local change")
        write = a.write
        def fail_binding(path, raw, expected):
            if path == self.state: raise OSError("synthetic failure")
            return write(path, raw, expected)
        with patch.object(a, "write", side_effect=fail_binding), self.assertRaises(OSError):
            a.operate(self.state, self.request("collect"))
        self.assertTrue(self.state.with_suffix(".pending.json").exists())
        with self.assertRaises(ValueError): a.operate(self.state, self.request("collect"))
        result = a.operate(self.state, self.request("recover"))
        self.assertTrue(result["recovered"])
        self.assertFalse(self.state.with_suffix(".pending.json").exists())
        self.assertTrue(a.operate(self.state, self.request("collect"))["unchanged"])

    def test_failed_write_then_new_edit_is_not_recovered(self):
        self.register(); self.target.write_bytes(b"first edit")
        write = a.write
        def fail_binding(path, raw, expected):
            if path == self.state: raise OSError("synthetic failure")
            return write(path, raw, expected)
        with patch.object(a, "write", side_effect=fail_binding), self.assertRaises(OSError):
            a.operate(self.state, self.request("collect"))
        self.target.write_bytes(b"second edit")
        with self.assertRaises(ValueError): a.operate(self.state, self.request("recover"))
        self.assertTrue(self.state.with_suffix(".pending.json").exists())

    def test_history_rewrite_refused(self):
        _, source = self.register()
        doc = a.revision(json.loads(source.read_bytes()), b"next")
        doc["history"][0]["at"] = "2020-01-01T00:00:00+00:00"
        source.write_bytes(a.encoded(doc))
        with self.assertRaises(ValueError): a.operate(self.state, self.request("apply", inUse=False))

    def test_git_transport_preserves_snapshot_and_history(self):
        _, source = self.register()
        self.git("add", "agent-documents"); self.git("commit", "-m", "v1")
        first = self.git("rev-parse", "HEAD")
        remote = self.root / "remote.git"
        subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
        self.git("push", str(remote), "main")
        clone = self.root / "second"
        subprocess.run(["git", "clone", "-b", "main", str(remote), str(clone)], check=True, capture_output=True)
        self.target.write_bytes(b"whole v2")
        a.operate(self.state, self.request("collect"))
        self.git("add", "agent-documents"); self.git("commit", "-m", "v2")
        self.git("push", str(remote), "main")
        a.git(clone, "pull", "--ff-only")
        relative = source.relative_to(self.repo)
        self.assertEqual(json.loads((clone / relative).read_bytes()), json.loads(source.read_bytes()))
        self.assertEqual(a.content(json.loads((clone / relative).read_bytes())), self.target.read_bytes())
        self.assertEqual(a.content(json.loads(a.git(clone, "show", first + ":" + relative.as_posix()))), b"# Rules\r\nOriginal\r\n")

    def test_records_and_catalog_accept_document_kind(self):
        request = dict(id="agent-document:test", patch=dict(name="Codex rules", kind="agent-document", sourceIdentity="document:test"))
        doc = record_decision.apply_update(dict(schemaVersion=1, records=[]), request)
        self.assertEqual(doc["records"][0]["kind"], "agent-document")
        item = dict(id="agent-document:test", kind="agent-document", name="Codex rules", ownership="derived", triggerPrompt="导入全文")
        row = build_catalog.export(dict(schemaVersion=1, resources=[item]))["resources"][0]
        self.assertEqual(row["triggerPrompt"], "导入全文")

    def test_sync_commit_integrity_preserves_document_digest_contract(self):
        binding, source = self.register()
        self.git("add", "agent-documents"); self.git("commit", "-m", "Snapshot")
        resource_id = "agent-document:" + binding["documentId"]
        observed = a.operate(self.state, self.request("inspect"))
        value = dict(resourceId=resource_id, sourceDigest=observed["sourceDigest"],
            installedDigest=observed["installedDigest"], head=self.git("rev-parse", "HEAD"),
            remoteTip=self.git("rev-parse", "HEAD"), localPaths=[],remotePaths=[],
            remoteAvailable=True,scopeReviewed=True,inUse=False)
        state = dict(session=dict(id="fixture",identity=[str(self.repo),"unused","main"],
            resources={resource_id:dict(id=resource_id,kind="agent-document",sourcePath=str(source),
                installedPath=str(self.target),documentBindingPath=str(self.state))}))
        s.check_integrity(state,value)
        self.assertEqual(state["integrity"]["sourceDigest"],observed["sourceDigest"])
        self.assertEqual(state["integrity"]["fileCount"],1)
        source.write_bytes(source.read_bytes()+b" ")
        with self.assertRaisesRegex(ValueError,"Committed document bundle differs"):
            s.check_integrity(state,value)


if __name__ == "__main__":
    unittest.main()
