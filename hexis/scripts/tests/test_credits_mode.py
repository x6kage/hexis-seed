"""Credits mode ends at the weekly reset by itself."""

from __future__ import annotations

import calendar
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "hooks"))

import credits_mode


def utc(*parts):
    return calendar.timegm(parts)


class CreditsMode(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.real = credits_mode.STATE
        credits_mode.STATE = os.path.join(self.tmp, "logs", "credits.json")
        self.addCleanup(setattr, credits_mode, "STATE", self.real)
        self.progress = os.path.join(self.tmp, "PROGRESS.md")

    def write(self, text):
        with open(self.progress, "w", encoding="utf-8") as fh:
            fh.write(text)

    def test_the_weekly_reset_is_monday_midnight_jst(self):
        # Tuesday 2026-11-10 08:24 JST -> Monday 2026-11-16 00:00 JST (the usage card's resetsAt, 2026-11-15T15:00Z)
        self.assertEqual(credits_mode.next_reset(utc(2026, 11, 9, 23, 24, 0)), utc(2026, 11, 15, 15, 0, 0))
        self.assertEqual(credits_mode.jst(utc(2026, 11, 15, 15, 0, 0)), "Mon 2026-11-16 00:00 JST")
        # at the reset itself the next one is a week on; the one of 2026-10-26 00:00 JST is on the same grid
        self.assertEqual(credits_mode.next_reset(utc(2026, 11, 15, 15, 0, 0)), utc(2026, 11, 22, 15, 0, 0))
        self.assertEqual(credits_mode.next_reset(utc(2026, 10, 24, 3, 0, 0)), utc(2026, 10, 25, 15, 0, 0))

    def test_on_lasts_until_the_reset_and_no_longer(self):
        sunday = utc(2026, 11, 8, 3, 0, 0)
        end = utc(2026, 11, 8, 15, 0, 0)
        self.assertEqual(credits_mode.switch(True, sunday), end)
        self.assertIn("CREDITS MODE ON until Mon 2026-11-09 00:00 JST", credits_mode.line(self.progress, sunday))
        self.assertEqual(credits_mode.line(self.progress, end), "")  # Monday 00:00 JST: over by itself
        self.assertIsNone(credits_mode.until(end + 3600))

    def test_off_ends_it_at_once(self):
        now = utc(2026, 11, 8, 3, 0, 0)
        credits_mode.switch(True, now)
        credits_mode.switch(False, now)
        self.assertIsNone(credits_mode.until(now))

    def test_a_progress_line_that_outlived_the_reset_is_flagged(self):
        # A "CREDITS MODE" line with no end in PROGRESS.md would keep launches labelled as paid from credits.
        monday = utc(2026, 11, 9, 13, 0, 0)
        self.write("# Progress\n## Now\n- CREDITS MODE: owner is on usage credits\n")
        out = credits_mode.line(self.progress, monday)
        self.assertIn("none is active", out)
        self.assertIn("Mon 2026-11-09 00:00 JST", out)
        self.write("# Progress\n## Now\n- credits mode ended at the 11-09 00:00 JST reset\n")
        self.assertEqual(credits_mode.line(self.progress, monday), "")
        self.write("# Progress\n## Now\n- credits mode is a state now (hooks/credits_mode.py)\n")
        self.assertEqual(credits_mode.line(self.progress, monday), "")
        self.write("# Progress\n## Now\n- nothing about it\n")
        self.assertEqual(credits_mode.line(self.progress, monday), "")


if __name__ == "__main__":
    unittest.main()
