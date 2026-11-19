"""SessionStart hook. Injects the project's PROGRESS.md whole plus the inbox/ entries when PROGRESS.md exists; otherwise
bounds the project's STATE.md and injects its tail, its open pending items and its un-graduated decisions. Then the
knowledge line and as much of the cross-project STATE tail as still fits under CAP.
Claude Code keeps only 10,000 characters of a hook's additionalContext and puts the rest in a file behind a 2 KB
preview; an injection of 27-48k characters left sessions with the preview only, and the open items and decisions
never reached the model. So the project's own state goes first, the total
stays under CAP, and anything that still does not fit is cut with a notice to the model and to the user."""

import base64
import datetime
import json
import os
import subprocess
import sys
import time

import _common

LIMIT, KEEP, TAIL, BLOCK, GTAIL = 400, 200, 60, 40, 20
MANY_OPEN, MANY_DECISIONS, LONG = 15, 20, 300
PROGRESS_LONG = 80
PROGRESS_CHARS = 6_500  # leaves room under CAP for OWNER.md, the instructions and the inbox
OWNER_CHARS = 1_500
CAP = 9_500
TAILS = (60, 40, 25, 15, 8)
SWEEP = os.path.join(_common.ROOT, "scripts", "sweep.py")
SWEEP_STAMP = os.path.join(_common.ROOT, "logs", "sweep", "last-start")
SWEEP_EVERY = 24 * 3600
# The hook's job refuses CREATE_BREAKAWAY_FROM_JOB (Access is denied), so a pwsh without a console window
# (CREATE_NO_WINDOW) asks WMI to create the sweep, hidden through cmd.exe, outside the job.
SWEEP_WMI = (
    "$si = New-CimInstance -ClassName Win32_ProcessStartup -ClientOnly -Property @{{ ShowWindow = [uint16]0 }}; "
    "Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{{ CommandLine = '{cmd}'; "
    "CurrentDirectory = '{cwd}'; ProcessStartupInformation = $si }} | Out-Null"
)


def archive(path, lines, cut):
    with open(os.path.join(os.path.dirname(path), "STATE-archive.md"), "a", encoding="utf-8") as fh:
        fh.write("\n".join(lines[:cut]) + "\n")
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(lines[cut:]) + "\n")


def block(label, lines, records):
    if not records:
        return ""
    out = "\n" + label + ":\n" + "\n".join(lines[r["i"]] for r in records[:BLOCK])
    return out + (f"\n... {len(records) - BLOCK} more" if len(records) > BLOCK else "")


def start_sweep():
    """scripts/sweep.py at most once per SWEEP_EVERY, hidden and out of the job; never delays or fails the hook.
    Windows only: sweep.py assumes the Windows temp layout and the start goes through pwsh and WMI."""
    if os.name != "nt":
        return
    try:
        if os.path.exists(SWEEP_STAMP) and time.time() - os.path.getmtime(SWEEP_STAMP) < SWEEP_EVERY:
            return
        os.makedirs(os.path.dirname(SWEEP_STAMP), exist_ok=True)
        with open(SWEEP_STAMP, "w", encoding="utf-8") as fh:
            fh.write(datetime.datetime.now().astimezone().isoformat(timespec="seconds") + "\n")
        script = SWEEP_WMI.format(cmd=f'cmd.exe /c ""{sys.executable}" -I "{SWEEP}""', cwd=_common.ROOT)
        subprocess.Popen(
            [
                "pwsh.exe",
                "-NoProfile",
                "-NonInteractive",
                "-EncodedCommand",
                base64.b64encode(script.encode("utf-16-le")).decode(),
            ],
            cwd=_common.ROOT,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except Exception as exc:  # noqa: BLE001 - a failed start is logged, the session start goes on
        try:
            with open(SWEEP_STAMP + ".error", "a", encoding="utf-8") as fh:
                fh.write(f"{datetime.datetime.now().astimezone().isoformat(timespec='seconds')} {exc!r}\n")
        except Exception:  # noqa: BLE001, S110 - the error note itself must not raise
            pass


def main(payload):
    start_sweep()
    if payload.get("source") == "compact":  # skills pushed before a compaction are pushed again after it
        _common.clear_pushed(payload.get("session_id") or "")
    state = _common.state_path(payload)
    lines = None
    if state and os.path.exists(state):
        with open(state, encoding="utf-8") as fh:
            lines = fh.read().splitlines()
    progress = _common.progress_path(payload)
    if progress and os.path.exists(progress):
        core, source = progress_block(progress, state), progress
    elif lines is None:
        core, source = (
            (
                f"This project has no {state or 'memory/STATE.md'} yet, so nothing from earlier work is "
                "recorded: verify every detail against the filesystem before stating or acting on it, and "
                "start recording there now."
            ),
            None,
        )
    else:
        core, source = state_block(state, lines), state
    return out(fit(owner_block(_common.owner_path(payload)) + core, source))


def owner_block(owner):
    """OWNER.md goes first: owner decisions ignored this month all sat in files no session was routed to."""
    if not owner:
        return ""
    head = (
        f"Owner decisions and owner facts for this project ({owner}): they come before anything below. Append a new "
        "one the moment the user states it - restated in English, never quoted - and keep the file under "
        f"{OWNER_CHARS} characters by merging, not adding.\n"
    )
    if not os.path.exists(owner):
        return head.replace(": they come before anything below.", " does not exist yet; create it with the first one.")
    with open(owner, encoding="utf-8") as fh:
        text = fh.read().strip()
    if len(text) > OWNER_CHARS:
        text = text[:OWNER_CHARS] + f"\n... cut at {OWNER_CHARS} characters: read {owner} whole and merge it down."
    return head + text + "\n\n"


def progress_block(progress, state):
    with open(progress, encoding="utf-8") as fh:
        plines = fh.read().splitlines()
    msg = (
        "Continue from this project's PROGRESS.md below, not from recollection or from a compaction summary; "
        "anything not in it must be re-read from the filesystem before you state or act on it. Rewrite "
        f"{progress} (Now, Open, Next, and the Updated line from the machine clock) whenever the state changes. "
        "Bracketed slugs in Open are handles for hooks and are never shown to the user. Decisions and lessons "
        "are applied directly to knowledge/, decisions/ or the rules; a finding that cannot be applied yet goes "
        "to ~/.claude/inbox/ as YYYY-MM-DD-<topic>.md with an `expires: YYYY-MM-DD` first line. "
        f"{state or 'memory/STATE.md'} is frozen history: read it only when a detail is needed, never append "
        "to it.\n" + "\n".join(plines)
    )
    size = sum(len(l) + 1 for l in plines)
    if len(plines) > PROGRESS_LONG or size > PROGRESS_CHARS:
        msg = (
            f"PROGRESS.md has {len(plines)} lines and {size} characters (limit {PROGRESS_LONG} lines, "
            f"{PROGRESS_CHARS} characters): cut it to the current state - move what is settled into knowledge/, "
            "decisions/ or the rules.\n" + msg
        )
    entries = _common.inbox_entries(datetime.datetime.now().astimezone().date().isoformat())
    if entries:
        msg += "\nInbox (~/.claude/inbox/) - consolidate into knowledge/ or drop, then delete:\n" + "\n".join(
            f"- {name} expires {exp}" + (" EXPIRED" if expired else "") if exp else f"- {name} no expires line"
            for name, exp, expired in entries
        )
    return msg


def state_block(state, lines):
    records = _common.parse_state(lines)
    through = _common.graduated_through(records)
    opens = _common.open_pending(records)
    if len(lines) > LIMIT:
        cut = min(_common.graduated_prefix(records, through, opens), len(lines) - KEEP)
        if cut > 0:
            archive(state, lines, cut)
            lines = lines[cut:]
            records = _common.parse_state(lines)
            opens = _common.open_pending(records)
    decisions = [r for r in records if r["kind"] == "decision" and (not through or r["stamp"] > through)]
    msg = ""
    for tail in TAILS:  # the longest tail that keeps the block under CAP; open items and decisions come with it
        start = max(0, len(lines) - tail)
        msg = (
            "Continue from this project's STATE.md below, not from recollection or from a compaction summary. "
            "These are the recorded facts, decisions, paths and pending items; anything not in them must be "
            f"re-read from the filesystem before you state or act on it. Keep appending to {state}, next id: "
            f"{_common.next_pending_id(records)}."
            "\nRecent:\n" + "\n".join(lines[start:])
        )
        msg += block("Open", lines, [r for r in opens if r["i"] < start])
        msg += block("Decisions since graduation", lines, [r for r in reversed(decisions) if r["i"] < start])
        if len(opens) > MANY_OPEN or len(decisions) > MANY_DECISIONS or len(lines) > LONG:
            msg += (
                f"\nSTATE.md has {len(opens)} open items and {len(decisions)} un-graduated decisions: "
                "run /handoff graduate."
            )
        if len(msg) <= CAP:
            break
    return msg


def fit(core, source):
    """(context, notice): the project's block first, then the knowledge line and the newest cross-project STATE lines
    that still fit under CAP. A project block over CAP on its own is cut, with a notice naming the file to read."""
    notice = ""
    if len(core) > CAP:
        size = len(core)
        cut = (
            f"SessionStart injection cut: the project block is {size} characters and only {CAP} fit - "
            f"read {source} in full before anything else."
        )
        core = core[: CAP - len(cut) - 1] + "\n" + cut
        notice = (
            f"Session start: the project notes ({size} characters) were over the {CAP}-character limit and "
            "were cut; the model was told to open the file itself. Nothing for you to do."
        )
    knowledge = os.path.expanduser("~").replace("\\", "/") + "/.claude/knowledge/INDEX.md"
    stamp = (
        datetime.datetime.fromtimestamp(os.path.getmtime(knowledge)).astimezone().strftime("%Y-%m-%d")
        if os.path.exists(knowledge)
        else "missing"
    )
    msg = core
    line = f"\n~/.claude/knowledge/INDEX.md last updated {stamp}. Read it before deriving machine or environment facts."
    if len(msg) + len(line) <= CAP:
        msg += line
    gstate = _common.global_state_path()
    glines = []
    if os.path.exists(gstate):
        with open(gstate, encoding="utf-8") as fh:
            glines = [l for l in fh.read().splitlines() if l.startswith("- ")]
    header = (
        "\nCross-project STATE (~/.claude/STATE.md, newest lines that fit) - how I work and what this machine is. "
        "Append here instead of a project when the lesson is not about one project:\n"
    )
    take, room = [], CAP - len(msg) - len(header)
    for l in reversed(glines[-GTAIL:]):
        if len(l) + 1 > room:
            break
        take.insert(0, l)
        room -= len(l) + 1
    if take:
        msg += header + "\n".join(take)
    return msg, notice


def out(fitted):
    msg, notice = fitted
    result = {"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": msg}}
    if notice:
        result["systemMessage"] = notice
    return json.dumps(result)


_common.run("session-start.py", main)
