"""Offline tests for the Jev hooks (ERG-22): the Noul goes through a fake, nothing touches the network."""

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

# Hermetic: the live settings.json enables jev-band, which changes what the hooks inject.
SETTINGS_REAL = os.path.join(tempfile.mkdtemp(), "settings-no-band.json")
with open(SETTINGS_REAL, "w", encoding="utf-8") as _fh:
    _fh.write("{}")
_common.SETTINGS = SETTINGS_REAL
SESSION_SURFACES_REAL = _common.session_surfaces
BAND_SURFACES_DIR_REAL = _common.BAND_SURFACES_DIR

TMP = tempfile.mkdtemp()
jev_client.LOG = os.path.join(TMP, "logs", "jev-hooks.jsonl")
jev_client.READINGS = os.path.join(TMP, "readings")
jev_client.MODEL_FILE = os.path.join(TMP, "jev-model.txt")
_common.SKILLS = os.path.join(TMP, "no-skills")
_common.SKILL_STATE = os.path.join(TMP, "skill-push")


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


misread = load("misread-check")
relay = load("relay-check")
setattr(relay, "STATE_DIR", os.path.join(TMP, "relay-check"))  # noqa: B010 - see below
hold = load("hold-gate")
setattr(hold, "STATE_DIR", os.path.join(TMP, "hold-gate"))  # noqa: B010 - see below
output = load("output-check")
setattr(output, "STOPS", os.path.join(TMP, "stops"))  # noqa: B010 - output is a dynamically loaded module; pyright rejects direct attribute assignment on ModuleType
commit = load("commit-gate")
brief = load("brief-check")
setattr(brief, "RECORDS", os.path.join(TMP, "briefs"))  # noqa: B010 - see above
setattr(brief, "ONCE_DIR", os.path.join(TMP, "brief-check"))  # noqa: B010 - see above
md = load("md-check")
setattr(md, "RECORDS", os.path.join(TMP, "md-checks"))  # noqa: B010 - see above


def transcript(*records):
    path = os.path.join(TMP, f"t{len(os.listdir(TMP))}.jsonl")
    with open(path, "w", encoding="utf-8") as fh:
        fh.writelines(
            json.dumps({"type": role, "message": {"role": role, "content": content}}) + "\n"
            for role, content in records
        )
    return path


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
        return {qid: (["instruction", 0.9] if spec[0] == "choice" else self.p) for qid, spec in questions.items()}


class Base(unittest.TestCase):
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

    def logs(self, n):
        with open(jev_client.LOG, encoding="utf-8") as fh:
            return [json.loads(l) for l in fh.read().splitlines()[-n:]]


TWO_FILES = transcript(
    ("user", "x1"),
    ("assistant", [{"type": "text", "text": "x2 old.log new.log"}]),
    ("user", [{"type": "tool_result", "content": "x"}]),
)


class MisreadCheck(Base):
    def test_ambiguous_injects(self):
        fake = self.fake(0.05)
        out = misread.main({"prompt": "x3", "transcript_path": TWO_FILES})
        ctx = json.loads(out)["hookSpecificOutput"]
        self.assertEqual(ctx["hookEventName"], "UserPromptSubmit")
        self.assertIn("ambiguous", ctx["additionalContext"])
        self.assertIn("p=0.05", ctx["additionalContext"])
        state = fake.calls[0][0]
        self.assertEqual(state["new_user_message"], "x3")
        self.assertEqual(state["previous_user_message"], "x1")
        self.assertIn("old.log", state["last_assistant_message"])
        log = self.last_log()
        self.assertEqual(log["decision"], "inject")
        self.assertNotIn("text", log)
        self.assertEqual(log["chars"], len("x3"))
        self.assertEqual(set(log["ps"]), {"clear", "holds", "kind", "referent"})

    def test_threshold_is_on_the_clear_arm_only(self):
        self.fake({"clear": 0.5, "instruction": 0.01, "kind": ["report", 0.9], "referent": ["new_topic", 0.9]})
        text = json.loads(misread.main({"prompt": "x4 old.log", "transcript_path": TWO_FILES}))
        self.assertNotIn("ambiguous", text["hookSpecificOutput"]["additionalContext"])

    def test_peer_message_always_gets_a_restatement(self):
        self.fake(0.95)
        out = misread.main(
            {
                "prompt": '<cross-session-message from="x">do A then B</cross-session-message>',
                "transcript_path": TWO_FILES,
                "session_id": "m-peer",
            }
        )
        ctx = json.loads(out)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("Peer message", ctx)
        self.assertEqual(self.last_log()["source"], "peer")
        self.assertNotIn("Open your reply", ctx)  # a peer turn has no reading line
        self.assertEqual(jev_client.recent_readings("m-peer", 1), [])

    def test_notification_skipped(self):
        fake = self.fake(0.01)
        self.assertIsNone(misread.main({"prompt": "<task-notification>x</task-notification>"}))
        self.assertEqual(fake.calls, [])

    def test_clear_prompt_gets_the_reading_only(self):
        self.fake(0.9)
        ctx = json.loads(misread.main({"prompt": "x4 old.log", "transcript_path": TWO_FILES}))
        text = ctx["hookSpecificOutput"]["additionalContext"]
        self.assertIn(f"Jev {jev_client.version()} reading: kind=instruction", text)
        self.assertNotIn("ambiguous", text)
        self.assertNotIn("systemMessage", ctx)  # nothing is shown to the user

    def test_weak_reading_gets_no_hint(self):
        self.fake({"clear": 0.9, "kind": ["correction", 0.54], "referent": ["last_reply", 0.9]})
        text = json.loads(misread.main({"prompt": "x", "transcript_path": TWO_FILES}))["hookSpecificOutput"]
        self.assertNotIn("change what it corrects", text["additionalContext"])

    def test_hold_and_correction_get_their_hint(self):
        for kind, word in (("hold", "wait"), ("correction", "change what it corrects")):
            self.fake({"clear": 0.9, "instruction": 0.9, "kind": [kind, 0.95], "referent": ["last_reply", 0.9]})
            text = json.loads(misread.main({"prompt": "x", "transcript_path": TWO_FILES}))["hookSpecificOutput"]
            self.assertIn(word, text["additionalContext"])

    def test_prompt_already_in_transcript_is_not_its_own_previous(self):
        fake = self.fake(0.9)
        path = transcript(("user", "first"), ("assistant", [{"type": "text", "text": "ok"}]), ("user", "second"))
        misread.main({"prompt": "second", "transcript_path": path})
        self.assertEqual(fake.calls[0][0]["previous_user_message"], "first")

    def test_jev_error_fails_open(self):
        self.fake(None)
        self.assertIsNone(misread.main({"prompt": "x3", "transcript_path": TWO_FILES}))
        self.assertEqual(self.last_log()["decision"], "error")


def skill_file(root, name, description, body):
    os.makedirs(os.path.join(root, name), exist_ok=True)
    with open(os.path.join(root, name, "SKILL.md"), "w", encoding="utf-8") as fh:
        fh.write(f"---\nname: {name}\ndescription: {description}\n---\n\n{body}\n")


class SkillRoute(Base):
    """Tier 2 of the skill push: the `skill` Choice in misread-check's call."""

    def setUp(self):
        super().setUp()
        self.dirs = (_common.SKILLS, _common.SKILL_STATE)
        root = tempfile.mkdtemp(dir=TMP)
        _common.SKILLS, _common.SKILL_STATE = os.path.join(root, "home"), os.path.join(root, "state")
        self.cwd = os.path.join(root, "project")
        skill_file(_common.SKILLS, "hexis-commit", "Use before any git commit. " + "x" * 300, "COMMIT BODY")
        skill_file(_common.SKILLS, "hexis-shell", "Use before a heredoc.", "SHELL BODY")
        skill_file(os.path.join(_common.SKILLS, "synced"), "hidden", "Never listed.", "HIDDEN")
        skill_file(os.path.join(self.cwd, ".claude", "skills"), "proj", "A project skill.", "PROJ BODY")
        skill_file(os.path.join(self.cwd, ".agents", "skills"), "agentskill", "An .agents skill.", "AGENT BODY")

    def tearDown(self):
        super().tearDown()
        _common.SKILLS, _common.SKILL_STATE = self.dirs

    def route(self, pick, session, prompt="commit it"):
        fake = self.fake(
            {"clear": 0.9, "holds": 0.0, "kind": ["instruction", 0.9], "referent": ["new_topic", 0.9], "skill": pick}
        )
        out = json.loads(
            misread.main({"prompt": prompt, "transcript_path": TWO_FILES, "cwd": self.cwd, "session_id": session})
        )
        return fake, out["hookSpecificOutput"]["additionalContext"], out.get("systemMessage")

    def test_options_come_from_every_catalogue_but_synced(self):
        fake, _, _ = self.route(["none", 0.9], "r-opts")
        name, instructions, options = fake.calls[0][1]["skill"]
        self.assertEqual(name, "choice")
        self.assertIn("`new_user_message`", instructions)
        self.assertEqual(set(options), {"hexis-commit", "hexis-shell", "proj", "agentskill", "none"})
        self.assertEqual(len(options["hexis-commit"]), misread.SKILL_DESC)
        self.assertEqual(options["none"], "No listed skill applies.")

    def test_confident_pick_pushes_the_body_once(self):
        _, ctx, shown = self.route(["hexis-commit", 0.8], "r-push")
        self.assertIn("Skill hexis-commit (Jev 0.80) applies to this message - follow it:\nCOMMIT BODY", ctx)
        self.assertNotIn("name:", ctx)
        self.assertIsNone(shown)  # nothing is shown to the user
        self.assertEqual(_common.pushed_skills("r-push"), {"main": ["hexis-commit"]})
        log = self.last_log()
        self.assertEqual((log["hook"], log["decision"], log["p"]), ("skill-route", "push", 0.8))
        _, ctx, _ = self.route(["hexis-commit", 0.8], "r-push")
        self.assertIn("Skill hexis-commit is already in context.", ctx)
        self.assertNotIn("COMMIT BODY", ctx)
        self.assertEqual(self.last_log()["decision"], "already")

    def test_project_skill_is_pushed_from_its_own_directory(self):
        _, ctx, _ = self.route(["agentskill", 0.9], "r-proj")
        self.assertIn("AGENT BODY", ctx)

    def test_weak_pick_is_a_suggestion(self):
        _, ctx, _ = self.route(["hexis-shell", 0.4], "r-weak")
        self.assertIn("Jev suggests skill hexis-shell (0.40); load it if it applies.", ctx)
        self.assertNotIn("SHELL BODY", ctx)
        self.assertEqual(_common.pushed_skills("r-weak"), {})
        self.assertEqual(self.last_log()["decision"], "suggest")

    def test_none_adds_nothing(self):
        _, ctx, _ = self.route(["none", 0.95], "r-none")
        self.assertNotIn("Skill ", ctx)
        self.assertNotIn("suggests", ctx)
        lines = ctx.split("\n")  # the reading line, then the reading; no skill block appended
        self.assertEqual(len(lines), 2)
        self.assertTrue(lines[1].startswith(f"Jev {jev_client.version()} reading:"))
        self.assertEqual(self.last_log()["decision"], "none")

    def test_context_opens_with_the_reading_line_and_saves_it(self):
        self.fake(
            {
                "clear": 0.3,
                "holds": 0.0,
                "kind": ["question", 0.76],
                "referent": ["last_reply", 0.59],
                "skill": ["hexis-shell", 0.52],
            }
        )
        out = json.loads(
            misread.main({"prompt": "x", "transcript_path": TWO_FILES, "cwd": self.cwd, "session_id": "r-line"})
        )
        line = f"Jev {jev_client.version()} · question 0.76 · last_reply 0.59 · clear 0.30 · hexis-shell 0.52"
        ctx = out["hookSpecificOutput"]["additionalContext"]
        self.assertTrue(ctx.startswith(f"Open your reply with this line, verbatim: {line}\n"))
        self.assertNotIn("systemMessage", out)
        self.assertEqual(jev_client.recent_readings("r-line", 1)[0]["line"], line)

    def test_context_stays_under_the_cap(self):
        skill_file(_common.SKILLS, "big", "A large skill.", "B" * 20_000)
        _, ctx, _ = self.route(["big", 0.9], "r-big")
        self.assertLessEqual(len(ctx), misread.CONTEXT_CAP)
        self.assertEqual(ctx.count("B"), _common.SKILL_CHARS)
        catalogue = misread.skill_catalogue(self.cwd)
        decision, text = misread.skill_route(["big", 0.9], catalogue, "r-room", 500)
        self.assertEqual(decision, "push")
        self.assertLessEqual(len(text), 500)
        decision, text = misread.skill_route(["hexis-shell", 0.9], catalogue, "r-room", 20)
        self.assertEqual(decision, "suggest")
        self.assertNotIn("hexis-shell", _common.pushed_skills("r-room").get("main", []))


USER_HOLD = transcript(
    ("user", "x5 Plane"),
    ("assistant", [{"type": "text", "text": "x6"}]),
)


class RelayCheck(Base):
    def send(self, message, to="peer-a", path=USER_HOLD):
        return relay.main(
            {
                "tool_name": "SendMessage",
                "session_id": self.id(),
                "transcript_path": path,
                "tool_input": {"to": to, "summary": "tracker", "message": message},
            }
        )

    def test_tier_is_prompt(self):
        self.assertEqual(relay.TIER, "prompt")

    def test_speaking_for_the_user_prompts_once_as_a_confirm(self):
        fake = self.fake({"claims_user": 0.8, "hold_to_go": 0.1})
        out = json.loads(self.send("The owner decided: new Product work goes to Linear project Product."))
        hook = out["hookSpecificOutput"]
        self.assertEqual(hook["permissionDecision"], "deny")
        reason = hook["permissionDecisionReason"]
        self.assertIn("speaks for the user", reason)
        self.assertIn("resend it unchanged", reason)
        self.assertIn("own words", reason)
        self.assertNotIn("quote", reason)
        self.assertEqual(set(fake.calls[0][1]), {"claims_user"})
        self.assertEqual(fake.calls[0][0]["user_recent_messages"], ["x5 Plane"])
        self.assertEqual(self.last_log()["decision"], "prompt")
        self.assertEqual(self.last_log()["source"], "peer-a")

    def test_identical_resend_passes(self):
        self.fake({"claims_user": 0.8, "hold_to_go": 0.1})
        message = "The owner decided: new Product work goes to Linear project Product."
        self.assertIsNotNone(self.send(message))
        self.assertIsNone(self.send(message))
        self.assertEqual(self.last_log()["decision"], "resend")

    def test_reworded_resend_to_the_same_recipient_in_the_same_turn_is_not_judged_again(self):
        fake = self.fake({"claims_user": 0.8, "hold_to_go": 0.1})
        self.assertIsNotNone(self.send("The owner decided: new work goes to Linear."))
        self.assertIsNone(self.send("My reading of the user's decision: new work goes to Linear."))
        self.assertEqual(len(fake.calls), 1)
        self.assertEqual(self.last_log()["decision"], "resend")

    def test_another_recipient_or_a_new_user_turn_is_judged_again(self):
        fake = self.fake({"claims_user": 0.8, "hold_to_go": 0.1})
        self.assertIsNotNone(self.send("The owner decided: new work goes to Linear."))
        self.assertIsNotNone(self.send("The owner decided: new work goes to Linear.", to="peer"))
        later = transcript(("user", "x5 Plane"), ("assistant", [{"type": "text", "text": "x6"}]), ("user", "x7 next"))
        self.assertIsNotNone(self.send("The owner decided: new work goes to Linear.", path=later))
        self.assertEqual(len(fake.calls), 3)

    def test_failed_state_write_lets_the_message_through(self):
        self.fake({"claims_user": 0.8, "hold_to_go": 0.1})
        blocker = os.path.join(TMP, "relay-blocker")
        Path(blocker).write_text("", encoding="utf-8")
        state_dir = relay.STATE_DIR
        setattr(relay, "STATE_DIR", os.path.join(blocker, "sub"))  # noqa: B010 - pyright rejects assigning to a loaded module
        try:
            self.assertIsNone(self.send("The owner decided: new work goes to Linear."))
        finally:
            setattr(relay, "STATE_DIR", state_dir)  # noqa: B010 - as above
        self.assertEqual(self.last_log()["decision"], "would-prompt")

    def test_retired_questions_are_not_asked(self):
        fake = self.fake({"claims_user": 0.1})
        self.assertIsNone(self.send("Go ahead and file it now."))
        self.assertNotIn("hold_to_go", fake.calls[0][1])
        self.assertNotIn("added", fake.calls[0][1])

    def test_middle_band_is_logged_as_near_and_allowed(self):
        self.fake({"claims_user": 0.4, "hold_to_go": 0.1})
        self.assertIsNone(self.send("The user wants the inventory by tonight."))
        self.assertEqual(self.last_log()["decision"], "near")

    def test_faithful_relay_allowed(self):
        self.fake(0.1)
        self.assertIsNone(self.send("x7 : Plane"))
        self.assertEqual(self.last_log()["decision"], "allow")

    def test_own_report_is_not_held_to_the_users_words(self):
        self.fake({"claims_user": 0.1, "hold_to_go": 0.1})
        self.assertIsNone(self.send("Build finished; 12 tests green."))
        self.assertEqual(self.last_log()["decision"], "allow")

    def test_message_to_own_background_agent_is_not_judged(self):
        fake = self.fake(0.9)
        out = relay.main(
            {
                "tool_name": "SendMessage",
                "transcript_path": USER_HOLD,
                "tool_input": {"to": "a4fa82487cf8c4164", "message": "Add the scripts too."},
            }
        )
        self.assertIsNone(out)
        self.assertEqual(fake.calls, [])

    def test_saved_reading_reaches_the_relay_state(self):
        jev_client.save_reading("s-hold", {"kind": "hold"})
        fake = self.fake(0.1)
        relay.main(
            {
                "tool_name": "SendMessage",
                "session_id": "s-hold",
                "transcript_path": USER_HOLD,
                "tool_input": {"to": "peer-a", "message": "keep holding"},
            }
        )
        self.assertEqual(fake.calls[0][0]["user_recent_readings"], ["hold"])

    def test_other_tool_ignored(self):
        fake = self.fake(0.99)
        self.assertIsNone(relay.main({"tool_name": "Bash", "tool_input": {"message": "The owner wants x"}}))
        self.assertEqual(fake.calls, [])

    def test_jev_error_fails_open(self):
        self.fake(None)
        self.assertIsNone(self.send("The user wants all work in Linear now."))
        self.assertEqual(self.last_log()["decision"], "error")


COST = "\n\nCost: $1 | main $1 (opus-5-5 $1 now) | agents $0 | turn $0 | avg $0.07/req | context 1k | cold 0 = $0.00"


def turn(prompt, *blocks):
    return transcript(("user", prompt), ("assistant", list(blocks)))


class HoldGate(Base):
    def call(self, session, tool="mcp__linear-mcp__save_issue", title="x"):
        return hold.main(
            {"session_id": session, "transcript_path": USER_HOLD, "tool_name": tool, "tool_input": {"title": title}}
        )

    def test_tier_is_prompt(self):
        self.assertEqual(hold.TIER, "prompt")

    def test_identical_resend_passes_and_a_changed_call_is_judged(self):
        jev_client.save_reading("g-once", {"kind": "hold", "kind_conf": 0.95})
        fake = self.fake(0.8)
        out = json.loads(self.call("g-once"))
        self.assertIn("send the same call again unchanged", out["hookSpecificOutput"]["permissionDecisionReason"])
        self.assertEqual(self.last_log()["decision"], "prompt")
        self.assertIsNone(self.call("g-once"))
        self.assertEqual(self.last_log()["decision"], "resend")
        self.assertEqual(len(fake.calls), 1)
        self.assertIsNotNone(self.call("g-once", title="y"))
        self.assertEqual(len(fake.calls), 2)

    def test_no_hold_means_no_call(self):
        jev_client.save_reading("g-instr", {"kind": "instruction", "kind_conf": 0.99})
        fake = self.fake(0.99)
        self.assertIsNone(self.call("g-instr"))
        self.assertEqual(fake.calls, [])

    def test_weak_hold_reading_means_no_call(self):
        jev_client.save_reading("g-weak", {"kind": "hold", "kind_conf": 0.5})
        fake = self.fake(0.99)
        self.assertIsNone(self.call("g-weak"))
        self.assertEqual(fake.calls, [])

    def test_stopping_work_passes_a_hold(self):
        jev_client.save_reading("g-stop", {"kind": "hold", "kind_conf": 0.95})
        fake = self.fake(0.99)
        self.assertIsNone(self.call("g-stop", tool="TaskStop"))
        self.assertEqual(fake.calls, [])

    def test_acting_on_the_hold_is_denied(self):
        jev_client.save_reading("g-hold", {"kind": "hold", "kind_conf": 0.95})
        fake = self.fake(0.8)
        out = json.loads(self.call("g-hold"))
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertEqual(fake.calls[0][0]["user_message"], "x5 Plane")

    def test_unrelated_call_under_a_hold_passes(self):
        jev_client.save_reading("g-hold2", {"kind": "hold", "kind_conf": 0.95})
        self.fake(0.1)
        self.assertIsNone(self.call("g-hold2", tool="Bash"))
        self.assertEqual(self.last_log()["decision"], "allow")


class OutputCheck(Base):
    def setUp(self):
        super().setUp()
        self.band(True)

    def tearDown(self):
        super().tearDown()
        _common.SETTINGS = SETTINGS_REAL
        _common.session_surfaces = SESSION_SURFACES_REAL
        _common.BAND_SURFACES_DIR = BAND_SURFACES_DIR_REAL

    def band(self, enabled, installed=True):
        path = os.path.join(TMP, f"settings-band-{enabled}.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"enabledPlugins": {_common.BAND_PLUGIN: True} if enabled else {}}, fh)
        _common.SETTINGS = path
        markets = os.path.join(TMP, f"markets-{installed}.json")
        with open(markets, "w", encoding="utf-8") as fh:
            json.dump({"hexis-mods": {}} if installed else {"claude-plugins-official": {}}, fh)
        _common.MARKETPLACES = markets
        _common.session_surfaces = lambda _s: ["desktop"]

    def test_a_phone_attached_brings_the_lines_back(self):
        # the mod cannot be seen on a phone; there the reply carries the lines again.
        self.fake(0.1)
        _common.session_surfaces = lambda _s: ["desktop", "mobile"]
        self.assertFalse(_common.band_visible("o-phone"))
        out = json.loads(self.stop("o-phone", turn("x", {"type": "text", "text": "x23"})))
        self.assertIn("cost line", out["reason"])

    def test_no_surfaces_file_means_no_band(self):
        self.fake(0.1)
        _common.session_surfaces = SESSION_SURFACES_REAL
        _common.BAND_SURFACES_DIR = os.path.join(TMP, "no-band-files")
        self.assertFalse(_common.band_visible("o-nofile"))
        os.makedirs(_common.BAND_SURFACES_DIR, exist_ok=True)
        with open(os.path.join(_common.BAND_SURFACES_DIR, "o-file.json"), "w", encoding="utf-8") as fh:
            json.dump({"surfaces": ["desktop", "terminal"]}, fh)
        self.assertTrue(_common.band_visible("o-file"))

    def test_enabled_in_linked_settings_but_not_installed_here_still_blocks(self):
        # A WSL distro whose settings.json links to the Windows tree: its own plugins/ never had the plugin.
        self.fake(0.1)
        self.band(True, installed=False)
        self.assertFalse(_common.band_installed())
        out = json.loads(self.stop("o-linked", turn("x", {"type": "text", "text": "x22"})))
        self.assertIn("cost line", out["reason"])

    def stop(self, session, path, active=False):
        return output.main({"session_id": session, "transcript_path": path, "stop_hook_active": active})

    def test_without_the_band_a_missing_line_still_blocks(self):
        # Fable audit: until the jev-band plugin is enabled the reply is the only place the lines show.
        self.fake(0.1)
        self.band(False)
        line = "Jev 1.14.0 · instruction 0.90 · new_topic 0.90 · clear 0.90"
        jev_client.save_reading("o-noband", {"kind": "instruction", "kind_conf": 0.9, "line": line})
        out = json.loads(self.stop("o-noband", turn("x", {"type": "text", "text": "x20"})))
        self.assertEqual(out["decision"], "block")
        self.assertIn(f'no text block of the reply opens with the Jev reading line "{line}"', out["reason"])
        self.assertIn("cost line", out["reason"])

    def test_without_the_band_a_complete_reply_passes(self):
        self.fake(0.1)
        self.band(False)
        line = "Jev 1.14.0 · question 0.76 · last_reply 0.59 · clear 0.30"
        jev_client.save_reading("o-noband-ok", {"kind": "question", "kind_conf": 0.76, "line": line})
        self.assertIsNone(self.stop("o-noband-ok", turn("x", {"type": "text", "text": line + "\nx21" + COST})))

    def test_clean_reply_passes(self):
        self.fake(0.1)
        path = turn("x8", {"type": "thinking", "thinking": "all fine"}, {"type": "text", "text": "x9" + COST})
        self.assertIsNone(self.stop("o-clean", path))
        self.assertEqual(self.last_log()["decision"], "pass")

    def test_an_english_block_blocks_once_band_or_not(self):
        # 33 of 132 replies carried an English block, and with the band visible nothing caught them. The Japanese restatement added under the flagged block ends the check.
        self.fake(0.1)
        en = {"type": "text", "text": "I don't know yet how to pair it back; a research agent is still reading." + COST}
        out = json.loads(self.stop("o-en", turn("x", en)))
        self.assertIn("text block 1 of this turn is in English", out["reason"])
        ja = {"type": "text", "text": "まだ戻し方は分かりません。調査エージェントが読んでいるところです。" + COST}
        self.assertIsNone(self.stop("o-en", turn("x", en, ja)))

    def test_a_report_md_without_a_reader_document_blocks_once(self):
        # every md for him gets a Japanese reader document in the turn it is written.
        self.fake(0.1)
        write = {
            "type": "tool_use",
            "id": "w1",
            "name": "Write",
            "input": {
                "file_path": os.path.join(os.path.expanduser("~"), "dev", "p", "research", "r.md"),
                "content": "x",
            },
        }
        done = {"type": "text", "text": "報告を書きました。" + COST}
        path = turn("x", write, done)
        out = json.loads(self.stop("o-md", path))
        self.assertIn("without naming a reader document", out["reason"])
        self.assertIn("r.md", out["reason"])
        self.assertIsNone(self.stop("o-md", path))  # once per turn

    def test_a_report_md_with_its_reader_url_passes(self):
        self.fake(0.1)
        write = {
            "type": "tool_use",
            "id": "w2",
            "name": "Write",
            "input": {
                "file_path": os.path.join(os.path.expanduser("~"), "dev", "p", "docs", "d.md").replace("\\", "/"),
                "content": "x",
            },
        }
        done = {"type": "text", "text": "読む用の文書です: https://claude.ai/artifact/abc" + COST}
        self.assertIsNone(self.stop("o-md-ok", turn("x", write, done)))

    def test_code_and_paths_in_a_japanese_reply_pass(self):
        self.fake(0.1)
        text = (
            f"直しました。`{os.path.join(os.path.expanduser('~'), '.claude', 'hooks', 'output-check.py')}` の判定です。\n"
            "```text\nAlways reply in Japanese. Keep technical terms in their original language.\n```" + COST
        )
        self.assertIsNone(self.stop("o-ja", turn("x", {"type": "text", "text": text})))

    def test_progress_slug_reaching_the_user_blocks(self):
        self.fake(0.1)
        path = turn("x10", {"type": "text", "text": "x11 [s-open] x12" + COST})
        memory = os.path.join(os.path.dirname(path), "memory")
        os.makedirs(memory, exist_ok=True)
        with open(os.path.join(memory, "PROGRESS.md"), "w", encoding="utf-8") as fh:
            fh.write(
                "# Progress\nUpdated: 2026-09-26 06:00\n\n## Now\nx13\n\n## Open\n- [s-open] x14\n\n## Next\nx15\n"
            )
        try:
            out = json.loads(self.stop("o-slug", path))
            self.assertIn("s-open", out["reason"])
        finally:
            os.remove(os.path.join(memory, "PROGRESS.md"))

    def test_ids_block_and_a_missing_cost_line_is_logged_only(self):
        self.fake(0.1)
        out = json.loads(self.stop("o-ids", turn("x8", {"type": "text", "text": "x10 p68"})))
        self.assertEqual(out["decision"], "block")
        self.assertNotIn("cost line", out["reason"])
        self.assertIn("p68", out["reason"])
        note, main = self.logs(2)
        self.assertEqual((note["decision"], note["flags"]), ("format-note", ["no-cost-line"]))
        self.assertEqual(main["decision"], "block")

    def test_missing_cost_line_alone_is_not_blocked(self):
        self.fake(0.1)
        self.assertIsNone(self.stop("o-nocost", turn("x8", {"type": "text", "text": "x10"})))
        note, main = self.logs(2)
        self.assertEqual((note["decision"], note["flags"]), ("format-note", ["no-cost-line"]))
        self.assertEqual(main["decision"], "pass")

    def test_percentile_notation_passes_but_bracketed_ids_do_not(self):
        """p50 / p95 / p99 written as percentiles were blocked as internal ids; the user confirmed the
        notation is normal. The bracketed form pending[p50] still counts as an id."""
        self.fake(0.1)
        text = "x11 p50 / p95 / p99" + COST
        self.assertIsNone(self.stop("o-pct", turn("x12", {"type": "text", "text": text})))
        out = json.loads(self.stop("o-pct2", turn("x13", {"type": "text", "text": "x14 pending[p95]" + COST})))
        self.assertIn("p95", out["reason"])

    def test_the_fixed_reply_is_checked_but_a_turn_blocks_at_most_twice(self):
        self.fake(0.1)
        path = turn("x", {"type": "text", "text": "x p68" + COST})
        self.assertIsNotNone(self.stop("o-limit", path))
        self.assertIsNotNone(self.stop("o-limit", path, active=True))
        self.assertIsNone(self.stop("o-limit", path, active=True))
        self.assertEqual(self.last_log()["decision"], "over-limit")

    def test_a_new_turn_resets_the_block_count(self):
        self.fake(0.1)
        for _ in range(2):
            self.stop("o-reset", turn("first", {"type": "text", "text": "x p68" + COST}))
        other = raw_transcript(
            {"type": "user", "uuid": "u-2", "message": {"content": "second"}},
            {"type": "assistant", "message": {"content": [{"type": "text", "text": "x p69" + COST}]}},
        )
        self.assertIsNotNone(self.stop("o-reset", other))

    def test_defect_left_unfixed_is_logged_never_blocking(self):
        self.fake({"quotes_user": 0.1, "promise": 0.1, "left_unfixed": 0.9})
        self.assertIsNone(
            self.stop("o-unfixed", turn("x", {"type": "text", "text": "The check does not work yet." + COST}))
        )
        log = self.last_log()
        self.assertEqual(log["decision"], "would-block")
        self.assertEqual(log["flags"], ["left_unfixed"])

    def test_jev_tier_is_log_and_code_checks_still_block(self):
        self.assertEqual(output.TIER, "log")
        self.fake({"quotes_user": 0.9, "promise": 0.9, "left_unfixed": 0.9})
        out = json.loads(self.stop("o-mixed", turn("x", {"type": "text", "text": "x p68"})))
        self.assertIn("p68", out["reason"])
        self.assertNotIn("cost line", out["reason"])
        self.assertNotIn("Jev", out["reason"])
        log = self.last_log()
        self.assertEqual(log["decision"], "block")
        self.assertEqual(log["flags"], ["quotes_user", "promise", "left_unfixed"])

    def test_reply_opening_with_the_reading_line_passes(self):
        self.fake(0.1)
        line = "Jev 1.14.0 · question 0.76 · last_reply 0.59 · clear 0.30 · none 0.52"
        jev_client.save_reading("o-line", {"kind": "question", "kind_conf": 0.76, "line": line})
        path = turn("x", {"type": "text", "text": "\n" + line + "  \nx16" + COST})
        self.assertIsNone(self.stop("o-line", path))

    def test_reply_without_the_reading_line_is_logged_never_blocking(self):
        self.fake(0.1)
        line = "Jev 1.14.0 · instruction 0.90 · new_topic 0.90 · clear 0.90"
        jev_client.save_reading("o-noline", {"kind": "instruction", "kind_conf": 0.9, "line": line})
        self.assertIsNone(self.stop("o-noline", turn("x", {"type": "text", "text": "x17\n" + line + COST})))
        note, main = self.logs(2)
        self.assertEqual((note["decision"], note["flags"]), ("format-note", ["no-reading-line"]))
        self.assertEqual(main["decision"], "pass")

    def test_reading_line_at_the_top_of_any_block_passes(self):
        # A long turn writes the line at the top of its first block, runs
        # tools, and closes with a block that starts without it; the closing block alone was judged and blocked.
        self.fake(0.1)
        line = "Jev 1.14.0 · instruction 0.90 · new_topic 0.90 · clear 0.90"
        jev_client.save_reading("o-anyblock", {"kind": "instruction", "kind_conf": 0.9, "line": line})
        path = turn(
            "x",
            {"type": "text", "text": line + "\nstarting"},
            {"type": "tool_use", "id": "t-ab", "name": "Bash", "input": {"command": "echo"}},
            {"type": "text", "text": "done: x18" + COST},
        )
        self.assertIsNone(self.stop("o-anyblock", path))
        self.assertEqual(self.last_log()["decision"], "pass")
        self.assertNotEqual(self.logs(2)[0].get("decision"), "format-note")
        path = turn(
            "x",
            {"type": "text", "text": "working on it"},
            {"type": "tool_use", "id": "t-ab2", "name": "Bash", "input": {"command": "echo"}},
            {"type": "text", "text": line + "\ndone: x19" + COST},
        )
        self.assertIsNone(self.stop("o-anyblock", path))
        self.assertEqual(self.last_log()["decision"], "pass")
        self.assertNotEqual(self.logs(2)[0].get("decision"), "format-note")

    def test_reading_without_a_line_is_not_checked(self):
        self.fake(0.1)
        jev_client.save_reading("o-oldline", {"kind": "instruction", "kind_conf": 0.9})
        self.assertIsNone(self.stop("o-oldline", turn("x", {"type": "text", "text": "x18" + COST})))
        jev_client.save_reading("o-err", {"kind": None, "error": True})
        self.assertIsNone(self.stop("o-err", turn("x", {"type": "text", "text": "x19" + COST})))

    def _peer_after_human(self, session, summary):
        """A saved line from the previous human prompt, then a peer message (isMeta, turnOrigin peer), optionally
        the compaction summary the harness writes right after it (turnOrigin peer, isMeta unset, older timestamp)."""
        line = "Jev 1.14.0 · question 0.76 · last_reply 0.59 · clear 0.30"
        jev_client.save_reading(session, {"kind": "question", "kind_conf": 0.76, "line": line})
        rows = [
            {"type": "user", "message": {"content": "earlier human prompt"}},
            {"type": "assistant", "message": {"content": [{"type": "text", "text": line + "\nx" + COST}]}},
            {
                "type": "user",
                "isMeta": True,
                "turnOrigin": "peer",
                "timestamp": "2026-11-01T05:27:14.642Z",
                "message": {"content": "Another Claude session sent a message:\nx"},
            },
        ]
        if summary:
            rows.append(
                {
                    "type": "user",
                    "turnOrigin": "peer",
                    "isCompactSummary": True,
                    "timestamp": "2026-10-28T17:51:02.634Z",
                    "message": {"content": "This session is being continued from a previous conversation"},
                }
            )
        rows.append({"type": "assistant", "message": {"content": [{"type": "text", "text": "reply" + COST}]}})
        return raw_transcript(*rows)

    def test_peer_turn_needs_no_reading_line(self):
        self.fake(0.1)
        self.assertIsNone(self.stop("o-peer", self._peer_after_human("o-peer", summary=False)))

    def test_compaction_summary_after_a_peer_message_does_not_open_a_human_turn(self):
        self.fake(0.1)
        path = self._peer_after_human("o-peer-sum", summary=True)
        prompt, _blocks, _results, _ = output.this_turn(output.entries(path))
        self.assertTrue(prompt.startswith("Another Claude session sent"))
        self.assertIsNone(self.stop("o-peer-sum", path))

    def test_peer_origin_without_ismeta_still_counts_as_a_peer_turn(self):
        self.fake(0.1)
        path = self._peer_after_human("o-peer-nometa", summary=False)
        rows = [json.loads(l) for l in Path(path).read_text(encoding="utf-8").splitlines()]
        rows[2].pop("isMeta")
        path = raw_transcript(*rows)
        self.assertIsNone(self.stop("o-peer-nometa", path))

    def test_a_plain_human_prompt_still_notes_a_missing_line(self):
        self.fake(0.1)
        line = "Jev 1.14.0 · question 0.76 · last_reply 0.59 · clear 0.30"
        jev_client.save_reading("o-human", {"kind": "question", "kind_conf": 0.76, "line": line})
        self.assertIsNone(self.stop("o-human", turn("x", {"type": "text", "text": "reply" + COST})))
        self.assertEqual(self.logs(2)[0]["flags"], ["no-reading-line"])

    def test_turn_ending_on_a_tool_call_is_skipped(self):
        fake = self.fake(0.99)
        path = turn("x", {"type": "text", "text": "working"}, {"type": "tool_use", "name": "Bash", "input": {}})
        self.assertIsNone(self.stop("o-tool", path))
        self.assertEqual(fake.calls, [])

    def test_correction_needs_a_lesson_logged_never_blocking(self):
        """The check rests on misread-check's Jev reading (kind == correction), so it is log tier."""
        jev_client.save_reading("o-corr", {"kind": "correction", "kind_conf": 0.95})
        self.fake(0.1)
        self.assertIsNone(self.stop("o-corr", turn("x13", {"type": "text", "text": "x14" + COST})))
        self.assertEqual(self.last_log()["decision"], "would-block")
        self.assertEqual(self.last_log()["flags"], ["correction"])
        # a note about the correction is not the fix
        for note in (
            os.path.join(TMP, "projects", "x", "memory", "feedback-x.md"),
            os.path.join(TMP, "projects", "x", "memory", "STATE.md"),
        ):
            jev_client.save_reading("o-note", {"kind": "correction", "kind_conf": 0.95})
            path = turn(
                "x13",
                {"type": "tool_use", "name": "Write", "input": {"file_path": note}},
                {"type": "text", "text": "x15" + COST},
            )
            self.assertIsNone(self.stop("o-note", path))
            self.assertEqual(self.last_log()["flags"], ["correction"])
        # changing what it corrects, or an inbox entry, is
        for fix in (
            os.path.join(TMP, "rules", "quality.md"),
            os.path.join(TMP, "hooks", "x.py"),
            os.path.join(TMP, ".claude", "inbox", "2026-09-26-x.md"),
        ):
            jev_client.save_reading("o-fix", {"kind": "correction", "kind_conf": 0.95})
            path = turn(
                "x13",
                {"type": "tool_use", "name": "Edit", "input": {"file_path": fix}},
                {"type": "text", "text": "x14" + COST},
            )
            self.assertIsNone(self.stop("o-fix", path))
            self.assertNotIn("flags", self.last_log())

    def test_jev_bars_are_per_question(self):
        self.fake({"quotes_user": 0.1, "promise": 0.65, "overclaim": 0.1, "dropped": 0.75})
        path = turn("x", {"type": "thinking", "thinking": "r"}, {"type": "text", "text": "ok" + COST})
        self.assertIsNone(self.stop("o-bars", path))
        self.assertEqual(self.last_log()["flags"], ["promise"])

    def test_tool_results_become_evidence(self):
        fake = self.fake({"quotes_user": 0.1, "promise": 0.1, "unsupported": 0.9})
        path = raw_transcript(
            {"type": "user", "message": {"content": "x16"}},
            {
                "type": "assistant",
                "message": {
                    "content": [{"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "pytest -q"}}]
                },
            },
            {
                "type": "user",
                "message": {
                    "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "3 failed, 10 passed"}]
                },
            },
            {"type": "assistant", "message": {"content": [{"type": "text", "text": "x17" + COST}]}},
        )
        out = self.stop("o-ev", path)
        state = fake.calls[0][0]
        self.assertEqual(
            state["tool_results"], [{"tool": "Bash", "asked": "pytest -q", "result": "3 failed, 10 passed"}]
        )
        # `unsupported` is retired: never asked (Peer Jev policy)
        self.assertIsNone(out)
        self.assertNotIn("unsupported", fake.calls[0][1])
        self.assertNotIn("unsupported", self.last_log().get("flags") or [])

    def test_reply_before_a_closing_state_write_is_the_closing_message(self):
        fake = self.fake(0.1)
        path = turn(
            "x",
            {"type": "text", "text": "Here are the two texts."},
            {"type": "tool_use", "id": "s1", "name": "Bash", "input": {"command": "echo >> STATE.md"}},
            {"type": "text", "text": COST.strip()},
        )
        self.stop("o-close", path)
        self.assertEqual(fake.calls[0][0]["final_reply"], "Here are the two texts.")

    def test_agent_report_that_opened_the_turn_is_evidence(self):
        fake = self.fake(0.1)
        path = raw_transcript(
            {"type": "user", "message": {"content": "<task-notification>result: 5,976 user turns</task-notification>"}},
            {"type": "assistant", "message": {"content": [{"type": "text", "text": "5,976 turns." + COST}]}},
        )
        self.stop("o-report", path)
        self.assertIn("5,976", fake.calls[0][0]["tool_results"][0]["result"])

    def test_pending_ids_inside_a_fenced_block_are_allowed(self):
        self.fake(0.1)
        text = "Handoff below.\n```text\n- pending[p81]: relay\n```" + COST
        self.assertIsNone(self.stop("o-fence", turn("x", {"type": "text", "text": text})))

    def test_unanswered_question_is_logged_never_blocking(self):
        jev_client.save_reading("o-q", {"kind": "question", "kind_conf": 0.95})
        fake = self.fake({"quotes_user": 0.1, "promise": 0.1, "answered": 0.1})
        self.assertIsNone(self.stop("o-q", turn("x18", {"type": "text", "text": "x19" + COST})))
        self.assertIn("answered", fake.calls[0][1])
        self.assertEqual(self.last_log()["decision"], "would-block")
        self.assertEqual(self.last_log()["flags"], ["answered"])


def queued(prompt):
    return {
        "type": "attachment",
        "attachment": {"type": "queued_command", "prompt": prompt, "commandMode": "prompt", "humanTurn": True},
    }


def raw_transcript(*rows):
    path = os.path.join(TMP, f"r{len(os.listdir(TMP))}.jsonl")
    with open(path, "w", encoding="utf-8") as fh:
        fh.writelines(json.dumps(row, ensure_ascii=False) + "\n" for row in rows)
    return path


class MidTurnMessages(Base):
    """A message sent while a turn runs is a queued_command attachment, not a user entry."""

    def rows(self):
        return raw_transcript(
            {"type": "user", "message": {"content": "first"}},
            {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Bash", "input": {}}]}},
            {"type": "user", "message": {"content": [{"type": "tool_result", "content": "x"}]}},
            queued("x20"),
            {"type": "assistant", "message": {"content": [{"type": "text", "text": "ok" + COST}]}},
        )

    def test_turns_include_queued_prompts(self):
        users = [t for r, t in jev_client.turns(self.rows()) if r == "user"]
        self.assertEqual(users, ["first", "x20"])

    def test_output_check_answers_the_newest_prompt(self):
        prompt, blocks, _results, _ = output.this_turn(output.entries(self.rows()))
        self.assertEqual(prompt, "x20")
        self.assertEqual([b["type"] for b in blocks], ["tool_use", "text"])

    def test_relay_sees_a_queued_decision(self):
        fake = self.fake(0.1)
        relay.main(
            {
                "tool_name": "SendMessage",
                "session_id": "",
                "transcript_path": self.rows(),
                "tool_input": {"to": "x", "message": "the user decided to rebuild"},
            }
        )
        self.assertIn("x20", fake.calls[0][0]["user_recent_messages"])


class CommitGate(Base):
    def setUp(self):
        super().setUp()
        import subprocess

        self.repo = tempfile.mkdtemp(dir=TMP)
        self.git = lambda *a: subprocess.run(["git", *a], cwd=self.repo, capture_output=True, text=True, check=False)
        self.git("init", "-q")
        self.git("config", "user.email", "t@example.com")
        self.git("config", "user.name", "t")
        Path(self.repo, "a.py").write_text("x = 1\n", encoding="utf-8")
        self.git("add", "-A")
        self.git("commit", "-qm", "Add a")
        Path(self.repo, "a.py").write_text("x = 2\n", encoding="utf-8")

    def gate(self, command):
        return commit.main({"tool_name": "Bash", "cwd": self.repo, "tool_input": {"command": command}})

    def test_non_commit_is_ignored(self):
        fake = self.fake(0.99)
        self.assertIsNone(self.gate("git status && git log -3"))
        self.assertEqual(fake.calls, [])

    def test_attribution_is_denied_without_jev(self):
        fake = self.fake(0.0)
        out = json.loads(self.gate('git commit -am "x" -m "Co-Authored-By: Claude <c@x>"'))
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertEqual(fake.calls, [])

    def test_add_in_the_same_command_is_seen(self):
        fake = self.fake(0.1)
        self.assertIsNone(self.gate('git add a.py && git commit -qm "Bump x"'))
        state = fake.calls[0][0]
        self.assertIn("x = 2", state["staged_diff"])
        self.assertEqual(state["message"], "Bump x")

    def test_new_file_in_the_same_command_is_seen(self):
        fake = self.fake(0.1)
        Path(self.repo, "b.py").write_text("y = 3\n", encoding="utf-8")
        self.gate('git add b.py && git commit -m "Add b"')
        self.assertIn("new file: b.py", fake.calls[0][0]["staged_diff"])

    def test_follow_up_to_unpushed_head_is_logged_never_denied(self):
        self.assertEqual(commit.TIER, "log")
        self.fake({"mixed": 0.1, "mismatch": 0.1, "follow_up": 0.9})
        self.git("add", "a.py")
        self.assertIsNone(self.gate('git commit -m "Tweak a"'))
        self.assertEqual(self.last_log()["decision"], "would-deny")
        self.assertEqual(self.last_log()["flags"], ["follow_up"])

    def test_block_tier_still_denies_with_the_reasons(self):
        self.fake({"mixed": 0.9, "mismatch": 0.1, "follow_up": 0.1})
        self.git("add", "a.py")
        setattr(commit, "TIER", "block")  # noqa: B010 - pyright rejects assigning to a loaded module
        try:
            out = json.loads(self.gate('git commit -m "Tweak a"'))
        finally:
            setattr(commit, "TIER", "log")  # noqa: B010 - as above
        self.assertIn("one commit per topic", out["hookSpecificOutput"]["permissionDecisionReason"])

    def test_fixup_is_not_asked_follow_up(self):
        fake = self.fake(0.9)
        self.git("add", "a.py")
        self.gate("git commit --fixup=HEAD")
        self.assertNotIn("follow_up", fake.calls[0][1])
        self.assertIn("fits_topic", fake.calls[0][1])

    def test_fixup_target_from_a_variable_is_resolved(self):
        fake = self.fake(0.9)
        self.gate("H=$(git log --format=%h --grep '^Add' -1); git add a.py && git commit -q --fixup=$H")
        self.assertIn("Add a", fake.calls[0][0]["target_commit"])

    def test_fixup_target_from_a_substitution_is_resolved(self):
        fake = self.fake(0.9)
        self.git("add", "a.py")
        self.gate("git commit -q --fixup=$(git rev-parse HEAD)")
        self.assertIn("Add a", fake.calls[0][0]["target_commit"])

    def test_unresolvable_fixup_target_is_denied_not_skipped(self):
        fake = self.fake(0.9)
        self.git("add", "a.py")
        out = json.loads(self.gate("git commit -q --fixup=$SOMEWHERE"))
        self.assertIn("cannot be resolved", out["hookSpecificOutput"]["permissionDecisionReason"])
        self.assertEqual(fake.calls, [])

    def test_fixup_into_the_wrong_topic_is_logged_never_denied(self):
        self.fake({"mixed": 0.1, "fits_topic": 0.1})
        self.git("add", "a.py")
        self.assertIsNone(self.gate("git commit -q --fixup=HEAD"))
        self.assertEqual(self.last_log()["decision"], "would-deny")
        self.assertEqual(self.last_log()["flags"], ["fits_topic"])

    def test_two_commits_in_one_command_are_split(self):
        fake = self.fake(0.0)
        out = json.loads(self.gate('git commit -qm "a" && git add x && git commit -qm "b"'))
        self.assertIn("its own command", out["hookSpecificOutput"]["permissionDecisionReason"])
        self.assertEqual(fake.calls, [])

    def test_reset_before_commit_is_split(self):
        out = json.loads(self.gate('git reset -q --soft HEAD~1 && git add a.py && git commit -qm "regroup"'))
        self.assertIn("its own command", out["hookSpecificOutput"]["permissionDecisionReason"])

    def test_rebase_after_the_commit_is_fine(self):
        fake = self.fake({"mixed": 0.1, "fits_topic": 0.9})
        self.git("add", "a.py")
        self.assertIsNone(
            self.gate("git commit -q --fixup=HEAD && GIT_SEQUENCE_EDITOR=: git rebase -q -i --autosquash X")
        )
        self.assertEqual(len(fake.calls), 1)

    def test_nothing_visible_is_denied_not_passed(self):
        fake = self.fake(0.0)
        self.git("checkout", "--", "a.py")
        out = json.loads(self.gate('printf "z" > a.py && git add a.py && git commit -m "x"'))
        self.assertIn("cannot see", out["hookSpecificOutput"]["permissionDecisionReason"])
        self.assertEqual(fake.calls, [])

    def test_message_only_amend_passes(self):
        fake = self.fake(0.99)
        self.git("checkout", "--", "a.py")
        self.assertIsNone(self.gate('git commit --amend -m "better message"'))
        self.assertEqual(fake.calls, [])

    def test_commit_with_config_flags_is_seen(self):
        fake = self.fake(0.1)
        self.git("add", "a.py")
        self.gate('git -c user.email=t@x -c user.name=t commit -qm "Bump x"')
        self.assertEqual(len(fake.calls), 1)

    def session(self, *steps):
        """A transcript of tool calls: ("edit", relative path) or ("run", command, output, is_error)."""
        records = []
        for i, step in enumerate(steps):
            uid = f"u{i}"
            if step[0] == "edit":
                use = {
                    "type": "tool_use",
                    "id": uid,
                    "name": "Edit",
                    "input": {"file_path": os.path.join(self.repo, step[1])},
                }
                result = {"type": "tool_result", "tool_use_id": uid, "content": "updated"}
            else:
                use = {"type": "tool_use", "id": uid, "name": "Bash", "input": {"command": step[1]}}
                result = {"type": "tool_result", "tool_use_id": uid, "content": step[2], "is_error": step[3]}
            records += [("assistant", [use]), ("user", [result])]
        return transcript(*records)

    def verified(self, path, command='git add a.py && git commit -qm "Bump x"', check: str | None = "scripts/check.py"):
        if check:
            os.makedirs(os.path.join(self.repo, ".claude"), exist_ok=True)
            Path(self.repo, ".claude", "quality.json").write_text(json.dumps({"check": check}), encoding="utf-8")
        return commit.main(
            {"tool_name": "Bash", "cwd": self.repo, "transcript_path": path, "tool_input": {"command": command}}
        )

    def reason(self, out):
        return json.loads(out)["hookSpecificOutput"]["permissionDecisionReason"]

    def test_edited_and_never_checked_is_denied_without_jev(self):
        fake = self.fake(0.1)
        self.assertIn("has not run green", self.reason(self.verified(self.session(("edit", "a.py")))))
        self.assertEqual(fake.calls, [])

    def test_green_check_after_the_edit_verifies(self):
        fake = self.fake(0.1)
        path = self.session(
            ("edit", "a.py"), ("run", "cd ~/.claude && python scripts/check.py", "check: passed", False)
        )
        self.assertIsNone(self.verified(path))
        self.assertEqual(len(fake.calls), 1)

    def test_failed_check_does_not_verify(self):
        self.fake(0.1)
        path = self.session(
            ("edit", "a.py"), ("run", "python scripts/check.py", "Exit code 1\ncheck: FAILED (2 of 9)", True)
        )
        self.assertIn("has not run green", self.reason(self.verified(path)))

    def test_failure_count_in_output_does_not_verify(self):
        self.fake(0.1)
        path = self.session(("edit", "a.py"), ("run", "python scripts/check.py", "1 failed, 3 passed", False))
        self.assertIsNotNone(self.verified(path))

    def test_check_before_the_last_edit_does_not_verify(self):
        self.fake(0.1)
        path = self.session(
            ("edit", "a.py"), ("run", "python scripts/check.py", "check: passed", False), ("edit", "a.py")
        )
        self.assertIsNotNone(self.verified(path))

    def test_another_test_run_is_not_the_check(self):
        self.fake(0.1)
        path = self.session(
            ("edit", "a.py"),
            ("run", "python -m unittest discover", "OK", False),
            ("run", "grep -n x a.py && python a.py", "x = 2", False),
        )
        self.assertIn("has not run green", self.reason(self.verified(path)))

    def test_no_declared_check_is_denied_with_a_suggestion(self):
        self.fake(0.1)
        Path(self.repo, "Cargo.toml").write_text("[package]\n", encoding="utf-8")
        reason = self.reason(self.verified(self.session(("edit", "a.py")), check=None))
        self.assertIn("declares no check", reason)
        self.assertIn("cargo clippy", reason)

    def test_any_language_needs_the_check(self):
        self.fake(0.1)
        Path(self.repo, "main.zig").write_text("const x = 1;\n", encoding="utf-8")
        path = self.session(("edit", "main.zig"))
        self.assertIn("main.zig", self.reason(self.verified(path, 'git add main.zig && git commit -qm "Add main"')))

    def test_dotfile_without_extension_needs_no_check(self):
        fake = self.fake(0.1)
        Path(self.repo, ".gitignore").write_text("x\n", encoding="utf-8")
        path = self.session(("edit", ".gitignore"))
        self.assertIsNone(self.verified(path, 'git add .gitignore && git commit -qm "Ignore x"'))
        self.assertEqual(len(fake.calls), 1)

    def test_docs_need_no_test_run(self):
        fake = self.fake(0.1)
        Path(self.repo, "README.md").write_text("notes\n", encoding="utf-8")
        path = self.session(("edit", "README.md"))
        self.assertIsNone(self.verified(path, 'git add README.md && git commit -qm "Notes"'))
        self.assertEqual(len(fake.calls), 1)

    def test_code_not_edited_in_this_session_needs_no_test_run(self):
        fake = self.fake(0.1)
        path = self.session(("run", "git status", "clean", False))
        self.assertIsNone(self.verified(path))
        self.assertEqual(len(fake.calls), 1)

    def test_cd_in_the_middle_picks_the_repo(self):
        fake = self.fake(0.1)
        self.git("add", "a.py")
        commit.main(
            {
                "tool_name": "Bash",
                "cwd": TMP,
                "tool_input": {
                    "command": 'X=1; cd "{}" && git commit -qm "Bump x"'.format(self.repo.replace("\\", "/"))
                },
            }
        )
        self.assertIn("x = 2", fake.calls[0][0]["staged_diff"])


class PartialHold(Base):
    def test_hold_inside_an_approval_opens_the_gate(self):
        jev_client.save_reading("h-part", {"kind": "approval", "kind_conf": 0.85, "hold": 0.9})
        self.fake(0.8)
        out = json.loads(
            hold.main(
                {
                    "session_id": "h-part",
                    "transcript_path": USER_HOLD,
                    "tool_name": "mcp__linear-mcp__save_issue",
                    "tool_input": {},
                }
            )
        )
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_reading_saved_even_when_jev_fails(self):
        self.fake(None)
        misread.main({"prompt": "x", "transcript_path": TWO_FILES, "session_id": "h-err"})
        self.assertEqual(jev_client.recent_readings("h-err", 1), [dict(jev_client.recent_readings("h-err", 1)[0])])
        self.assertIsNone(jev_client.recent_readings("h-err", 1)[0]["kind"])


class Client(unittest.TestCase):
    def test_latest_moving_is_noted_once_while_the_decider_stays_pinned(self):
        jev_client.LAST_SHADOW = {"jev-latest": {"model": "jev-1.13.0", "ps": {}}}
        self.assertEqual(jev_client.model_change_note(), "")  # first sighting only records
        jev_client.LAST_SHADOW = {"jev-latest": {"model": "jev-1.14.0", "ps": {}}}
        note = jev_client.model_change_note()
        self.assertIn("from jev-1.13.0 to jev-1.14.0", note)
        self.assertIn(f"still decide on {jev_client.MODEL}", note)
        self.assertEqual(jev_client.model_change_note(), "")
        jev_client.LAST_SHADOW = None

    def test_missing_key_returns_none(self):
        key = jev_client.KEY_FILE
        jev_client.KEY_FILE = os.path.join(TMP, "no-such-key.txt")
        try:
            self.assertIsNone(jev_client.nouls("x", {"q": ("Is this x?", None)}))
        finally:
            jev_client.KEY_FILE = key

    def test_unreachable_returns_none(self):
        url, key = jev_client.URL, jev_client.KEY_FILE
        jev_client.KEY_FILE = os.path.join(TMP, "k.txt")
        Path(jev_client.KEY_FILE).write_text("k", encoding="utf-8")
        jev_client.URL = "http://127.0.0.1:9/v1/systemone"
        try:
            self.assertIsNone(jev_client.nouls("x", {"q": ("Is this x?", None)}))
            self.assertEqual(jev_client.LAST_SHADOW, {})
        finally:
            jev_client.URL, jev_client.KEY_FILE = url, key


class ScoreTag(unittest.TestCase):
    def test_score_is_shown_with_version_and_question(self):
        last = jev_client.LAST_MODEL
        jev_client.LAST_MODEL = "jev-1.13.0"
        try:
            self.assertEqual(jev_client.tag("dropped", 0.81), "Jev 1.13.0: dropped 0.81")
        finally:
            jev_client.LAST_MODEL = last


USER_REQ = transcript(
    ("user", "x21"),
    ("assistant", [{"type": "text", "text": "x22"}]),
    ("user", '<cross-session-message from="peer-a">peer text</cross-session-message>'),
)


class BriefCheck(Base):
    def launch(self, prompt, model="sonnet", kind="general-purpose", tool="Agent"):
        return brief.main(
            {
                "tool_name": tool,
                "transcript_path": USER_REQ,
                "session_id": "s-brief",
                "tool_input": {"prompt": prompt, "model": model, "subagent_type": kind},
            }
        )

    def test_stage_one_logs_would_deny_and_allows(self):
        fake = self.fake({"dropped": 0.8, "changed": 0.8, "added": 0.8, "no_acceptance": 0.8, "loosened": 0.1})
        self.assertIsNone(self.launch("x23 Add an button in blue and refactor the save path."))
        log = self.last_log()
        self.assertEqual(log["decision"], "would-deny")
        self.assertEqual(set(fake.calls[0][1]), {"dropped", "changed", "added", "no_acceptance", "loosened"})
        self.assertEqual(log["source"], "general-purpose/sonnet")
        state = fake.calls[0][0]
        self.assertEqual(state["user_recent_messages"], ["x21"])
        self.assertIn("blue", state["brief"])

    def test_deny_mode_denies_and_names_the_hits(self):
        self.fake({"dropped": 0.1, "changed": 0.9, "added": 0.7, "no_acceptance": 0.2})
        self.assertEqual(brief.TIER, "log")
        setattr(brief, "TIER", "block")  # noqa: B010 - brief is a dynamically loaded module; pyright rejects direct attribute assignment on ModuleType
        try:
            out = json.loads(self.launch("x23 Add an button in blue and refactor the save path."))
        finally:
            setattr(brief, "TIER", "log")  # noqa: B010 - see above
        hook = out["hookSpecificOutput"]
        self.assertEqual(hook["permissionDecision"], "deny")
        self.assertIn("Jev brief check", hook["permissionDecisionReason"])
        self.assertIn("changed 0.90, added 0.70", hook["permissionDecisionReason"])

    def test_faithful_brief_allowed(self):
        self.fake(0.1)
        self.assertIsNone(self.launch("x24 Button label , red; do not touch the save path. Done when the test passes."))
        self.assertEqual(self.last_log()["decision"], "allow")

    def test_middle_band_is_near(self):
        self.fake({"dropped": 0.4, "changed": 0.1, "added": 0.1, "no_acceptance": 0.1})
        self.assertIsNone(self.launch("x25 Button label , red."))
        self.assertEqual(self.last_log()["decision"], "near")

    def test_opus_trigger_asked_only_for_opus(self):
        fake = self.fake(0.1)
        self.launch("x", model="sonnet")
        self.launch("x", model="opus")
        self.launch("x", model="", kind="implementer")
        self.assertNotIn("opus_untriggered", fake.calls[0][1])
        self.assertIn("opus_untriggered", fake.calls[1][1])
        self.assertIn("opus_untriggered", fake.calls[2][1])

    def test_other_tool_ignored(self):
        fake = self.fake(0.99)
        self.assertIsNone(self.launch("x", tool="Bash"))
        self.assertEqual(fake.calls, [])

    def test_loosened_brief_is_stopped_once_then_passes(self):
        self.fake({"dropped": 0.1, "changed": 0.1, "added": 0.1, "no_acceptance": 0.1, "loosened": 0.8})
        text = "x32 White hair from the hood's edge; if nothing reads as hair, drop it and say why."
        out = json.loads(self.launch(text))
        self.assertIn("loosened 0.80", out["hookSpecificOutput"]["permissionDecisionReason"])
        self.assertEqual(self.last_log()["decision"], "prompt")
        self.assertIsNone(self.launch(text))
        self.assertEqual(self.last_log()["decision"], "would-deny")

    def test_follow_up_message_is_asked_only_loosened(self):
        fake = self.fake(0.8)
        payload = {
            "tool_name": "SendMessage",
            "transcript_path": USER_REQ,
            "session_id": "s-msg",
            "tool_input": {"to": "a0123456789abcdef", "message": "x33 if nothing reads as hair, drop it"},
        }
        self.assertIn('"deny"', brief.main(payload))
        self.assertEqual(set(fake.calls[0][1]), {"loosened"})
        self.assertEqual(self.last_log()["source"], "message/-")

    def test_started_session_brief_is_judged(self):
        fake = self.fake(0.1)
        payload = {
            "tool_name": brief.START,
            "transcript_path": USER_REQ,
            "session_id": "s-start",
            "tool_input": {"prompt": "x34 Paint the button red.", "background": "x34 The theme is dark."},
        }
        self.assertIsNone(brief.main(payload))
        state, questions = fake.calls[0]
        self.assertIn("Paint the button red.", state["brief"])
        self.assertIn("The theme is dark.", state["brief"])
        self.assertIn("loosened", questions)
        self.assertIn("dropped", questions)

    def test_workflow_script_is_judged_as_the_brief(self):
        fake = self.fake({"dropped": 0.8, "changed": 0.8, "added": 0.8, "no_acceptance": 0.8, "loosened": 0.1})
        script = "x26 export const meta = {name: 'x'}\nawait agent('Paint the button blue')"
        brief.main(
            {
                "tool_name": "Workflow",
                "transcript_path": USER_REQ,
                "session_id": "s-wf",
                "tool_input": {"script": script},
            }
        )
        self.assertIn("Paint the button blue", fake.calls[0][0]["brief"])
        self.assertEqual(self.last_log()["source"], "workflow/-")
        self.assertEqual(self.last_log()["decision"], "would-deny")

    def test_jev_error_fails_open(self):
        self.fake(None)
        self.assertIsNone(self.launch("x"))
        self.assertEqual(self.last_log()["decision"], "error")

    def test_state_is_capped_by_dropping_the_oldest_prompts(self):
        fake = self.fake(0.1)
        path = transcript(*[("user", f"x28 {i} " + "y" * 1400) for i in range(20)])
        brief.main(
            {
                "tool_name": "Agent",
                "transcript_path": path,
                "session_id": "s-cap",
                "tool_input": {"prompt": "b" * 12000, "model": "sonnet", "subagent_type": "general-purpose"},
            }
        )
        state = fake.calls[0][0]
        self.assertLessEqual(sum(map(len, state["user_recent_messages"])) + len(state["brief"]), brief.STATE_CHARS)
        self.assertTrue(state["user_recent_messages"][-1].startswith("x28 19"))

    def test_checked_brief_is_kept_as_a_record(self):
        self.fake(0.1)
        self.launch("x31 Button label , red; do not touch the save path.")
        day = os.path.join(brief.RECORDS, max(os.listdir(brief.RECORDS)))
        with open(os.path.join(day, max(os.listdir(day))), encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn("x31 Button label , red; do not touch the save path.", text)
        self.assertIn("brief-check: allow", text)
        self.assertIn("agent: general-purpose / sonnet", text)


class MdCheck(Base):
    """Paths are built with os.path.join from a temp root, so the tests run the same on Windows, Linux and macOS."""

    def write(self, *parts, text="The user prefers blue buttons.", tool="Write"):
        key = "content" if tool == "Write" else "new_string"
        return md.main(
            {
                "tool_name": tool,
                "transcript_path": USER_REQ,
                "session_id": "s-md",
                "tool_input": {"file_path": os.path.join(TMP, *parts), key: text},
            }
        )

    def test_feedback_memory_is_logged_never_denied(self):
        self.assertEqual(md.TIER, "log")
        self.fake({"dropped": 0.1, "changed": 0.8, "added": 0.2})
        self.assertIsNone(self.write("projects", "p", "memory", "feedback-x.md"))
        self.assertEqual(self.last_log()["decision"], "would-deny")
        self.assertEqual(self.last_log()["source"], "feedback-memory")

    def test_block_tier_denies(self):
        self.fake({"dropped": 0.1, "changed": 0.8, "added": 0.2})
        setattr(md, "TIER", "block")  # noqa: B010 - pyright rejects assigning to a loaded module
        try:
            out = json.loads(self.write("projects", "p", "memory", "feedback-x.md"))
        finally:
            setattr(md, "TIER", "log")  # noqa: B010 - as above
        self.assertIn("Jev md check", out["hookSpecificOutput"]["permissionDecisionReason"])

    def test_rules_edit_is_logged_only(self):
        self.fake(0.9)
        self.assertIsNone(self.write("rules", "agents.md", tool="Edit"))
        self.assertEqual(self.last_log()["decision"], "would-deny")

    def test_faithful_memory_allowed(self):
        self.fake(0.1)
        self.assertIsNone(self.write("projects", "p", "memory", "feedback-y.md"))
        self.assertEqual(self.last_log()["decision"], "allow")

    def test_japanese_prose_in_a_record_is_denied(self):
        # Records are English (CLAUDE.md): a report written in Japanese under outputs/ or a project memory is refused
        # by code, before any Jev call; docs/ is the user's and stays Japanese.
        self.fake(0.1)
        jp = "この比較は日本語で書かれている。" * 20
        out = json.loads(self.write(".claude", "knowledge", "report.md", text=jp))
        self.assertIn("Records are English", out["hookSpecificOutput"]["permissionDecisionReason"])
        self.assertEqual(self.last_log()["decision"], "deny-language")
        out = json.loads(self.write("projects", "p", "memory", "PROGRESS.md", text=jp))
        self.assertIn("Records are English", out["hookSpecificOutput"]["permissionDecisionReason"])
        # what the user reads stays Japanese: docs/ and the docs hub are not checked; a Japanese document under
        # outputs/ is refused there because he cannot see ~/.claude
        self.assertIsNone(self.write(".claude", "docs", "report.md", text=jp))
        self.assertIsNone(self.write(".claude", "outputs", "docs-hub", "originals", "x.md", text=jp))
        out = json.loads(self.write(".claude", "outputs", "inventory.md", text=jp))
        self.assertIn("project's dev working directory", out["hookSpecificOutput"]["permissionDecisionReason"])
        self.assertIsNone(self.write(".claude", "outputs", "analysis.md", text="English working record. " * 40))
        titles = "English prose around quoted Linear titles. " * 30 + "- 「棚卸の一覧を作る」\n" * 8
        self.assertIsNone(self.write(".claude", "knowledge", "inventory.md", text=titles))

    def test_other_files_are_not_judged(self):
        fake = self.fake(0.99)
        for parts in (("projects", "p", "memory", "STATE.md"), ("notes", "feedback-z.txt"), ("docs", "readme.md")):
            self.assertIsNone(self.write(*parts))
        self.assertEqual(fake.calls, [])

    def test_jev_error_fails_open(self):
        self.fake(None)
        self.assertIsNone(self.write("projects", "p", "memory", "feedback-w.md"))
        self.assertEqual(self.last_log()["decision"], "error")

    def test_edit_is_judged_as_the_resulting_file(self):
        path = os.path.join(TMP, "projects", "p", "memory", "feedback-e.md")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("keep this line\ndrop this line\n")
        fake = self.fake(0.1)
        md.main(
            {
                "tool_name": "Edit",
                "transcript_path": USER_REQ,
                "session_id": "s-md",
                "tool_input": {"file_path": path, "old_string": "drop this line\n", "new_string": ""},
            }
        )
        self.assertEqual(fake.calls[0][0]["document"], "keep this line\n")


class JapaneseReminder(unittest.TestCase):
    # Text written after an English denial or block drifted into English; every one the main session
    # reads now ends with the language line.
    DENY = json.dumps({"hookSpecificOutput": {"permissionDecision": "deny", "permissionDecisionReason": "x30."}})

    def test_a_denial_in_the_main_session_ends_with_the_line(self):
        out = json.loads(_common.remind_japanese(self.DENY, {"hook_event_name": "PreToolUse"}))
        self.assertTrue(out["hookSpecificOutput"]["permissionDecisionReason"].endswith(_common.JA_REMINDER))

    def test_a_stop_block_ends_with_the_line(self):
        block = json.dumps({"decision": "block", "reason": "x31."})
        out = json.loads(_common.remind_japanese(block, {"hook_event_name": "Stop"}))
        self.assertTrue(out["reason"].endswith(_common.JA_REMINDER))

    def test_agents_prompts_and_plain_context_are_left_alone(self):
        self.assertEqual(
            _common.remind_japanese(self.DENY, {"hook_event_name": "PreToolUse", "agent_id": "a"}), self.DENY
        )
        prompt_block = json.dumps({"decision": "block", "reason": "x32."})
        self.assertEqual(_common.remind_japanese(prompt_block, {"hook_event_name": "UserPromptSubmit"}), prompt_block)
        context = json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": "x33"}})
        self.assertEqual(_common.remind_japanese(context, {"hook_event_name": "PostToolUse"}), context)


class ShellWriteCountsAsFix(unittest.TestCase):
    def test_heredoc_append_to_knowledge_counts(self):
        block = {"type": "tool_use", "name": "Bash", "input": {"command": "cat >> knowledge/x.md <<'EOF'\nline\nEOF"}}
        self.assertTrue(output.wrote_lesson([block]))

    def test_progress_only_write_does_not_count(self):
        block = {"type": "tool_use", "name": "Bash", "input": {"command": "sed -i 's/a/b/' memory/PROGRESS.md"}}
        self.assertFalse(output.wrote_lesson([block]))


class SkillCatalogueScope(unittest.TestCase):
    def test_home_directory_agents_skills_are_not_offered(self):
        home = os.path.expanduser("~")
        names = set(misread.skill_catalogue(home))
        self.assertNotIn("sdk", names)


class InputJournal(unittest.TestCase):
    def test_fired_decision_saves_redacted_input_and_others_do_not(self):
        import tempfile as _t

        old = jev_client.INPUTS
        setattr(jev_client, "INPUTS", _t.mkdtemp())  # noqa: B010 - pyright rejects assigning to a loaded module
        self.addCleanup(setattr, jev_client, "INPUTS", old)
        setattr(jev_client, "LAST_INPUT", {"state": {"msg": "token sk-abcdefghijklmnop here"}})  # noqa: B010
        import time as _time

        # today's date: a fixed one fell past INPUT_DAYS and save_input pruned its own folder
        today = _time.strftime("%Y-%m-%d")
        jev_client.save_input({"ts": today + "T20:00:00+0900", "hook": "relay-check", "session": "s1234567x"})
        day = os.path.join(jev_client.INPUTS, today)
        files = os.listdir(day)
        self.assertEqual(len(files), 1)
        with open(os.path.join(day, files[0]), encoding="utf-8") as fh:
            saved = fh.read()
        self.assertNotIn("sk-abcdefghijklmnop", saved)
        self.assertIn("[redacted]", saved)
        self.assertNotIn("allow", jev_client.FIRED)


class CostLineFile(unittest.TestCase):
    def test_the_saved_line_has_the_rules_output_format(self):
        meter = load("cost-meter")
        setattr(meter, "COST_LINES", os.path.join(TMP, "cost-meter"))  # noqa: B010 - see above
        rows = {"opus-5-5": {"usd": 24.694}, "fable-5-1": {"usd": 27.091}}
        s = {"usd": 65.98, "main": 51.77, "agents": 14.2, "delta": 0.44, "avg": 0.231, "context": 442_400}
        meter.save_cost_line("c-1", dict(s, fam="fable-5-1"), rows, 5, 15.886)
        with open(os.path.join(TMP, "cost-meter", "c-1.txt"), encoding="utf-8") as fh:
            self.assertEqual(
                fh.read(),
                "Cost: $65.98 | main $51.77 (fable-5-1 $27.09 now, opus-5-5 $24.69) | agents $14.20 | turn $0.44 "
                "| avg $0.23/req | context 442k | cold 5 = $15.89\n",
            )
        meter.save_cost_line("", dict(s, fam="fable-5-1"), rows, 0, 0.0)
        self.assertEqual(os.listdir(os.path.join(TMP, "cost-meter")), ["c-1.txt"])


if __name__ == "__main__":
    unittest.main()
