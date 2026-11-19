"""PreToolUse hook on Agent and Workflow, Jev first: each launched agent's model tier and effort are judged against the
routing table, so an agent that runs above what its task needs is caught before it runs (a workflow
ran an inventory on Sonnet 5 medium and a merge of structured results on Opus 5.5 high); the user chose Jev, not
keyword rules, to judge over-provisioning.

One Noul per agent (all in one call). An agent scoring at or above FLAG_AT denies the launch ONCE per session: the
reason names each flagged agent, and the same launch sent again passes, because a deliberate choice must stay possible
without a bypass. Every judgement is logged under `route-check` for labelling. Fail-open on any error or timeout.

Before Jev, one fact needs no judgement : a launch that puts an agent on Fable while the session's main model is Fable spends Fable twice on
one check. It is denied once the same way, with the audit chain of a Fable main in the reason (rules/agents.md)."""

import io
import json
import os
import re
import sys
from typing import cast

import _common
import jev_client
import main_model

# Jev policy (no Jev question meets a block bar yet): "prompt" stops a launch
# once with a confirm request and lets the identical relaunch pass; "log" judges and records only; "block" may refuse.
TIER = "prompt"
FLAG_AT = 0.7  # provisional: to be fitted on labelled route-check rows in evals/jev, select split then holdout
AGENTS_DIR = os.path.join(os.path.expanduser("~"), ".claude", "agents")
WORKFLOWS_DIR = os.path.join(os.path.expanduser("~"), ".claude", "workflows")
STATE_DIR = os.path.join(jev_client.ROOT, "logs", "route-check")
CALL = re.compile(r"(?<![\w.$])agent\s*\(")
IDENT = re.compile(r"[A-Za-z_$][\w$]*")
DESTRUCTURE = re.compile(r"(?<![\w.$])(?:const|let|var)\s*[{\[]")
DEFN = re.compile(r"(?<![\w.$])(?:const|let|var|function\*?|async\s+function)\s+([A-Za-z_$][\w$]*)")
STATE_CHARS = 24000  # Jev takes ~32K tokens of state (see brief-check.py); the routing table and args come off first
AGENT_CHARS = 12000  # an Agent launch: description plus the head of its prompt
CALL_CHARS = 6000  # a workflow agent() call: its window plus the definitions it uses
LINES_BEFORE = 3  # lines above an agent() call kept with it: the map or pipeline that feeds it sits there
DEF_CHARS = 2000
DEF_DEPTH = 2
ARGS_CHARS = 2000
ROUTING_TABLE = {
    "model": {
        "haiku": "Retrieval and mechanical work with no judgement: locating, listing, inventories, format conversion, "
        "running a fixed command.",
        "sonnet": "Reading comprehension without deep reasoning: summaries, drafting from a clear spec, merging or "
        "integrating structured results, single-lens review.",
        "opus": "Judgement: design decisions, debugging an unclear cause, multi-file implementation, security review, "
        "audits, deriving numbers or classifications from raw data.",
        "fable": "The cross-model audit of another model's judgement work only.",
    },
    "effort": {
        "low": "Retrieval and fixed procedures.",
        "medium": "Implementation from a clear spec, summaries, briefs.",
        "high": "Debugging, design, derivation, audits.",
        "max": "Ambiguous raw-data derivation, security review, a task high already failed, the final pre-deploy audit.",
    },
}
QUESTION = "Does `{key}` run on a model tier or effort above what its task needs, under `routing_table`?"
CRITERIA = {
    "true": "The task of `{key}` falls under a lower model tier or a lower effort level in `routing_table` than the "
    "ones it runs on.",
    "false": "The model tier and effort `{key}` runs on are the lowest ones in `routing_table` whose definitions "
    "cover its task.",
}
FABLE_ROW = re.compile(
    r"""\bmodel\s*:\s*['"`][\w.-]*fable"""
)  # a workflow table row that an agent() reads its model from
FABLE_MAIN = (
    "Fable under a Fable main: this session's main model is Fable and {what} would run on Fable too, so one check "
    'spends Fable twice (rules/agents.md "Audit"). The Fable audit is this session\'s own final '
    "pass, in place: the diff, the worker's report and the audit agent's findings against the original request. The "
    "audit agent before it is `auditor-opus` (Opus 5.5, xhigh) over Sonnet 5.5 work; Opus 5.5 work has none. Relaunch "
    "unchanged only when the user named a Fable agent for this task - the same launch passes the second time."
)


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
    if tool not in ("Agent", "Workflow") or payload.get("agent_id"):
        return None
    inp = payload.get("tool_input") or {}
    if tool == "Agent":
        agents, key_text, extra = [agent_launch(payload, inp)], json.dumps(inp, sort_keys=True, ensure_ascii=False), {}
    else:
        src = script_of(inp)
        if not src:
            return None
        agents, key_text = workflow_agents(src), src
        extra = {"workflow_args": json.dumps(inp["args"], ensure_ascii=False)[:ARGS_CHARS]} if inp.get("args") else {}
    if not agents:
        return None
    session = payload.get("session_id") or ""
    cwd = payload.get("cwd") or ""
    launch = _common.once_key(key_text)
    source = f"{tool.lower()}/{len(agents)} agent(s)"
    seen = _common.once_seen(STATE_DIR, session)
    if launch in seen:
        jev_client.log("route-check", None, "relaunch", 0, key_text, cwd, source, seen[launch].get("ps"), session)
        return None
    fable = on_fable(tool, agents, key_text)
    if fable and main_model.tier(payload) == "fable" and _common.once_mark(STATE_DIR, session, launch, {"ps": None}):
        jev_client.log("route-check", None, "fable-main", 0, key_text, cwd, source, session=session)
        return out(FABLE_MAIN.format(what=fable))
    state = dict(extra, routing_table=ROUTING_TABLE)
    for i, a in enumerate(agents, 1):
        state[f"agent_{i}"] = a
    questions = {
        f"agent_{i}": (QUESTION.format(key=f"agent_{i}"), {k: v.format(key=f"agent_{i}") for k, v in CRITERIA.items()})
        for i in range(1, len(agents) + 1)
    }
    ps, ms = jev_client.timed_nouls(state, questions)
    if ps is None:
        jev_client.log("route-check", None, "error", ms, key_text, cwd, source, session=session)
        return None
    ps = cast(dict[str, float], ps)
    flagged = [(a, ps[f"agent_{i}"]) for i, a in enumerate(agents, 1) if ps.get(f"agent_{i}", 0.0) >= FLAG_AT]
    p = max(ps.values()) if ps else None
    jev_client.log("route-check", p, "flag" if flagged else "pass", ms, key_text, cwd, source, ps, session)
    if not flagged or not _common.once_mark(STATE_DIR, session, launch, {"ps": ps}):
        return None
    lines = "; ".join(f"`{a['label']}` ({a['model']}/{a['effort']}) {v:.2f}" for a, v in flagged)
    return out(
        f"Route check (Jev {jev_client.version()}): {len(flagged)} agent(s) run above the tier or effort their task "
        f"needs under the routing table in rules/agents.md: {lines}. Route it down, or relaunch unchanged if the "
        "choice is deliberate - the same launch passes the second time."
    )


def on_fable(tool, agents, src):
    """The agents of this launch that would run on Fable, named for the denial; '' when there is none."""
    labels = [f"`{a['label']}`" for a in agents if "fable" in a["model"]]
    if labels:
        return ", ".join(labels)
    return "an agent() reading `model: 'fable'` from the script" if tool == "Workflow" and FABLE_ROW.search(src) else ""


def agent_launch(payload, inp):
    agent_type = (inp.get("subagent_type") or "").strip()
    fields = frontmatter(agent_type)
    model = (inp.get("model") or fields.get("model") or "unset").strip().lower()
    effort = fields.get("effort") or "inherited:" + (session_effort(payload) or "unknown")
    prompt = inp.get("prompt")
    prompt = prompt if isinstance(prompt, str) else json.dumps(prompt, ensure_ascii=False)
    desc = inp.get("description") or ""
    return {
        "label": desc or agent_type or "agent",
        "agent_type": agent_type or "general-purpose",
        "model": model,
        "effort": effort,
        "task": (desc + "\n\n" + prompt)[:AGENT_CHARS],
    }


def script_of(inp):
    src = inp.get("script") or ""
    path = inp.get("scriptPath") or (os.path.join(WORKFLOWS_DIR, inp["name"] + ".js") if inp.get("name") else "")
    if not src and path:
        try:
            with open(os.path.expanduser(path), encoding="utf-8") as fh:
                src = fh.read()
        except OSError:
            return ""
    return src


def workflow_agents(src):
    """Each agent() call as {label, model, effort, task}: `task` is the call with the lines above it, followed by the
    definitions of the names it uses (the prompt builder, the table it maps over), each capped, within the budget."""
    mask = code_mask(src)
    defs = definitions(mask)
    calls = []
    for n, hit in enumerate(CALL.finditer(mask), 1):
        end = call_end(mask, hit.end())
        parts = top_level_spans(mask, hit.end(), end - 1)
        opts = option_values(src, mask, parts[1]) if len(parts) > 1 else {}
        start = src.rfind("\n", 0, hit.start()) + 1
        for _ in range(LINES_BEFORE):
            start = src.rfind("\n", 0, start - 1) + 1 if start > 0 else 0
        calls.append((n, start, hit.start(), end, opts))
    budget = max(1500, min(CALL_CHARS, (STATE_CHARS - 3000) // max(len(calls), 1)))
    agents = []
    for n, start, at, end, opts in calls:
        pieces, used, spans, frontier = [src[start:end]], {"agent"}, set(), [(start, end)]
        for _ in range(DEF_DEPTH):
            nxt = []
            for s, e in frontier:
                for name in IDENT.findall(mask[s:e]):
                    if name in used or name not in defs:
                        continue
                    used.add(name)
                    ds, de = defs[name]
                    if (ds, de) in spans or ds <= at < de or (ds >= start and de <= end):
                        continue
                    spans.add((ds, de))
                    pieces.append(src[ds:de][:DEF_CHARS])
                    nxt.append((ds, de))
            frontier = nxt
        agents.append(
            {
                "label": opts.get("label") or f"agent() #{n}",
                "model": opts.get("model") or "unset",
                "effort": opts.get("effort") or "unset",
                "task": "\n\n".join(pieces)[:budget],
            }
        )
    return agents


def definitions(mask):
    """name -> (start, end) of the statement that defines it at any depth: const/let/var or a function declaration."""
    out_ = {}
    for m in DEFN.finditer(mask):
        out_.setdefault(m.group(1), (m.start(), statement_end(mask, m.end())))
    for m in DESTRUCTURE.finditer(mask):
        close = call_end(mask, m.end())
        for name in IDENT.findall(mask[m.end() : close - 1]):
            out_.setdefault(name, (m.start(), statement_end(mask, close)))
    return out_


def statement_end(mask, i):
    depth, n, seen_body = 0, len(mask), False
    while i < n:
        c = mask[i]
        if c in "([{":
            depth += 1
        elif c in ")]}":
            depth -= 1
            if depth < 0:
                return i
            if depth == 0 and c == "}":
                seen_body = True
        elif depth == 0 and c == ";":
            return i + 1
        elif depth == 0 and c == "\n":
            before = mask[:i].rstrip()[-1:]
            after = mask[i:].lstrip()[:1]
            if before and before not in "=,(+-*/?:&|[{" and after not in (".", "?", ":", "+", "|", "&"):
                return i
            if seen_body and after not in (".", "?", ":"):
                return i
        i += 1
    return n


def call_end(mask, j):
    depth = 1
    while j < len(mask) and depth:
        depth += {"(": 1, "[": 1, "{": 1, ")": -1, "]": -1, "}": -1}.get(mask[j], 0)
        j += 1
    return j


def top_level_spans(mask, s, e):
    spans, depth, start = [], 0, s
    for k in range(s, e):
        ch = mask[k]
        depth += {"(": 1, "[": 1, "{": 1, ")": -1, "]": -1, "}": -1}.get(ch, 0)
        if ch == "," and depth == 0:
            spans.append((start, k))
            start = k + 1
    spans.append((start, e))
    return spans


def option_values(src, mask, span):
    """label, model and effort from an inline options object: a string literal's text, else the expression's source."""
    s, e = span
    body = mask[s:e].strip()
    if not body.startswith("{"):
        return {}
    s = mask.index("{", s) + 1
    e = mask.rindex("}", s - 1, e)
    vals = {}
    for ps, pe in top_level_spans(mask, s, e):
        m = re.match(r"\s*(label|model|effort)\s*:", mask[ps:pe])
        if m:
            vals[m.group(1)] = " ".join(src[ps + m.end() : pe].split()).strip("'\"`")
    return vals


def code_mask(src):
    """Copied from agent-guard.py (hyphenated hooks cannot be imported): the script with string, template-literal text
    and comment characters blanked (same length), so calls and brackets are only found in code."""
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
    e = payload.get("effort")
    level = e.get("level") if isinstance(e, dict) else e
    return str(level or os.environ.get("CLAUDE_EFFORT") or "").strip().lower()


def frontmatter(agent_type):
    """`model` and `effort` from AGENTS_DIR/<agent_type>.md frontmatter; {} when there is no such file."""
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


cast(io.TextIOWrapper, sys.stdin).reconfigure(encoding="utf-8")
_common.run("route-check.py", main)
