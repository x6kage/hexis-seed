"""PreToolUse hook: only Hexis touches the tracker (the user's order).

Every session whose cwd is not Hexis (the home directory or anything under ~/.claude) is denied every
linear-mcp / plane-mcp tool, reads included, and any shell command that runs linear_ops.py, plane_ops.py or
plane_to_linear.py: project sessions that file issues without the user's go force the team to be rebuilt. The user's
order: nobody but Hexis touches Linear. Lifting the lock is the user's call.
"""

import json
import os
import re

import _common


# Built from the home directory, not written out (the setup also runs on Linux and macOS). Git Bash
# spells C:/Users/x as /c/Users/x, so that form is added on Windows.
def _forms(path):
    p = path.replace("\\", "/").lower().rstrip("/")
    return {p} | ({"/" + p[0] + p[2:]} if len(p) > 2 and p[1] == ":" else set())


HEXIS_EXACT = tuple(_forms(os.path.expanduser("~")))
HEXIS_PREFIX = tuple(_forms(os.path.join(os.path.expanduser("~"), ".claude")))
TRACKER_TOOL = re.compile(r"^mcp__(linear-mcp|plane-mcp|linear-claude|plane-claude)__", re.IGNORECASE)
TRACKER_CMD = re.compile(r"(linear_ops|plane_ops|plane_to_linear)\.py", re.IGNORECASE)


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


def main(payload):
    cwd = (payload.get("cwd") or os.getcwd()).replace("\\", "/").lower().rstrip("/")
    if cwd in HEXIS_EXACT or cwd.startswith(HEXIS_PREFIX):
        return None
    tool = payload.get("tool_name") or ""
    command = (payload.get("tool_input") or {}).get("command") or ""
    if TRACKER_TOOL.match(tool) or (tool in ("Bash", "PowerShell") and TRACKER_CMD.search(command)):
        return out(
            "Tracker access is locked for every session except Hexis by the user's order: no "
            "Linear or Plane access, reads included, until Hexis has finished setting up how Linear is "
            "operated and the user lifts the lock. Prepare your inventory locally (parents with children, "
            "Done included) and tell Hexis where it is."
        )
    return None


_common.run("tracker-lock.py", main)
