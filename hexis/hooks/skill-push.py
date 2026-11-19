"""PreToolUse hook, tier 1 of the skill push: procedures reach the model as skills at the moment of
action. A tool call that matches a skill's trigger is denied ONCE per session and agent scope, with the skill body as
the reason - a deny is read before anything runs, while PreToolUse additionalContext only arrives with the call's
result. The same call run again passes. Tier 2 (Jev routing on the prompt) lives in misread-check.py and marks the
same state file, so a skill it already pushed is not pushed again here. session-start.py clears the state on compact.
Fail-open: a missing skill file, an unreadable state or a failed write lets the call through."""

import json
import os
import re

import _common

COMMIT = re.compile(r"\bgit(?:\s+-[cC]\s+(?:\"[^\"]+\"|'[^']+'|\S+))*\s+commit\b")
# Record files: every project memory file (PROGRESS, STATE, MEMORY, feedback), the global STATE.md, inbox, knowledge,
# decisions. Stage 1 of the rules tiering moved the record rules out of the always-loaded files, so
# every way of writing a record must trigger the push - a shell redirect or tee into one as well as Edit/Write.
RECORD_DIRS = ("/memory/", ".claude/inbox/", ".claude/knowledge/", ".claude/decisions/")
RECORD_WRITE = re.compile(r"(?:>>?|\btee\b(?:\s+-a)?)\s*[\"']?[^\s|;&\"']*(?:STATE|PROGRESS|MEMORY)\.md")
# Tool configuration and installs: the current primary source is fetched before either (tool configs
# get set up from memory even while rules/research.md is loaded).
CONFIG_FILE = re.compile(
    r"(?:^|/)(?:package\.json|tsconfig[\w.-]*\.json|jsconfig\.json|biome\.jsonc?|bunfig\.toml|vercel\.json|"
    r"pyproject\.toml|ruff\.toml|pyrightconfig\.json|Cargo\.toml|go\.mod|deno\.jsonc?)$"
)
INSTALL = re.compile(
    r"\b(?:bun\s+(?:add|install\s+\S)|npm\s+(?:i|install)\s+\S|pnpm\s+add|pip\s+install|python\s+-m\s+pip\s+install|"
    r"winget\s+install|cargo\s+(?:add|install)|go\s+get)\b"
)


HEREDOC = re.compile(r"<<-?\s*(['\"]?)(\w+)\1")


def without_heredoc_bodies(command):
    """The command without its heredoc bodies: words inside a body (a note that mentions a commit or an install) are
    data, not the command - otherwise they fire the commit and research pushes."""
    lines, kept, i = command.split("\n"), [], 0
    while i < len(lines):
        kept.append(lines[i])
        m = HEREDOC.search(lines[i])
        i += 1
        if m:
            while i < len(lines) and lines[i].strip() != m.group(2):
                i += 1
            i += 1
    return "\n".join(kept)


def skills_for(tool, tool_input):
    """Every skill a call triggers, in priority order; the hook pushes the first one not yet pushed."""
    found = []
    if tool in ("Agent", "Workflow"):
        found.append("hexis-routing")
    command = (tool_input.get("command") or "") if tool in ("Bash", "PowerShell") else ""
    code = without_heredoc_bodies(command)
    if COMMIT.search(code):
        found.append("hexis-commit")
    if "linear_ops" in code or tool.startswith("mcp__linear-mcp__"):
        found.append("hexis-linear")
    if "<<" in command or "\n" in command:
        found.append("hexis-shell")
    if RECORD_WRITE.search(code):
        found.append("hexis-records")
    if INSTALL.search(code):
        found.append("hexis-research")
    if tool in ("Edit", "Write", "MultiEdit"):
        path = (tool_input.get("file_path") or "").replace("\\", "/")
        if path.endswith("/.claude/STATE.md") or any(d in path for d in RECORD_DIRS):
            found.append("hexis-records")
        if CONFIG_FILE.search(path):
            found.append("hexis-research")
    return found


def skill_for(tool, tool_input):
    """The highest-priority skill a call triggers; None when none does."""
    found = skills_for(tool, tool_input)
    return found[0] if found else None


def main(payload):
    session = payload.get("session_id") or ""
    if not session:
        return None
    scope = payload.get("agent_id") or "main"
    pushed = _common.pushed_skills(session).get(scope, [])
    name = next(
        (s for s in skills_for(payload.get("tool_name") or "", payload.get("tool_input") or {}) if s not in pushed),
        None,
    )
    if not name:
        return None
    body = _common.skill_body(os.path.join(_common.SKILLS, name, "SKILL.md"))
    if not body or not _common.mark_pushed(session, scope, name):
        return None
    reason = f"Procedure for this action (skill {name}) - read it, then run the same call again.\n{body}"
    return json.dumps(
        {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": reason,
            }
        }
    )


_common.run("skill-push.py", main)
