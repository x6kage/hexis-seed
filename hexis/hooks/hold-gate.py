"""PreToolUse hook (Jev first): when Jev read the user's latest input as a hold, every acting tool call is judged by
Jev against that hold before it runs, and a call that acts on what was held is stopped once; the identical call sent
again passes. The reading is the one misread-check saved for this session - no second reading - so the check costs
nothing while there is no hold. Read-only tools never reach this hook (see the matcher in settings.json). A 'wait until
I have deleted it' or a 'just confirm with Hexis' must not turn into writes. Fail-open: no
reading, no key, a Jev error or a failed state write lets the call through."""

import json
import os
from typing import cast

import _common
import jev_client

# Jev policy (no Jev question meets a block bar yet): "prompt" stops a call
# once with a confirm request and lets the identical resend pass; "log" judges and records only; "block" may refuse.
TIER = "prompt"
STATE_DIR = os.path.join(jev_client.ROOT, "logs", "hold-gate")
MIN_KIND_CONF = 0.7
THRESHOLD = 0.5
CHARS = 1500
PEER = ("<cross-session-message", "Another Claude session sent")
QUESTIONS = {
    "acts_on_hold": (
        (
            "`user_message` put something on hold (stop, wait, not yet, only confirm or check), possibly while approving "
            "other things. Does the tool call in `tool` and `tool_input` act on what was put on hold - not on the parts "
            "the message approved?"
        ),
        {
            "true": "It changes, sends, files, deletes, deploys, commits or starts the held thing, or tells another "
            "session to.",
            "false": "It only reads, checks, lists, or records notes and state, or it acts on something the hold does "
            "not cover.",
        },
    ),
}


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


STOP_TOOLS = ("TaskStop", "mcp__ccd_session_mgmt__stop_session")


def main(payload):
    # Stopping work is what a hold asks for, never a breach of it (a stop order read as a hold denied TaskStop).
    if payload.get("tool_name") in STOP_TOOLS:
        return None
    session = payload.get("session_id") or ""
    last = jev_client.recent_readings(session, 1)
    r = last[0] if last else {}
    # A message can approve one thing and hold another; its kind is then 'approval', so the separate `hold` answer
    # opens the gate as well.
    if not (
        (r.get("kind") == "hold" and (r.get("kind_conf") or 0) >= MIN_KIND_CONF)
        or (r.get("hold") or 0) >= MIN_KIND_CONF
    ):
        return None
    users = [
        t for r, t in jev_client.turns(payload.get("transcript_path") or "") if r == "user" and not t.startswith(PEER)
    ]
    if not users:
        return None
    tool = payload.get("tool_name") or ""
    raw_input = json.dumps(payload.get("tool_input") or {}, sort_keys=True, ensure_ascii=False)
    tool_input = json.dumps(payload.get("tool_input") or {}, ensure_ascii=False)[: 2 * CHARS]
    cwd = payload.get("cwd") or ""
    key = _common.once_key(tool + "\n" + raw_input)
    if key in _common.once_seen(STATE_DIR, session):
        jev_client.log("hold-gate", None, "resend", 0, tool_input, cwd, tool, session=session)
        return None
    state = {"user_message": users[-1][-CHARS:], "tool": tool, "tool_input": tool_input}
    ps, ms = jev_client.timed_nouls(state, QUESTIONS)
    if ps is None:
        jev_client.log("hold-gate", None, "error", ms, tool_input, cwd, tool, session=session)
        return None
    p = cast(float, ps["acts_on_hold"])  # a Noul, not a Choice
    decision = "prompt" if p >= THRESHOLD else "allow"
    if decision == "prompt" and (TIER != "prompt" or not _common.once_mark(STATE_DIR, session, key, {"ps": ps})):
        decision = "would-prompt"
    jev_client.log("hold-gate", p, decision, ms, tool_input, cwd, tool, ps, session=session)
    if decision != "prompt":
        return None
    return out(
        "Jev hold gate: the user's latest message holds something back (kind {} {:.2f}, hold {:.2f}) and this "
        "{} call may act on what it holds ({}). If it does, acknowledge and wait or ask the user; if it does not, "
        "send the same call again unchanged to run it.".format(
            r.get("kind"), r.get("kind_conf") or 0, r.get("hold") or 0, tool, jev_client.tag("acts_on_hold", p)
        )
    )


_common.run("hold-gate.py", main)
