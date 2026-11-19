"""Offline tests for the PROGRESS.md form of session state: session-start, stop-gate and the misread referent, each
with PROGRESS.md present and with the unchanged STATE.md fallback."""

from __future__ import annotations

import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

HOOKS = Path(__file__).resolve().parents[2] / "hooks"
sys.path.insert(0, str(HOOKS))
import _common
import jev_client

TMP = tempfile.mkdtemp()
# Hermetic: the live settings.json enables jev-band, which changes what the hooks inject.
_common.SETTINGS = os.path.join(TMP, "settings-no-band.json")
with open(_common.SETTINGS, "w", encoding="utf-8") as _fh:
    _fh.write("{}")
PROGRESS = """# Progress
Updated: 2026-09-26 10:00

## Now
Hook rework in place.

## Open
- [jev-labels] Relabel the Jev evaluation set
  against the new kinds
- Decide the inbox expiry default

## Next
Run the suite.
"""
STATE = """- 2026-09-20 09:00 fact: something verified
- 2026-09-20 09:05 pending[p7]: finish the loader probe
- 2026-09-20 09:10 decision: keep the old path
"""


def load(name):
    run, _common.run = _common.run, lambda n, f: None
    stdin, sys.stdin = sys.stdin, io.TextIOWrapper(io.BytesIO())
    try:
        spec = importlib.util.spec_from_file_location("progress_" + name.replace("-", "_"), HOOKS / (name + ".py"))
        assert spec and spec.loader
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    finally:
        _common.run, sys.stdin = run, stdin


session_start = load("session-start")
stop_gate = load("stop-gate")
misread = load("misread-check")


def project(progress=None, state=None, tool_uses=()):
    """A fake project dir: transcript.jsonl with the given tool uses, memory/PROGRESS.md and memory/STATE.md."""
    d = tempfile.mkdtemp(dir=TMP)
    os.makedirs(os.path.join(d, "memory"))
    for name, text in (("PROGRESS.md", progress), ("STATE.md", state)):
        if text is not None:
            with open(os.path.join(d, "memory", name), "w", encoding="utf-8") as fh:
                fh.write(text)
    path = os.path.join(d, "transcript.jsonl")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(json.dumps({"type": "user", "message": {"role": "user", "content": "x1"}}) + "\n")
        for name, inp in tool_uses:
            fh.write(
                json.dumps(
                    {
                        "type": "assistant",
                        "message": {"role": "assistant", "content": [{"type": "tool_use", "name": name, "input": inp}]},
                    }
                )
                + "\n"
            )
    return {"transcript_path": path, "cwd": d, "session_id": ""}


def memory(payload, name):
    return os.path.join(os.path.dirname(payload["transcript_path"]), "memory", name)


def context(out):
    return json.loads(out)["hookSpecificOutput"]["additionalContext"]


class SessionStart(unittest.TestCase):
    def setUp(self):
        self.inbox = tempfile.mkdtemp(dir=TMP)
        self.real = _common.inbox_dir
        _common.inbox_dir = lambda: self.inbox

    def tearDown(self):
        _common.inbox_dir = self.real

    def test_progress_injected_whole_with_inbox(self):
        for name, first in (
            ("README.md", "# inbox"),
            ("2020-01-01-old.md", "expires: 2020-01-02"),
            ("2026-09-26-new.md", "expires: 2999-01-01"),
            ("2026-09-26-bare.md", "no expiry"),
        ):
            with open(os.path.join(self.inbox, name), "w", encoding="utf-8") as fh:
                fh.write(first + "\nbody\n")
        payload = project(progress=PROGRESS, state=STATE)
        ctx = context(session_start.main(payload))
        self.assertIn(PROGRESS.strip(), ctx)
        self.assertIn("frozen history", ctx)
        self.assertNotIn("Recent:", ctx)
        self.assertNotIn("pending[p7]", ctx)
        self.assertNotIn("next id", ctx)
        self.assertIn("- 2020-01-01-old.md expires 2020-01-02 EXPIRED", ctx)
        self.assertIn("- 2026-09-26-new.md expires 2999-01-01\n", ctx + "\n")
        self.assertIn("- 2026-09-26-bare.md no expires line", ctx)
        self.assertNotIn("README", ctx)
        self.assertNotIn("lines (limit", ctx)

    def test_owner_goes_first(self):
        payload = project(progress=PROGRESS)
        with open(memory(payload, "OWNER.md"), "w", encoding="utf-8") as fh:
            fh.write("- build cache capped at 10 GB\n")
        ctx = context(session_start.main(payload))
        self.assertLess(ctx.index("build cache capped at 10 GB"), ctx.index(PROGRESS.strip()[:20]))

    def test_missing_owner_asks_for_it(self):
        self.assertIn("OWNER.md) does not exist yet", context(session_start.main(project(progress=PROGRESS))))

    def test_long_owner_is_cut(self):
        payload = project(progress=PROGRESS)
        with open(memory(payload, "OWNER.md"), "w", encoding="utf-8") as fh:
            fh.write("x" * (session_start.OWNER_CHARS + 500))
        ctx = context(session_start.main(payload))
        self.assertIn("merge it down", ctx)
        self.assertLessEqual(len(ctx), session_start.CAP)

    def test_long_progress_warns(self):
        payload = project(progress=PROGRESS + "\n".join(f"- filler {i}" for i in range(80)))
        self.assertIn("(limit 80 lines", context(session_start.main(payload)))

    def test_injection_stays_under_the_cap(self):
        """Claude Code keeps 10,000 characters of additionalContext; a long cross-project STATE is trimmed to fit and
        an oversized PROGRESS.md is cut with a notice to the model and the user."""
        gstate = os.path.join(tempfile.mkdtemp(dir=TMP), "STATE.md")
        with open(gstate, "w", encoding="utf-8") as fh:
            fh.write("\n".join("- 2026-09-26 00:{:02d} fact: {}".format(i, "y" * 900) for i in range(20)) + "\n")
        real, _common.global_state_path = _common.global_state_path, lambda: gstate
        try:
            out = json.loads(session_start.main(project(progress=PROGRESS, state=STATE)))
            ctx = out["hookSpecificOutput"]["additionalContext"]
            self.assertLessEqual(len(ctx), session_start.CAP)
            self.assertTrue(ctx.startswith("Owner decisions and owner facts"))
            self.assertIn("Continue from this project's PROGRESS.md", ctx)
            self.assertIn(PROGRESS.strip(), ctx)
            self.assertIn("00:19 fact", ctx)
            self.assertNotIn("systemMessage", out)
            big = PROGRESS + "\n".join("- item {} {}".format(i, "z" * 200) for i in range(60))
            out = json.loads(session_start.main(project(progress=big)))
            ctx = out["hookSpecificOutput"]["additionalContext"]
            self.assertLessEqual(len(ctx), session_start.CAP)
            self.assertIn("injection cut", ctx)
            self.assertIn("were cut", out["systemMessage"])
            self.assertNotIn("read ", out["systemMessage"])
            self.assertIn("characters (limit", ctx[:700])
        finally:
            _common.global_state_path = real

    def test_state_fallback_unchanged(self):
        payload = project(state=STATE)
        ctx = context(session_start.main(payload))
        self.assertIn("Recent:\n" + STATE.strip(), ctx)
        self.assertIn("next id: p8", ctx)
        self.assertNotIn("PROGRESS", ctx)
        self.assertNotIn("Inbox", ctx)

    def test_no_state_no_progress(self):
        self.assertIn("has no", context(session_start.main(project())))


EDIT = ("Edit", {"file_path": "D:/proj/notes.md"})


class StopGate(unittest.TestCase):
    def test_progress_edit_without_rewrite_blocks(self):
        payload = project(progress=PROGRESS, state=STATE, tool_uses=[EDIT])
        out = json.loads(stop_gate.main(payload))
        self.assertEqual(out["decision"], "block")
        self.assertIn("PROGRESS.md", out["reason"])
        self.assertIn("Now, Open and Next", out["reason"])

    def test_progress_rewrite_passes(self):
        payload = project(progress=PROGRESS, tool_uses=[EDIT])
        payload = project(progress=PROGRESS, tool_uses=[EDIT, ("Write", {"file_path": memory(payload, "PROGRESS.md")})])
        self.assertIsNone(stop_gate.main(payload))

    def test_progress_ignores_state_append(self):
        payload = project(
            progress=PROGRESS,
            state=STATE,
            tool_uses=[EDIT, ("Bash", {"command": "echo '- x fact: y' >> memory/STATE.md"})],
        )
        self.assertIn("PROGRESS.md", json.loads(stop_gate.main(payload))["reason"])

    def test_rewrite_before_edit_blocks(self):
        payload = project(progress=PROGRESS)
        payload = project(progress=PROGRESS, tool_uses=[("Edit", {"file_path": memory(payload, "PROGRESS.md")}), EDIT])
        self.assertEqual(json.loads(stop_gate.main(payload))["decision"], "block")

    def test_state_fallback_unchanged(self):
        payload = project(state=STATE, tool_uses=[EDIT])
        reason = json.loads(stop_gate.main(payload))["reason"]
        self.assertIn("after the last STATE.md line", reason)
        payload = project(state=STATE, tool_uses=[EDIT, ("Bash", {"command": "echo '- x fact: y' >> memory/STATE.md"})])
        self.assertIsNone(stop_gate.main(payload))

    def test_no_edit_passes(self):
        self.assertIsNone(stop_gate.main(project(progress=PROGRESS)))


class DeclaredCheck(unittest.TestCase):
    """The test command stop-gate names: a declared quality.json "check" wins, package.json means Bun, never npm."""

    def repo(self, files):
        root = tempfile.mkdtemp()
        for rel, text in files.items():
            os.makedirs(os.path.dirname(os.path.join(root, rel)) or root, exist_ok=True)
            with open(os.path.join(root, rel), "w", encoding="utf-8") as fh:
                fh.write(text)
        return root

    def test_quality_json_check_key_is_read(self):
        root = self.repo({".claude/quality.json": '{"check": "bun run check"}', "package.json": "{}"})
        self.assertEqual(stop_gate.project_root(os.path.join(root, "a.py"))[1], "bun run check")

    def test_package_json_means_bun(self):
        with_script = self.repo({"package.json": '{"scripts": {"test": "uv run pytest -q"}}'})
        bare = self.repo({"package.json": "{}"})
        self.assertEqual(stop_gate.project_root(os.path.join(with_script, "a.ts"))[1], "bun run test")
        self.assertEqual(stop_gate.project_root(os.path.join(bare, "a.ts"))[1], "bun test")

    def test_shell_rewrite_of_progress_counts(self):
        cmd = "sed -i 's/^Updated: .*/Updated: now/' ~/.claude/projects/x/memory/PROGRESS.md"
        self.assertTrue(stop_gate.PROGRESS_FILE.search(cmd) and stop_gate.WRITE.search(cmd))

    def test_declared_check_counts_as_a_test_run(self):
        self.assertTrue(stop_gate.RUNNERS.search("cd D:/dev/proj-a && bun run check"))


class Referent(unittest.TestCase):
    def setUp(self):
        self.saved = (jev_client.nouls, jev_client.LOG, jev_client.READINGS, jev_client.MODEL_FILE)
        jev_client.LOG = os.path.join(TMP, "logs", "jev-hooks.jsonl")
        jev_client.READINGS = os.path.join(TMP, "readings")
        jev_client.MODEL_FILE = os.path.join(TMP, "jev-model.txt")

    def tearDown(self):
        jev_client.nouls, jev_client.LOG, jev_client.READINGS, jev_client.MODEL_FILE = self.saved

    def test_progress_open_items(self):
        options = misread.referent_question(project(progress=PROGRESS, state=STATE))[2]
        self.assertEqual(set(options), {"last_reply", "new_topic", "jev-labels", "item-2"})
        self.assertEqual(options["jev-labels"], "Relabel the Jev evaluation set against the new kinds")
        self.assertEqual(options["item-2"], "Decide the inbox expiry default")

    def test_state_fallback_unchanged(self):
        options = misread.referent_question(project(state=STATE))[2]
        self.assertEqual(set(options), {"last_reply", "new_topic", "p7"})
        self.assertEqual(options["p7"], "finish the loader probe")

    def test_slug_not_shown(self):
        jev_client.nouls = lambda state, qs: {
            "clear": 0.9,
            "holds": 0.0,
            "kind": ["instruction", 0.9],
            "referent": ["jev-labels", 0.9],
        }
        payload = dict(project(progress=PROGRESS), prompt="x2")
        out = json.loads(misread.main(payload))
        ctx = out["hookSpecificOutput"]["additionalContext"]
        self.assertNotIn("systemMessage", out)
        self.assertNotIn("jev-labels", ctx)
        self.assertIn("refers to an open item (0.90): Relabel the Jev", ctx)
        self.assertIn(" · an open item 0.90 · ", ctx.split("\n")[0])  # the reading line hides the slug too

    def test_state_id_shown(self):
        jev_client.nouls = lambda state, qs: {
            "clear": 0.9,
            "holds": 0.0,
            "kind": ["instruction", 0.9],
            "referent": ["p7", 0.9],
        }
        payload = dict(project(state=STATE), prompt="x2")
        out = json.loads(misread.main(payload))
        self.assertIn("refers to p7 (0.90): finish the loader probe", out["hookSpecificOutput"]["additionalContext"])


if __name__ == "__main__":
    unittest.main()
