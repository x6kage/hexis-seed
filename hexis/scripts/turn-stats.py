"""What a session's replies cost the reader and the bill: user messages (mid-turn ones included), the visible text
after each message split into mid-work narration (text followed by more tool calls in its turn) and the final reply
(the cost line apart), output tokens per API request by recorded effort, and the Jev hook decisions, so a
change to how the sessions work is measured instead of argued. The user's
"output" is the visible text.

A turn that has not finished (its last block is a tool call, as when this runs inside the session it measures) is
left out with its messages: counting it dragged the averages down on the night it was written.

usage: python turn-stats.py <transcript.jsonl> [--split HH:MM] [--tz 9]
  --split compares messages before and after a local time (e.g. when a hook went live) instead of by hour."""

import argparse
import json
import os
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone

LOG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs", "jev-hooks.jsonl")
NOT_USER = (
    "<task-notification",
    "<system-reminder",
    "<command-",
    "<local-command",
    "<cross-session-message",
    "Another Claude session sent",
)
COST = re.compile(r"^Cost:.*$", re.MULTILINE)


def rows(path):
    with open(path, "rb") as fh:
        data = fh.read()
    for raw in data.split(b"\n"):
        try:
            yield json.loads(raw)
        except Exception:  # noqa: BLE001, S112 - a malformed transcript line is skipped, not fatal
            continue


def human_text(d):
    """The text of a human message (a prompt entry or a mid-turn queued_command attachment), else None."""
    if d.get("type") == "attachment":
        a = d.get("attachment") or {}
        return a.get("prompt") if a.get("type") == "queued_command" and isinstance(a.get("prompt"), str) else None
    if d.get("type") != "user":
        return None
    c = (d.get("message") or {}).get("content")
    if isinstance(c, str):
        return c
    if isinstance(c, list) and any(isinstance(b, dict) and b.get("type") == "text" for b in c):
        return " ".join(b.get("text", "") for b in c if isinstance(b, dict) and b.get("type") == "text")
    return None


def parse(path):
    """Turns: {"msgs": [{"ts", "user"}], "blocks": [(msg index, "text"|"tool_use", text)]}; plus requests and session."""
    turns, requests, seen, session = [], [], set(), None
    for d in rows(path):
        if d.get("isSidechain"):
            continue
        session = session or d.get("sessionId")
        h = human_text(d)
        if h is not None and h.strip():
            if d.get("type") == "user" or not turns:  # a prompt starts a turn; a queued message joins the running one
                turns.append({"msgs": [], "blocks": []})
            turns[-1]["msgs"].append({"ts": d["timestamp"], "user": not h.startswith(NOT_USER)})
            continue
        if d.get("type") != "assistant" or not turns:
            continue
        m = d.get("message") or {}
        for b in m.get("content") or []:
            if isinstance(b, dict) and b.get("type") in ("text", "tool_use"):
                turns[-1]["blocks"].append((len(turns[-1]["msgs"]) - 1, b["type"], b.get("text") or ""))
        if m.get("id") not in seen:
            seen.add(m.get("id"))
            requests.append((d["timestamp"], d.get("effort") or "?", (m.get("usage") or {}).get("output_tokens") or 0))
    if turns and (not turns[-1]["blocks"] or turns[-1]["blocks"][-1][1] != "text"):
        turns.pop()  # unfinished
    return turns, requests, session


def per_message(turns):
    """One record per user message: ts, narration chars, final-reply chars (cost line apart), cost-line chars."""
    out = []
    for t in turns:
        last_tool = max([i for i, (_, k, _) in enumerate(t["blocks"]) if k == "tool_use"], default=-1)
        acc = [[0, 0, 0] for _ in t["msgs"]]
        for i, (mi, k, x) in enumerate(t["blocks"]):
            if k != "text" or mi < 0:
                continue
            if i < last_tool:
                acc[mi][0] += len(x)
            else:
                cost = sum(len(c) for c in COST.findall(x))
                acc[mi][1] += len(x) - cost
                acc[mi][2] += cost
        for m, (n, f, c) in zip(t["msgs"], acc, strict=False):
            if m["user"]:
                out.append({"ts": m["ts"], "narration": n, "final": f, "cost": c})
    return out


def summary(label, recs):
    if not recs:
        print(f"{label:22s}    0 messages")
        return
    vis = sorted(r["narration"] + r["final"] for r in recs)
    n = len(recs)
    print(
        f"{label:22s} {n:4d} msgs  visible/msg mean {sum(vis) / n:5.0f} median {vis[n // 2]:5d}  "
        f"narration {sum(r['narration'] for r in recs) / n:5.0f}  final {sum(r['final'] for r in recs) / n:5.0f}  "
        f"cost line {sum(r['cost'] for r in recs) / n:4.0f}"
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("transcript")
    ap.add_argument("--split", help="local HH:MM to compare before/after (the transcript's first day)")
    ap.add_argument("--tz", type=float, default=9)
    args = ap.parse_args()
    tz = timezone(timedelta(hours=args.tz))
    local = lambda ts: datetime.fromisoformat(ts).astimezone(tz)
    turns, requests, session = parse(args.transcript)
    recs = per_message(turns)
    if args.split and recs:
        hh, mm = map(int, args.split.split(":"))
        cut = local(recs[0]["ts"]).replace(hour=hh, minute=mm, second=0)
        summary("before " + args.split, [r for r in recs if local(r["ts"]) < cut])
        summary("after " + args.split, [r for r in recs if local(r["ts"]) >= cut])
    else:
        by_hour = defaultdict(list)
        for r in recs:
            by_hour[local(r["ts"]).strftime("%m-%d %H:00")].append(r)
        for hr in sorted(by_hour):
            summary(hr, by_hour[hr])
    out = defaultdict(lambda: [0, 0])
    for ts, eff, o in requests:
        k = (local(ts).strftime("%m-%d %H:00"), eff)
        out[k][0] += 1
        out[k][1] += o
    print("\nhour         effort  requests  output tok/req")
    for (hr, eff), (n, o) in sorted(out.items()):
        print(f"{hr}  {eff:6s}  {n:8d}  {o / n:14.0f}")
    decisions = defaultdict(int)
    try:
        with open(LOG, encoding="utf-8") as fh:
            for raw in fh:
                d = json.loads(raw)
                if d.get("session") == session:
                    decisions[(d.get("hook"), d.get("decision"))] += 1
    except Exception:  # noqa: BLE001, S110 - a missing or corrupt log just reports no decisions
        pass
    print("\nJev hook decisions:", dict(sorted(decisions.items())))


if __name__ == "__main__":
    main()
