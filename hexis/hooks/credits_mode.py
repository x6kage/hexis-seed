"""Credits mode as a state with an end: on while the account spends purchased usage credits, over
by itself at the next weekly reset. `python ~/.claude/hooks/credits_mode.py on [--until "YYYY-MM-DD HH:MM"] | off |
status`; cost-meter.py puts `line()` into every prompt. The state file sits beside the real hooks directory, so a WSL
environment that links hooks/ to the Windows tree shares it."""

import calendar
import json
import os
import re
import sys
import time

WEEK = 7 * 86400
# One weekly reset of the account (Monday 00:00 JST = Sunday 15:00 UTC). Every reset is a whole number of weeks from it.
ANCHOR = calendar.timegm((2026, 11, 15, 15, 0, 0))
STATE = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), "logs", "credits.json")
MENTION = re.compile(r"credits?[ -]mode|usage credits|on credits|from credits", re.IGNORECASE)
# Not a claim that it is on: a line saying it ended, or one about this mechanism (a note naming this script must not
# be flagged).
ENDED = re.compile(r"\b(ended|ends|ending|over|off|lifted|no longer)\b|credits_mode\.py", re.IGNORECASE)


def next_reset(now):
    """The first weekly reset strictly after `now` (epoch seconds)."""
    return ANCHOR + ((now - ANCHOR) // WEEK + 1) * WEEK


def jst(ts):
    return time.strftime("%a %Y-%m-%d %H:%M JST", time.gmtime(ts + 9 * 3600))


def until(now):
    """The end of the credits mode active at `now`, or None."""
    try:
        with open(STATE, encoding="utf-8") as fh:
            end = json.load(fh).get("until")
    except (OSError, ValueError):
        return None
    return end if isinstance(end, (int, float)) and now < end else None


def switch(on, now, end=None):
    if not on:
        if os.path.isfile(STATE):
            os.remove(STATE)
        return None
    end = end or next_reset(now)
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    with open(STATE, "w", encoding="utf-8") as fh:
        json.dump({"since": now, "until": end}, fh)
    return end


def line(progress, now):
    """What every prompt is told: credits mode with its end while it lasts, and a PROGRESS.md line that still speaks of
    credits mode once none is active (a note without an end keeps a session labelling launches as paid from
    credits past the reset)."""
    end = until(now)
    if end:
        return (
            f" CREDITS MODE ON until {jst(end)} (the weekly reset): launch no agent, workflow or fan-out without the "
            "user's yes in that turn (rules/agents.md); it ends by itself at that time."
        )
    try:
        with open(progress, encoding="utf-8") as fh:
            stale = [l.strip() for l in fh if MENTION.search(l) and not ENDED.search(l)]
    except OSError:
        return ""
    if not stale:
        return ""
    return (
        f" PROGRESS.md speaks of credits mode ({stale[0][:80]!r}) but none is active: the weekly limit reset at "
        f"{jst(next_reset(now) - WEEK)}. Remove that line and label nothing as paid from credits; if the user said "
        "after that reset that he is on usage credits, run `python ~/.claude/hooks/credits_mode.py on` instead."
    )


def main(argv):
    now = int(time.time())
    cmd = argv[1] if len(argv) > 1 else "status"
    if cmd == "on":
        end = None
        if "--until" in argv:
            end = calendar.timegm(time.strptime(argv[argv.index("--until") + 1], "%Y-%m-%d %H:%M")) - 9 * 3600
        switch(True, now, end)
    elif cmd == "off":
        switch(False, now)
    end = until(now)
    print(
        f"credits mode ON until {jst(end)}"
        if end
        else f"credits mode OFF (last weekly reset {jst(next_reset(now) - WEEK)})"
    )


if __name__ == "__main__":
    main(sys.argv)
