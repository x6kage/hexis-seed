"""SubagentStart hook: a hard ceiling on the agents one user prompt may start, workflows included, in total and per model
(even with ultracode on, agents are right-sized and minimal; counts are set per model because the model sets the
cost - a game-data run spent ~$7.5 per Opus agent against ~$1 per Sonnet agent).
Past workflow runs used a median of 5 agents, p90 24, max 102 (the 102-agent run cost $268).
The payload names no model; a workflow agent's model is read from the `agent-<id>.meta.json` the runtime writes when
it starts it, under the session's subagents folder - waited for briefly, because it can land a few milliseconds after
the hook starts. Each started agent leaves one marker file named by its model, and the count is the number of markers,
so agents that start together are all counted (a shared counter file lost one of two parallel starts). An exit of 2
blocks the subagent (docs); a denied workflow agent returns null to its script. Counts are per session and prompt_id.
Fail-open on any error."""

import glob
import json
import os
import sys
import time

import _common

# Sized so a full raw-data analysis still runs (14 Opus derivations + coverage + audit; the cap is a cost/effect
# trade-off, not a ban) while a 64- or 102-agent run cannot: total = the p90 of past runs.
CAP = 24
MODEL_CAPS = {"fable": 2, "opus": 16, "sonnet": 16, "haiku": 24}
STATE = os.path.join(_common.ROOT, "logs", "agent-cap")
PROJECTS = os.path.join(_common.ROOT, "projects")
META_WAIT = 0.5  # seconds to wait for the runtime's meta file


def model_of(payload):
    """The tier of the agent being started, from its meta file; '' when it cannot be found in time."""
    agent, transcript = payload.get("agent_id") or "", payload.get("transcript_path") or ""
    session = payload.get("session_id") or ""
    if not agent:
        return ""
    name = f"agent-{agent}.meta.json"
    # The first live probe found no meta file from the parent-transcript guess alone, so every place the runtime puts
    # it is searched: beside the given transcript, under it, and under the session's folder in any project.
    patterns = [os.path.join(PROJECTS, "*", session, "subagents", "**", name)] if session else []
    if transcript:
        patterns += [
            os.path.join(os.path.dirname(transcript), name),
            os.path.join(os.path.splitext(transcript)[0], "subagents", "**", name),
        ]
    deadline = time.monotonic() + META_WAIT
    while True:
        for path in (p for pattern in patterns for p in glob.glob(pattern, recursive=True)):
            try:
                with open(path, encoding="utf-8") as fh:
                    model = str(json.load(fh).get("model") or "").lower()
            except (OSError, ValueError):
                continue
            return next((tier for tier in MODEL_CAPS if tier in model), "")
        if time.monotonic() >= deadline:
            return ""
        time.sleep(0.05)


def main(payload):
    session, prompt = payload.get("session_id") or "", payload.get("prompt_id") or "none"
    if not session:
        return
    model = model_of(payload)
    folder = os.path.join(STATE, session, prompt)
    os.makedirs(folder, exist_ok=True)
    marker = os.path.join(folder, f"{payload.get('agent_id') or time.monotonic_ns()}.{model or 'unknown'}")
    with open(marker, "w", encoding="utf-8") as fh:
        fh.write(time.strftime("%Y-%m-%d %H:%M:%S"))
    started = os.listdir(folder)
    same = sum(1 for name in started if name.endswith("." + model)) if model else 0
    if len(started) <= CAP and (not model or same <= MODEL_CAPS[model]):
        return
    os.remove(marker)
    what = f"{MODEL_CAPS[model]} {model} agents" if model and same > MODEL_CAPS[model] else f"{CAP} agents"
    sys.stderr.write(
        f"Agent cap: this prompt has already started {what}, the most one prompt may start (hooks/agent-cap.py, "
        f"caps {MODEL_CAPS}, total {CAP}). Do the remaining work with the results you have, route it to a cheaper "
        "tier, or ask the user to raise the cap."
    )
    sys.exit(2)


_common.run("agent-cap.py", main)
