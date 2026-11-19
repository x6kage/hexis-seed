"""PostToolUse hook for Agent. Blocks a subagent result that does not carry the sections its agent type promises,
so an unusable report is re-run instead of being read as an answer."""

import json
import re

import _common

URL_OR_PATH = re.compile(r"https?://|[A-Za-z]:[\\/]|(?:^|\s)[~./][\w./\\-]*\.\w+", re.MULTILINE)
HEADING = r"^[#*\s]{0,6}.{0,20}%s"


def text_of(response):
    if isinstance(response, str):
        return response
    if isinstance(response, list):
        return "\n".join(text_of(x) for x in response)
    if isinstance(response, dict):
        for key in ("content", "result", "output", "text", "response"):
            if key in response:
                return text_of(response[key])
    return ""


def is_launch_stub(response, text):
    """A run_in_background Agent call returns a launch stub, not a report: there is nothing to check yet."""
    if isinstance(response, dict) and (response.get("isAsync") or response.get("status") == "async_launched"):
        return True
    return text.lstrip().startswith("Async agent launched successfully.")


def check(kind, text):
    lines = [l for l in text.splitlines() if l.strip()]
    if kind == "auditor":
        if not re.search(HEADING % "decisions and uncertainties", text, re.IGNORECASE | re.MULTILINE):
            return 'no "decisions and uncertainties" heading'
    elif kind == "qa-gate":
        missing = []
        if not lines or not re.match(r"(PASS|FAIL)\b", lines[0].strip().lstrip("#* ")):
            missing.append("the first line is not PASS or FAIL")
        if len(text.splitlines()) > 40:
            missing.append("the report is longer than 40 lines")
        if "did not check" not in text.lower():
            missing.append('no "what I did not check" section')
        if missing:
            return "; ".join(missing)
    elif kind == "lesson-recall":
        if len(lines) > 15 and "no recorded lesson" not in text.lower():
            return 'more than 15 lines and no "no recorded lesson" line'
    elif kind == "docs-lookup":
        missing = []
        if not URL_OR_PATH.search(text):
            missing.append("no source URL or file path is quoted")
        if not re.search(r"not documented|could not find", text, re.IGNORECASE):
            missing.append('no "not documented" / "could not find" section')
        if missing:
            return "; ".join(missing)
    elif kind == "grep-scout":
        if not re.search(r"\S+:\d+", text) and "not found" not in text.lower():
            return 'no path:line hit and no "not found" statement'
    elif kind == "implementer":
        missing = [
            h
            for h in ("## Tests", "## Evidence", "## Decisions and uncertainties")
            if not re.search(rf"^{re.escape(h)}", text, re.IGNORECASE | re.MULTILINE)
        ]
        if missing:
            return "missing heading(s) " + ", ".join(missing)
    return None


def main(payload):
    response = payload.get("tool_response")
    text = text_of(response)
    if is_launch_stub(response, text):
        return None
    kind = (payload.get("tool_input") or {}).get("subagent_type") or ""
    miss = check(kind, text)
    if not miss:
        return None
    return json.dumps(
        {
            "decision": "block",
            "reason": f"CONTRACT MISS ({kind}): {miss}. Do not accept this result; re-run the agent asking for the missing part.",
        }
    )


_common.run("agent-contract.py", main)
