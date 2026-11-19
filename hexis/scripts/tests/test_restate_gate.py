"""Offline tests for hooks/restate-gate.py: the Noul goes through a fake, nothing touches the network."""

from __future__ import annotations

import json
import os
import unittest

import jev_client
from test_jev_hooks import TMP, Base, load

restate = load("restate-gate")
setattr(restate, "STATE_DIR", os.path.join(TMP, "restate-gate"))  # noqa: B010 - a dynamically loaded module; pyright rejects direct attribute assignment on ModuleType


def log_size():
    return os.path.getsize(jev_client.LOG) if os.path.exists(jev_client.LOG) else 0


def transcript(*records):
    path = os.path.join(TMP, f"r{len(os.listdir(TMP))}.jsonl")
    with open(path, "w", encoding="utf-8") as fh:
        fh.writelines(
            json.dumps({"type": role, "message": {"role": role, "content": content}}) + "\n"
            for role, content in records
        )
    return path


def ran(uid, name, inp):
    return [
        ("assistant", [{"type": "tool_use", "id": uid, "name": name, "input": inp}]),
        ("user", [{"type": "tool_result", "tool_use_id": uid, "content": "ok"}]),
    ]


SHORT = transcript(("user", "これ直して"))
LONG = transcript(
    ("user", "hooks/relay-check.py の THRESHOLD を 0.59 から 0.6 に上げて、テストの pin も合わせて直しておいてください")
)
TEXT = transcript(
    ("user", "これ直して"),
    ("assistant", [{"type": "text", "text": "Reading this as: fix X in hooks/a.py, nothing else."}]),
)
ACTED = transcript(("user", "これ直して"), *ran("t1", "Edit", {"file_path": "a.py"}))
EDIT = {"file_path": "a.py", "old_string": "x", "new_string": "y"}


class RestateGate(Base):
    def call(self, session, path=SHORT, tool="Edit", inp=None, **extra):
        payload = {"session_id": session, "transcript_path": path, "tool_name": tool, "tool_input": inp or EDIT}
        return restate.main(dict(payload, **extra))

    def test_tier_is_prompt(self):
        self.assertEqual(restate.TIER, "prompt")

    def test_short_prompt_first_write_is_stopped_once(self):
        fake = self.fake(0.9)
        out = json.loads(self.call("r-short"))
        self.assertIn("send the same call again", out["hookSpecificOutput"]["permissionDecisionReason"])
        self.assertEqual(self.last_log()["decision"], "prompt")
        self.assertEqual(self.last_log()["chars"], len("これ直して"))
        self.assertEqual(fake.calls, [])
        self.assertIsNone(self.call("r-short"))
        self.assertEqual(self.last_log()["decision"], "resend")

    def test_long_prompt_with_a_named_target_passes(self):
        fake = self.fake(0.0)
        self.assertIsNone(self.call("r-long", path=LONG))
        self.assertEqual(self.last_log()["decision"], "named")
        self.assertEqual(fake.calls, [])

    def test_long_pronoun_only_prompt_is_stopped(self):
        path = transcript(
            (
                "user",
                "できたわ画面崩れてる原因これな。あとタスクバー消すのがタイミングによってなのか知らんけど領域自体占領したり一瞬復活してきたりするからそっちも全部消してくれよ",
            )
        )
        self.fake(0.0)
        self.assertIsNotNone(self.call("r-pron", path=path))
        self.assertEqual(self.last_log()["flags"], ["pronoun"])

    def test_turn_that_already_restated_is_still_stopped_once(self):
        # A restating line followed by the act is not a confirmation: the first act is stopped
        # whatever the reply said, without asking Jev; the same call resent passes.
        fake = self.fake(0.9)
        out = json.loads(self.call("r-said", path=TEXT))
        self.assertIn("do not decide it", out["hookSpecificOutput"]["permissionDecisionReason"])
        self.assertEqual(self.last_log()["decision"], "prompt")
        self.assertEqual(fake.calls, [])
        self.assertIsNone(self.call("r-said", path=TEXT))
        self.assertEqual(self.last_log()["decision"], "resend")

    def test_filler_text_is_stopped(self):
        self.fake(0.1)
        self.assertIsNotNone(self.call("r-filler", path=TEXT))

    def test_second_outward_act_passes(self):
        self.fake(0.0)
        self.assertIsNone(self.call("r-second", path=ACTED))
        self.assertEqual(self.last_log()["decision"], "not-first")

    def test_subagent_is_exempt(self):
        self.fake(0.0)
        size = log_size()
        self.assertIsNone(self.call("r-agent", agent_id="a0123456789abcdef"))
        self.assertEqual(log_size(), size)  # exempt calls are not logged

    def test_read_only_bash_is_exempt_and_a_shell_write_is_not(self):
        self.fake(0.0)
        size = log_size()
        self.assertIsNone(self.call("r-bash", tool="Bash", inp={"command": "git status && grep -n x a.py"}))
        self.assertEqual(log_size(), size)  # a read-only call is not logged
        self.assertIsNotNone(self.call("r-bash", tool="Bash", inp={"command": "echo x >> a.py"}))
        self.assertIsNotNone(self.call("r-bash2", tool="Bash", inp={"command": "git add a.py && git commit -m x"}))

    def test_agent_notice_turn_is_judged_only_for_own_choices(self):
        # A notice opens no user request, so the short-prompt stop never applies; Jev reads it for an
        # agent's own decision instead, and a clean report passes.
        self.fake(0.0)
        path = transcript(("user", "<task-notification>done</task-notification>"))
        self.assertIsNone(self.call("r-notice", path=path))
        self.assertEqual(self.last_log()["decision"], "own-choice-clear")

    def test_jev_down_changes_nothing(self):
        # The gate no longer asks Jev, so a Jev outage neither allows nor errors: the first act is stopped
        # once as usual.
        fake = self.fake(None)
        self.assertIsNotNone(self.call("r-down", path=TEXT))
        self.assertEqual(self.last_log()["decision"], "prompt")
        self.assertEqual(fake.calls, [])

    def test_unclear_instruction_stops_an_irreversible_act_without_resend(self):
        # A short instruction Jev read at low referent
        # clarity still gets no resend escape for an act that cannot be taken back.
        fake = self.fake(0.0)
        jev_client.save_reading("r-unclear", {"kind": "instruction", "kind_conf": 0.9, "clear": 0.13, "line": "x"})
        rm = {"command": "rm -rf build"}
        out = json.loads(self.call("r-unclear", tool="Bash", inp=rm))
        self.assertIn("cannot be taken back", out["hookSpecificOutput"]["permissionDecisionReason"])
        self.assertIn("plain text", out["hookSpecificOutput"]["permissionDecisionReason"])
        self.assertEqual(self.last_log()["decision"], "ask")
        self.assertIn("unclear", self.last_log()["flags"])
        self.assertIsNotNone(self.call("r-unclear", tool="Bash", inp=rm))
        self.assertEqual(self.last_log()["decision"], "ask")
        self.assertEqual(fake.calls, [])

    def test_unclear_instruction_keeps_the_resend_for_a_reversible_act(self):
        # A reversible edit is stopped once, as any short prompt's first act, and the resend passes.
        self.fake(0.0)
        jev_client.save_reading("r-corr", {"kind": "correction", "kind_conf": 0.9, "clear": 0.12, "line": "x"})
        out = json.loads(self.call("r-corr"))
        self.assertIn("do not decide it", out["hookSpecificOutput"]["permissionDecisionReason"])
        self.assertIsNone(self.call("r-corr"))
        self.assertEqual(self.last_log()["decision"], "resend")

    def test_unclear_approval_keeps_the_resend(self):
        # An approval with a vague referent (his go for a task the reply had just proposed) is stopped once as before.
        self.fake(0.0)
        jev_client.save_reading("r-ok", {"kind": "approval", "kind_conf": 0.8, "clear": 0.31, "line": "x"})
        self.assertIsNotNone(self.call("r-ok"))
        self.assertIsNone(self.call("r-ok"))
        self.assertEqual(self.last_log()["decision"], "resend")

    def test_clear_instruction_keeps_the_resend(self):
        self.fake(0.0)
        jev_client.save_reading("r-clear", {"kind": "instruction", "kind_conf": 0.9, "clear": 0.75, "line": "x"})
        self.assertIsNotNone(self.call("r-clear"))
        self.assertIsNone(self.call("r-clear"))

    def test_reading_without_clarity_keeps_the_resend(self):
        # misread-check down (kind None) or a reading from before `clear` was saved: the old once-only stop.
        self.fake(0.0)
        jev_client.save_reading("r-noclear", {"kind": None, "error": True})
        self.assertIsNotNone(self.call("r-noclear"))
        self.assertIsNone(self.call("r-noclear"))

    def test_agent_result_with_an_own_choice_stops_the_turn_once(self):
        # An agent's own removal is put to him before anything moves.
        fake = self.fake(0.9)
        path = transcript(
            (
                "user",
                "<task-notification>Rebuilt. Changes you should know about: removed Alt+Left drag.</task-notification>",
            )
        )
        out = json.loads(self.call("r-own", path=path))
        reason = out["hookSpecificOutput"]["permissionDecisionReason"]
        self.assertIn("deciding on its own", reason)
        self.assertIn("keep or revert", reason)
        self.assertIn("never an AskUserQuestion list", reason)
        self.assertEqual(self.last_log()["decision"], "own-choice")
        # Stopped once per turn; the resend after settling and naming each item passes.
        self.assertIsNone(self.call("r-own", path=path, tool="SendMessage", inp={"to": "x", "message": "done"}))
        self.assertEqual(self.last_log()["decision"], "own-choice-resend")
        self.assertIsNone(self.call("r-own", path=path))
        self.assertEqual(len(fake.calls), 1)  # Jev is asked once per turn

    def test_own_choice_answered_through_askuserquestion_reopens_the_turn(self):
        # The items were put with AskUserQuestion and answered in the same turn.
        fake = self.fake(0.9)
        path = transcript(
            ("user", "<task-notification>Removed Alt+Left drag.</task-notification>"),
            *ran("q1", "AskUserQuestion", {"questions": []}),
        )
        self.assertIsNone(self.call("r-asked", path=path))
        self.assertEqual(self.last_log()["decision"], "own-choice-answered")
        self.assertEqual(fake.calls, [])

    def test_agent_result_without_an_own_choice_passes(self):
        self.fake(0.1)
        path = transcript(
            ("user", "<task-notification>Done as briefed; open point listed, not built.</task-notification>")
        )
        self.assertIsNone(self.call("r-clean", path=path))
        self.assertEqual(self.last_log()["decision"], "own-choice-clear")

    def test_agent_result_with_jev_down_passes(self):
        self.fake(None)
        path = transcript(("user", "<task-notification>Rebuilt.</task-notification>"))
        self.assertIsNone(self.call("r-own-down", path=path))
        self.assertEqual(self.last_log()["decision"], "own-choice-error")


if __name__ == "__main__":
    unittest.main()
