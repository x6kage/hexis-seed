"""PreToolUse hook. Denies, in every permission mode, any command or file content that would synthesize input on
the user's desktop or steal the foreground: mouse_event, SendInput, keybd_event, SetCursorPos, BlockInput,
ClipCursor, SendKeys / SendWait, SetForegroundWindow and the PowerShell cursor setter. A verification script that drives
the cursor takes the mouse from the user (rules/quality.md "No synthetic input on the user's desktop, ever"). The one exception is SetForegroundWindow inside the own Rust sources of a project listed in local.json (foreground_projects below), where a
user-triggered game restore is a decided feature; scripts and every other file never get it."""

import json
import os
import re

import _common

INPUT_APIS = [
    r"\bmouse_event\b",
    r"\bSendInput\b",
    r"\bkeybd_event\b",
    r"\bSetCursorPos\b",
    r"\bBlockInput\b",
    r"\bClipCursor\b",
    r"\bSendKeys\b",
    r"\bSendWait\b",
    r"\bSetForegroundWindow\b",
    r"Cursor\]::Position\s*=",
]
LOCAL_CONFIG = os.path.join(os.path.expanduser("~"), ".claude", "local.json")


def foreground_projects():
    """Folder names under ~/dev whose own Rust sources may raise their window: `foreground_projects` in
    ~/.claude/local.json, none when the file or the key is absent."""
    try:
        with open(LOCAL_CONFIG, encoding="utf-8") as fh:
            names = json.load(fh).get("foreground_projects") or []
    except (OSError, ValueError, AttributeError):
        return []
    return [n for n in names if isinstance(n, str) and n]


def foreground_ok(path):
    dev = os.path.join(os.path.expanduser("~"), "dev")
    for name in foreground_projects():
        project = os.path.join(dev, name)
        rx = "^" + r"[\\/]".join(re.escape(p) for p in re.split(r"[\\/]", project)) + r"[\\/].*[\\/]src[\\/].*\.rs$"
        if re.match(rx, path, re.IGNORECASE):
            return True
    return False


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


def texts(tool, inp):
    if tool in ("Bash", "PowerShell"):
        return inp.get("command", "") or ""
    if tool == "Write":
        return inp.get("content", "") or ""
    if tool == "Edit":
        return inp.get("new_string", "") or ""
    if tool == "MultiEdit":
        return "\n".join((e.get("new_string") or "") for e in (inp.get("edits") or []))
    return ""


def main(payload):
    tool = payload.get("tool_name")
    if tool not in ("Bash", "PowerShell", "Write", "Edit", "MultiEdit"):
        return None
    inp = payload.get("tool_input") or {}
    text = texts(tool, inp)
    if not text:
        return None
    path = inp.get("file_path", "") or ""
    if tool in ("Write", "Edit", "MultiEdit") and path.lower().endswith(".md"):
        return None  # documentation may name the APIs; nothing runs from a Markdown file
    hits = [p for p in INPUT_APIS if re.search(p, text)]
    if tool != "Bash" and tool != "PowerShell" and foreground_ok(path):
        hits = [p for p in hits if "SetForegroundWindow" not in p]
    if not hits:
        return None
    return out(
        f"Synthetic input is never produced on the user's desktop (matched {', '.join(hits)}): no mouse_event, "
        "SendInput, keybd_event, SetCursorPos, BlockInput, ClipCursor, SendKeys or SetForegroundWindow in any "
        "command or file, by any session. A check that needs a hand is the user's own, or is reported as not "
        "demonstrated. See rules/quality.md."
    )


_common.run("input-guard.py", main)
