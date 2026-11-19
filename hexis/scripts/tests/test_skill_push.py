"""Offline tests for tier 1 of the skill push (hooks/skill-push.py) and its reset in session-start.py."""

from __future__ import annotations

import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from typing import cast

HOOKS = Path(__file__).resolve().parents[2] / "hooks"
sys.path.insert(0, str(HOOKS))
import _common


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


push = load("skill-push")
session_start = load("session-start")
SKILLS = ("hexis-routing", "hexis-shell", "hexis-commit", "hexis-linear", "hexis-records", "hexis-research")


class Base(unittest.TestCase):
    def setUp(self):
        self.dirs = (_common.SKILLS, _common.SKILL_STATE)
        root = tempfile.mkdtemp()
        _common.SKILLS, _common.SKILL_STATE = os.path.join(root, "skills"), os.path.join(root, "state")
        for name in SKILLS:
            os.makedirs(os.path.join(_common.SKILLS, name))
            with open(os.path.join(_common.SKILLS, name, "SKILL.md"), "w", encoding="utf-8") as fh:
                fh.write(f"---\nname: {name}\ndescription: When {name} applies.\n---\n\nBODY OF {name}\n")

    def tearDown(self):
        _common.SKILLS, _common.SKILL_STATE = self.dirs

    def call(self, tool, session="s1", agent=None, **tool_input):
        payload = {"tool_name": tool, "tool_input": tool_input, "session_id": session}
        if agent:
            payload["agent_id"] = agent
        out = push.main(payload)
        return json.loads(out)["hookSpecificOutput"] if out else None


class Mapping(unittest.TestCase):
    def test_each_rule(self):
        cases = [
            ("Agent", {"prompt": "x"}, "hexis-routing"),
            ("Workflow", {"script": "x"}, "hexis-routing"),
            ("Bash", {"command": 'git commit -m "x"'}, "hexis-commit"),
            ("PowerShell", {"command": "git -C D:/r commit --amend"}, "hexis-commit"),
            ("Bash", {"command": "git commit -F - <<'EOF'\nmsg\nEOF"}, "hexis-commit"),
            ("Bash", {"command": "python ~/.claude/scripts/linear_ops.py list"}, "hexis-linear"),
            ("mcp__linear-mcp__list_issues", {}, "hexis-linear"),
            ("Bash", {"command": "cat > x <<'EOF'\nhi\nEOF"}, "hexis-shell"),
            ("PowerShell", {"command": "a\nb"}, "hexis-shell"),
            ("Write", {"file_path": "C:/Users/k/.claude/projects/p/memory/PROGRESS.md"}, "hexis-records"),
            ("Edit", {"file_path": "C:\\Users\\k\\.claude\\inbox\\2026-09-26-x.md"}, "hexis-records"),
            ("MultiEdit", {"file_path": "/home/k/.claude/knowledge/machine.md"}, "hexis-records"),
            ("Edit", {"file_path": "C:\\Users\\k\\.claude\\decisions\\d.md"}, "hexis-records"),
            # stage 1 of the rules tiering: every record write triggers the push
            ("Write", {"file_path": "C:/Users/k/.claude/projects/p/memory/STATE.md"}, "hexis-records"),
            ("Edit", {"file_path": "C:/Users/k/.claude/projects/p/memory/feedback-x.md"}, "hexis-records"),
            ("Edit", {"file_path": "C:/Users/k/.claude/STATE.md"}, "hexis-records"),
            ("Bash", {"command": 'echo "- 2026-09-26 16:00 fact: x" >> memory/STATE.md'}, "hexis-records"),
            (
                "PowerShell",
                {"command": "'x' | tee -a C:/Users/k/.claude/projects/p/memory/PROGRESS.md"},
                "hexis-records",
            ),
        ]
        for tool, tool_input, want in cases:
            self.assertEqual(push.skill_for(tool, tool_input), want, (tool, tool_input))

    def test_config_edits_and_installs_push_research(self):
        cases = [
            ("Edit", {"file_path": "C:/Users/k/.claude/mcp/linear_mcp/package.json"}),
            ("Write", {"file_path": "C:\\Users\\k\\proj\\tsconfig.build.json"}),
            ("Edit", {"file_path": "/home/k/p/biome.jsonc"}),
            ("Write", {"file_path": "C:/p/bunfig.toml"}),
            ("Edit", {"file_path": "C:/p/pyproject.toml"}),
            ("Bash", {"command": "bun add -D -E @biomejs/biome"}),
            ("PowerShell", {"command": "winget install -e --id astral-sh.ruff"}),
            ("Bash", {"command": "python -m pip install --ignore-installed ruff"}),
        ]
        for tool, tool_input in cases:
            self.assertEqual(push.skill_for(tool, tool_input), "hexis-research", (tool, tool_input))
        for tool, tool_input in [
            ("Edit", {"file_path": "C:/p/src/package.json.bak"}),
            ("Edit", {"file_path": "C:/p/src/tools.ts"}),
            ("Bash", {"command": "bun install"}),
            ("Bash", {"command": "bun test"}),
        ]:
            self.assertIsNone(push.skill_for(tool, tool_input), (tool, tool_input))

    def test_words_inside_a_heredoc_body_are_data(self):
        cmd = "python - <<'EOF'\nnote = 'run git commit, then bun add x and linear_ops'\nEOF"
        self.assertEqual(push.skills_for("Bash", {"command": cmd}), ["hexis-shell"])
        self.assertEqual(
            push.skills_for("Bash", {"command": "cat >> memory/STATE.md <<EOF\ngit commit\nEOF"}),
            ["hexis-shell", "hexis-records"],
        )

    def test_all_triggered_skills_in_priority_order(self):
        cmd = "cat >> memory/STATE.md <<'EOF'\n- x\nEOF"
        self.assertEqual(push.skills_for("Bash", {"command": cmd}), ["hexis-shell", "hexis-records"])

    def test_non_matching_calls(self):
        cases = [
            ("Bash", {"command": "git status"}),
            ("Bash", {"command": "cat memory/STATE.md > /tmp/copy.txt"}),
            ("Read", {"file_path": "C:/Users/k/.claude/knowledge/machine.md"}),
            ("Edit", {"file_path": "C:/Users/k/.claude/rules/code.md"}),
            ("Grep", {"pattern": "git commit"}),
            ("Edit", {"file_path": "C:/x.py", "command": "git commit"}),
            ("mcp__plane-mcp__list", {}),
        ]
        for tool, tool_input in cases:
            self.assertIsNone(push.skill_for(tool, tool_input), (tool, tool_input))


class DenyOnce(Base):
    def test_second_skill_of_a_call_is_pushed_once_the_first_is(self):
        cmd = "cat >> memory/STATE.md <<'EOF'\n- x\nEOF"
        self.assertIn("hexis-shell", cast(dict, self.call("Bash", command=cmd))["permissionDecisionReason"])
        self.assertIn("hexis-records", cast(dict, self.call("Bash", command=cmd))["permissionDecisionReason"])
        self.assertIsNone(self.call("Bash", command=cmd))

    def test_first_call_denied_with_the_body_then_allowed(self):
        out = cast(dict, self.call("Bash", command="git commit -m x"))
        self.assertEqual(out["permissionDecision"], "deny")
        reason = out["permissionDecisionReason"]
        self.assertTrue(
            reason.startswith(
                "Procedure for this action (skill hexis-commit) - read it, then run the same "
                "call again.\nBODY OF hexis-commit"
            )
        )
        self.assertNotIn("description:", reason)
        self.assertIsNone(self.call("Bash", command="git commit -m x"))
        self.assertEqual(
            cast(dict, self.call("Agent", prompt="x"))["permissionDecision"], "deny"
        )  # another skill still fires

    def test_scopes_are_per_agent(self):
        self.assertIsNotNone(self.call("Agent", session="s2", prompt="x"))
        self.assertIsNone(self.call("Agent", session="s2", prompt="x"))
        self.assertIsNotNone(self.call("Agent", session="s2", agent="a1", prompt="x"))
        self.assertIsNone(self.call("Agent", session="s2", agent="a1", prompt="x"))
        self.assertIsNotNone(self.call("Agent", session="s2", agent="a2", prompt="x"))
        self.assertIsNotNone(self.call("Agent", session="s3", prompt="x"))
        self.assertEqual(
            _common.pushed_skills("s2"), {"main": ["hexis-routing"], "a1": ["hexis-routing"], "a2": ["hexis-routing"]}
        )

    def test_non_matching_call_passes_and_records_nothing(self):
        self.assertIsNone(self.call("Bash", session="s4", command="ls"))
        self.assertEqual(_common.pushed_skills("s4"), {})

    def test_missing_skill_file_allows(self):
        os.remove(os.path.join(_common.SKILLS, "hexis-shell", "SKILL.md"))
        self.assertIsNone(self.call("Bash", session="s5", command="a\nb"))
        self.assertEqual(_common.pushed_skills("s5"), {})

    def test_unwritable_state_allows(self):
        os.makedirs(os.path.dirname(_common.SKILL_STATE), exist_ok=True)
        with open(_common.SKILL_STATE, "w") as fh:  # a file where the state directory should be
            fh.write("x")
        self.assertIsNone(self.call("Agent", session="s6", prompt="x"))

    def test_corrupt_state_is_read_as_empty(self):
        os.makedirs(_common.SKILL_STATE)
        with open(os.path.join(_common.SKILL_STATE, "s7.json"), "w") as fh:
            fh.write("{not json")
        self.assertIsNotNone(self.call("Agent", session="s7", prompt="x"))
        self.assertIsNone(self.call("Agent", session="s7", prompt="x"))

    def test_no_session_allows(self):
        self.assertIsNone(self.call("Agent", session="", prompt="x"))


class Reset(Base):
    def test_compact_clears_the_session_only(self):
        self.call("Agent", session="c1", prompt="x")
        self.call("Agent", session="c2", prompt="x")
        session_start.main({"source": "resume", "session_id": "c1"})
        self.assertIn("main", _common.pushed_skills("c1"))
        session_start.main({"source": "compact", "session_id": "c1"})
        self.assertEqual(_common.pushed_skills("c1"), {})
        self.assertIn("main", _common.pushed_skills("c2"))
        self.assertIsNotNone(self.call("Agent", session="c1", prompt="x"))


class RealSkills(unittest.TestCase):
    def test_every_pushed_skill_exists_and_fits(self):
        root = Path(__file__).resolve().parents[2] / "skills"
        for name in SKILLS:
            path = root / name / "SKILL.md"
            self.assertEqual(_common.skill_meta(str(path))[0], name)
            body = cast(str, _common.skill_body(str(path), 10**6))
            self.assertLessEqual(len(body), _common.SKILL_CHARS, name)


if __name__ == "__main__":
    unittest.main()
