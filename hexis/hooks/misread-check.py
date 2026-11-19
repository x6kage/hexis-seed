"""UserPromptSubmit hook, Jev first: every user prompt and peer message is read by Jev before the model acts.
One call asks: `kind` (Choice: instruction / hold / question / correction / suggestion / approval / report),
`referent` (Choice: the last reply, a new topic, or one of this project's open items from PROGRESS.md, else STATE), `clear` (Noul: is the
referent unambiguous), `holds` (Noul: is any part of it a hold, whatever the kind) and `skill` (Choice: the one skill
the message needs, whose body is pushed into the context above SKILL_PUSH_AT). The reading is saved per session
for the other hooks. It is always injected, with a hint for a confident hold / correction / question / suggestion and
for a partial hold; below THRESHOLD on `clear` it also asks for the referent to be stated;
a peer message always gets a restatement demand. A user prompt also gets a one-line reading the reply must open with,
saved with the reading so output-check can verify it. A relayed hold read as 'file new work in Linear' forces a
Linear team rebuild, and an ordered instruction relayed from Hexis can be skipped.
Fail-open: no key, no network or a slow Jev injects nothing. Every call is logged to logs/jev-hooks.jsonl."""

import io
import json
import os
import re
import sys
from typing import cast

import _common
import jev_client

THRESHOLD = 0.12  # 0.5 fired on all 9 prompts of a test day (p 0.08-0.49); only the 0.08 one was genuinely ambiguous
CHARS = 1500
# A jev_client question is a Noul (instructions, criteria-or-None) or a Choice ("choice", instructions, {option: desc}).
QuestionSpec = tuple[str, dict[str, str] | None] | tuple[str, str, dict[str, str]]
# Definitions only, no examples: with the input read by the `kind` and `referent` Choices first, the boundary cases
# the examples used to draw are carried by those answers.
QUESTIONS: dict[str, QuestionSpec] = {
    "clear": (
        (
            "Does `new_user_message` refer unambiguously to exactly one topic, object or earlier item, so that it can be "
            "acted on without guessing what it refers to? Use `previous_user_message` and `last_assistant_message` only "
            "to resolve what it points at."
        ),
        {
            "true": "The message names what it is about, or the previous turns contain only one thing it could mean.",
            "false": "The message uses a pronoun or a vague pointer, or a bare one-word instruction, while the previous turns mention "
            "two or more things it could mean.",
        },
    ),
    # `kind` picks ONE kind, so a message that approves one thing and holds another read as approval and lost its
    # hold ('put Jev before commits ... but keep the ERG filing on hold' -> approval 0.85). The hold is
    # therefore asked on its own and drives hold-gate whatever the kind.
    "holds": (
        (
            "Does `new_user_message` put anything on hold - tell the assistant to stay, wait, not do something yet, or "
            "only confirm or check - even if it also approves or asks for other things?"
        ),
        {
            "true": "At least one part of the message says not to act on something yet.",
            "false": "Nothing in the message holds anything back.",
        },
    ),
}
HOLD_AT = 0.7
# The reading is the base every other Jev hook builds on: a call that took 3.4 s timed out at the old shared 3 s and
# left the prompt unread; a burst later showed spikes up to 6.5 s. Prompt latency is the price.
READ_TIMEOUT = 8.0


# Jev first: every user input is READ by Jev before the model acts - what kind of message it is
# and what it points at - and that typed reading is injected, so the model starts from a judgement it did not make
# itself. Hexis's misses were judgement misses, not generation ones: a wait taken as an order, a 'just confirm'
# taken as a go, a correction that was never written down.
KIND: QuestionSpec = (
    "choice",
    "What kind of message is `new_user_message`, as addressed to the assistant?",
    {
        "instruction": "Tells the assistant to do something now.",
        "hold": "Tells the assistant to stop, wait, not act yet, or only confirm/check without acting.",
        "question": "Asks for information or an explanation; nothing is to be changed yet.",
        "correction": "Points out that the assistant got something wrong, missed something, or broke a rule.",
        "suggestion": "Offers a new idea or opinion that was not among the options just offered, and leaves the "
        "decision open.",
        "approval": "Answers or decides something `last_assistant_message` asked or offered - a yes, a pick among "
        "the offered options, or a go-ahead - also when phrased as a suggestion for one of the offered "
        "options.",
        "report": "Tells the assistant a fact or what the user did; asks for nothing.",
    },
)
HINTS = {
    "hold": "Act on nothing the hold covers; acknowledge and wait.",
    "correction": "Before anything else this turn: say what was wrong in one line, then change what it corrects "
    "(rule, knowledge, test, hook or code), or put it in inbox/ if it cannot be applied now. A STATE or "
    "PROGRESS line or a feedback memory is not the fix.",
    "question": "Answer it first; the user often phrases a direction as a question, so say what you will do.",
    "suggestion": "Give a verdict on it; act only where it is cheap to undo.",
}
MAX_OPEN = 25
STATE_KEY = re.compile(r"p\d+|open-\d+")
# A hint steers the turn, so it follows only a confident reading: a clarification read as 'correction' at 0.54 would
# have demanded a feedback memory for a lesson that did not exist. Same bar output-check uses.
MIN_HINT_CONF = 0.7
# Tier 2 of the skill push: the same call picks the one skill the message needs, and a confident
# pick puts the skill body into the context before the turn. Provisional until fitted on labelled prompts with a
# holdout in evals/jev (every pick is logged under `skill-route` for that).
SKILL_PUSH_AT = 0.6
SKILL_DESC = 200
CONTEXT_CAP = 9_500  # Claude Code keeps only 10,000 characters of a hook's additionalContext
PROJECT_SKILLS = (os.path.join(".claude", "skills"), os.path.join(".agents", "skills"))


def skill_catalogue(cwd):
    """{name: (description, SKILL.md path)} from ~/.claude/skills and the project's .claude/skills and .agents/skills;
    the first of a name wins and `synced` directories are skipped."""
    out = {}
    home = os.path.normcase(os.path.abspath(os.path.expanduser("~")))
    # a session opened in the home directory would otherwise offer Cursor/Codex's own ~/.agents/skills (an `sdk` skill
    # was pushed 12 times whenever the user wrote SDK)
    project = cwd if cwd and os.path.normcase(os.path.abspath(cwd)) != home else ""
    for root in (_common.SKILLS, *(os.path.join(project, r) for r in PROJECT_SKILLS if project)):
        try:
            dirs = sorted(os.listdir(root))
        except OSError:
            continue
        for d in dirs:
            path = os.path.join(root, d, "SKILL.md")
            if d == "synced" or not os.path.isfile(path):
                continue
            try:
                name, desc = _common.skill_meta(path)
            except Exception:  # noqa: BLE001, S112 - a SKILL.md that fails to parse is skipped, not fatal
                continue
            out.setdefault(name, (desc, path))
    return out


def skill_question(catalogue) -> QuestionSpec:
    options = {name: desc[:SKILL_DESC] for name, (desc, _) in catalogue.items()}
    options["none"] = "No listed skill applies."
    return ("choice", "Which one skill does `new_user_message` need?", options)


def skill_route(pick, catalogue, session, room):
    """(decision, text to append to the context) for Jev's skill pick; the push is marked in the skill-push state."""
    name, conf = pick
    if name not in catalogue:
        return "none", ""
    if name in _common.pushed_skills(session).get("main", []):
        return "already", f"Skill {name} is already in context."
    if conf >= SKILL_PUSH_AT:
        head = f"Skill {name} (Jev {conf:.2f}) applies to this message - follow it:"
        body = _common.skill_body(catalogue[name][1], max(0, min(_common.SKILL_CHARS, room - len(head) - 1)))
        if body and _common.mark_pushed(session, "main", name):
            return "push", head + "\n" + body
    return "suggest", f"Jev suggests skill {name} ({conf:.2f}); load it if it applies."


def referent_question(payload) -> QuestionSpec:
    """A Choice over what the message can point at: the last reply, a new topic, or one of the open items - PROGRESS.md
    `## Open` bullets keyed by their slug when the project has PROGRESS.md, else the open STATE pendings."""
    options = {
        "last_reply": "Something in `last_assistant_message`.",
        "new_topic": "A new topic not in the previous turns or the open items.",
    }
    try:
        with open(_common.progress_path(payload), encoding="utf-8") as fh:
            items = _common.progress_open(fh.read().splitlines())
        for n, (slug, text) in enumerate(items[:MAX_OPEN], 1):
            key = slug if slug and slug not in options else f"item-{n}"
            options[key] = text[:160]
        return ("choice", "Which one item does `new_user_message` refer to?", options)
    except Exception:  # noqa: BLE001, S110 - a missing or unreadable PROGRESS.md falls through to the STATE.md options
        pass
    try:
        with open(_common.state_path(payload), encoding="utf-8") as fh:
            records = _common.parse_state(fh.read().splitlines())
        for r in _common.open_pending(records)[:MAX_OPEN]:
            options[r["id"] or "open-{}".format(r["i"])] = r["text"][:160]
    except Exception:  # noqa: BLE001, S110 - a missing or unreadable STATE.md just leaves the fallback options as they are
        pass
    return ("choice", "Which one item does `new_user_message` refer to?", options)


def build_state(prompt, turns):
    if turns and turns[-1] == ("user", prompt):
        turns = turns[:-1]
    last_assistant = next((t for r, t in reversed(turns) if r == "assistant"), "")
    previous_user = next((t for r, t in reversed(turns) if r == "user"), "")
    return {
        "previous_user_message": previous_user[-CHARS:],
        "last_assistant_message": last_assistant[-CHARS:],
        "new_user_message": prompt[-CHARS:],
    }


def main(payload):
    prompt = (payload.get("prompt") or "").strip()
    # Task notifications and system reminders are machine output and are skipped.
    if not prompt or prompt.startswith(("<task-notification", "<system-reminder")):
        return None
    peer = prompt.startswith(("<cross-session-message", "Another Claude session sent"))
    source, cwd = ("peer" if peer else "user"), payload.get("cwd") or ""
    state = build_state(prompt, jev_client.turns(payload.get("transcript_path") or ""))
    questions: dict[str, QuestionSpec] = dict(QUESTIONS, kind=KIND, referent=referent_question(payload))
    catalogue = skill_catalogue(cwd)
    if catalogue:
        questions["skill"] = skill_question(catalogue)
    jev_client.TIMEOUT = READ_TIMEOUT
    ps, ms = jev_client.timed_nouls(state, questions)
    session = payload.get("session_id") or ""
    if ps is None:
        jev_client.log("misread-check", None, "error", ms, prompt, cwd, source, session=session)
        if not peer:  # keep one reading per prompt, or relay-check pairs every later prompt with the wrong reading
            jev_client.save_reading(session, {"kind": None, "error": True})
        return None
    p = cast(float, ps["clear"])  # a Noul, not a Choice
    fired = p < THRESHOLD
    jev_client.log("misread-check", p, "inject", ms, prompt, cwd, source, ps, session=session)
    kind, kconf = cast("list | None", ps.get("kind")) or ["?", 0]  # a Choice, not a Noul
    ref, rconf = cast("list | None", ps.get("referent")) or ["?", 0]  # a Choice, not a Noul
    hold = cast(float, ps.get("holds") or 0.0)  # a Noul, not a Choice
    ref_text = (
        ""
        if ref in ("last_reply", "new_topic")
        else cast("tuple[str, str, dict[str, str]]", questions["referent"])[2].get(ref, "")
    )
    # A PROGRESS slug is a machine handle and never reaches the user; a STATE id is shown as before.
    shown = ref if not ref_text or STATE_KEY.fullmatch(ref) else "an open item"
    skill, sconf = cast("list | None", ps.get("skill")) or ["none", 0]  # a Choice, not a Noul
    skill = skill if skill in catalogue else "none"
    msg = "Jev {} reading: kind={} ({:.2f}), refers to {} ({:.2f}){}, referent clear p={:.2f}{}.".format(
        jev_client.version(),
        kind,
        kconf,
        shown,
        rconf,
        (": " + ref_text[:100]) if ref_text else "",
        p,
        f", skill={skill} ({sconf:.2f})" if "skill" in questions else "",
    )
    if not peer:
        # The user sees the reading as the reply's first line, the way the cost line is its last: a hook's
        # `systemMessage` renders as a notice/warning on every client and read as an error.
        line = "Jev {} · {} {:.2f} · {} {:.2f} · clear {:.2f}{}".format(
            jev_client.version(),
            kind,
            kconf,
            shown,
            rconf,
            p,
            f" · {skill} {sconf:.2f}" if "skill" in questions else "",
        )
        jev_client.save_reading(
            session,
            {
                "kind": kind,
                "kind_conf": kconf,
                "referent": ref,
                "referent_conf": rconf,
                "clear": p,
                "hold": hold,
                "line": line,
            },
        )
        if not _common.band_visible(session):  # the band shows the line; nothing to copy then (not on a phone)
            msg = f"Open your reply with this line, verbatim: {line}\n" + msg
    if kind in HINTS and kconf >= MIN_HINT_CONF:
        msg += " " + HINTS[kind]
    if hold >= HOLD_AT and kind != "hold":
        # A reading, not a verdict: a request to look or check scored 0.78 here and the
        # old wording ("act on nothing it holds") stopped work the user never held.
        msg += (
            " Jev reads a possible hold ({}): if a part of this message holds something, name it and leave that part "
            "undone; if nothing is held, proceed."
        ).format(jev_client.tag("hold", hold))
    msg += jev_client.model_change_note()
    if peer:
        # A peer's request is restated whatever p is: skipping one is the failure, not ambiguity alone.
        msg += (
            " Peer message: before acting, restate in one line each thing it asks for, in the order it asks, and "
            "say which you will do now and which you will not."
        )
    elif fired:
        msg += (
            " The referent may be ambiguous: state in one line what you take it to refer to, and ask if unsure - "
            "especially before any action that is hard to undo or relayed to another session."
        )
    context = msg
    if "skill" in questions:
        decision, extra = skill_route([skill, sconf], catalogue, session, CONTEXT_CAP - len(msg) - 1)
        jev_client.log(
            "skill-route", sconf, decision, ms, prompt, cwd, source, {"skill": [skill, sconf]}, session=session
        )
        if extra and len(msg) + 1 + len(extra) <= CONTEXT_CAP:
            context += "\n" + extra
    # No `systemMessage`: the user sees the reading only as the reply's first line, which output-check enforces.
    return json.dumps({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": context}})


cast(io.TextIOWrapper, sys.stdin).reconfigure(encoding="utf-8")
_common.run("misread-check.py", main)
