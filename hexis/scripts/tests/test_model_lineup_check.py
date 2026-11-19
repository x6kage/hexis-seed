"""Offline tests for scripts/model-lineup-check.py: no change, a new ID, the same ID twice, a legacy move, a parse failure."""

import contextlib
import importlib.util
import io
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
FIX = Path(__file__).resolve().parent / "fixtures"
spec = importlib.util.spec_from_file_location("model_lineup_check", SCRIPTS / "model-lineup-check.py")
assert spec and spec.loader
check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check)

NEW_ID = "claude-fable-5-2"


class LineupCheck(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.page = self.tmp / "page.md"
        self.page.write_text((FIX / "models-overview.md").read_text(encoding="utf-8"), encoding="utf-8")

    def run_check(self, page: Path | None = None, pricing: Path | None = None) -> int:
        args = [
            "--page", str(page or self.page),
            "--settings", str(FIX / "settings.json"),
            "--pricing", str(pricing or FIX / "model-pricing.md"),
            "--inbox", str(self.tmp / "inbox"),
            "--state", str(self.tmp / "state.json"),
            "--log", str(self.tmp / "log.txt"),
        ]  # fmt: skip
        with contextlib.redirect_stdout(io.StringIO()):
            return check.main(args)

    def notes(self) -> list[Path]:
        return sorted((self.tmp / "inbox").glob("*.md")) if (self.tmp / "inbox").exists() else []

    def add_new_model(self) -> None:
        text = self.page.read_text(encoding="utf-8").replace("`claude-fable-5-1`", f"`claude-fable-5-1`, `{NEW_ID}`", 1)
        self.page.write_text(text, encoding="utf-8")

    def test_parse_fixture(self):
        current, legacy, scope = check.parse_page(self.page.read_text(encoding="utf-8"))
        self.assertEqual(scope, "compare table")
        for i in ("claude-fable-5-1", "claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5"):
            self.assertIn(i, current)
        self.assertIn("claude-opus-5", legacy)
        self.assertNotIn("claude-opus-5-5", legacy)

    def test_no_change_writes_no_note(self):
        self.assertEqual(self.run_check(), 0)
        self.assertEqual(self.run_check(), 0)
        self.assertEqual(self.notes(), [])
        self.assertIn("ok scope=compare table", (self.tmp / "log.txt").read_text(encoding="utf-8"))

    def test_new_id_writes_note_with_expiry_and_procedure(self):
        self.add_new_model()
        self.assertEqual(self.run_check(), 0)
        (note,) = self.notes()
        body = note.read_text(encoding="utf-8")
        self.assertRegex(body.splitlines()[0], r"^expires: \d{4}-\d{2}-\d{2}$")
        self.assertIn(NEW_ID, body)
        self.assertIn("pwsh -File ~/claude-autoupdate.ps1 -Update", body)
        self.assertIn("skills/hexis-routing/SKILL.md", body)

    def test_same_new_id_twice_writes_one_note(self):
        self.add_new_model()
        self.run_check()
        self.run_check()
        self.assertEqual(len(self.notes()), 1)

    def test_known_id_moved_to_legacy(self):
        self.run_check()  # baseline: the current IDs are recorded
        text = self.page.read_text(encoding="utf-8").replace(
            "Legacy models (still available): ",
            "Legacy models (still available): [Claude Sonnet 5.5](https://x/models/sonnet-5-5/overview), ",
            1,
        )
        text = text.replace("`claude-sonnet-5-5`", "`claude-sonnet-5-6`")
        self.page.write_text(text, encoding="utf-8")
        self.assertEqual(self.run_check(), 0)
        (note,) = self.notes()
        body = note.read_text(encoding="utf-8")
        self.assertIn("claude-sonnet-5-6", body)
        self.assertIn("Known IDs that moved to the legacy list: claude-sonnet-5-5", body)

    def test_parse_failure_exits_2_without_note(self):
        bad = self.tmp / "bad.md"
        bad.write_text("<html>nothing here</html>", encoding="utf-8")
        self.assertEqual(self.run_check(page=bad), 2)
        self.assertEqual(self.notes(), [])
        self.assertIn("FAIL (1 in a row)", (self.tmp / "log.txt").read_text(encoding="utf-8"))

    def test_three_failures_write_one_failing_note(self):
        bad = self.tmp / "bad.md"
        bad.write_text("<html>nothing here</html>", encoding="utf-8")
        for _ in range(4):
            self.assertEqual(self.run_check(page=bad), 2)
        (note,) = self.notes()
        self.assertIn("model-lineup-check-failing", note.name)
        self.assertTrue(note.read_text(encoding="utf-8").startswith("expires: "))

    def test_dry_run_writes_nothing(self):
        self.add_new_model()
        with contextlib.redirect_stdout(io.StringIO()):
            rc = check.main(["--dry-run", "--page", str(self.page), "--settings", str(FIX / "settings.json"), "--pricing", str(FIX / "model-pricing.md"), "--inbox", str(self.tmp / "inbox"), "--state", str(self.tmp / "state.json"), "--log", str(self.tmp / "log.txt")])  # fmt: skip
        self.assertEqual(rc, 0)
        self.assertEqual(list(self.tmp.glob("*")), [self.page])


if __name__ == "__main__":
    unittest.main()
