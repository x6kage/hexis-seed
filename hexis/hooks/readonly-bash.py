"""PreToolUse hook for the grep-scout agent. Denies any Bash command whose parts are not read-only lookups."""

import json

import _common

ALLOWED = (
    "ls",
    "find",
    "cat",
    "head",
    "tail",
    "git log",
    "git show",
    "git status",
    "git diff",
    "tasklist",
    "reg query",
    "wc",
    "stat",
    "which",
    "where",
)


def main(payload):
    cmd = (payload.get("tool_input") or {}).get("command", "")
    parts = cmd.replace("&&", "\n").replace("||", "\n").replace(";", "\n").replace("|", "\n").split("\n")
    bad = [p.strip() for p in parts if p.strip() and not p.strip().startswith(ALLOWED)]
    if not bad:
        return None
    return json.dumps(
        {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": (
                    "grep-scout is read-only: `"
                    + bad[0][:80]
                    + "` is not one of "
                    + ", ".join(ALLOWED)
                    + ". Report what you found and let the caller act on it."
                ),
            }
        }
    )


_common.run("readonly-bash.py", main)
