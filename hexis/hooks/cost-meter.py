"""UserPromptSubmit hook. Prices this session from its own transcript and its subagents, incrementally, and injects
one line with the running cost, the last turn and the context size - a second line when a threshold says to hand off."""

import importlib.util
import json
import os
import shutil
import time

import _common
import credits_mode

WARN_TOTAL = 15
WARN_TURN = 2.0
COMPACT_WINDOW = 900_000
MIN_REQUESTS = 20
PAYBACK_MAX = 60
MODEL_ID = {
    "fable-5-2": "claude-fable-5-2",
    "fable-5-1": "claude-fable-5-1",
    "opus-5-5": "claude-opus-5-5",
    "opus-5": "claude-opus-5",
}
COST_LINES = os.path.join(_common.ROOT, "logs", "cost-meter")  # one file per session: the latest cost line
SWEEP_LATEST = os.path.join(_common.ROOT, "logs", "sweep", "latest.txt")
DISK_ALARM = 20 * 1024**3  # bytes free
# The disk that holds the home directory: its drive on Windows (C:), the home volume elsewhere.
_DRIVE = os.path.splitdrive(os.path.expanduser("~"))[0]
DISK = _DRIVE + os.sep if _DRIVE else os.path.expanduser("~")
DISK_LABEL = _DRIVE or "the home disk"
CALC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts", "session-cost.py")


def calculator():
    spec = importlib.util.spec_from_file_location("session_cost", CALC)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def crossover(calc, s):
    """Which of fable / opus is the cheaper main model from here, and what the switch itself costs.

    Per request a model costs C x read + n x write + o x output, so the cheaper read (fable) wins once the context it
    re-reads outweighs the extra it pays to write and to speak. Switching is not free: the new model's cache is cold,
    so the whole context is re-written once at ITS write rate. The line is only worth printing when that one-off pays
    back inside a plausible number of remaining requests."""
    fam, row = s.get("fam"), (s.get("main_rows") or {}).get(s.get("fam"))
    if fam not in MODEL_ID or not row or row["n"] < MIN_REQUESTS:
        return ""
    # A Fable main is the user's decision: Opus 5.5 is cheaper on writes and output on every prompt, and
    # the line would advise against that decision each time, so none is printed.
    if fam.startswith("fable"):
        return ""
    table, _ = calc.rates()
    other = "opus-5-5" if fam.startswith("fable") else "fable-5-2"
    # Which cache TTL a session writes into is a property of the client, not of the request: this desktop app puts
    # every write in the 1h bucket, the CLI uses 5m after the first. Price the bucket the session actually uses, and
    # exclude only the cold-start write - keying either on "the 1h bucket" reads n = 0 on a 1h-only session.
    wr = 2 if row["write1h"] > row["write5"] else 1
    w, first = row["write5"] + row["write1h"], row.get("first")
    n1 = w / row["n"] if first is None else max(0.0, w - first) / max(1, row["n"] - 1)
    o1 = row["output"] / row["n"]
    c = s["context"]

    def per_request(m):
        r = calc.rate_of(table, m)
        return (c * r[3] + n1 * r[wr] + o1 * r[4]) / 1e6

    saving = per_request(fam) - per_request(other)
    if saving <= 0:
        return ""
    switch = c * calc.rate_of(table, other)[wr] / 1e6
    payback = switch / saving
    if payback > PAYBACK_MAX:
        return ""
    return (
        f"\n{other} is the cheaper main model from here: ${per_request(other):.3f} per request against ${per_request(fam):.3f} at this context (~{c / 1000.0:.0f}k, "
        f"{n1 / 1000.0:.1f}k new, {o1 / 1000.0:.1f}k output). Switching re-caches the whole context once at ${switch:.2f}, so `/model {MODEL_ID.get(other, other)}` pays "
        f"back after ~{payback:.0f} more requests - worth it only if the session has that much left in it."
    )


def handoff(s):
    """Never asks for a handoff: auto-compaction is accepted, while a handoff chops the work and the
    rebuild repeats it up to 1M again. Near the window it says how the main context is kept small instead."""
    c = s["context"]
    if c < COMPACT_WINDOW:
        return ""
    return (
        f"\nContext ~{c / 1000.0:.0f}k is near auto-compaction, which is accepted - do not hand off. Keep the main context "
        "small by sending reading and bulk work to workflows and agents."
    )


def alarm(usage):
    """The C: warning when free space is under DISK_ALARM bytes, naming the last sweep."""
    if usage.free >= DISK_ALARM:
        return ""
    try:
        with open(SWEEP_LATEST, encoding="utf-8") as fh:
            last = fh.read().strip() or "no sweep has run"
    except OSError:
        last = "no sweep has run"
    return (
        f" WARNING: {DISK_LABEL} has {usage.free / 1024**3:.1f} GB free ({usage.free / usage.total * 100:.1f} %): tell the user, "
        f"and name the last sweep: {last}."
    )


def save_cost_line(session, s, rows, cold_n, cold_usd):
    """The rules/output.md cost line, built from this prompt's figures, for the jev-band mod to draw above the prompt.
    Best-effort: a failed write never fails the hook."""
    if not session:
        return
    split = ", ".join(
        "{} ${:.2f}{}".format(f, r["usd"], " now" if f == s.get("fam") else "")
        for f, r in sorted(rows.items(), key=lambda kv: -kv[1]["usd"])
    )
    line = (
        "Cost: ${:.2f} | main ${:.2f} ({}) | agents ${:.2f} | turn ${:.2f} | avg ${:.2f}/req | context {:.0f}k "
        "| cold {} = ${:.2f}".format(
            s["usd"], s["main"], split, s["agents"], s["delta"], s["avg"], s["context"] / 1000.0, cold_n, cold_usd
        )
    )
    try:
        os.makedirs(COST_LINES, exist_ok=True)
        with open(os.path.join(COST_LINES, session + ".txt"), "w", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except Exception:  # noqa: BLE001, S110 - the saved cost line is best-effort, never worth failing the hook over
        pass


JAPANESE = " Reply to the user in Japanese (CLAUDE.md); records, peer messages and commits stay English."


def credits(payload):
    """Credits mode with its end while it lasts, or the PROGRESS.md line that outlived it."""
    return credits_mode.line(_common.progress_path(payload), int(time.time()))


def alarm_only(payload, user=True):
    """The paths that print no meter line: the disk warning (the alarm on every prompt), credits mode
    and, on a user prompt, the Japanese line - a fresh session's first prompts have no priced request yet, and a session
    can answer in English after re-reading its English records."""
    text = ((JAPANESE if user else "") + alarm(shutil.disk_usage(DISK)) + credits(payload)).strip()
    return (
        json.dumps({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": text}})
        if text
        else None
    )


def main(payload):
    if payload.get("agent_id"):
        return alarm_only(payload, user=False)
    transcript = payload.get("transcript_path") or ""
    if not os.path.isfile(transcript):
        return alarm_only(payload)
    calc = calculator()
    s = calc.summarise_incremental(transcript, transcript + ".cost.json")
    if not s["requests"] or s["usd"] <= 0:
        return alarm_only(payload)
    session = payload.get("session_id") or ""
    # While the band shows the cost line, the figures stay out of the context: only the conditional lines below are
    # injected; a cost statement reads the saved line instead.
    visible = _common.band_visible(session)
    msg = (
        "Session cost ${:.2f} (main ${:.2f}, agents ${:.2f}), last turn ${:.2f}, context ~{:.0f}k, "
        "avg ${:.2f} per request.".format(s["usd"], s["main"], s["agents"], s["delta"], s["context"] / 1000.0, s["avg"])
    )
    rows = s.get("main_rows") or {}
    per_model = ", ".join(
        "{} ${:.2f}".format(f, r["usd"]) for f, r in sorted(rows.items(), key=lambda kv: -kv[1]["usd"])
    )
    cold_n = sum(r.get("cold_n", 0) for r in rows.values())
    cold_usd = sum(r.get("cold_usd", 0.0) for r in rows.values())
    msg += f" Main by model: {per_model}."
    save_cost_line(session, s, rows, cold_n, cold_usd)
    if visible:
        msg = ""  # the figures are in the band and in logs/cost-meter/<session>.txt
    if cold_n and not visible:
        msg += (
            f" Cold re-caches: {cold_n} = ${cold_usd:.2f} (session start, an idle gap past the cache TTL, or a model switch each "
            "re-write the whole context at the write rate)."
        )
    prev_cold = s.get("prev_cold", 0)
    if cold_n > prev_cold and s["requests"] > 1:
        msg += " WARNING: the last turn re-cached the whole context cold."
    if s["delta"] >= WARN_TURN:
        msg += " WARNING: the last turn alone cost ${:.2f}.".format(s["delta"])
    if s["usd"] >= WARN_TOTAL and not visible:
        msg += " Cost lines quote the measured ${:.2f} per request, not a guess.".format(s["avg"])
    if not visible:  # the band draws the cost line; a phone or a band-less session gets it in the reply
        msg += (
            "\nReport this line's total, per-model split and cold re-cache figure to the user at the end of the reply."
        )
    # Sits at the tail of the context every turn: replies drifted into English 21/305 times in one session, the rate
    # rising with context size (0/32 under 200k, 7/31 over 800k).
    msg += JAPANESE
    msg += handoff(s) or crossover(calc, s)
    msg += alarm(shutil.disk_usage(DISK))
    msg += credits(payload)
    msg = msg.strip()
    return json.dumps({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": msg}})


_common.run("cost-meter.py", main)
