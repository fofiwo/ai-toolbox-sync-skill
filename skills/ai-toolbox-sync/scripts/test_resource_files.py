import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import resource_files as resources


class ResourceFileTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source, self.target = self.root / "source", self.root / "target"
        self.source.mkdir()
        self.target.mkdir()
        (self.source / "SKILL.md").write_bytes(b"new")
        (self.target / "SKILL.md").write_bytes(b"old")
        (self.source / "references").mkdir()
        (self.source / "references" / "guide.md").write_bytes(b"complete reference")
        self.receipt, self.backup = self.root / "receipt.json", self.root / "backup"

    def test_restore_complete_resource_and_recovery_copy(self):
        plan = resources.prepare(self.source, self.target)
        outcome = resources.apply(plan, self.receipt, self.backup)
        self.assertEqual(outcome["status"], "applied")
        self.assertEqual((self.target / "references/guide.md").read_bytes(), b"complete reference")
        self.assertEqual((self.backup / "SKILL.md").read_bytes(), b"old")
        self.assertEqual((self.source / "SKILL.md").read_bytes(), b"new")

    def test_collect_uses_same_engine_with_explicit_reverse_direction(self):
        (self.target / "references").mkdir()
        (self.target / "references/guide.md").write_bytes(b"complete reference")
        plan = resources.prepare(self.target, self.source)
        resources.apply(plan, self.receipt, self.backup)
        self.assertEqual((self.source / "SKILL.md").read_bytes(), b"old")
        self.assertEqual((self.backup / "SKILL.md").read_bytes(), b"new")

    def test_case_aliases_restore_without_delete_and_keep_recovery_copy(self):
        (self.target / "SKILL.md").rename(self.target / "skill.md")
        if not (self.target / "SKILL.md").exists():
            self.skipTest("Target filesystem distinguishes filename case")
        (self.target / "REFERENCES").mkdir()
        (self.target / "REFERENCES/GUIDE.md").write_bytes(b"old reference")
        (self.source / "references/extra.txt").write_bytes(b"new nested asset")
        plan = resources.prepare(self.source, self.target)
        self.assertTrue(all(change["after"] is not None for change in plan["changes"]))
        resources.apply(plan, self.receipt, self.backup)
        self.assertEqual((self.target / "skill.md").read_bytes(), b"new")
        self.assertEqual((self.target / "REFERENCES/GUIDE.md").read_bytes(), b"complete reference")
        self.assertEqual((self.target / "references/extra.txt").read_bytes(), b"new nested asset")
        self.assertEqual((self.backup / "SKILL.md").read_bytes(), b"old")
        self.assertEqual((self.backup / "references/guide.md").read_bytes(), b"old reference")
        self.assertEqual(resources.prepare(self.source, self.target)["changes"], [])

    def test_case_aliases_still_reject_edits_after_review(self):
        (self.target / "SKILL.md").rename(self.target / "skill.md")
        if not (self.target / "SKILL.md").exists():
            self.skipTest("Target filesystem distinguishes filename case")
        plan = resources.prepare(self.source, self.target)
        (self.target / "skill.md").write_bytes(b"later user edit")
        with self.assertRaisesRegex(ValueError, "changed since review"):
            resources.apply(plan, self.receipt, self.backup)
        self.assertEqual((self.target / "skill.md").read_bytes(), b"later user edit")
        self.assertFalse(self.receipt.exists())

    def test_same_content_with_case_alias_is_not_a_change(self):
        (self.target / "SKILL.md").rename(self.target / "skill.md")
        if not (self.target / "SKILL.md").exists():
            self.skipTest("Target filesystem distinguishes filename case")
        (self.target / "skill.md").write_bytes(b"new")
        (self.target / "references").mkdir()
        (self.target / "references/guide.md").write_bytes(b"complete reference")
        plan = resources.prepare(self.source, self.target)
        self.assertEqual(plan["changes"], [])
        self.assertEqual(plan["sourceDigest"], plan["targetDigest"])

    def test_distinct_case_paths_require_delete_on_case_sensitive_filesystem(self):
        (self.target / "SKILL.md").rename(self.target / "skill.md")
        if (self.target / "SKILL.md").exists():
            self.skipTest("Target filesystem treats filename case as an alias")
        plan = resources.prepare(self.source, self.target)
        with self.assertRaisesRegex(ValueError, "Deletion"):
            resources.apply(plan, self.receipt, self.backup)
        resources.apply(plan, self.receipt, self.backup, allow_delete=True)
        self.assertFalse((self.target / "skill.md").exists())
        self.assertEqual((self.target / "SKILL.md").read_bytes(), b"new")

    def test_later_local_modification_refuses_before_writes(self):
        plan = resources.prepare(self.source, self.target)
        (self.target / "SKILL.md").write_bytes(b"local edit after review")
        with self.assertRaisesRegex(ValueError, "changed since review"):
            resources.apply(plan, self.receipt, self.backup)
        self.assertEqual((self.target / "SKILL.md").read_bytes(), b"local edit after review")
        self.assertFalse(self.receipt.exists())

    def test_deletion_is_explicit_and_preserves_original(self):
        (self.target / "local.txt").write_bytes(b"keep until approved")
        plan = resources.prepare(self.source, self.target)
        with self.assertRaisesRegex(ValueError, "Deletion"):
            resources.apply(plan, self.receipt, self.backup)
        self.assertTrue((self.target / "local.txt").exists())
        resources.apply(plan, self.receipt, self.backup, allow_delete=True)
        self.assertEqual((self.backup / "local.txt").read_bytes(), b"keep until approved")

    def test_tampered_plan_is_rejected(self):
        plan = copy.deepcopy(resources.prepare(self.source, self.target))
        plan["changes"][0]["path"] = "../escape"
        with self.assertRaisesRegex(ValueError, "changed since review"):
            resources.apply(plan, self.receipt, self.backup)
        self.assertFalse(self.receipt.exists())

    def test_sensitive_entries_and_nested_targets_rejected(self):
        with self.assertRaisesRegex(ValueError, "separate"):
            resources.prepare(self.source, self.source / "nested")
        (self.source / ".env").write_bytes(b"synthetic placeholder")
        with self.assertRaisesRegex(ValueError, "Sensitive"):
            resources.prepare(self.source, self.target)

    def test_target_parent_file_conflict_preserved(self):
        (self.target / "references").write_bytes(b"local file")
        with self.assertRaisesRegex(ValueError, "shape conflict"):
            resources.prepare(self.source, self.target)
        self.assertEqual((self.target / "references").read_bytes(), b"local file")

    def test_new_install(self):
        self.target = self.root / "new-install"
        plan = resources.prepare(self.source, self.target)
        resources.apply(plan, self.receipt, self.backup)
        self.assertEqual((self.target / "SKILL.md").read_bytes(), b"new")

    def test_reviewed_runtime_exclusion_is_preserved(self):
        (self.source / "cache").mkdir()
        (self.target / "cache").mkdir()
        (self.source / "cache/generated.txt").write_bytes(b"source runtime")
        (self.target / "cache/generated.txt").write_bytes(b"local runtime")
        plan = resources.prepare(self.source, self.target, ["cache"])
        resources.apply(plan, self.receipt, self.backup)
        self.assertEqual((self.target / "cache/generated.txt").read_bytes(), b"local runtime")
        self.assertFalse((self.backup / "cache").exists())

    def test_recovery_inside_resource_or_repository_is_rejected(self):
        plan = resources.prepare(self.source, self.target)
        with self.assertRaises(ValueError):
            resources.apply(plan, self.source / "receipt.json", self.backup)
        repo = self.root / "git-repo"
        repo.mkdir()
        (repo / ".git").mkdir()
        with self.assertRaisesRegex(ValueError, "outside Git"):
            resources.apply(plan, repo / "receipt.json", self.backup)

    def test_interruption_retains_receipt_and_backups(self):
        plan = resources.prepare(self.source, self.target)
        original = resources.atomic
        def interrupted(path, content):
            if path == self.target / "SKILL.md":
                raise OSError("synthetic interruption")
            return original(path, content)
        with patch.object(resources, "atomic", side_effect=interrupted):
            with self.assertRaises(OSError):
                resources.apply(plan, self.receipt, self.backup)
        self.assertEqual(json.loads(self.receipt.read_text())["status"], "incomplete")
        self.assertEqual((self.target / "SKILL.md").read_bytes(), b"old")
        self.assertEqual((self.backup / "SKILL.md").read_bytes(), b"old")


if __name__ == "__main__":
    unittest.main()
