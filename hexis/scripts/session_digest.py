"""Digest of a predecessor session for the session that takes its work over: every message the user typed, in order,
with its time, and the head of the reply that closed that turn. PROGRESS and HANDOFF files carry conclusions; the
reasons, holds and preferences the user stated in the chat live only in the transcript, so a successor reads this
(a moved session did not know why commits were on hold). Read on demand, never saved into
memory or a record: it carries the user's sentences verbatim, which records must not (rules/context.md).

  python ~/.claude/scripts/session_digest.py <transcript.jsonl> [--out file.md] [--reply-chars 400]"""

import argparse
import datetime
import io
import json
import sys
from typing import cast

SKIP = ("<command-", "<local-command", "<task-notification", "<system-reminder", "Stop hook feedback", "Caveat:")
PEER = "<cross-session-message"


def local(ts):
    try:
        return datetime.datetime.fromisoformat(ts).astimezone().strftime("%Y-%m-%d %H:%M")
    except (TypeError, ValueError):
        return "?"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("transcript")
    ap.add_argument("--out", default="")
    ap.add_argument("--reply-chars", type=int, default=400)
    a = ap.parse_args()
    cast(io.TextIOWrapper, sys.stdout).reconfigure(encoding="utf-8")
    turns, cur = [], None
    with open(a.transcript, encoding="utf-8") as fh:
        for line in fh:
            try:
                d = json.loads(line)
            except ValueError:
                continue
            if d.get("isSidechain"):
                continue
            m = d.get("message") or {}
            content = m.get("content")
            if d.get("type") == "user" and isinstance(content, str):
                text = content.strip()
                if not text or text.startswith(SKIP):
                    continue
                who = "peer" if text.startswith(PEER) else "user"
                cur = {"ts": local(d.get("timestamp")), "who": who, "text": text, "reply": ""}
                turns.append(cur)
            elif d.get("type") == "assistant" and cur is not None:
                for c in content if isinstance(content, list) else []:
                    if isinstance(c, dict) and c.get("type") == "text" and c.get("text", "").strip():
                        cur["reply"] = c["text"].strip()
    out = [
        f"# Digest of {a.transcript}",
        "",
        f"{len(turns)} turns; user messages verbatim, replies cut to {a.reply_chars} chars.",
        "",
    ]
    for t in turns:
        body = t["text"] if t["who"] == "user" else t["text"][:600]
        out.append(f"## {t['ts']} {t['who']}")
        out.append(body)
        if t["reply"]:
            reply = t["reply"].split("\nCost:")[0].strip()
            out.append("> " + reply[: a.reply_chars].replace("\n", "\n> "))
        out.append("")
    text = "\n".join(out)
    if a.out:
        with open(a.out, "w", encoding="utf-8") as fh:
            fh.write(text)
        print(f"{len(turns)} turns, {len(text):,} chars -> {a.out}")
    else:
        print(text)


main()
