"""PreToolUse hook on SendMessage, Jev first. Every outgoing peer message is compared with the user's last
six prompts AND Jev's own reading of them (kind: instruction / hold / question / ..., saved per session by
misread-check), so a hold the user gave is known as a hold before the relay is judged. Two Nouls: `claims_user` (it
speaks for the user) is the trigger; `hold_to_go` and `added` are retired. A message that
speaks for the user is stopped once with a confirm request; any resend to the same recipient in the same user turn
passes unjudged, so a reworded relay cannot loop. A "don't execute yet" relayed as "file new work in Linear", or a
"just confirm with Hexis" relayed as "filing: you do it", costs a Linear team rebuild. Fail-open: a Jev error or a failed state write allows the send."""

import io
import json
import os
import re
import sys
from typing import cast

import _common
import jev_client

# Jev policy (no Jev question meets a block bar yet): "prompt" stops a message
# once with a confirm request and lets the resend pass; "log" judges and records only; "block" may refuse. `added` is
# no longer asked (4 right against 10 wrong blocks on the labelled set); `hold_to_go` is retired.
TIER = "prompt"
THRESHOLD = 0.59  # calibration ruling: holdout precision 0.88, recall 1.0 (n 28); provisional, re-fit after 50 ground-truth labels
NEAR = 0.3  # logged as "near" for calibration; the send is allowed
CHARS = 1000
# The user's last WINDOW prompts, peer messages excluded. Three was too few: when the user sends several
# messages mid-turn, the decision a relay carried falls out of the window and a faithful relay is denied (added 0.93).
WINDOW = 6
PEER = ("<cross-session-message", "Another Claude session sent")
STATE_DIR = os.path.join(jev_client.ROOT, "logs", "relay-check")
# Definitions only: the user's hold is supplied as Jev's reading (`user_recent_readings`), not re-derived from examples.
QUESTIONS = {
    "claims_user": (
        (
            "Does `outgoing_message` present something as the user's own wish, order or decision (the user wants, the "
            "user said, a user order, the owner decided)?"
        ),
        {
            "true": "It passes on, or claims to pass on, what the user wants or decided.",
            "false": "It is the sender's own report, question, reply or coordination; it speaks for no user wish.",
        },
    ),
}
# `hold_to_go` retired (calibration ruling): 0 true of 71 artefact-labelled fires. `added` retired the same day
# (6 true of 65, precision 0.09).


def out(reason):
    return json.dumps(
        {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": reason,
            }
        }
    )


OWN_AGENT = re.compile(r"a[0-9a-f]{16}")


def main(payload):
    if payload.get("tool_name") != "SendMessage":
        return None
    inp = payload.get("tool_input") or {}
    # A message to one of this session's own background agents (addressed by its agent id) is the session's brief,
    # not a relay of the user to a peer; brief-check judged that brief at launch.
    to = str(inp.get("to") or "")
    if OWN_AGENT.fullmatch(to):
        return None
    message = inp.get("message")
    message = message if isinstance(message, str) else json.dumps(message, ensure_ascii=False)
    session = payload.get("session_id") or ""
    cwd = payload.get("cwd") or ""
    prompts = [
        t for r, t in jev_client.turns(payload.get("transcript_path") or "") if r == "user" and not t.startswith(PEER)
    ][-WINDOW:]
    # One prompt per recipient per user turn; the user turn is named by its prompt (the hook gets no turn id).
    key = _common.once_key(to + "\n" + (prompts[-1] if prompts else ""))
    if key in _common.once_seen(STATE_DIR, session):
        jev_client.log("relay-check", None, "resend", 0, message, cwd, to, session=session)
        return None
    readings = [r.get("kind") for r in jev_client.recent_readings(session, len(prompts))]
    state = {
        "user_recent_messages": [t[-CHARS:] for t in prompts],
        "user_recent_readings": readings,
        "outgoing_message": message[: 2 * CHARS],
    }
    ps, ms = jev_client.timed_nouls(state, QUESTIONS)
    if ps is None:
        jev_client.log("relay-check", None, "error", ms, message, cwd, to, session=session)
        return None
    ps = cast(dict[str, float], ps)  # every question here is a Noul; jev_client.nouls's return type also covers Choice
    p = ps["claims_user"]
    decision = "prompt" if p >= THRESHOLD else "near" if p >= NEAR else "allow"
    if decision == "prompt" and (TIER != "prompt" or not _common.once_mark(STATE_DIR, session, key, {"ps": ps})):
        decision = "would-prompt"
    jev_client.log("relay-check", p, decision, ms, message, cwd, to, ps, session=session)
    if decision != "prompt":
        return None
    return out(
        "Relay check ({}): this message speaks for the user. Check that it matches what they said, in your own "
        "words, then resend it unchanged to send.".format(jev_client.tag("claims_user", p))
    )


cast(io.TextIOWrapper, sys.stdin).reconfigure(encoding="utf-8")
_common.run("relay-check.py", main)
