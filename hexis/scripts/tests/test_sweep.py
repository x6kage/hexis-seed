"""Offline tests for scripts/sweep.py (ended vs live session dirs, KEEP, links out of the root, dry run, report) and for
the C: alarm in hooks/cost-meter.py."""

import collections
import importlib.util
import io
import os
import re
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
HOOKS = SCRIPTS.parent / "hooks"
spec = importlib.util.spec_from_file_location("sweep", SCRIPTS / "sweep.py")
assert spec and spec.loader
sweep = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sweep)

sys.path.insert(0, str(HOOKS))
import _common

DAY = 86400
A, B, C, D, E, F = (f"{n:08x}-0000-4000-8000-000000000000" for n in range(1, 7))


def load_meter():
    run, _common.run = _common.run, lambda _name, _fn: None
    stdin, sys.stdin = sys.stdin, io.TextIOWrapper(io.BytesIO())
    try:
        s = importlib.util.spec_from_file_location("cost_meter", HOOKS / "cost-meter.py")
        assert s and s.loader
        mod = importlib.util.module_from_spec(s)
        s.loader.exec_module(mod)
        return mod
    finally:
        _common.run, sys.stdin = run, stdin


def write(path, data=b"x" * 10):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(data)


def age(path, days):
    """Sets the mtime of path and everything under it (links not followed) to days ago."""
    t = time.time() - days * DAY
    for dirpath, dirnames, filenames in os.walk(path, topdown=False):
        for n in filenames + dirnames:
            p = os.path.join(dirpath, n)
            if not os.path.isjunction(p):
                os.utime(p, (t, t))
    os.utime(path, (t, t))


class Sweep(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.real = {
            k: getattr(sweep, k) for k in ("ROOT", "PROJECTS", "LOGS", "DEV", "NEVER", "LIST_FILE", "LIST_CARGO")
        }
        root, dev = os.path.join(self.tmp, "root"), os.path.join(self.tmp, "dev")
        for k, v in {
            "ROOT": root,
            "PROJECTS": os.path.join(self.tmp, "projects"),
            "LOGS": os.path.join(self.tmp, "logs"),
            "DEV": dev,
            "NEVER": (dev, os.path.join(self.tmp, "outside")),
            "LIST_FILE": 100,
            "LIST_CARGO": 50,
        }.items():
            setattr(sweep, k, v)
        self.root, self.dev = root, dev
        self.key = os.path.join(root, "K")

    def tearDown(self):
        for k, v in self.real.items():
            setattr(sweep, k, v)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def session(self, sid, days, transcript_days=None, key="K"):
        path = os.path.join(self.root, key, sid)
        write(os.path.join(path, "scratchpad", "a.bin"))
        age(path, days)
        if transcript_days is not None:
            t = os.path.join(sweep.PROJECTS, key, sid + ".jsonl")
            write(t)
            age(t, transcript_days)
        return path

    def test_ended_by_transcript_and_by_inner_mtime(self):
        a = self.session(A, 1, transcript_days=8)  # transcript old: ended although the files are new
        b = self.session(B, 30, transcript_days=1)  # transcript new: live although the files are old
        c = self.session(C, 8)  # no transcript, inner files old: ended
        d = self.session(D, 6)  # no transcript, inner files new: live
        out = sweep.sweep()
        self.assertFalse(os.path.exists(a))
        self.assertTrue(os.path.exists(b))
        self.assertFalse(os.path.exists(c))
        self.assertTrue(os.path.exists(d))
        self.assertEqual(out["ended"], 2)
        self.assertEqual(out["freed"], 20)

    def test_keep_is_honoured(self):
        e = self.session(E, 8)
        write(os.path.join(e, "scratchpad", "keepme", "KEEP"), b"")
        write(os.path.join(e, "scratchpad", "keepme", "data.bin"))
        write(os.path.join(e, "other", "junk.bin"))
        age(e, 8)
        sweep.sweep()
        self.assertTrue(os.path.isfile(os.path.join(e, "scratchpad", "keepme", "data.bin")))
        self.assertFalse(os.path.exists(os.path.join(e, "scratchpad", "a.bin")))
        self.assertFalse(os.path.exists(os.path.join(e, "other")))

    def test_link_outside_root_is_skipped(self):
        if sys.platform != "win32":
            self.skipTest("junctions are Windows-only")
        import _winapi

        outside = os.path.join(self.tmp, "outside")
        write(os.path.join(outside, "sentinel.txt"))
        f = self.session(F, 8, transcript_days=8)  # the new junction makes the inner mtime fresh
        link = os.path.join(f, "scratchpad", "out")
        _winapi.CreateJunction(outside, link)
        age(f, 8)
        top = os.path.join(self.root, "toplink")
        _winapi.CreateJunction(outside, top)
        out = sweep.sweep()
        self.assertTrue(os.path.isfile(os.path.join(outside, "sentinel.txt")))
        self.assertTrue(os.path.isjunction(link))
        self.assertIn(link, out["skipped"])
        self.assertIn(top, out["skipped"])
        self.assertFalse(os.path.exists(os.path.join(f, "scratchpad", "a.bin")))

    def test_only_uuid_session_dirs_and_empty_key_dirs(self):
        other = os.path.join(self.root, "bundled-skills", "2.1.270")
        write(os.path.join(other, "skill.md"))
        age(other, 30)
        empty = os.path.join(self.root, "scan")
        os.makedirs(empty)
        self.session(A, 8, key="K2")
        sweep.sweep()
        self.assertTrue(os.path.isfile(os.path.join(other, "skill.md")))
        self.assertTrue(os.path.isdir(empty))  # empty before the sweep: not "left behind", so kept
        self.assertFalse(os.path.exists(os.path.join(self.root, "K2")))

    def test_dry_run_deletes_nothing(self):
        a = self.session(A, 8)
        now = time.time()
        out = sweep.sweep(dry=True, now=now)
        path = sweep.report(out, True, now)
        self.assertTrue(os.path.isfile(os.path.join(a, "scratchpad", "a.bin")))
        self.assertEqual(out["freed"], 10)
        with open(path, encoding="utf-8") as fh:
            self.assertIn("dry run, nothing deleted", fh.read())
        self.assertFalse(os.path.exists(os.path.join(sweep.LOGS, "latest.txt")))

    def test_listing_and_report(self):
        live = self.session(D, 1)
        write(os.path.join(live, "proj", "target", "CACHEDIR.TAG"), b"Signature")
        write(os.path.join(live, "proj", "target", "debug", "big"), b"x" * 60)
        write(os.path.join(self.dev, "repo", "video.mp4"), b"x" * 200)
        write(os.path.join(self.dev, "repo", ".git", "pack.bin"), b"x" * 200)
        write(os.path.join(self.dev, "rs", "target", "CACHEDIR.TAG"), b"Signature")
        write(os.path.join(self.dev, "rs", "target", "release", "big.bin"), b"x" * 300)
        self.session(A, 8)
        now = time.time()
        out = sweep.sweep(now=now)
        path = sweep.report(out, False, now)
        files = [p for p, _, _ in out["files"]]
        cargo = [p for p, _, _ in out["cargo"]]
        self.assertEqual(files, [os.path.join(self.dev, "repo", "video.mp4")])
        self.assertEqual(
            sorted(cargo), sorted([os.path.join(live, "proj", "target"), os.path.join(self.dev, "rs", "target")])
        )
        self.assertTrue(os.path.isfile(os.path.join(self.dev, "rs", "target", "release", "big.bin")))
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn(os.path.join(self.root, "K", A), text)
        self.assertIn("video.mp4", text)
        with open(os.path.join(sweep.LOGS, "latest.txt"), encoding="utf-8") as fh:
            latest = fh.read().strip()
        self.assertRegex(
            latest,
            r"^swept \d{4}-\d\d-\d\d \d\d:\d\d: freed \d+\.\d GB \(1 ended session dirs, 0 unused build dirs\); "
            + r"\d+\.\d GB listed for the owner "
            + r"in "
            + re.escape(path)
            + "; "
            + re.escape(sweep.DRIVE_LABEL)
            + r" \d+\.\d GB free$",
        )

    def test_unused_build_dirs_are_deleted_used_ones_and_venvs_listed(self):
        # a build cache matters only while it shortens builds.
        stale = os.path.join(self.dev, "old", "target")
        write(os.path.join(stale, "CACHEDIR.TAG"), b"Signature")
        write(os.path.join(stale, "release", "big.bin"), b"x" * 300)
        age(stale, sweep.BUILD_STALE_DAYS + 1)
        fresh = os.path.join(self.dev, "new", "target")
        write(os.path.join(fresh, "CACHEDIR.TAG"), b"Signature")
        write(os.path.join(fresh, "release", "big.bin"), b"x" * 300)
        venv = os.path.join(self.dev, "py", ".venv")
        write(os.path.join(venv, "CACHEDIR.TAG"), b"Signature")
        write(os.path.join(venv, "pyvenv.cfg"), b"home = x")
        write(os.path.join(venv, "Lib", "big.bin"), b"x" * 300)
        age(venv, sweep.BUILD_STALE_DAYS + 30)
        kept = os.path.join(self.dev, "deliverable", "target")
        write(os.path.join(kept, "CACHEDIR.TAG"), b"Signature")
        write(os.path.join(kept, "KEEP"), b"")
        write(os.path.join(kept, "release", "app.exe"), b"x" * 300)
        age(kept, sweep.BUILD_STALE_DAYS + 30)
        # off by default until the owner answers: nothing is deleted, the stale one is listed with its age
        out = sweep.sweep(now=time.time())
        self.assertTrue(os.path.exists(stale))
        self.assertEqual(out["builds"], [])
        self.assertIn(stale, [p for p, _, _ in out["cargo"]])
        setattr(sweep, "DELETE_STALE_BUILDS", True)  # noqa: B010 - a dynamically loaded module
        try:
            out = sweep.sweep(now=time.time())
        finally:
            setattr(sweep, "DELETE_STALE_BUILDS", False)  # noqa: B010 - see above
        self.assertFalse(os.path.exists(stale))
        self.assertEqual([p for p, _, _ in out["builds"]], [stale])
        self.assertTrue(os.path.isfile(os.path.join(fresh, "release", "big.bin")))
        self.assertTrue(os.path.isfile(os.path.join(venv, "Lib", "big.bin")))
        self.assertTrue(os.path.isfile(os.path.join(kept, "release", "app.exe")))
        listed = [p for p, _, _ in out["cargo"]]
        self.assertIn(fresh, listed)
        self.assertIn(venv + " (Python venv)", listed)

    def test_refuses_paths_outside_root(self):
        failures = []
        target = os.path.join(self.tmp, "outside", "x.bin")
        write(target)
        sweep.remove(target, False, failures)
        self.assertTrue(os.path.isfile(target))
        self.assertEqual(len(failures), 1)


class Alarm(unittest.TestCase):
    def setUp(self):
        self.meter = load_meter()
        self.tmp = tempfile.mkdtemp()
        setattr(self.meter, "SWEEP_LATEST", os.path.join(self.tmp, "latest.txt"))  # noqa: B010 - pyright and modules
        self.usage = collections.namedtuple("usage", "total used free")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_below_twenty_gb_warns_and_names_the_sweep(self):
        gb = 1024**3
        self.assertEqual(
            self.meter.alarm(self.usage(2000 * gb, 1985 * gb, 15 * gb)),
            f" WARNING: {self.meter.DISK_LABEL} has 15.0 GB free (0.8 %): tell the user, and name the last sweep: "
            "no sweep has run.",
        )
        write(self.meter.SWEEP_LATEST, b"swept 2026-11-03 06:00: freed 1.0 GB\n")
        self.assertIn(
            "last sweep: swept 2026-11-03 06:00: freed 1.0 GB.",
            self.meter.alarm(self.usage(2000 * gb, 1990 * gb, 10 * gb)),
        )

    def test_alarm_reaches_the_paths_without_a_meter_line(self):
        # the alarm on every prompt, agent prompts and unpriced sessions included.
        gb = 1024**3
        real = self.meter.shutil.disk_usage
        self.meter.shutil.disk_usage = lambda _d: self.usage(2000 * gb, 1985 * gb, 15 * gb)
        try:
            out = self.meter.main({"agent_id": "a1", "transcript_path": ""})
            self.assertIn(f"WARNING: {self.meter.DISK_LABEL} has 15.0 GB free", out)
            self.assertIn(f"WARNING: {self.meter.DISK_LABEL}", self.meter.main({"transcript_path": "missing.jsonl"}))
            self.assertNotIn("Japanese", out)  # an agent's prompt gets no reply-language line
            self.meter.shutil.disk_usage = lambda _d: self.usage(2000 * gb, 1900 * gb, 100 * gb)
            self.assertIsNone(self.meter.main({"agent_id": "a1"}))
            # a user prompt with no priced request yet still gets the Japanese line
            self.assertIn("Reply to the user in Japanese", self.meter.main({"transcript_path": "missing.jsonl"}))
        finally:
            self.meter.shutil.disk_usage = real

    def test_trimmed_meter_while_the_band_is_visible(self):
        # No figures in the context while the band shows them.
        gb = 1024**3
        calc = collections.namedtuple("calc", "summarise_incremental")
        summary = {
            "requests": 5,
            "usd": 1.0,
            "main": 1.0,
            "agents": 0.0,
            "delta": 0.1,
            "context": 10000,
            "avg": 0.2,
            "main_rows": {"opus-5-5": {"usd": 1.0}},
            "fam": "opus-5-5",
            "prev_cold": 0,
        }
        real = (
            self.meter.calculator,
            self.meter.handoff,
            self.meter.crossover,
            self.meter.shutil.disk_usage,
            self.meter.save_cost_line,
            _common.band_visible,
        )
        transcript = os.path.join(self.tmp, "t.jsonl")
        write(transcript)
        try:
            setattr(self.meter, "calculator", lambda: calc(lambda *_a: dict(summary)))  # noqa: B010 - loaded module
            setattr(self.meter, "handoff", lambda _s: "")  # noqa: B010
            setattr(self.meter, "crossover", lambda _c, _s: "")  # noqa: B010
            self.meter.shutil.disk_usage = lambda _d: self.usage(2000 * gb, 1000 * gb, 1000 * gb)
            setattr(self.meter, "save_cost_line", lambda *_a: None)  # noqa: B010
            _common.band_visible = lambda _s: True
            out = self.meter.main({"transcript_path": transcript, "session_id": "s"})
            self.assertNotIn("Session cost", out)
            self.assertNotIn("Report this line", out)
            self.assertIn("Reply to the user in Japanese", out)
            _common.band_visible = lambda _s: False
            out = self.meter.main({"transcript_path": transcript, "session_id": "s"})
            self.assertIn("Session cost $1.00", out)
            self.assertIn("Report this line", out)
        finally:
            for name, value in zip(("calculator", "handoff", "crossover"), real[:3], strict=True):
                setattr(self.meter, name, value)
            self.meter.shutil.disk_usage = real[3]
            setattr(self.meter, "save_cost_line", real[4])  # noqa: B010
            _common.band_visible = real[5]

    def test_no_switch_proposal_while_the_main_is_fable(self):
        # the main is his decision; the meter never advises leaving a Fable main for Opus 5.5.
        row = {"n": 50, "write5": 0, "write1h": 200_000, "output": 100_000, "first": 0}
        for fam in ("fable-5-2", "opus-5-5"):
            s = {"fam": fam, "main_rows": {fam: row}, "context": 400_000}
            self.assertEqual(self.meter.crossover(self.meter.calculator(), s), "")

    def test_at_or_above_twenty_gb_is_silent(self):
        gb = 1024**3
        self.assertEqual(self.meter.alarm(self.usage(2000 * gb, 1980 * gb, 20 * gb)), "")
        self.assertEqual(self.meter.alarm(self.usage(2000 * gb, 1850 * gb, 150 * gb)), "")


if __name__ == "__main__":
    unittest.main()
