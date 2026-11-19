"""Offline tests for hooks/agent-cap.py: ceilings on agent starts per session and prompt, in total and per model."""

import contextlib
import importlib.util
import io
import json
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path

HOOKS = Path(__file__).resolve().parents[2] / "hooks"
sys.path.insert(0, str(HOOKS))
import _common


def load():
    run, _common.run = _common.run, lambda _name, _fn: None
    stdin, sys.stdin = sys.stdin, io.TextIOWrapper(io.BytesIO())
    try:
        spec = importlib.util.spec_from_file_location("agent_cap", HOOKS / "agent-cap.py")
        assert spec and spec.loader
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    finally:
        _common.run, sys.stdin = run, stdin


cap = load()


class AgentCap(unittest.TestCase):
    def setUp(self):
        self.real = (cap.STATE, cap.META_WAIT)
        setattr(cap, "STATE", tempfile.mkdtemp())  # noqa: B010 - pyright rejects assigning to a loaded module
        setattr(cap, "META_WAIT", 0.0)  # noqa: B010 - as above
        self.root = tempfile.mkdtemp()
        self.n = 0
        self.last_error = ""

    def tearDown(self):
        setattr(cap, "STATE", self.real[0])  # noqa: B010 - as above
        setattr(cap, "META_WAIT", self.real[1])  # noqa: B010 - as above

    def payload(self, session="s1", prompt="p1", model=None):
        self.n += 1
        agent = f"a{self.n}"
        if model:  # the runtime writes <session>/subagents/workflows/wf_x/agent-<id>.meta.json when it starts an agent
            meta_dir = os.path.join(self.root, "sess", "subagents", "workflows", "wf_x")
            os.makedirs(meta_dir, exist_ok=True)
            with open(os.path.join(meta_dir, f"agent-{agent}.meta.json"), "w", encoding="utf-8") as fh:
                json.dump({"agentType": "workflow-subagent", "model": model}, fh)
        return {
            "session_id": session,
            "prompt_id": prompt,
            "agent_id": agent,
            "agent_type": "workflow-subagent",
            "transcript_path": os.path.join(self.root, "sess.jsonl"),
        }

    def start(self, **kw):
        err = io.StringIO()
        try:
            with contextlib.redirect_stderr(err):
                cap.main(self.payload(**kw))
            return "allowed"
        except SystemExit as e:
            self.last_error = err.getvalue()
            return f"exit {e.code}"

    def test_the_total_cap_holds_per_prompt(self):
        results = [self.start() for _ in range(cap.CAP + 2)]
        self.assertEqual(results[: cap.CAP], ["allowed"] * cap.CAP)
        self.assertEqual(results[cap.CAP :], ["exit 2", "exit 2"])
        self.assertIn("Agent cap", self.last_error)

    def test_a_new_prompt_and_another_session_reset_the_count(self):
        for _ in range(cap.CAP):
            self.start()
        self.assertEqual(self.start(prompt="p2"), "allowed")
        self.assertEqual(self.start(session="s2"), "allowed")

    def test_per_model_caps(self):
        opus = cap.MODEL_CAPS["opus"]
        self.assertEqual([self.start(model="opus") for _ in range(opus + 1)], ["allowed"] * opus + ["exit 2"])
        self.assertIn(f"{opus} opus agents", self.last_error)
        self.assertEqual(self.start(model="sonnet"), "allowed")  # another tier still has room
        fable = cap.MODEL_CAPS["fable"]
        self.assertEqual([self.start(model="fable") for _ in range(fable + 1)], ["allowed"] * fable + ["exit 2"])

    def test_parallel_starts_are_all_counted(self):
        payloads = [self.payload(model="haiku") for _ in range(6)]
        threads = [threading.Thread(target=cap.main, args=(p,)) for p in payloads]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(len(os.listdir(os.path.join(cap.STATE, "s1", "p1"))), 6)

    def test_no_session_allows(self):
        for _ in range(cap.CAP + 1):
            self.assertIsNone(cap.main({"prompt_id": "p"}))


if __name__ == "__main__":
    unittest.main()
