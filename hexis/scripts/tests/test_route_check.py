"""Offline tests for hooks/route-check.py: the Noul goes through a fake, nothing touches the network."""

from __future__ import annotations

import importlib.util
import io
import json
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path

HOOKS = Path(__file__).resolve().parents[2] / "hooks"
sys.path.insert(0, str(HOOKS))
import _common
import jev_client

TMP = tempfile.mkdtemp()
jev_client.LOG = os.path.join(TMP, "logs", "jev-hooks.jsonl")
jev_client.MODEL_FILE = os.path.join(TMP, "jev-model.txt")


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


route = load("route-check")
setattr(route, "AGENTS_DIR", os.path.join(TMP, "agents"))  # noqa: B010 - route is a dynamically loaded module; pyright rejects direct attribute assignment on ModuleType
setattr(route, "STATE_DIR", os.path.join(TMP, "route-check"))  # noqa: B010 - see above
os.makedirs(route.AGENTS_DIR)
with open(os.path.join(route.AGENTS_DIR, "scout.md"), "w", encoding="utf-8") as fh:
    fh.write("---\nname: scout\ndescription: x\nmodel: haiku\neffort: low\n---\nbody\n")


class FakeJev:
    """Stands in for jev_client.nouls: `p` is one probability for every question, a {qid: p} dict, or None."""

    def __init__(self, p):
        self.p, self.calls = p, []

    def __call__(self, state, questions):
        self.calls.append((state, questions))
        if self.p is None:
            return None
        if isinstance(self.p, dict):
            return dict(self.p)
        return dict.fromkeys(questions, self.p)


WORKFLOW = """const files = ['a.png', 'b.png']
const render = (f) => `List every texture referenced by ${f}`
const listed = await parallel(files.map(f => () => agent(render(f), { model: 'opus', effort: 'high', label: 'inventory' })))
const merged = await agent(`Merge ${JSON.stringify(listed)} into one table`, { model: 'sonnet', effort: 'medium', label: 'merge' })
"""


class RouteCheck(unittest.TestCase):
    def setUp(self):
        self.real = jev_client.nouls

    def tearDown(self):
        jev_client.nouls = self.real

    def fake(self, p):
        jev_client.nouls = FakeJev(p)
        return jev_client.nouls

    def last_log(self):
        with open(jev_client.LOG, encoding="utf-8") as fh:
            return json.loads(fh.read().splitlines()[-1])

    def agent(self, session, **inp):
        payload = {"tool_name": "Agent", "session_id": session, "tool_input": inp, "effort": {"level": "xhigh"}}
        return route.main(payload)

    def test_agent_flagged_then_relaunch_passes(self):
        self.assertEqual(route.TIER, "prompt")
        fake = self.fake(0.9)
        inp = {"subagent_type": "general-purpose", "model": "opus", "description": "list assets", "prompt": "List x."}
        out = self.agent("s-flag", **inp)
        reason = json.loads(out)["hookSpecificOutput"]["permissionDecisionReason"]
        self.assertIn("`list assets` (opus/inherited:xhigh) 0.90", reason)
        self.assertIn("relaunch unchanged", reason)
        self.assertEqual(self.last_log()["decision"], "flag")
        self.assertIsNone(self.agent("s-flag", **inp))
        self.assertEqual(len(fake.calls), 1)
        self.assertEqual(self.last_log()["decision"], "relaunch")
        self.assertIsNotNone(self.agent("s-other", **inp))

    def test_workflow_flags_only_the_overprovisioned_agent(self):
        fake = self.fake({"agent_1": 0.85, "agent_2": 0.2})
        out = route.main({"tool_name": "Workflow", "session_id": "s-wf", "tool_input": {"script": WORKFLOW}})
        reason = json.loads(out)["hookSpecificOutput"]["permissionDecisionReason"]
        self.assertIn("`inventory` (opus/high) 0.85", reason)
        self.assertNotIn("merge", reason)
        state, questions = fake.calls[0]
        self.assertEqual(set(questions), {"agent_1", "agent_2"})
        self.assertEqual(state["routing_table"], route.ROUTING_TABLE)
        self.assertIn("List every texture", state["agent_1"]["task"])
        self.assertIn("const files", state["agent_1"]["task"])
        self.assertEqual((state["agent_2"]["model"], state["agent_2"]["effort"]), ("sonnet", "medium"))
        log = self.last_log()
        self.assertEqual(
            (log["hook"], log["decision"], log["ps"]), ("route-check", "flag", {"agent_1": 0.85, "agent_2": 0.2})
        )

    def test_nothing_flagged_passes(self):
        self.fake(0.3)
        self.assertIsNone(
            route.main({"tool_name": "Workflow", "session_id": "s-ok", "tool_input": {"script": WORKFLOW}})
        )
        self.assertEqual(self.last_log()["decision"], "pass")

    def test_jev_error_fails_open(self):
        self.fake(None)
        self.assertIsNone(self.agent("s-err", model="opus", prompt="x"))
        self.assertEqual(self.last_log()["decision"], "error")

    def test_pinned_definition_supplies_model_and_effort(self):
        fake = self.fake(0.1)
        self.assertIsNone(self.agent("s-pin", subagent_type="scout", prompt="Find x."))
        entry = fake.calls[0][0]["agent_1"]
        self.assertEqual((entry["model"], entry["effort"]), ("haiku", "low"))

    def test_question_and_criteria_carry_no_examples(self):
        texts = [route.QUESTION, *route.CRITERIA.values()]
        texts += [v for group in route.ROUTING_TABLE.values() for v in group.values()]
        for text in texts:
            self.assertIsNone(
                re.search(r"e\.g\.|for example|for instance|such as|\blike\b|\"", text, re.IGNORECASE), text
            )


def transcript(name, *models):
    """A transcript whose main-chain replies ran on `models`, oldest first, followed by a subagent's Opus record."""
    path = os.path.join(TMP, name + ".jsonl")
    rows = [{"type": "assistant", "message": {"model": m, "content": []}} for m in models]
    rows.append({"type": "assistant", "isSidechain": True, "message": {"model": "claude-opus-5-5"}})
    rows.append({"type": "user", "message": {"content": 'a tool result quoting "assistant" text'}})
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(json.dumps(r) for r in rows) + "\n")
    return path


class FableMain(unittest.TestCase):
    """A Fable agent under a Fable main is stopped once without asking Jev; under another main the launch is judged."""

    def setUp(self):
        self.real = jev_client.nouls
        jev_client.nouls = self.jev = FakeJev(0.1)

    def tearDown(self):
        jev_client.nouls = self.real

    def launch(self, session, path, tool="Agent", **inp):
        return route.main({"tool_name": tool, "session_id": session, "transcript_path": path, "tool_input": inp})

    def test_main_model_is_the_newest_main_chain_reply(self):
        self.assertEqual(route.main_model.tier({"transcript_path": transcript("t-f", "claude-fable-5-2")}), "fable")
        switched = transcript("t-o", "claude-fable-5-2", "claude-opus-5-5", "<synthetic>")
        self.assertEqual(route.main_model.tier({"transcript_path": switched}), "opus")
        self.assertEqual(route.main_model.tier({"transcript_path": os.path.join(TMP, "absent.jsonl")}), "")
        self.assertEqual(route.main_model.tier({}), "")

    def test_fable_agent_under_fable_main_stops_once_then_passes(self):
        path = transcript("t-main-fable", "claude-opus-5-5", "claude-fable-5-2")
        inp = {"subagent_type": "auditor", "model": "fable", "description": "audit the diff", "prompt": "Audit."}
        reason = json.loads(self.launch("s-ff", path, **inp))["hookSpecificOutput"]["permissionDecisionReason"]
        self.assertIn("`audit the diff` would run on Fable too", reason)
        self.assertIn("auditor-opus", reason)
        self.assertEqual(self.jev.calls, [])
        self.assertIsNone(self.launch("s-ff", path, **inp))
        self.assertEqual(self.jev.calls, [])

    def test_fable_agent_under_another_main_is_judged_as_before(self):
        path = transcript("t-main-opus", "claude-fable-5-2", "claude-opus-5-5")
        self.assertIsNone(self.launch("s-of", path, subagent_type="auditor", model="fable", prompt="Audit."))
        self.assertEqual(len(self.jev.calls), 1)

    def test_other_tiers_under_fable_main_are_judged_as_before(self):
        path = transcript("t-main-fable2", "claude-fable-5-2")
        self.assertIsNone(self.launch("s-fo", path, model="opus", prompt="Audit."))
        self.assertEqual(len(self.jev.calls), 1)

    def test_workflow_with_a_fable_agent_or_table_row_stops(self):
        path = transcript("t-main-fable3", "claude-fable-5-2")
        inline = "const v = await agent(`Audit the diff`, { model: 'fable', effort: 'high', label: 'audit' })\n"
        reason = json.loads(self.launch("s-wf1", path, tool="Workflow", script=inline))
        self.assertIn("`audit` would run on Fable too", reason["hookSpecificOutput"]["permissionDecisionReason"])
        table = (
            "const STEPS = [{ key: 'audit', model: 'fable', effort: 'high' }]\n"
            "await parallel(STEPS.map(d => () => agent(d.key, { model: d.model, effort: d.effort })))\n"
        )
        reason = json.loads(self.launch("s-wf2", path, tool="Workflow", script=table))
        self.assertIn("reading `model: 'fable'`", reason["hookSpecificOutput"]["permissionDecisionReason"])
        self.assertIsNone(self.launch("s-wf3", path, tool="Workflow", script=WORKFLOW))
        self.assertEqual(len(self.jev.calls), 1)


if __name__ == "__main__":
    unittest.main()
