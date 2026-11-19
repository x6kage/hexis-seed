"""Offline tests for hooks/knowledge-check.py: a fixture index in a temp dir, no network, no Jev."""

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

TMP = tempfile.mkdtemp()


def load(name):
    run, _common.run = _common.run, lambda n, f: None
    stdin, sys.stdin = sys.stdin, io.TextIOWrapper(io.BytesIO())
    try:
        spec = importlib.util.spec_from_file_location(name.replace("-", "_"), HOOKS / (name + ".py"))
        assert spec and spec.loader
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    finally:
        _common.run, sys.stdin = run, stdin


kc = load("knowledge-check")
INDEX = os.path.join(TMP, "INDEX.md")
with open(INDEX, "w", encoding="utf-8") as fh:
    fh.write(
        "# Knowledge index\n\n"
        "- [machine.md](machine.md) — hardware, Windows shells, the Job object, WSL vhdx and Python on this machine\n"
        "- [desktop-wm.md](desktop-wm.md) — komorebi + whkd + yasb setup: files, autostart, restart safely\n"
        "- [stream-overlays.md](stream-overlays.md) - Streamlabs layout, OBS 32.2.2, Twitch CORS, YouTube API quota\n"
        "- [stream-clips.md](stream-clips.md) - OBS replay buffer, Twitch clips, YouTube Shorts, Vosk trigger\n"
        "- [exchange-geoblock.md](exchange-geoblock.md) - Exchange geoblock and the trading records\n"
    )
setattr(kc, "INDEX", INDEX)  # noqa: B010 - kc is a dynamically loaded module; pyright rejects direct attribute assignment on ModuleType
setattr(kc, "STATE_DIR", os.path.join(TMP, "state"))  # noqa: B010 - see above
setattr(kc, "LOG", os.path.join(TMP, "logs", "knowledge-check.jsonl"))  # noqa: B010 - see above
setattr(kc, "WORKFLOWS_DIR", os.path.join(TMP, "workflows"))  # noqa: B010 - see above

PLUGINS = os.path.join(TMP, "plugins")
USER_SKILLS = os.path.join(TMP, "skills")


def write_skill(root, folder, name, description):
    os.makedirs(os.path.join(root, "skills", folder), exist_ok=True)
    with open(os.path.join(root, "skills", folder, "SKILL.md"), "w", encoding="utf-8") as fh:
        fh.write(f"---{chr(10)}name: {name}{chr(10)}description: {description}{chr(10)}---{chr(10)}body{chr(10)}")


for plugin, folder, name, description in [
    ("vidforge", "vidforge-create", "vidforge-create", "Create a new Vidforge video"),
    (
        "toolbox",
        "clip-export",
        "clip-export",
        "Export clips through the FFmpeg pipeline using Mediabunny and Chromium.",
    ),
    ("design", "design-critique", "design-critique", "Get structured feedback on usability."),
]:
    root = os.path.join(PLUGINS, "synced", "sync-id", plugin)
    os.makedirs(os.path.join(root, ".claude-plugin"), exist_ok=True)
    with open(os.path.join(root, ".claude-plugin", "plugin.json"), "w", encoding="utf-8") as fh:
        json.dump({"name": plugin}, fh)
    write_skill(root, folder, name, description)
write_skill(
    os.path.join(TMP), "hexis-pushed", "hexis-pushed", "Pushed by a hook already, Vidforge Pushed."
)  # user skills dir is TMP/skills
setattr(kc, "PLUGINS_DIR", PLUGINS)  # noqa: B010 - see above
setattr(kc, "USER_SKILLS_DIR", USER_SKILLS)  # noqa: B010 - see above
setattr(kc, "SKILL_CACHE", os.path.join(TMP, "logs", "skills.json"))  # noqa: B010 - see above

STREAM = "Build a go-live panel: post to Twitch and YouTube when OBS starts streaming."
GENERIC = (
    "Read the file, check the session and the project rules, then write the result before the user reads it. "
    "Run it with Python on Windows inside the Job object, as Claude Code on Opus does; report what changed and why."
)


class KnowledgeCheck(unittest.TestCase):
    def call(self, session, tool="Agent", **inp):
        return kc.main({"session_id": session, "tool_name": tool, "tool_input": inp, "cwd": TMP})

    def last_log(self):
        with open(kc.LOG, encoding="utf-8") as fh:
            return json.loads(fh.readlines()[-1])

    def log_lines(self):
        if not os.path.exists(kc.LOG):
            return 0
        with open(kc.LOG, encoding="utf-8") as fh:
            return len(fh.readlines())

    def test_subagent_and_other_tools_are_exempt_and_unlogged(self):
        before = self.log_lines()
        payload = {"session_id": "k-sub", "tool_name": "Agent", "tool_input": {"prompt": STREAM}, "agent_id": "a1"}
        self.assertIsNone(kc.main(payload))
        self.assertIsNone(kc.main({"session_id": "k-sub", "tool_name": "Bash", "tool_input": {"command": STREAM}}))
        self.assertEqual(self.log_lines(), before)

    def test_unrelated_brief_passes(self):
        self.assertIsNone(self.call("k-none", prompt="Rename the variable foo to bar in src/app.ts and run the tests."))
        row = self.last_log()
        self.assertEqual(row["decision"], "pass")
        self.assertEqual(row["matched"], {})

    def test_overlapping_uncited_brief_is_stopped_once(self):
        out = json.loads(self.call("k-stop", prompt=STREAM))
        reason = out["hookSpecificOutput"]["permissionDecisionReason"]
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertIn("knowledge/stream-overlays.md (terms: ", reason)
        self.assertIn("knowledge/stream-clips.md", reason)
        self.assertNotIn("machine.md", reason)
        row = self.last_log()
        self.assertEqual(row["decision"], "deny")
        self.assertEqual(sorted(row["matched"]), ["stream-clips.md", "stream-overlays.md"])
        self.assertEqual(row["chars"], len(STREAM))
        self.assertIsNone(self.call("k-stop", prompt=STREAM))
        self.assertEqual(self.last_log()["decision"], "resend")

    def test_changed_brief_is_stopped_again(self):
        self.assertIsNotNone(self.call("k-change", prompt=STREAM))
        self.assertIsNotNone(self.call("k-change", prompt=STREAM + " Also add a clock."))

    def test_stem_alone_overlaps(self):
        out = self.call("k-stem", prompt="Check the Exchange order book depth.")
        self.assertIn(
            "knowledge/exchange-geoblock.md", json.loads(out)["hookSpecificOutput"]["permissionDecisionReason"]
        )

    def test_cited_brief_passes(self):
        cited = STREAM + " knowledge/stream-overlays.md settles the CORS question; stream-clips.md does not apply."
        self.assertIsNone(self.call("k-cited", prompt=cited))
        row = self.last_log()
        self.assertEqual(row["decision"], "pass")
        self.assertEqual(sorted(row["cited"]), ["stream-clips.md", "stream-overlays.md"])

    def test_bare_hyphenated_stem_cites_but_one_word_stem_does_not(self):
        self.assertTrue(kc.cites("see stream-overlays for the quota", "stream-overlays.md"))
        self.assertFalse(kc.cites("on this machine", "machine.md"))
        self.assertTrue(kc.cites("see knowledge/machine for the shell", "machine.md"))

    def test_workflow_script_text_is_read(self):
        script = "export default async () => { await agent(`" + STREAM + "`, {model: 'sonnet', effort: 'low'}) }"
        out = self.call("k-wf", tool="Workflow", script=script)
        self.assertIn("stream-overlays.md", json.loads(out)["hookSpecificOutput"]["permissionDecisionReason"])
        self.assertEqual(self.last_log()["tool"], "Workflow")

    def test_workflow_script_path_and_string_args_are_read(self):
        path = os.path.join(TMP, "wf.js")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("export default async (args) => agent(args, {model: 'haiku', effort: 'low'})")
        self.assertIsNotNone(self.call("k-wfpath", tool="Workflow", scriptPath=path, args=STREAM))
        self.assertIsNone(self.call("k-wfargs", tool="Workflow", scriptPath=path, args={"brief": STREAM}))

    def test_stoplist_keeps_a_generic_brief_from_matching(self):
        self.assertEqual(len({"python", "windows", "job"} & kc.brief_tokens(GENERIC)), 3)
        self.assertIsNone(self.call("k-generic", prompt=GENERIC))
        self.assertEqual(self.last_log()["matched"], {})

    def reason(self, out):
        return json.loads(out)["hookSpecificOutput"]["permissionDecisionReason"]

    def test_skill_overlap_is_stopped_once_naming_the_skill(self):
        brief = "Cut the intro for the stream: make a Vidforge intro with the title card."
        reason = self.reason(self.call("k-skill", prompt=brief))
        self.assertIn("installed skill covers - vidforge:vidforge-create (terms: vidforge)", reason)
        self.assertNotIn("knowledge/", reason)
        row = self.last_log()
        self.assertEqual(row["decision"], "deny")
        self.assertEqual(sorted(row["skills"]), ["vidforge:vidforge-create"])
        self.assertIsNone(self.call("k-skill", prompt=brief))
        self.assertEqual(self.last_log()["decision"], "resend")

    def test_skill_and_knowledge_overlap_share_one_message(self):
        reason = self.reason(self.call("k-both", prompt=STREAM + " Make it with Vidforge."))
        self.assertIn("knowledge/stream-overlays.md", reason)
        self.assertIn("vidforge:vidforge-create", reason)
        self.assertEqual(reason.count("send the launch again"), 1)

    def test_three_description_terms_overlap_without_the_plugin_name(self):
        reason = self.reason(self.call("k-terms", prompt="Cut the clips with FFmpeg, Mediabunny and Chromium."))
        self.assertIn("toolbox:clip-export", reason)

    def test_naming_the_skill_or_saying_why_not_passes(self):
        for i, brief in enumerate(
            [
                "Make a Vidforge intro; the vidforge:vidforge-create skill does the render.",
                "Make a Vidforge intro. Not using vidforge because the scene is hand-drawn canvas code.",
                "Make a Vidforge intro with the vidforge skill.",
                "Use FFmpeg, Mediabunny and Chromium via clip-export for the cuts.",
            ]
        ):
            self.assertIsNone(self.call(f"k-named{i}", prompt=brief), brief)
            self.assertEqual(self.last_log()["decision"], "pass")
        self.assertEqual(self.last_log()["skills_cited"], ["toolbox"])

    def test_generic_plugin_name_alone_is_not_a_match(self):
        self.assertIsNone(self.call("k-design", prompt="Name the design of the new tool and write it down."))
        self.assertEqual(self.last_log()["skills"], {})

    def test_hook_pushed_user_skills_are_not_indexed(self):
        self.assertNotIn(["", "hexis-pushed"], [r[:2] for r in kc.scan_skills()])

    def test_skill_cache_is_reused_until_a_directory_changes(self):
        calls = []
        real = kc.scan_skills
        setattr(kc, "scan_skills", lambda: calls.append(1) or real())  # noqa: B010 - see above
        try:
            if os.path.exists(kc.SKILL_CACHE):
                os.remove(kc.SKILL_CACHE)
            first = kc.load_skill_entries()
            self.assertEqual(kc.load_skill_entries(), first)
            self.assertEqual(len(calls), 1)
            skills_dir = os.path.join(PLUGINS, "synced", "sync-id", "vidforge", "skills")
            future = os.stat(skills_dir).st_mtime + 100
            os.utime(skills_dir, (future, future))
            kc.load_skill_entries()
            self.assertEqual(len(calls), 2)
        finally:
            setattr(kc, "scan_skills", real)  # noqa: B010 - see above

    def test_failed_state_write_lets_the_launch_through(self):
        saved = kc.STATE_DIR
        blocker = os.path.join(TMP, "not-a-dir")
        with open(blocker, "w", encoding="utf-8") as fh:
            fh.write("x")
        setattr(kc, "STATE_DIR", os.path.join(blocker, "state"))  # noqa: B010 - see above
        try:
            self.assertIsNone(self.call("k-fail", prompt=STREAM))
            self.assertEqual(self.last_log()["decision"], "would-deny")
        finally:
            setattr(kc, "STATE_DIR", saved)  # noqa: B010 - see above


if __name__ == "__main__":
    unittest.main()
