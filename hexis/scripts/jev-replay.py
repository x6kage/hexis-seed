"""Replay logged Jev hook decisions under the CURRENT hook code - questions, thresholds and state building - so a change
is judged on the same inputs as the decisions it would replace (keel-style replayable cases). The
calibration log keeps no text, so each case is rebuilt from its session transcript, cut at the
logged time.

  python scripts/jev-replay.py [--hook output-check] [--session 4e3c6702] [--decision block,near]
                               [--since YYYY-MM-DD] [--limit 20]

Replays output-check, brief-check, relay-check, misread-check and md-check (commit-gate and hold-gate depend on git or saved
readings of that moment and are skipped). Results go to logs/jev-replay.jsonl; the real calibration log, the Stop-hook
block counters and the brief records are never touched. Calls the real Jev. output-check reads the session's CURRENT
saved reading, not the one it had then - the `kind`-dependent checks can differ for that reason alone."""

import argparse
import atexit
import datetime
import glob
import importlib.util
import io
import json
import os
import shutil
import sys
import tempfile
from typing import cast

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOOKS = os.path.join(ROOT, "hooks")
sys.path.insert(0, HOOKS)
import _common
import jev_client

TMP = tempfile.mkdtemp(prefix="jev-replay-")
# The transcript cuts are copies of whole sessions (one run left 2.6 GB); left behind they fill the disk.
atexit.register(shutil.rmtree, TMP, True)
REPLAY_LOG = os.path.join(ROOT, "logs", "jev-replay.jsonl")
SLACK = datetime.timedelta(seconds=2)  # a hook runs just after the entries it judges are written
UTC = datetime.UTC


def load(name):
    run, _common.run = _common.run, lambda n, f: None
    stdin, sys.stdin = sys.stdin, io.TextIOWrapper(io.BytesIO())
    try:
        spec = importlib.util.spec_from_file_location(name.replace("-", "_"), os.path.join(HOOKS, name + ".py"))
        assert spec and spec.loader
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    finally:
        _common.run, sys.stdin = run, stdin


def when(ts):
    return datetime.datetime.fromisoformat(ts).astimezone(UTC)


def transcript_of(session):
    hits = glob.glob(os.path.join(ROOT, "projects", "**", session + ".jsonl"), recursive=True)
    return hits[0] if hits else None


def cut(path, until):
    """The transcript as it stood at `until`: every line up to the first one stamped later."""
    out = os.path.join(TMP, f"cut-{len(os.listdir(TMP))}.jsonl")
    with open(path, encoding="utf-8", errors="replace") as src, open(out, "w", encoding="utf-8") as dst:
        for line in src:
            try:
                ts = json.loads(line).get("timestamp")
            except ValueError:
                ts = None
            if ts and when(ts) > until:
                break
            dst.write(line)
    return out


def last_tool_input(path, tool):
    found = None
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if f'"{tool}"' not in line:
                continue
            try:
                d = json.loads(line)
            except ValueError:
                continue
            for b in (d.get("message") or {}).get("content") or []:
                if isinstance(b, dict) and b.get("type") == "tool_use" and b.get("name") == tool:
                    found = b.get("input") or {}
    return found


mod_kind = lambda path: None


def payload_for(hook, row, path):
    base = {"session_id": row["session"], "transcript_path": path, "cwd": row.get("cwd") or ""}
    if hook == "output-check":
        return base
    if hook in ("brief-check", "relay-check"):
        tool = "Agent" if hook == "brief-check" else "SendMessage"
        inp = last_tool_input(path, tool)
        return inp is not None and dict(base, tool_name=tool, tool_input=inp)
    if hook == "md-check":
        # the last Write/Edit of a checked .md in the cut transcript (a denied call is still recorded as a tool_use);
        # an Edit is applied to the file as it is NOW, so a replay approximates the file it would have left behind
        for tool in ("Edit", "Write"):
            inp = last_tool_input(path, tool)
            if inp and mod_kind(inp.get("file_path") or ""):
                return dict(base, tool_name=tool, tool_input=inp)
        return None
    if hook == "misread-check":
        users = [t for r, t in jev_client.turns(path) if r == "user"]
        # a replay id, so the reading this saves never lands in the live session's readings
        return users and dict(base, prompt=users[-1], session_id="replay-" + row["session"][:8])
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hook", default="output-check")
    ap.add_argument("--session", default="")
    ap.add_argument("--decision", default="")
    ap.add_argument("--since", default="")
    ap.add_argument("--limit", type=int, default=20)
    ap.add_argument("--model", default="", help="decide under this Jev version instead of the pinned one")
    a = ap.parse_args()
    cast(io.TextIOWrapper, sys.stdout).reconfigure(encoding="utf-8")
    mod = load(a.hook)
    if a.model:
        jev_client.MODEL = a.model
    jev_client.LOG = REPLAY_LOG
    if a.hook == "output-check":
        setattr(mod, "STOPS", os.path.join(TMP, "stops"))  # noqa: B010 - mod is a dynamically loaded module; pyright rejects direct attribute assignment on ModuleType
    if a.hook == "brief-check":
        setattr(mod, "RECORDS", os.path.join(TMP, "briefs"))  # noqa: B010 - see above
    if a.hook == "md-check":
        setattr(mod, "RECORDS", os.path.join(TMP, "md-checks"))  # noqa: B010 - see above
        global mod_kind
        mod_kind = lambda path: mod.kind_of(path)
    wanted = set(filter(None, a.decision.split(",")))
    with open(os.path.join(ROOT, "logs", "jev-hooks.jsonl"), encoding="utf-8") as fh:
        rows = [json.loads(l) for l in fh if l.strip()]
    rows = [
        r
        for r in rows
        if r.get("hook") == a.hook
        and r.get("session", "").startswith(a.session)
        and (not wanted or r.get("decision") in wanted)
        and r.get("ts", "") >= a.since
    ][-a.limit :]
    print(f"replaying {len(rows)} {a.hook} decisions; results in {REPLAY_LOG}")
    for row in rows:
        src = transcript_of(row.get("session") or "")
        if not src:
            print(row["ts"], "no transcript for session", row.get("session"))
            continue
        path = cut(src, when(row["ts"]) + SLACK)
        payload = payload_for(a.hook, row, path)
        if not payload:
            print(row["ts"], "nothing to replay (no matching input in the cut transcript)")
            continue
        size = os.path.getsize(REPLAY_LOG) if os.path.exists(REPLAY_LOG) else 0
        if hasattr(mod, "STATE_DIR"):
            # a fresh deny-once state per row: a replay never reads or marks the live session's state
            setattr(mod, "STATE_DIR", tempfile.mkdtemp(dir=TMP))  # noqa: B010 - see above
        mod.main(payload)
        new = None
        if os.path.exists(REPLAY_LOG) and os.path.getsize(REPLAY_LOG) > size:
            with open(REPLAY_LOG, encoding="utf-8") as fh:
                fh.seek(size)
                new = json.loads(fh.read().splitlines()[-1])
        over = lambda ps: (
            ",".join(sorted(k for k, v in (ps or {}).items() if isinstance(v, (int, float)) and v >= 0.5)) or "-"
        )
        old_p = row.get("p")
        print(
            "{}  {:>10s} {:>5} [{}]  ->  {:>10s} {:>5} [{}]".format(
                row["ts"][5:19],
                str(row.get("decision")),
                "-" if old_p is None else f"{float(old_p):.2f}",
                over(row.get("ps")),
                str(new and new.get("decision")),
                "-" if not new or new.get("p") is None else "{:.2f}".format(float(new["p"])),
                over(new and new.get("ps")),
            )
        )


if __name__ == "__main__":
    main()
