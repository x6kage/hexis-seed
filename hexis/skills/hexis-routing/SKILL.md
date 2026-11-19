---
name: hexis-routing
description: Use before launching any subagent (Agent tool), Workflow or fan-out, or when deciding whether work runs inline or in an agent - how to pick model and effort, the mandatory cost statement, and the audit rule.
---

# Routing agents and workflows

Full text: `~/.claude/rules/agents.md`; prices `knowledge/model-pricing.md`.

## 1. Cost statement - before EVERY launch, same message
One line, in order: **count, model, effort, expected requests, expected context, dollars, comparison**. Never launch without it; it replaces asking. Dollars always, rates only from `model-pricing.md`. Comparison: requests x the agent's fresh context vs requests x this session's live context (the meter's `avg $ per request`, never a guess); take the cheaper.

## 2. Pick the definition (it routes effort)
The Agent tool has no effort argument: an unpinned agent inherits the session's effort (agent-guard denies it at `xhigh`/`max`).

| agent | model | effort | for |
|---|---|---|---|
| grep-scout | haiku | low | locate, grep, list |
| lesson-recall | haiku | low | recall lessons |
| docs-lookup | sonnet | medium | docs, summaries, web research |
| worker | sonnet | medium | mechanical or specified edits |
| implementer | opus | medium | multi-file implementation |
| analyst | opus | high | design, reviews, raw-data derivation |
| auditor | fable | high | cross-model audit |
| qa-gate | fable | xhigh | pre-deploy gate |
| auditor-opus | opus | xhigh | audit under a Fable main |
| raw-analyst-max | opus | max | ambiguous raw-data derivation |

Every launch sets `model` (one differing from a pin is denied); every Workflow `agent()` states `model` AND `effort` inline, or it is denied.

## 3. Effort by task
`low` retrieval, listings, format conversion, fixed procedures. `medium` implementation from a clear spec, summaries, single-lens review of a small diff, briefs. `high` debugging, design, multi-file implementation, audits. `max` ambiguous raw-data derivation, security review, a task `high` already failed, the final pre-deploy audit.

## 4. Model tier
- **Sonnet 5.5 is the default** without reasoning; Haiku 5.5 for retrieval. With reasoning use Opus 5.5 medium/high,
  not xhigh: Sonnet 5 cost 2-5x more and solved less (5.5 unmeasured).
- **Opus 5.5 only with a named trigger in the launch line**: unclear cause to debug, design decision, multi-file implementation, security review, audit, derivation from raw data. None named -> Sonnet.
- Fable 5.2 agent: audits only, `high`+, never under a Fable main.
- Take the cheaper tier, escalate only if insufficient; trial one item per tier before a fan-out (`process/fan-out.md`).

## 5. Inline or agent
Under ~20k tokens of new material with a short answer -> inline (the bar falls as the session grows); more, or bulk output -> agent. Sequential env work: inline.

## 6. Launching
- Independent parts launch together, 2-4 per message, 3-8 per stage; no refutation panels or verifier swarms.
- Workflows run without asking under a harness-recognised opt-in (the user's request, `ultracode`, a skill); otherwise parallel Agent calls; say a workflow is available.
- Every brief says: do it yourself, no child. Decided = settled facts only; open points "do not decide; return options + recommendation". Report each decision's basis (reference, user's words, measurement).
- **Never poll a background job**: builds and tests run in the foreground.

## 7. Audit
- Evidence outside any model first (a test, a program-written diff, an exe write site; the user's in-game check last). A claim that could have evidence and has none is a finding.
- Otherwise ONE auditor of a different model per finding, never Opus over Opus. All code, the main's own too, is audited before it is called done or pushed.
- Main not Fable: `auditor`; `qa-gate` before every deploy/install.
- Main Fable: no Fable agent. `auditor-opus` over Sonnet and Fable work, the main's own code too (plus the `qa-gate` checklist before deploy/install), then the main's final pass.
- Worker vs auditor disagreement is settled by evidence or goes to the user with both positions, never by rank.

## 8. After the run
Report model, effort, requests and dollars; audit its decisions section and the diff.
