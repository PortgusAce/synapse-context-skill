import importlib.util
import json
import os
from pathlib import Path
import subprocess
import shutil
import sys
import tempfile
import unittest
import uuid
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "skills/synapse-context/scripts/context_ledger.py"
spec = importlib.util.spec_from_file_location("context_ledger", SCRIPT)
ledger = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ledger)


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.temp_parent = Path(os.environ.get("SYNAPSE_TEST_TMP", tempfile.gettempdir())).resolve()
        self.base = self.temp_parent / ("synapse-context-test-" + uuid.uuid4().hex)
        # Inherit test-parent permissions (Windows restricted tokens cannot
        # reopen Python 3.13+ TemporaryDirectory's owner-only directories).
        self.base.mkdir()
        self.root = self.base / "project with spaces"
        self.root.mkdir()

    def tearDown(self):
        # Only clean the temporary tree allocated by this test.
        self.assertTrue(self.base.is_relative_to(self.temp_parent))
        self.assertTrue(self.base.name.startswith("synapse-context-test-"))
        shutil.rmtree(self.base)

    def put(self, path, text):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        return target

    def begin(self, *scopes, **kwargs):
        return ledger.start(self.root, scopes or ["."], **kwargs)["run_id"]

    def directory(self, run):
        return self.root / ".contextos/runs" / run

    def test_non_git_created_modified_deleted_and_unchanged(self):
        self.put("src/a.py", "old")
        self.put("src/delete.py", "delete")
        self.put("src/same.py", "same")
        run = self.begin("src")
        self.put("src/a.py", "new")
        self.put("src/new.py", "new")
        (self.root / "src/delete.py").unlink()
        result = ledger.finish(self.root, run)
        self.assertEqual({c["path"]: c["operation"] for c in result["changes"]}, {
            "src/a.py": "modified", "src/delete.py": "deleted", "src/new.py": "created"})
        self.assertTrue(all(c["attribution"] == "observed_only" for c in result["changes"]))
        self.assertIsNone(result["task_success"])
        self.assertFalse((self.root / ".git").exists())

    def test_closed_result_is_idempotent_and_reports_later_drift(self):
        self.put("a.txt", "before")
        run = self.begin("a.txt")
        self.put("a.txt", "during")
        first = ledger.finish(self.root, run)
        self.put("a.txt", "after")
        self.assertEqual(first, ledger.finish(self.root, run))
        report = ledger.report(self.root, run)
        self.assertEqual(report["changes"], first["changes"])
        self.assertEqual(report["current_drift"][0]["operation"], "modified")

    def test_note_freshness_and_preserved_history(self):
        self.put("experiment.py", "attempt 1")
        run = self.begin("experiment.py")
        ledger.note(self.root, run, "experiment.py", "Reproduce CSV error", "temporary")
        self.assertEqual(ledger.report(self.root, run)["notes"][0]["freshness"], "current")
        self.put("experiment.py", "attempt 2")
        self.assertEqual(ledger.report(self.root, run)["notes"][0]["freshness"], "stale")
        (self.root / "experiment.py").unlink()
        report = ledger.report(self.root, run)
        self.assertEqual(report["notes"][0]["freshness"], "missing")
        self.assertEqual(report["notes"][0]["source"], "agent_suggestion")

    def test_limited_report_keeps_recent_notes_without_erasing_old_ones(self):
        self.put("a.txt", "one")
        run = self.begin("a.txt")
        ledger.note(self.root, run, "a.txt", "first purpose", "temporary")
        self.put("a.txt", "two")
        ledger.note(self.root, run, "a.txt", "updated purpose", "active")
        report = ledger.report(self.root, run, limit=1)
        self.assertEqual(report["notes"][0]["purpose"], "updated purpose")
        self.assertEqual(report["notes"][0]["freshness"], "current")
        self.assertEqual(report["notes_omitted"], 1)
        self.assertEqual(len(list((self.directory(run) / "notes").glob("*.json"))), 2)

    def test_inaccessible_baseline_is_not_a_creation(self):
        self.put("a.txt", "old")
        with patch.object(ledger, "fingerprint", side_effect=PermissionError):
            run = self.begin("a.txt")
        self.put("a.txt", "new")
        result = ledger.finish(self.root, run)
        self.assertEqual(result["changes"][0]["operation"], "unknown")
        self.assertEqual(result["coverage"], "partial")

    def test_unreadable_directory_is_not_mass_deletion(self):
        self.put("src/a.txt", "a")
        self.put("src/b.txt", "b")
        run = self.begin("src")
        real = Path.iterdir

        def blocked(path):
            if path == self.root / "src":
                raise PermissionError("fixture")
            return real(path)

        with patch.object(Path, "iterdir", blocked):
            result = ledger.finish(self.root, run)
        self.assertEqual([c["operation"] for c in result["changes"]], ["unknown", "unknown"])

    def test_excluded_files_and_ledger_do_not_enter_manifests(self):
        self.put(".env", "synthetic-secret")
        self.put("keys/demo.pem", "synthetic-key")
        self.put("node_modules/a.js", "dep")
        self.put("cache/item.txt", "cache")
        self.put("readme.md", "keep")
        run = self.begin(".", patterns=["cache"])
        before = ledger.read_json(self.directory(run) / "before.json")
        self.assertEqual(set(before["entries"]), {"readme.md"})
        self.assertEqual(ledger.finish(self.root, run)["changes"], [])
        self.assertIn("*", (self.root / ".contextos/.gitignore").read_text())

    def test_missing_scope_can_be_created_later(self):
        run = self.begin("new-directory")
        self.put("new-directory/example.py", "new")
        self.assertEqual(ledger.finish(self.root, run)["changes"][0]["operation"], "created")

    def test_rename_is_add_delete_not_invented_identity(self):
        self.put("old.txt", "same bytes")
        run = self.begin(".")
        (self.root / "old.txt").rename(self.root / "new.txt")
        self.assertEqual({c["operation"] for c in ledger.finish(self.root, run)["changes"]}, {"created", "deleted"})

    def test_overlapping_runs_are_independent_not_causal(self):
        self.put("a.txt", "before")
        first = self.begin("a.txt", label="A")
        second = self.begin("a.txt", label="B")
        self.assertNotEqual(first, second)
        self.put("a.txt", "an unattributed writer")
        for run in (first, second):
            self.assertEqual(ledger.finish(self.root, run)["changes"][0]["attribution"], "observed_only")
            self.assertFalse(ledger.report(self.root, run)["fork_base_known"])

    def test_invalid_scopes_and_run_ids_cannot_escape(self):
        for scope in ("../outside", "/outside", "C:/outside", "a:stream", ".env", ".contextos"):
            with self.subTest(scope=scope), self.assertRaises(ValueError):
                self.begin(scope)
        with self.assertRaises(ValueError):
            ledger.load_run(self.root, "../../outside")
        self.assertFalse((self.root / ".contextos").exists())

    def test_note_does_not_expand_scope(self):
        self.put("in/a.txt", "a")
        self.put("out/b.txt", "b")
        run = self.begin("in")
        with self.assertRaises(ValueError):
            ledger.note(self.root, run, "out/b.txt", "outside", "active")
        self.assertFalse((self.directory(run) / "notes").exists())

    def test_symlink_scope_and_ledger_are_rejected(self):
        outside = self.base / "outside"
        outside.mkdir()
        (outside / "secret.txt").write_text("fixture", encoding="utf-8")
        try:
            (self.root / "link").symlink_to(outside, target_is_directory=True)
        except OSError as exc:
            self.skipTest("OS does not permit symlink creation: " + str(exc))
        with self.assertRaises(ValueError):
            self.begin("link")
        run = self.begin(".")
        before = ledger.read_json(self.directory(run) / "before.json")
        self.assertEqual(before["entries"], {})
        self.assertEqual(before["coverage"], "partial")

    def test_missing_baseline_cannot_be_silently_rebuilt(self):
        run = self.begin(".")
        (self.directory(run) / "before.json").unlink()
        with self.assertRaises(FileNotFoundError):
            ledger.finish(self.root, run)
        self.assertFalse((self.directory(run) / "result.json").exists())

    def test_existing_lock_does_not_get_removed_or_overwritten(self):
        run = self.begin(".")
        lock = self.directory(run) / ".lock"
        lock.write_text("other-writer", encoding="utf-8")
        with self.assertRaises(ValueError):
            ledger.finish(self.root, run)
        self.assertEqual(lock.read_text(), "other-writer")

    def test_resume_preserves_already_captured_end_snapshot(self):
        self.put("a.txt", "before")
        run = self.begin("a.txt")
        self.put("a.txt", "at end")
        snap = ledger.snapshot(self.root, ["a.txt"], [])
        ledger.write_json(self.directory(run) / "after.json", snap)
        self.put("a.txt", "after interruption")
        result = ledger.finish(self.root, run)
        self.assertEqual(result["changes"][0]["after_hash"], snap["entries"]["a.txt"]["sha256"])
        self.assertTrue(ledger.report(self.root, run)["current_drift"])

    def test_late_tracking_and_truncation_are_explicit(self):
        run = self.begin(".", late=True)
        self.put("a.txt", "a")
        self.put("b.txt", "b")
        report = ledger.report(self.root, run, limit=1)
        self.assertTrue(report["tracking_started_late"])
        self.assertEqual(report["changes_omitted"], 1)
        self.assertEqual(report["current_drift_omitted"], 1)
        self.assertEqual(report["state"], "open")

    def test_cli_workflow_with_unicode_paths(self):
        self.put("资料/输入.txt", "before")

        def cli(*args):
            proc = subprocess.run([sys.executable, str(SCRIPT), *args, "--root", str(self.root)],
                                  capture_output=True, encoding="utf-8", env={**os.environ, 'PYTHONIOENCODING': 'utf-8'})
            self.assertEqual(proc.returncode, 0, proc.stderr)
            return json.loads(proc.stdout)

        run = cli("start", "--include", "资料", "--label", "编码检查")["run_id"]
        self.put("资料/输入.txt", "after")
        cli("note", "--run", run, "--path", "资料/输入.txt", "--purpose", "编码测试资料", "--lifecycle", "temporary")
        self.assertEqual(cli("finish", "--run", run)["change_count"], 1)
        result = cli("report", "--run", run)
        self.assertEqual(result["notes"][0]["freshness"], "current")
        self.assertEqual(result["counts"]["modified"], 1)


if __name__ == "__main__":
    unittest.main()
