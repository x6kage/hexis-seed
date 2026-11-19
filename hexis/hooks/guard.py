"""PreToolUse hook. Denies the commands that tear down this machine, in every permission mode, and still asks before
a recursive delete when the session is not in bypassPermissions. Replaces guard-teardown.py."""

import json
import re

import _common

DENY = [
    r"winget\s+uninstall",
    r"msiexec(\.exe)?\s+.*(/x|/uninstall)",
    r"\bapt(-get)?\s+(remove|purge)",
    r"\bpip3?\s+uninstall",
    r"\bnpm\s+(uninstall|remove)\s+-g",
    r"brew\s+uninstall",
    r"Remove-ItemProperty\s+.*CurrentVersion\\Run",
    r"reg(\.exe)?\s+delete\s+.*CurrentVersion\\Run",
    r"Startup\\[^\s'\"]*\.lnk",
    r"(Stop-Process|taskkill)\b.*\b(explorer|komorebi|whkd|yasb|Flow\.Launcher|NordVPN|Discord|Steam|Razer|Wallpaper)",
    r"komorebic(\.exe)?\s+stop",
    r"wsl(\.exe)?\s+--unregister",
    r"Restart-Computer|shutdown\s+/r|shutdown\s+-r",
    r"\blaunchctl\s+(unload|bootout|remove|disable)\b",
    r"\bkillall\s+(-\S+\s+)*(Finder|Dock|SystemUIServer|WindowServer)\b",
    r"(^|[;&|(]\s*)(sudo\s+)?reboot\b",
    r"shutdown\s+-h",
    r"\b(rm|unlink)\b[^;&|\n]*Library/LaunchAgents/",
]
ASK = [r"Remove-Item\s+.*-Recurse", r"\brm\s+-rf?\b"]


def out(decision, reason):
    return json.dumps(
        {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": decision,
                "permissionDecisionReason": reason,
            }
        }
    )


def main(payload):
    inp = payload.get("tool_input") or {}
    if payload.get("tool_name") not in ("Bash", "PowerShell"):
        return None
    cmd = inp.get("command", "")
    hit = next((p for p in DENY if re.search(p, cmd, re.IGNORECASE)), None)
    if hit:
        return out(
            "deny",
            f"Teardown-class command (matched /{hit}/). Uninstalls, autostart removal, killing a "
            "resident desktop process and reboots are never run from a session: tell the user what "
            "to run and why. See rules/working-style.md.",
        )
    if payload.get("permission_mode") == "bypassPermissions":
        return None
    hit = next((p for p in ASK if re.search(p, cmd, re.IGNORECASE)), None)
    if hit:
        return out("ask", f"Recursive delete (matched /{hit}/). Confirm the target is what the user asked for.")
    return None


_common.run("guard.py", main)
