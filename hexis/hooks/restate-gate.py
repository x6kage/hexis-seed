"""PreToolUse hook (Jev first): the first outward act of a turn (an edit, a shell write, a peer message) that answers a
short or pronoun-only prompt is stopped once until the reply has said in one line how the request was read - target,
scope, action - so the user can interrupt a wrong reading before anything leaves the session. Measured:
misread-check's ambiguity score did not predict the user's corrections (4.1 % flagged vs 3.6 %
base) and an offline output check failed its pre-registered bar; what caught wrong readings was that one line. One deny per user turn; any outward call after it passes. Every evaluation is
logged under "restate-gate" so the conditions can be re-fitted. Fail-open: a Jev error or a failed state write lets
the call through.

The resend escape closes when Jev read the prompt as a short instruction or correction with an unclear referent
(at low referent clarity a short instruction can be acted on against the wrong target even after the turn has
written "my reading is X" and resent the stopped call as certain).
Below CLEAR_FLOOR the model's own certainty opens nothing: every state-changing call of the turn is denied and the turn
has to end in a question to the user; the answer opens a new turn with its own reading."""

import json
import os
import re

import _common
import jev_client

# Jev policy: "prompt" stops a call once and lets the resend pass; "log" judges and records only.
TIER = "prompt"
# Acts that cannot be taken back: the only ones a misread still stops hard (every open point is
# asked, but asking never halts the rest of the work).
IRREVERSIBLE = re.compile(
    r"\bgit\s+(push|reset\s+--hard|clean|rebase)\b|(^|[;&|]\s*)(rm|del|rmdir)\s|Remove-Item|Clear-RecycleBin|"
    r"\bdelete-stack\b|\bterminate-instances\b|\bgh\s+(repo\s+delete|release\s+delete)\b",
    re.IGNORECASE,
)
# Referent clarity (misread-check's `clear` Noul, saved per prompt) under which an instruction or correction gets no
# resend escape for an irreversible act. Evidence: misreads acted on at 0.13 and 0.42; correct readings at 0.12 and 0.23 the same
# day, so clarity alone does not separate them and the user chose asking over guessing. Re-fit from the "ask" rows.
CLEAR_FLOOR = 0.5
UNCLEAR_KINDS = ("instruction", "correction")  # an approval or a question with a vague referent keeps the resend
# An agent's or workflow's result that shows an agent deciding on its own (an Opus 5.5 rebuild agent removed a
# window-drag gesture and a setting on its own reasoning although its brief kept everything built; its report said so, the main session moved on, the Fable audit flagged
# the drift, and the user asked why). Jev reads the report once per turn; at or above OWN_CHOICE_AT every
# state-changing call of that turn is denied, so the turn can only end in putting each such change to the user.
AGENT_RESULT = "<task-notification"
OWN_CHOICE_AT = 0.5  # uncalibrated; re-fit from the "own-choice" rows
REPORT_CHARS = 12000
OWN_CHOICE = {
    "own_choice": (
        (
            "Does `agent_report` show an agent (the one reporting, or the work it reviewed) making a change or a choice "
            "its brief did not give it: removing, renaming, replacing or dropping an existing behaviour, setting, "
            "feature or requirement, or settling a default or an open point by its own judgement instead of leaving "
            "it unbuilt as an open point for the user?"
        ),
        {
            "true": "The report names at least one such change or choice that was made, or flags one as drift.",
            "false": "Everything done was asked for; open points were left unbuilt and listed, or there were none.",
        },
    ),
}
STATE_DIR = os.path.join(jev_client.ROOT, "logs", "restate-gate")
# Prompt length below which a request counts as short. Over 1,260 misread-check user rows: 64.4 % of prompts
# are under 60 chars, 75.6 % under 80, 84.7 % under 120 (median 42). Replayed over 490 main-session
# turns, short AND an outward act came to 43.9 % of turns at 60, 54.9 % at 80, 61.6 % at 120 (31.8 / 40.0 / 45.3 %
# with no text before the act): 60 is the largest cut that keeps the worst case a minority of turns. 40 sits under
# the median and would exempt the typical short request.
SHORT = 60
THRESHOLD = 0.5  # restated at or above this; uncalibrated, re-fit from the logged rows
CHARS = 1500
OUTWARD_TOOLS = ("Edit", "Write", "MultiEdit", "NotebookEdit", "SendMessage")
SHELL_TOOLS = ("Bash", "PowerShell")
# stop-gate.py's WRITE, unchanged, so the measured shares hold for what ships: a file write from the shell. It does not
# see git commit/push, rm, mv or a script that writes.
WRITE = re.compile(
    r"Set-Content|Out-File|sed -i|\bcp\s|Copy-Item|\.write\(|\bopen\([^)]*['\"][wax]|>>?\s*(?!&|/dev/null|NUL\b|nul\b)\S",
    re.IGNORECASE,
)
# The shell acts WRITE does not see and this gate must: commits and pushes, deletions and moves. Added after the shares
# above were measured, so live firing runs a little higher than them.
SIDE_EFFECT = re.compile(
    r"\bgit\s+(commit|push|rm|mv|reset|checkout|rebase|merge)\b|(^|[;&|]\s*)(rm|mv|del|rmdir)\s|Remove-Item|Move-Item",
    re.IGNORECASE,
)
# A turn opened by these is not a user request: an agent's notice, a slash command, a peer session's message.
NOT_A_REQUEST = jev_client.SKIP_PREFIXES + ("<cross-session-message", "Another Claude session sent")
# A demonstrative standing in for the target; the lookaheads drop compounds that name nothing (それぞれ, あれば, このまま).
PRONOUN = re.compile(
    r"これ(?!から|まで)|それ(?!ぞれ|から|で|と|に)|あれ(?!ば)|こっち|あっち|そっち|向こう|この(?!まま|前|間|辺)"
    r"|その(?!まま|他|後|前|辺)|あの"
)
# A named target: a path, a quoted term, or an ASCII identifier or proper name of three characters or more.
NAMED = re.compile(r"[\\/]|[`'\"「」『』]|[A-Za-z0-9][A-Za-z0-9_.\-]{2,}")


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


def outward(name, inp):
    if name in OUTWARD_TOOLS:
        return True
    command = str((inp or {}).get("command") or "")
    return name in SHELL_TOOLS and bool(WRITE.search(command) or SIDE_EFFECT.search(command))


def this_turn(path):
    """(prompt that opened the turn, latest prompt, [assistant blocks], {tool_use_id: is_error}) for the running turn.
    A tool result is a user entry but starts no turn; a message the user sent mid-turn (queued_command) becomes the
    latest prompt without starting one."""
    rows = []
    try:
        with open(path, "rb") as fh:
            fh.seek(0, 2)
            size = fh.tell()
            fh.seek(max(0, size - jev_client.TAIL_BYTES))
            data = fh.read()
    except Exception:  # noqa: BLE001 - a missing or unreadable transcript just yields no turn
        return "", "", [], {}
    lines = data.split(b"\n")
    if len(data) < size:
        lines = lines[1:]
    for raw in lines:
        try:
            rows.append(json.loads(raw))
        except Exception:  # noqa: BLE001, S112 - a malformed transcript line is skipped, not fatal
            continue
    start, opened = None, ""
    for i, d in enumerate(rows):
        if not jev_client.opens_turn(d):
            continue
        content = (d.get("message") or {}).get("content")
        if isinstance(content, str) or (
            isinstance(content, list) and any(isinstance(b, dict) and b.get("type") == "text" for b in content)
        ):
            start, opened = i, jev_client._text(content).strip()
    if start is None:
        return "", "", [], {}
    prompt, blocks, results = opened, [], {}
    for d in rows[start + 1 :]:
        att = d.get("attachment") if d.get("type") == "attachment" else None
        if att and att.get("type") == "queued_command" and isinstance(att.get("prompt"), str):
            prompt = att["prompt"].strip()
        if d.get("isSidechain"):
            continue
        content = (d.get("message") or {}).get("content")
        if d.get("type") == "assistant":
            blocks += [b for b in content or [] if isinstance(b, dict)]
        elif d.get("type") == "user" and isinstance(content, list):
            for b in content:
                if isinstance(b, dict) and b.get("type") == "tool_result" and b.get("tool_use_id"):
                    results[b["tool_use_id"]] = bool(b.get("is_error"))
    return opened, prompt, blocks, results


def own_choice_gate(opened, prompt, tool, cwd, session):
    """Deny every outward call of a turn opened by an agent result that shows an agent's own decision. Jev is asked
    once per turn; its answer is kept under the turn's key so later calls of the same turn reuse it. Fail-open: a Jev
    error lets the call through and is logged."""
    key = _common.once_key("own-choice:" + opened)
    seen = _common.once_seen(STATE_DIR, session).get(key)
    if seen is None:
        ps, ms = jev_client.timed_nouls({"agent_report": opened[-REPORT_CHARS:]}, OWN_CHOICE)
        p = (ps or {}).get("own_choice")
        _common.once_mark(STATE_DIR, session, key, {"tool": tool, "own_choice": p})
    else:
        p, ms = seen.get("own_choice"), 0
    if not isinstance(p, (int, float)):
        jev_client.log("restate-gate", None, "own-choice-error", ms, prompt, cwd, tool, session=session)
        return None
    if p < OWN_CHOICE_AT:
        jev_client.log("restate-gate", p, "own-choice-clear", ms, prompt, cwd, tool, session=session)
        return None
    stop_key = _common.once_key("own-choice-stop:" + opened)
    if stop_key in _common.once_seen(STATE_DIR, session):
        jev_client.log("restate-gate", p, "own-choice-resend", 0, prompt, cwd, tool, session=session)
        return None
    _common.once_mark(STATE_DIR, session, stop_key, {"tool": tool})
    jev_client.log("restate-gate", p, "own-choice", ms, prompt, cwd, tool, session=session, flags=["own-choice"])
    return out(
        "Restate gate: the agent result that opened this turn shows an agent deciding on its own (Jev {}): a removal, "
        "rename, replaced or dropped behaviour or setting, or a default or open point it settled itself. "
        "Do not decide it for him: put each to him as a question in the reply, in plain text (what "
        "changed, which of his words or brief it departs from, keep or revert, your recommendation) - never an "
        "AskUserQuestion list - and do not build on it or relay it as done until he answers; everything that does not "
        "depend on it goes on. Then send the same call again.".format(jev_client.tag("own_choice", p))
    )


def main(payload):
    tool = payload.get("tool_name") or ""
    inp = payload.get("tool_input") or {}
    session = payload.get("session_id") or ""
    cwd = payload.get("cwd") or ""
    # Cheap exits first, unlogged: this hook sees every edit and shell call (about 11 per main turn, measured),
    # and a re-fit needs only the outward evaluations.
    if payload.get("agent_id") or not outward(tool, inp):
        return None
    opened, prompt, blocks, results = this_turn(payload.get("transcript_path") or "")
    if opened.startswith(AGENT_RESULT):
        # An AskUserQuestion the user answered in this turn is his answer to the items it asked (without this he
        # answers the items there and still has to type a separate go to unblock the turn).
        if any(
            b.get("type") == "tool_use" and b.get("name") == "AskUserQuestion" and results.get(b.get("id")) is False
            for b in blocks
        ):
            jev_client.log("restate-gate", None, "own-choice-answered", 0, prompt, cwd, tool, session=session)
            return None
        return own_choice_gate(opened, prompt, tool, cwd, session)
    if not opened or opened.startswith(NOT_A_REQUEST):
        jev_client.log("restate-gate", None, "not-a-request", 0, prompt, cwd, tool, session=session)
        return None
    # An outward call that already ran without error: the turn's first act is behind it. The pending call itself has
    # no result yet, and a denied one carries is_error.
    if any(
        b.get("type") == "tool_use" and results.get(b.get("id")) is False and outward(b.get("name"), b.get("input"))
        for b in blocks
    ):
        jev_client.log("restate-gate", None, "not-first", 0, prompt, cwd, tool, session=session)
        return None
    short = len(prompt) < SHORT
    if not short and not (PRONOUN.search(prompt) and not NAMED.search(prompt)):
        jev_client.log("restate-gate", None, "named", 0, prompt, cwd, tool, session=session)
        return None
    # No resend escape below CLEAR_FLOOR: the reading misread-check saved for this prompt says what
    # Jev took the request for; an unclear instruction or correction is asked about, and nothing of this turn changes
    # state until the user's answer opens a new turn.
    reading = (jev_client.recent_readings(session, 1) or [{}])[0]
    clarity = reading.get("clear")
    irreversible = tool in SHELL_TOOLS and bool(IRREVERSIBLE.search(str((inp or {}).get("command") or "")))
    if (
        irreversible
        and reading.get("kind") in UNCLEAR_KINDS
        and isinstance(clarity, (int, float))
        and clarity < CLEAR_FLOOR
    ):
        jev_client.log(
            "restate-gate",
            clarity,
            "ask",
            0,
            prompt,
            cwd,
            tool,
            session=session,
            flags=["short" if short else "pronoun", "unclear"],
        )
        return out(
            "Restate gate: this {} call cannot be taken back, and Jev read the request as a short {} whose referent is "
            "unclear (clarity {:.2f}, floor {}). Ask him in plain text which target he means - never an "
            "AskUserQuestion list - and leave this act undone; everything that does not depend on "
            "it goes on."
            "".format(tool, reading.get("kind"), clarity, CLEAR_FLOOR)
        )
    # One deny per user turn, named by the prompt that opened it (the hook gets no turn id).
    key = _common.once_key(opened)
    if key in _common.once_seen(STATE_DIR, session):
        jev_client.log("restate-gate", None, "resend", 0, prompt, cwd, tool, session=session)
        return None
    # A restating line in the reply no longer lets the act through: a restatement followed by the
    # act in the same turn is not a confirmation. The gate stops the first act once; the model either asks the user and
    # ends the turn, or resends the same call because its reading is certain. No Jev call is needed for that.
    p, ps, ms = None, None, 0
    flags = ["short" if short else "pronoun"]
    decision = "prompt"
    if TIER != "prompt" or not _common.once_mark(STATE_DIR, session, key, {"tool": tool, "ps": ps}):
        decision = "would-prompt"
    jev_client.log("restate-gate", p, decision, ms, prompt, cwd, tool, ps, session=session, flags=flags)
    if decision != "prompt":
        return None
    return out(
        "Restate gate: this {} call is the turn's first change or message, and the request was {}. If your reading "
        "is certain, state it in one line and send the same call again unchanged. If it is not, or the act would "
        "settle a point his words do not settle, do not decide it: ask him in plain text in the reply (the options and "
        "your recommendation) - never an AskUserQuestion list - leave that part undone, and go on with everything "
        "that does not depend on it (every open point is asked, and asking never halts the rest of "
        "the work).".format(tool, f"short ({len(prompt)} chars)" if short else "a pronoun with no named target")
    )


_common.run("restate-gate.py", main)
