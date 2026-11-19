"""PreToolUse hook on Write/Edit, Jev first: a markdown record that speaks for the user - a feedback memory, a rules
file - is compared with the user's own recent prompts before it is written, so a lesson or rule never carries a
meaning, scope or wish the user did not give. Feedback .md files were being written with nothing
checking them, and some attributed to the user what they had never said.

Nouls: `dropped` (part of the user's correction is missing), `changed` (its meaning, scope or force is bent; restating
it in English is not a change), `added` (something is presented as the user's that they never said), `mixed` (the
session's own analysis inside a passage reporting the user). Feedback memories and rules/*.md edits are judged and
logged; nothing is refused while TIER is "log". Paths are matched
by name with either separator, so the hook works unchanged on Windows, Linux and macOS. Fail-open: a Jev error allows
the write. Every judged text is kept under logs/md-checks/ with its verdict."""

import datetime
import io
import json
import os
import re
import sys
from typing import cast

import _common
import jev_client

# Jev policy (no Jev question meets a block bar yet): "log" judges and records
# a would-be refusal as "would-deny"; "block" may refuse. The feedback-memory refusal is log.
TIER = "log"
THRESHOLD = 0.5
NEAR = 0.3
CHARS = 1500
DOC_CHARS = 12000
WINDOW = 20
STATE_CHARS = 24000  # Jev's ~32K-token limit; Japanese is near one token per character (see brief-check)
PEER = ("<cross-session-message", "Another Claude session sent")
KINDS = (
    (re.compile(r"[\\/]memory[\\/]+feedback-[^\\/]*\.md$"), "feedback-memory"),
    (re.compile(r"[\\/]rules[\\/][^\\/]+\.md$"), "rules"),
)
# Records are English (CLAUDE.md "Language"): the places only sessions read. outputs/ and docs/ are not here - what
# the user reads there is Japanese. A code check, not Jev.
ENGLISH = re.compile(
    r"[\\/]\.claude[\\/](knowledge|process|decisions|inbox|agents|skills|rules)[\\/].*\.md$"
    r"|[\\/]memory[\\/][^\\/]+\.md$",
    re.IGNORECASE,
)
# A Japanese document under ~/.claude/outputs is one written for the owner to read, and he cannot see ~/.claude from
# where he works: it goes to the project's dev
# working directory. The docs hub keeps its originals under outputs/docs-hub, which it publishes as a page.
DEV_DOCS = os.path.join(os.path.expanduser("~"), "dev", "<project>", "docs") + os.sep
FOR_OWNER = re.compile(r"[\\/]\.claude[\\/]outputs[\\/](?!docs-hub[\\/]).*\.md$", re.IGNORECASE)
JAPANESE = re.compile(r"[぀-ヿ一-鿿]")
LATIN = re.compile(r"[A-Za-z]")
JP_MIN, JP_SHARE = 200, 0.4  # quoted Japanese titles in an English inventory stay under both
QUESTIONS = {
    "dropped": (
        (
            "Does `document` (a lesson or rule written from what the user said) leave out part of what "
            "`user_recent_messages` corrected, asked for or objected to on this point?"
        ),
        {
            "true": "Part of the user's correction or wish on this point is missing from the document.",
            "false": "The document carries everything the user said on this point. Something the user asked to leave "
            "out, or called unrelated to it, is rightly absent and is not dropped.",
        },
    ),
    "changed": (
        (
            "Does `document` state the user's correction or wish with a different meaning, scope or force than "
            "`user_recent_messages` gave it?"
        ),
        {
            "true": "It softens, widens, narrows or bends what the user said, or aims it at something else.",
            "false": "It keeps the user's meaning, scope and force. Restating it in English or in other words is not a "
            "change.",
        },
    ),
    "added": (
        (
            "Does `document` attribute to the user a rule, wish, intent or decision that none of `user_recent_messages` "
            "expressed?"
        ),
        {
            "true": "Something is presented as the user's view or order that the user never said.",
            "false": "Everything presented as the user's comes from their messages; the session's own account of what it "
            "did wrong and how it will apply the lesson is not attributed to the user.",
        },
    ),
}
QUESTIONS["mixed"] = (
    (
        "Does `document` put the session's own analysis, findings or conclusions inside a passage that presents what the "
        "user said?"
    ),
    {
        "true": "A sentence reporting the user's words also carries claims the user never made - the session's diagnosis, "
        "extra examples, causes or consequences - so they read as the user's.",
        "false": "The passages that report the user contain only what the user said; the session's own account, if any, "
        "stands apart and is marked as the session's.",
    },
)
RECORDS = os.path.join(jev_client.ROOT, "logs", "md-checks")


def kind_of(path):
    return next((k for rx, k in KINDS if rx.search(path)), None)


def record(text, path, kind, decision, ps, session):
    now = datetime.datetime.now().astimezone()
    folder = os.path.join(RECORDS, now.strftime("%Y-%m-%d"))
    os.makedirs(folder, exist_ok=True)
    out_path = os.path.join(folder, "{}-{}-{}.md".format(now.strftime("%H%M%S"), (session or "nosession")[:8], kind))
    scores = ", ".join(f"{q} {float(v):.2f}" for q, v in sorted((ps or {}).items()))
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(
            "# md-check {} {}\n\n- file: {}\n- session: {}\n- verdict: {} ({})\n\n{}\n".format(
                now.strftime("%Y-%m-%d %H:%M:%S"), kind, path, session, decision, scores or "-", text
            )
        )


def main(payload):
    if payload.get("tool_name") not in ("Write", "Edit"):
        return None
    inp = payload.get("tool_input") or {}
    path = str(inp.get("file_path") or "")
    kind = kind_of(path)
    english = bool(ENGLISH.search(path))
    if FOR_OWNER.search(path):
        body = inp.get("content") if payload.get("tool_name") == "Write" else inp.get("new_string")
        body = body if isinstance(body, str) else ""
        jp, latin = len(JAPANESE.findall(body)), len(LATIN.findall(body))
        if jp > JP_MIN and jp / (jp + latin) > JP_SHARE:
            jev_client.log("md-check", None, "deny-place", 0, body, payload.get("cwd") or "", "place")
            return json.dumps(
                {
                    "hookSpecificOutput": {
                        "hookEventName": "PreToolUse",
                        "permissionDecision": "deny",
                        "permissionDecisionReason": (
                            "A document for the owner never goes under ~/.claude/outputs: he cannot see ~/.claude from "
                            "where he works. Write it in the project's dev working directory - "
                            f"{DEV_DOCS} for documents, research{os.sep} for datasets and "
                            "inventories - and name it to him by that full path."
                        ),
                    }
                }
            )
    if not kind and not english:
        return None
    if payload.get("tool_name") == "Write":
        text = inp.get("content")
    else:
        # An Edit is judged as the file it leaves behind: its new_string alone is only a fragment, and a deletion
        # (empty new_string) was read as 'everything dropped'.
        old, new = inp.get("old_string") or "", inp.get("new_string") or ""
        try:
            with open(path, encoding="utf-8") as fh:
                current = fh.read()
            text = current.replace(old, new) if inp.get("replace_all") else current.replace(old, new, 1)
        except OSError:
            text = new
    text = text if isinstance(text, str) else ""
    session = payload.get("session_id") or ""
    if english:
        jp, latin = len(JAPANESE.findall(text)), len(LATIN.findall(text))
        share = jp / (jp + latin) if jp + latin else 0.0
        if jp > JP_MIN and share > JP_SHARE:
            jev_client.log(
                "md-check", share, "deny-language", 0, text, payload.get("cwd") or "", "language", session=session
            )
            return json.dumps(
                {
                    "hookSpecificOutput": {
                        "hookEventName": "PreToolUse",
                        "permissionDecision": "deny",
                        "permissionDecisionReason": (
                            f"Records are English (CLAUDE.md Language): this file is {share:.0%} Japanese by letters. "
                            "Write it in English; Japanese stays in quoted titles and in-game terms, and in docs/."
                        ),
                    }
                }
            )
    if not kind:
        return None
    prompts = [
        t for r, t in jev_client.turns(payload.get("transcript_path") or "") if r == "user" and not t.startswith(PEER)
    ][-WINDOW:]
    recent = [t[-CHARS:] for t in prompts]
    while recent and sum(map(len, recent)) + len(text[:DOC_CHARS]) > STATE_CHARS:
        recent.pop(0)
    ps, ms = jev_client.timed_nouls({"user_recent_messages": recent, "document": text[:DOC_CHARS]}, QUESTIONS)
    if ps is None:
        jev_client.log("md-check", None, "error", ms, text, payload.get("cwd") or "", kind, session=session)
        record(text, path, kind, "error", None, session)
        return None
    ps = cast(dict[str, float], ps)  # every question here is a Noul; jev_client.nouls's return type also covers Choice
    p = max(ps.values())
    verdict = "deny" if p >= THRESHOLD else "near" if p >= NEAR else "allow"
    decision = verdict if TIER == "block" or verdict != "deny" else "would-deny"
    jev_client.log("md-check", p, decision, ms, text, payload.get("cwd") or "", kind, ps, session=session)
    record(text, path, kind, decision, ps, session)
    if decision != "deny":
        return None
    hits = ", ".join(jev_client.tag(q, v) for q, v in sorted(ps.items(), key=lambda x: -x[1]) if v >= THRESHOLD)
    return json.dumps(
        {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": (
                    f"Jev md check: this {kind} does not match what the user said ({hits}). Put back what was "
                    "dropped, keep the user's meaning and force, and attribute to the user only what they "
                    "said; your own account of the mistake is fine as long as it is not presented as "
                    "theirs."
                ),
            }
        }
    )


cast(io.TextIOWrapper, sys.stdin).reconfigure(encoding="utf-8")
_common.run("md-check.py", main)
