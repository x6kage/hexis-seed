"""Offline tests for hooks/agent-guard.py: the model rules, the effort rule for unpinned agents and the workflow
agent() check, and the cold re-cache classification of scripts/session-cost.py."""

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
SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HOOKS))
import _common

TMP = tempfile.mkdtemp()


def load(path, name):
    run, _common.run = _common.run, lambda n, f: None
    stdin, sys.stdin = sys.stdin, io.TextIOWrapper(io.BytesIO())
    try:
        spec = importlib.util.spec_from_file_location(name, path)
        assert spec and spec.loader
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    finally:
        _common.run, sys.stdin = run, stdin


guard = load(HOOKS / "agent-guard.py", "agent_guard")
setattr(guard, "AGENTS_DIR", os.path.join(TMP, "agents"))  # noqa: B010 - guard is a dynamically loaded module; pyright rejects direct attribute assignment on ModuleType
os.makedirs(guard.AGENTS_DIR)
for name, head in (("pinned-low", "model: haiku\neffort: low"), ("model-only", "model: opus")):
    with open(os.path.join(guard.AGENTS_DIR, name + ".md"), "w", encoding="utf-8") as fh:
        fh.write(f"---\nname: {name}\n{head}\n---\nbody\n")
cost = load(SCRIPTS / "session-cost.py", "session_cost")


def launch(subagent_type="", model="sonnet", effort="max", **extra):
    payload = {
        "tool_name": "Agent",
        "tool_input": {"subagent_type": subagent_type, "model": model, "prompt": "x"},
        "effort": {"level": effort},
    }
    payload.update(extra)
    out = guard.main(payload)
    return json.loads(out)["hookSpecificOutput"]["permissionDecisionReason"] if out else None


def run_workflow(script=None, **inp):
    if script is not None:
        inp["script"] = script
    out = guard.main({"tool_name": "Workflow", "tool_input": inp})
    return json.loads(out)["hookSpecificOutput"]["permissionDecisionReason"] if out else None


class AgentLaunch(unittest.TestCase):
    def test_missing_model_denied(self):
        self.assertIn("without an explicit `model`", cast(str, launch(model="")))

    def test_child_launch_denied(self):
        self.assertIn("never spawns a child", cast(str, launch(agent_id="a1")))

    def test_model_must_match_the_pin(self):
        self.assertIn("pinned to `haiku`", cast(str, launch("pinned-low", model="sonnet")))

    def test_unpinned_effort_denied_at_max_and_xhigh(self):
        for level in ("max", "xhigh"):
            self.assertIn("pins none", cast(str, launch("general-purpose", effort=level)))
        self.assertIn("pins none", cast(str, launch("model-only", model="opus")))

    def test_unpinned_allowed_at_high_and_below(self):
        for level in ("high", "medium", "low"):
            self.assertIsNone(launch("general-purpose", effort=level))

    def test_pinned_effort_allowed_at_max(self):
        self.assertIsNone(launch("pinned-low", model="haiku", effort="max"))

    def test_effort_falls_back_to_the_environment(self):
        real = os.environ.get("CLAUDE_EFFORT")
        os.environ["CLAUDE_EFFORT"] = "max"
        try:
            out = guard.main({"tool_name": "Agent", "tool_input": {"subagent_type": "Explore", "model": "haiku"}})
            self.assertIn("pins none", out)
        finally:
            if real is None:
                del os.environ["CLAUDE_EFFORT"]
            else:
                os.environ["CLAUDE_EFFORT"] = real


class WorkflowScript(unittest.TestCase):
    GOOD = (
        "export const meta = {name: 'x', description: 'y'}\n"
        "const r = await parallel(ITEMS.map(i => () => agent(`read ${i.path} and report (agent(x) in text)`,\n"
        "  {label: `r-${i.n}`, model: 'sonnet', effort: 'low', schema: S})))\n"
        "// agent('commented out')\n"
        'const s = await agent(\'summarise\', {model: "opus", effort: "high"})\n'
    )

    def test_every_call_stated_passes(self):
        self.assertIsNone(run_workflow(self.GOOD))

    def test_missing_effort_denied(self):
        self.assertIn("1 agent() call", cast(str, run_workflow("await agent('p', {model: 'sonnet', label: 'x'})")))

    def test_no_options_or_variable_options_denied(self):
        self.assertIn("2 agent() call", cast(str, run_workflow("await agent('p')\nawait agent('q', OPTS)")))

    def test_nested_template_braces(self):
        src = "await agent(`a ${x.map(y => `${y}`).join(',')} b`, {model: 'haiku', effort: 'low'})"
        self.assertIsNone(run_workflow(src))

    def test_script_path_is_read(self):
        path = os.path.join(TMP, "wf.js")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("await agent('p', {model: 'sonnet'})")
        self.assertIn("1 agent() call", cast(str, run_workflow(scriptPath=path)))

    def test_unresolvable_name_passes(self):
        self.assertIsNone(run_workflow(name="no-such-workflow-here"))


class ColdRecache(unittest.TestCase):
    def transcript(self, usages):
        path = os.path.join(tempfile.mkdtemp(dir=TMP), "t.jsonl")
        with open(path, "w", encoding="utf-8") as fh:
            fh.writelines(
                json.dumps(
                    {
                        "type": "assistant",
                        "message": {
                            "id": f"m{i}",
                            "model": "claude-opus-5-5",
                            "usage": {
                                "input_tokens": 1,
                                "cache_read_input_tokens": read,
                                "output_tokens": 10,
                                "cache_creation": {
                                    "ephemeral_5m_input_tokens": 0,
                                    "ephemeral_1h_input_tokens": write,
                                },
                            },
                        },
                    }
                )
                + "\n"
                for i, (read, write) in enumerate(usages)
            )
        return path

    def cold(self, usages):
        st = cost.scan(self.transcript(usages), cost.blank())
        return sum(r.get("cold_n", 0) for r in st["fams"].values())

    def test_start_and_switches_count(self):
        # session start; normal turns; a model/effort switch that still reads the 41k tool prefix
        self.assertEqual(self.cold([(0, 60_000), (60_000, 2_000), (62_000, 3_000), (41_000, 372_000)]), 2)

    def test_large_tool_result_is_not_cold(self):
        self.assertEqual(self.cold([(0, 30_000), (30_000, 40_000), (100_000, 60_000)]), 1)


if __name__ == "__main__":
    unittest.main()
