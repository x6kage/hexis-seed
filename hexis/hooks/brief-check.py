"""PreToolUse hook on Agent, Workflow, start_session and SendMessage, Jev first: the brief handed to a subagent is compared with the user's own recent prompts
in the launching session, so a brief that drops, changes or adds to what the user asked is caught BEFORE an
implementer builds the wrong thing. Implementations often did not follow the user's instructions because nobody
checked the brief against them; briefs now travel inline (skills/hexis-linear/reference.md) so this hook can see them.

Nouls: `dropped` (a requirement the user gave for this work is missing), `changed` (a value, scope, name or wording
differs from the user's), `added` (the agent is to build something the user never asked for; procedure does not
count), `no_acceptance` (work with no condition for done), and for an Opus launch `opus_untriggered` (no
rules/agents.md trigger named). TIER = "log" never denies; the would-be decision is logged for calibration. Fail-open:
a Jev error allows the launch.

Every judged brief is also written to RECORDS as a markdown file (the brief .md is a record made
AFTER the check, not the carrier of the brief), so the record is exactly what was checked and handed to the agent."""

import datetime
import io
import json
import os
import sys
from typing import cast

import _common
import jev_client

# Jev policy (no Jev question meets a block bar yet): "log" judges and records a would-be refusal as "would-deny"; "block" may refuse.
TIER = "log"
THRESHOLD = 0.5  # uncalibrated; start from relay-check's bar
NEAR = 0.3
CHARS = 1500  # per user prompt
BRIEF_CHARS = 12000
# Wider than relay-check's six: a requirement is often given many prompts before the launch that carries it.
WINDOW = 20
# Jev takes at most ~32K tokens of state plus the longest question (TypeSafe docs as quoted by the karoukun_ai article); an oversized call errors and the hook then allows silently. Japanese runs near one token per character,
# so the state is capped in characters: the oldest prompts are dropped first.
STATE_CHARS = 24000
PEER = ("<cross-session-message", "Another Claude session sent")
FIDELITY = {
    "dropped": (
        (
            "Does `brief` leave out a requirement, constraint or correction that `user_recent_messages` gave for the work "
            "the brief is about?"
        ),
        {
            "true": "Something the user asked for in this work - a value, a behaviour, a name, a UI wording, an exclusion, "
            "a correction of an earlier attempt - is absent from the brief.",
            "false": "Every user requirement that bears on this task appears in the brief, or the user's messages give "
            "none for this task (they are about other work).",
        },
    ),
    "changed": (
        "Does `brief` state something the user specified in a different way from `user_recent_messages`?",
        {
            "true": "A value, scope, name, wording, order, priority or force differs from the user's own words.",
            "false": "Where the brief restates a user requirement it keeps its value, scope and force. Restating it in "
            "another language or in other words is not a change.",
        },
    ),
    "added": (
        "Does `brief` ask the agent to build or change behaviour that none of `user_recent_messages` asked for?",
        {
            "true": "The brief adds a feature, behaviour, file, UI element or scope the user never mentioned.",
            "false": "Everything the agent is to build traces back to the user's messages. Procedure does not count "
            "(build and test commands, report format, repo or tier constraints, 'do not delegate'), and a "
            "lookup or research task that builds nothing is false.",
        },
    ),
}
FORM = {
    "no_acceptance": (
        "Does `brief` give the agent work to do without saying how the result is judged done?",
        {
            "true": "No acceptance condition: no test to pass, expected output, value to reach or check to run.",
            "false": "It states how done is judged, or it is a lookup that simply returns an answer.",
        },
    ),
}
OPUS = {
    "opus_untriggered": (
        (
            "`model` is opus. Does `brief` fail to name why the task needs Opus: an unclear cause to debug, a design "
            "decision, a multi-file implementation, a security review, an audit, or a derivation from raw data?"
        ),
        {
            "true": "None of those triggers is named or evident from the task.",
            "false": "The brief names one of those triggers, or the task plainly is one.",
        },
    ),
}
PINNED_OPUS = ("implementer", "raw-analyst-max")
# A brief and its follow-up that both say "if it does not read, drop it and say why" ship rounds without a required
# item: `changed` sees the first brief but this hook only logs, and a follow-up by SendMessage was judged by nothing. `loosened` is asked on every
# route a brief travels (Agent, Workflow, a started session, a follow-up message) and stops a hit once, like
# relay-check; the same brief sent again passes.
LOOSE = {
    "loosened": (
        "Does `brief` let the worker leave out, skip or make optional something `user_recent_messages` asked for?",
        {
            "true": "A requirement the user gave becomes droppable at the worker's discretion: 'if it does not work, "
            "drop it and say why', 'optional', 'your call', 'or leave it out', 'try X, else skip it'.",
            "false": "Every user requirement the brief carries stays required. Choices among ways to meet a requirement, "
            "options the user offered, and conditions on things the user never asked for are not loosening.",
        },
    ),
}
START = "mcp__ccd_session__start_session"
ONCE_DIR = os.path.join(jev_client.ROOT, "logs", "brief-check")
RECORDS = os.path.join(jev_client.ROOT, "logs", "briefs")


def record(brief, kind, model, decision, ps, cwd, session):
    now = datetime.datetime.now().astimezone()
    folder = os.path.join(RECORDS, now.strftime("%Y-%m-%d"))
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, "{}-{}-{}.md".format(now.strftime("%H%M%S"), (session or "nosession")[:8], kind))
    scores = ", ".join(f"{q} {float(v):.2f}" for q, v in sorted((ps or {}).items()))
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(
            "# Brief {} {}\n\n- cwd: {}\n- session: {}\n- agent: {} / {}\n- brief-check: {} ({})\n\n{}\n".format(
                now.strftime("%Y-%m-%d %H:%M:%S"),
                kind,
                cwd,
                session,
                kind,
                model or "-",
                decision,
                scores or "-",
                brief,
            )
        )
    return path


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


def main(payload):
    tool = payload.get("tool_name")
    if tool not in ("Agent", "Workflow", "SendMessage", START):
        return None
    inp = payload.get("tool_input") or {}
    if tool == "SendMessage":
        brief = inp.get("message")
        brief = brief if isinstance(brief, str) else json.dumps(brief, ensure_ascii=False)
        kind, model = "message", ""
    elif tool == START:
        brief = "\n\n".join(str(inp.get(k) or "") for k in ("prompt", "background")).strip()
        kind, model = "session", inp.get("model") or ""
    elif tool == "Workflow":
        # A workflow's briefs live in its script (inline or a script file); without this they were never judged
        # (two workflow runs, zero brief-check rows). The whole script is the brief.
        brief = inp.get("script")
        if not brief and inp.get("scriptPath"):
            try:
                with open(inp["scriptPath"], encoding="utf-8") as fh:
                    brief = fh.read()
            except OSError:
                brief = ""
        brief = brief or json.dumps(inp, ensure_ascii=False)
        kind, model = "workflow", ""
    else:
        brief = inp.get("prompt")
        brief = brief if isinstance(brief, str) else json.dumps(brief, ensure_ascii=False)
        kind, model = inp.get("subagent_type") or "general-purpose", inp.get("model") or ""
    session = payload.get("session_id") or ""
    prompts = [
        t for r, t in jev_client.turns(payload.get("transcript_path") or "") if r == "user" and not t.startswith(PEER)
    ][-WINDOW:]
    if not brief:
        return None
    # A message is a follow-up brief or a peer note: only `loosened` is asked of it (relay-check judges the rest).
    questions = dict(LOOSE) if kind == "message" else dict(FIDELITY, **FORM, **LOOSE)
    if model == "opus" or kind in PINNED_OPUS:
        questions.update(OPUS)
    recent = [t[-CHARS:] for t in prompts]
    while recent and sum(map(len, recent)) + len(brief[:BRIEF_CHARS]) > STATE_CHARS:
        recent.pop(0)
    state = {"user_recent_messages": recent, "brief": brief[:BRIEF_CHARS], "model": model, "agent_type": kind}
    ps, ms = jev_client.timed_nouls(state, questions)
    source = "{}/{}".format(kind, model or "-")
    cwd = payload.get("cwd") or ""
    if ps is None:
        jev_client.log("brief-check", None, "error", ms, brief, cwd, source, session=session)
        if kind != "message":
            record(brief, kind, model, "error", None, cwd, session)
        return None
    ps = cast(dict[str, float], ps)  # every question here is a Noul; jev_client.nouls's return type also covers Choice
    loose = ps.get("loosened", 0.0)
    key = _common.once_key(brief)
    if loose >= THRESHOLD and key not in _common.once_seen(ONCE_DIR, session):
        stop = _common.once_mark(ONCE_DIR, session, key, {"ps": ps})
    else:
        stop = False
    p = max(ps.values())
    verdict = "deny" if p >= THRESHOLD else "near" if p >= NEAR else "allow"
    decision = "prompt" if stop else verdict if TIER == "block" or verdict != "deny" else "would-deny"
    jev_client.log("brief-check", p, decision, ms, brief, cwd, source, ps, session=session)
    if kind != "message":
        record(brief, kind, model, decision, ps, cwd, session)
    if stop:
        return out(
            f"Jev brief check ({jev_client.tag('loosened', loose)}): the brief lets the worker drop, skip or make "
            "optional something the user asked for. Only the user removes a requirement: state it as required, and "
            "if it cannot be met the worker stops and reports with the evidence. If nothing the user asked for is "
            "loosened, resend the same brief unchanged."
        )
    if decision != "deny":
        return None
    hits = ", ".join(f"{q} {v:.2f}" for q, v in sorted(ps.items(), key=lambda x: -x[1]) if v >= THRESHOLD)
    return out(
        f"Jev brief check: the brief does not match the user's own words (Jev {jev_client.version()}: {hits}). Compare it with what the user "
        "asked for this work: restore anything dropped, keep the user's values and wording, remove what the "
        "user never asked for, state how done is judged, and name the Opus trigger if it is an Opus launch. "
        "If a requirement comes from a ticket or file rather than the user, say so in the brief."
    )


cast(io.TextIOWrapper, sys.stdin).reconfigure(encoding="utf-8")
_common.run("brief-check.py", main)
