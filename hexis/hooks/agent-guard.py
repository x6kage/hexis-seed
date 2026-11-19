"""PreToolUse hook on the Agent and Workflow tools. Hard denials, in every permission mode:

1. A launch with no explicit `model`. The env backstop would silently price it, and an unargued tier is an unmade
   decision: an unpinned Fable session once spawned 644 subagents for $3,178, and an Opus agent averaged $7.95
   against $1.06 for Sonnet. Routing is stated, never inherited.
2. A subagent spawning its own child. The brief is paid for twice, the child runs on a tier the caller never priced,
   and the parent's turn ends before the child does, so the run is orphaned (rules/agents.md).
3. A `model` that differs from the pinned agent's frontmatter `model:` - the launch value overrides the pin and
   silently de-pins it (found by a Fable audit of an agent-guard port).
4. An agent whose definition pins no `effort`, launched while the session runs at xhigh or max. It inherits the
   session's effort, so retrieval and summaries would think at the main's most expensive level. Pinned definitions carry the effort the task needs.
5. A Workflow script with an agent() call that does not state `model` and `effort` inline in its options object - the
   same inheritance (left unchecked, most workflow agents ran unset).
"""

import json
import os
import re

import _common

TIERS = ("haiku", "sonnet", "opus", "fable")
HIGH_EFFORT = ("xhigh", "max")
AGENTS_DIR = os.path.join(os.path.expanduser("~"), ".claude", "agents")
WORKFLOWS_DIR = os.path.join(os.path.expanduser("~"), ".claude", "workflows")
CALL = re.compile(r"(?<![\w.$])agent\s*\(")


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
    tool = payload.get("tool_name")
    if tool == "Workflow":
        return workflow(payload.get("tool_input") or {})
    if tool != "Agent":
        return None
    if payload.get("agent_id"):
        return out(
            "A subagent does the work in its own turn; it never spawns a child. Carry out the brief "
            "yourself on the model you are running on, or report that you cannot and why. "
            "See rules/agents.md."
        )
    inp = payload.get("tool_input") or {}
    model = (inp.get("model") or "").strip().lower()
    if not model:
        return out(
            "Agent launched without an explicit `model`. Route it: haiku for retrieval and mechanical work, "
            "sonnet by default, opus only when the launch line names its trigger (unclear cause, design "
            "decision, multi-file implementation, security review, audit, derivation from raw data). "
            "An Opus agent averages $7.95 against $1.06 for Sonnet. See rules/agents.md."
        )
    if not any(t in model for t in TIERS):
        return out("`model` must name a tier: haiku, sonnet, opus or fable. See rules/agents.md.")
    # 3. A `model` that differs from a pinned agent's frontmatter overrides the pin and silently de-pins it (found by
    # a Fable audit), so it must match. An agent without a pin takes any tier.
    agent_type = (inp.get("subagent_type") or "").strip()
    fields = frontmatter(agent_type)
    pinned = next((t for t in TIERS if t in fields.get("model", "")), "")
    if pinned and pinned not in model:
        return out(
            f"`{agent_type}` is pinned to `{pinned}` in ~/.claude/agents; launch it with "
            f"model `{pinned}`, or use another agent. A different `model` silently overrides the pin."
        )
    effort = session_effort(payload)
    if effort in HIGH_EFFORT and not fields.get("effort"):
        return out(
            f"The session runs at effort `{effort}` and `{agent_type or 'general-purpose'}` pins none, so it "
            "would think at that level. Launch a pinned definition instead - grep-scout (haiku, low), "
            "docs-lookup (sonnet, medium), worker (sonnet, medium), implementer (opus, medium), analyst "
            "(opus, high), auditor (fable, high) - or a Workflow agent() with `effort` stated."
        )
    return None


def workflow(inp):
    """Every agent() call in the script names `model` and `effort` in an inline options object."""
    src = inp.get("script") or ""
    path = inp.get("scriptPath") or (os.path.join(WORKFLOWS_DIR, inp["name"] + ".js") if inp.get("name") else "")
    if not src and path:
        try:
            with open(os.path.expanduser(path), encoding="utf-8") as fh:
                src = fh.read()
        except OSError:
            return None  # a built-in or unresolvable workflow: nothing to read
    bad = unstated_calls(src)
    if not bad:
        return None
    return out(
        f"{len(bad)} agent() call(s) in this workflow do not state `model` and `effort` inline in the options "
        f"object (first: `{bad[0]}`). Each call inherits the session's effort otherwise; write "
        "`agent(prompt, {model: '...', effort: '...', ...})` on every call (rules/agents.md)."
    )


def unstated_calls(src):
    """The opening text of each agent(...) call whose second argument is not an inline object with model and effort."""
    mask, bad = code_mask(src), []
    for hit in CALL.finditer(mask):
        depth, j = 1, hit.end()
        while j < len(mask) and depth:
            depth += {"(": 1, "[": 1, "{": 1, ")": -1, "]": -1, "}": -1}.get(mask[j], 0)
            j += 1
        parts = top_level(mask[hit.end() : j - 1])
        opts = parts[1] if len(parts) > 1 else ""
        if not (opts.startswith("{") and re.search(r"\bmodel\s*:", opts) and re.search(r"\beffort\s*:", opts)):
            bad.append(" ".join(src[hit.start() : hit.start() + 70].split()))
    return bad


def top_level(args):
    parts, depth, cur = [], 0, []
    for ch in args:
        depth += {"(": 1, "[": 1, "{": 1, ")": -1, "]": -1, "}": -1}.get(ch, 0)
        if ch == "," and depth == 0:
            parts.append("".join(cur).strip())
            cur = []
        else:
            cur.append(ch)
    parts.append("".join(cur).strip())
    return parts


def code_mask(src):
    """The script with string, template-literal text and comment characters blanked (same length), so calls and
    brackets are only found in code - including the code inside ${...} of a template literal."""
    out_, i, n, stack, mode = [], 0, len(src), [], None
    while i < n:
        c, two = src[i], src[i : i + 2]
        if mode is None:
            if two in ("//", "/*"):
                mode = two
                out_.append("  ")
                i += 2
                continue
            if c in "'\"":
                mode = c
            elif c == "`":
                stack.append("`")
                mode = "`"
            elif c == "{" and stack:
                stack.append("{")
            elif c == "}" and stack and stack[-1] == "{":
                stack.pop()
                if stack and stack[-1] == "`":
                    mode = "`"
                    out_.append(" ")
                    i += 1
                    continue
            out_.append(" " if mode else c)
            i += 1
            continue
        if mode == "//":
            mode = None if c == "\n" else mode
        elif mode == "/*" and two == "*/":
            mode = None
            out_.append("  ")
            i += 2
            continue
        elif mode in ("'", '"', "`") and c == "\\":
            out_.append("  "[: n - i])
            i += 2
            continue
        elif mode in ("'", '"') and c == mode:
            mode = None
        elif mode == "`" and c == "`":
            stack.pop()
            mode = None
        elif mode == "`" and two == "${":
            stack.append("{")
            mode = None
            out_.append("  ")
            i += 2
            continue
        out_.append("\n" if c == "\n" else " ")
        i += 1
    return "".join(out_)


def session_effort(payload):
    """The session's effort level: the hook payload's `effort.level`, else CLAUDE_EFFORT in the environment."""
    e = payload.get("effort")
    level = e.get("level") if isinstance(e, dict) else e
    return str(level or os.environ.get("CLAUDE_EFFORT") or "").strip().lower()


def frontmatter(agent_type):
    """`model` and `effort` from ~/.claude/agents/<agent_type>.md frontmatter; {} when there is no such file."""
    if not agent_type or "/" in agent_type or "\\" in agent_type or ":" in agent_type:
        return {}
    try:
        with open(os.path.join(AGENTS_DIR, agent_type + ".md"), encoding="utf-8") as fh:
            text = fh.read(4000)
    except OSError:
        return {}
    match = re.match(r"---\s*\n(.*?)\n---", text, re.DOTALL)
    head = match.group(1) if match else ""
    return {
        k: m.group(1).strip().lower() for k in ("model", "effort") if (m := re.search(rf"(?m)^{k}:\s*([\w.-]+)", head))
    }


_common.run("agent-guard.py", main)
