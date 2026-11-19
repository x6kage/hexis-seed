# Fan-out procedure

For any workflow that runs the same task over many items (characters, files, tickets).

1. Scout inline first: list the items, build the work-list, generate any per-item brief mechanically (tables, precomputed values, checklists). The brief narrows what the agent has to judge.
2. Require a "decisions and uncertainties" section in every agent's output. Reviewing that section is cheaper than re-deriving the whole result.
3. Trial-run one item per model tier you intend to use. Review both. Fold every error pattern into the brief's checklist and regenerate the briefs.
4. Pick the tier from the trial, not from the plan. Set `model` and `effort` explicitly on every `agent()` call.
5. State the agent count and expected cost before launching the batch. A handful per stage; say so if more.
6. Launch with `pipeline()` (no barrier unless a stage needs all prior results). Log anything dropped or capped.
7. One review pass by the main model, merge, report with the dollar figure (model, tokens, tool calls, estimated cost). No refutation panels, no multiple verifiers per finding.
8. Before the launch, send the cost line required by `rules/agents.md` "Cost statement before any run". No launch without it.

