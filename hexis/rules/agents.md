# Agents, workflows, and model routing

## Budget
- Use subagents and workflows where they actually save wall-clock time: parallel investigation of independent areas, broad codebase or web searches, design and review passes that can run while you keep working. Don't hold back on those - and note that they also save money, because an agent starts with a fresh, small context while this session re-reads its whole one on every tool call ("Cost statement before any run").
- Don't use them for sequential work (applying config, environment setup, small fixes); do and verify that yourself.
- Size: a handful per stage (roughly 3-8). No refutation panels, no multiple verifiers per finding, no "final verification" swarms; one reviewer per lens at most. Dozens of agents is never acceptable, even with ultracode on.
  Enforced (right-sized and minimal even under ultracode): `workflowSizeGuideline: "medium"` (<10 agents,
  advice to Claude) in settings.json, and `hooks/agent-cap.py` on SubagentStart denies any agent past 24 per user prompt (p90 of past runs) and past a
  per-model count (fable 2, opus 16, sonnet 16, haiku 24 - sized so a full raw-data analysis run fits; the model read from the runtime's agent meta file), workflow agents included (a denied workflow agent returns null to its script).
  Over-provisioning is judged by Jev, not by keyword rules: `hooks/route-check.py` on Agent and
  Workflow asks one Noul per agent whether its model or effort sits above the lowest row of the routing table below that
  covers its task; a flagged launch is denied once with the agents named, and the same launch sent unchanged passes, so
  a deliberate choice stays possible. Keyword rules are added only if its log shows Jev missing plain cases.
- Never ask before launching an Agent: send the cost line ("Cost statement before any run" below), then start in the same turn. That line replaces the confirmation, and an ask of your own is never a substitute for it.
- **The user wants workflows used without being asked each time** (the point is that the user does
  less). The gate is the HARNESS's, not the user's: a Workflow runs only after an opt-in the harness recognises - the
  user's own request in that session (a standing "use workflows" counts for the whole session), `ultracode`, or a skill
  that calls it (`permissions.allow` is not the only gate). In a session that carries such an opt-in, run a workflow
  for any task with independent parts without asking; in one that does not, run the parts as parallel Agent calls and
  say in one line that a workflow is available.
- **Independent parts launch together.** When a task splits into parts that do not wait on each other, launch their
  agents in the same message (2-4 at once), not one after another. Time matters here: do not spend time that can be
  avoided, and the earlier a correct result is obtained, the better. (That sentence is Anthropic's recommendation for
  multiagent harnesses on Opus 5.5 - it makes a lead agent parallelise more; platform.claude.com
  prompting-claude-opus-5-5, "Time signals".)
- For many-item batches follow `process/fan-out.md` (or the saved `fan-out` workflow).

## Model routing
- The main conversation runs on whatever I selected; you cannot change it. But every Agent call and workflow `agent()` sets `model` explicitly. A launch without `model` is denied outright by `hooks/agent-guard.py` (see the enforced section at the end), and the env backstop `CLAUDE_CODE_SUBAGENT_MODEL` behind it is `claude-haiku-5-5`, so nothing inherits the main model by accident and a slip is cheap and visibly useless rather than silently expensive - but that is a backstop, not a routing decision: haiku and sonnet work still has to be routed by hand. On Max plans there is ONE weekly pool for all models (support.claude.com article 15424964:
Max and Ultra, every Fable model): Fable draws from it faster than other models and may take at most
50 % of it; past that, Fable needs usage credits. The panel's Fable bar is progress toward that cap, not a second
pool, so moving work off Fable onto Opus 5.5 or Sonnet 5.5 relieves the weekly limit directly. Read the panel for
which bar is closer to its end (desktop: `mcp__ccd_session_mgmt__get_usage`), or ask the user where no tool reads it.
- Tier names resolve to the IDs in CLAUDE.md "Models" (Fable 5.2 / Opus 5.5 / Sonnet 5.5 / Haiku 5.5), pinned via `env.ANTHROPIC_DEFAULT_*_MODEL` in settings.json (`fable` to `claude-fable-5-2`, `opus` to `claude-opus-5-5`). Two things matter for routing on Opus 5.5: its API default effort is `medium`, so an unpinned Opus 5.5 launch inherits the session effort but an external `claude -p` call without `--effort` thinks at `medium`; and thinking cannot be disabled on it at any effort, so `low` is the floor, not off.
- Prefer the pinned agents in `~/.claude/agents/`: `grep-scout` (haiku), `docs-lookup` (sonnet), `implementer` (opus), `auditor` (fable, audits only, never under a Fable main), `auditor-opus` (opus, the audit agent under a Fable main). Use the tiers below when none fits.
- `haiku`: retrieval and mechanical work with no judgement. Locate files or symbols, grep sweeps, read a doc page and quote it, inventories and listings, format conversion, run a fixed command and report its output, check that a file or URL exists.
- `sonnet`: reading comprehension without deep reasoning. Summarise docs or threads (claude-code-guide lookups included), explore a codebase and report its structure, draft boilerplate or tests from a clear spec, single-lens review of a small diff, web research with synthesis.
- `opus`: judgement. Design decisions, debugging with an unclear cause, multi-file implementation, security review, audits, and any analysis that derives numbers or classifications from raw data (game data, logs, sequences) even if it looks like "just reading". A Sonnet 5 result that needs an Opus 5.5-level fix costs more than Opus 5.5 from the start.
- `fable`: the cross-model auditor (see "Audit: evidence first, a different model second" below), at effort `high` or above, in a fresh small context - plus any task I name it for. Never for retrieval, never for implementation that Opus 5.5 can do, never a second auditor on the same finding, and never under a Fable main, where the main's own final pass is the Fable audit ("Audit" below).
- Opus 5.5 briefs open with "read the relevant sources before acting" - Anthropic's own prompting note for it (it gets to work quickly on loosely specified tasks).
- **Sonnet 5.5 is the default; Opus 5.5 is the exception that must be argued for.** Every Opus 5.5 launch line
  names the trigger that earns it, in the launch message, from this list: an unclear cause to debug,
  a design decision, a multi-file implementation, a security review, an audit, or a derivation from
  raw data. No trigger named means the agent goes to Sonnet 5.5. "It is important", "to be safe", "it
  touches the save format" and "the brief is long" are not triggers. Measured on Opus 5: an Opus agent
  averaged $7.95 (about $6.4 at Opus 5.5 rates) and a Sonnet 5 agent $1.06, so an unargued Opus 5.5 is still a
  ~6x charge for an unmade decision.
  Scope: the default covers work without reasoning - summaries, listings, specified edits. Where the task needs
  reasoning, Sonnet 5 was not the cheap option (measured on Sonnet 5; Sonnet 5.5 is not yet measured): it solved
  fewer problems at every effort and cost 2-5x Opus 5.5 at the same effort, because it thinks longer. Such work goes
  to Opus 5.5 at medium or high; xhigh gave the same verdicts as high at 1.86x the cost, and max is for a task high
  already failed.
- **Never poll a background job.** A build, a test run or a long command is started in the foreground
  and waited for: one request. Backgrounding it and checking back costs one full-context request per
  check and produces nothing (Sonnet 5 agents polling a `cargo test` burned ~$10). Background only what the turn genuinely
  continues past, and then wait on the completion signal rather than asking again. This applies to the main session
  as much as to agents.
- Between two tiers, take the cheaper one and escalate only if its result is insufficient. Before any fan-out over many items, trial-run one item per tier, review it, fold the error patterns into the brief, then commit the rest. When reporting a subagent's result, say which model it ran on.

## Effort
Effort is how much thinking a turn spends before answering, billed as output tokens. A subagent
**inherits the session's effort** unless its definition pins one, so an Opus 5.5 agent launched from a
High session thinks at High whether the task needs it or not. Route effort by the task, exactly as you route the
model.

| effort | what it is for |
|---|---|
| `low` | retrieval, listings, format conversion, fixed procedures, short replies |
| `medium` | implementation from a clear spec, summaries, single-lens review of a small diff, writing briefs |
| `high` | debugging, design, multi-file implementation, audits |
| `max` | ambiguous derivation from raw data, security review, a task `high` already failed once, the final audit before a deploy |

- **Effort ladder: the main runs at the effort the user sets per session (a Fable main at `max`; think only as far
  as the next act needs). On Opus 5.5, high = xhigh on verdicts at 1/1.86 the cost. `"ultracode": true` in
  settings.json (workflows without asking each session; ultracode sends `xhigh`). The main is the router, not the
  template: its judgement picks each agent's model and effort for the task from the table above - retrieval `low`,
  summaries and specified implementation `medium`, design and derivation `high`, `max` only for the rows that name
  it - and nothing inherits `max` by default (agent-guard denies it). Workers `medium`, the Fable audit `high` and
  up.** Measured on Opus 5.5 (`max` gave no more output per request than `xhigh`): output per request `high`
  700-1,100 tokens, `max` 1,230-1,740. An UNPINNED agent (general-purpose, Explore, Plan, claude-code-guide) inherits
  the main's effort: route cheap work to a pinned definition (grep-scout, docs-lookup, implementer) or state the
  price in the cost line.
  Anthropic sets Opus 5.5's default at `medium` and states Opus 5.5 at `medium` beats Opus 5 at `high` on coding
  and knowledge work, so implementation at `medium` costs less than it used to and is no worse. The gap between
  a `high` main and `medium` workers is a cost lever, not an independent check - same model, same blind spots;
  independence comes from evidence and from the Fable audit.
- The Agent tool has no effort argument: an agent inherits the session's effort unless its definition pins one, and
  `hooks/agent-guard.py` enforces it: an agent without an `effort` pin is denied while the session runs at
  `xhigh` or `max`, and a Workflow is denied when any `agent()` call lacks inline `model` and `effort`. So effort is
  routed by choosing the definition. Per-task effort still belongs to agents, not to switching the main: every main
  request re-reads the whole context, and the thinking a higher effort produces stays in it (an effort switch itself
  does not re-cache the context). Pins in `~/.claude/agents/`
  (frontmatter `effort:` / `model:`): grep-scout and lesson-recall `low` (haiku), docs-lookup `medium` (sonnet),
  worker `medium` (sonnet - mechanical or well-specified work with edits), implementer `medium` (opus), analyst
  `high` (opus - design synthesis, reviews, derivation from raw data, one report file), auditor `high` (fable - the
  cross-model audit) and qa-gate `xhigh` (fable - the final audit before a deploy), both only under a non-Fable
  main, auditor-opus `xhigh` (opus - the audit agent under a Fable main), raw-analyst-max `max` (opus - ambiguous
  derivation from raw data). A new or changed definition is picked up only by sessions started after it.
- Every Workflow `agent()` sets `effort` explicitly, the same way it sets `model`.
- By tier when no pinned agent fits (Workflow `agent()` takes `effort` directly): Opus 5.5 `medium` for
  implementation, `high` for debugging and derivation, Sonnet 5.5 `low`-`medium`, Haiku 5.5 `low`, Fable 5.2
  `high` or above and only for audits.
- Main effort is set per session by the user (read `$CLAUDE_EFFORT` in the Bash tool; set it with the desktop
  `set_session_effort` tool, or ask me to switch it in the CLI; state it in the cost line). A Fable audit runs at
  `high` or above: `xhigh`/`max` for the final audit before a deploy and for ambiguous raw data.

## Session roles by main model
- **Main model: Fable 5.2, with Opus 5.5 workers; the Fable-main rules below apply.** Cost is requests x context x rate, and the main holds hundreds
  of thousands of tokens over hundreds of requests. Fable 5.2 re-reads at Opus 5.5's rate ($0.20/M); its 1h cache
  write ($16 against $8/M) and its output ($40 against $20/M) are twice Opus 5.5's, so a cold re-cache and long
  output are what a Fable main pays extra, and reading and bulk work go to agents all the more.
- **Inline or agent is decided per task, by what the read leaves behind.** The number that
  decides is **how much new material stays in the 1M context**, not how much is produced: material that stays is
  re-read by every later request, so a grep over a million lines that prints twenty costs nothing to hold, while
  a 50k-line dump pasted inline is paid for again on every request that follows.
  - Under **~20k tokens of new material with a short answer**: inline - cheaper and far faster than briefing an
    agent. The threshold falls as the session lengthens; on Opus 5.5 ($8/M to cache 1h, $0.20/M to re-read)
    against a ~$1.5 Sonnet 5 agent the break-even is ~80k tokens with 50 requests left, ~55k at 100, ~30k at 200,
    ~17k at 400.
  - Over it, or whenever the output is bulk (save dumps, disassembly, whole-file reads, table exports): an agent,
    and the longer the session has left to run the more decisively so.
  - Worked case (on a Fable 5.1 main): 80k tokens of disassembly inline at 226k context came to ~$10 against ~$9
    for the Opus 5 agent that did it instead.
  - Unchanged: the cost line before every launch, ONE Opus 5.5 implementer for a multi-file change (worktree
    isolation only when several edit in parallel), audit the returned "decisions and uncertainties" section and
    the diff, and do not read raw subagent output in full.
- The main session may do judgement work directly, but the tier split still holds - retrieval, sweeps,
  inventories and mechanical edits go to haiku/sonnet (an agent, or a workflow when the items are independent),
  because doing them inline bills them at the main's rates with the whole session context re-sent.
- Sequential environment work (config, installs, small fixes) can be done turn by turn on the main
  session; hand it to ONE agent only when it is long enough that the session's context makes each step dear.
  Subagents inherit CLAUDE.md, so the machine's tool-shell pitfalls recorded in knowledge/ and the skill
  `hexis-shell` (on Windows: Job object, WMI starts, UAC needs the user) apply to them too.

## Audit: evidence first, a different model second
A model auditing its own kind of work shares its blind spots: Opus 5.5 checking Opus 5.5 catches slips, not the
systematic misses, so "escalate to Fable when Opus fails" is circular while Opus is also the one deciding what
failed. Two things are independent of the worker, and an audit uses them in this order:
- **Evidence outside any model**: a test, a before/after diff of a file the program itself wrote, an exe write
  site, the user's in-game check. Where such evidence exists, the audit is the comparison against it, and the
  model tier does not matter. A claim that could have evidence and has none is a finding in itself.
- **A different model**, only where evidence cannot close the question - design choices, interpretation of raw
  data, a named root cause: the work of Opus 5.5 (or Sonnet 5.5) is audited by Fable 5.2 at effort `high` or above,
  in a fresh agent that reads the report and the diff, never by another Opus 5.5. One auditor per finding.
- **Code always gets that Fable audit before it is presented as done, committed or pushed, whoever wrote it - an
  agent or the main session itself, the main's own inline code included, with no exception** (rules/quality.md
  "Every deploy is gated"). Parallel implementers can each build one feature their own way while gates and pixel
  diffs pass. Tests, type checks, builds and screenshots prove behaviour and looks; they say nothing about
  structure - work duplicated across parallel workers, a responsibility in the wrong module, drift from the
  handoff's stated requirements - and are never presented as showing quality or the absence of bugs. Run `auditor`
  (`high`) on the combined diff, the worker reports and the original request or handoff text, and `qa-gate`
  (`xhigh`) as the last pass before every deploy or install. When several implementers run in parallel, the audit
  covers their combined result, not each part alone.
- **Under a Fable main no Fable agent audits: the Fable audit is the main's own final pass** (a Fable `auditor`
  under a Fable main spends Fable twice on one check, out of the Fable share of the weekly pool). The chain there:
  the worker; then, over Sonnet 5.5 work and over Fable 5.2 work - the main's own inline code included - one audit
  agent in a fresh context on Opus 5.5 at `xhigh` (`auditor-opus` - a different model from the author, so Opus 5.5
  work gets no audit agent, and an `auditor-opus` its safeguard refuses is reported, not replaced: that work is
  reported as not audited); then the main, last and in place: the combined diff, the worker reports and the
  agent's findings against the original request or handoff text. Over code the main wrote itself that last pass is
  a same-model review, never the audit: there the agent's verdict is the audit. Before every deploy or install
  `auditor-opus` also applies the `qa-gate` checklist (agents/qa-gate.md) and the main's final pass is the gate -
  over the main's own code the agent's verdict is; both verdicts are reported. Under any other main the two
  bullets above stand as written - he moves a session's main to Opus 5.5 when he wants the Fable agent.
  `hooks/route-check.py` stops a launch that puts an agent on Fable under a Fable main once; the same launch passes
  the second time, for a Fable agent he named. The worker's tier is routed as above; his proposal of Sonnet 5.5 at
  `max` as the worker under a Fable main is open with him.
- Disagreement between worker and auditor is settled by evidence or put to the user; see "Inheriting a higher
  tier's conclusion" for why rank does not decide it.
- A known-answer audit measures this arrangement: the same brief audited by Opus 5.5 and by Fable 5.2, counting
  misses. If Fable 5.2 does not catch more, the arrangement is revisited.
- **Money and gate decisions are judged by closed questions, never by a prose reviewer.** Where a decision
  moves his money or passes a gate (a live set, a deploy, a re-entry), the independent check is Jev answering a fixed set of
  closed questions with probabilities behind a WRITTEN gate that code applies - confidence never sizes anything, no
  answer means no pass, the calibration is tabled weekly - and no talking model (Fable 5.2, Opus 5.5 or any other)
  writes the verdict: Fable / Opus prose reviews have returned persuasive PASS-WITH-CONDITIONS verdicts on changes
  that lost money. A departure from the written gate is reported to him as a departure, never justified in prose. The
  Fable audit above stays for code, designs and derivations, not for gates.

## Routing by task, and the fallback chain
- Nominal tier order is **Fable 5.2 > Opus 5.5 > Sonnet 5.5 > Haiku 5.5**, but on Anthropic's own published set
  Opus 5.5 scores at or above Fable 5.1 (Fable 5.2 is not measured here), so the order decides price and
  role, not who is right. Route by the TASK, not by habit: mechanical / well-specified work (apply a brief,
  regenerate an export, mechanical edits) -> Sonnet 5.5; trivial lookups -> Haiku 5.5; investigation, table /
  value analysis of raw data, deriving numbers and multi-file implementation -> Opus 5.5; the audit of a judgement
  -> a model other than the one that made it, i.e. Fable 5.2 over Opus 5.5 work.
- When the tier in use hits its limit, drop exactly one step (Opus 5.5 subagent 429 -> Sonnet 5.5), and
  re-audit a downgraded result with the higher tier once it is back. When Fable is out (its 50 % share of
  the weekly pool is spent), a cross-model audit waits or goes to the user - it never falls back to the same
  model as the worker, because that is no longer an independent check.
  Never skip an available tier downward, and never "upgrade" past the routed tier because a lower
  one is busy.
- A subagent must not spawn its own child on a tier known to be rate-limited; if its tier is out,
  it does the work itself on the model it is running on.

## Inheriting a higher tier's conclusion (applies everywhere, not to one project)
Quality order is **Fable 5.2 > Opus 5.5 > Sonnet 5.5 > Haiku 5.5**. A lower tier is, by definition, worse at the
judgement that produced a higher tier's conclusion. So:

- When a session is moved DOWN a tier mid-task - the refusal fallback (`switchModelsOnFlag`), a
  manual `/model` switch, a rate limit, or a subagent running below the main model - the conclusions
  the higher tier already reached are **inherited as established**. Continue from them. Say in the
  first line that the tier changed, then keep working from where the higher tier stopped.
- Do **not** re-derive, re-audit or "verify the premise" of a higher tier's finding. If it named a
  file, a table or a row as the next place to look, that is the next place to look.
- A higher tier's conclusion may only be overturned by **concrete contradicting evidence** (a byte,
  a row, a log line), never by a lower tier's own reasoning or by a clean sweep of everything else.
  State the evidence explicitly when overturning one.
- The same applies to a subagent's result: never let a lower-tier agent re-open a question the main
  session already settled; give it the settled facts in the brief.
- A cross-model audit is the exception to rank: when the Fable auditor disagrees with Opus 5.5 work,
  neither wins by tier. The disagreement is settled by external evidence (a test, a program-written diff, an
  exe write site, the user's in-game check), or it goes to the user as an open question with both positions.

## Credits mode (a state with an end)
- While the account spends purchased usage credits (a limit is hit and extra usage is on), the launch rules above are
  suspended: no subagent, workflow or fan-out without the user's explicit yes in that turn, estimates in dollars,
  recommend pausing until the reset, resume on the cheapest tier that can do the job, briefs ask for tight work; the
  sessions he named go on.
- It is recorded as a state, never as a note: the session he tells runs `python ~/.claude/hooks/credits_mode.py on`,
  which holds it until the next weekly reset (Monday 00:00 JST, as the usage card shows; `--until` for
  an earlier end, `off` on his word). `hooks/cost-meter.py` puts `CREDITS MODE ON until <time>` into every prompt of
  every session while it lasts and nothing once it is over, and flags a PROGRESS.md line that still speaks of
  credits mode when none is active, on every prompt until the line is gone. Nothing is labelled as paid from
  credits without that line in the turn. The usage card is the truth (desktop:
  `mcp__ccd_session_mgmt__get_usage`; extra usage disabled means no credits are spent).
- With extra usage off, a hit limit means waiting for the reset; every session keeps its spend small,
  the routing policy above, Sonnet included, is unchanged and cost is still weighed.

## Cost statement before any run (ABSOLUTE)
Before launching ANY subagent, workflow, fan-out or long autonomous job, state in the same message,
BEFORE the launch: **count, model, effort, expected requests, expected context, dollars, comparison**,
in that order. Never launch without that line; never quote tokens without the dollar figure; never use
a rate that is not in `knowledge/model-pricing.md` (re-verify the file when in doubt). For work done in
the main session, give the same estimate at the start of the task. Quote the usage page afterwards when
the user asks.

The measured model (from the transcripts themselves - `scripts/session-cost.py`):

    cost = requests x average context x cache-read rate
         + new tokens x cache-write rate
         + output x output rate

- **Requests x context is the bill, not the work.** Every tool call is one API request that re-reads
  the whole context; a tool-using agent makes **50-120 requests**. On one measured session, 338 requests re-read
  58.4M cache tokens: 95.8 % of the TOKENS, but 45.4 % of the $54.82 - cache writes were 33.6 % and output 20.9 %.
  Writes are therefore a third of a real bill, and most of them are cold re-caches - a resume after an idle gap past the
  cache TTL, or a model switch, re-writes the whole context at the write rate.
- **A subagent or a workflow `agent()` starts with a fresh, small context. That is the main reason to
  delegate; the model's price is secondary.** The main session's own turns re-read their whole context
  on every tool call, so the same work costs multiples in a long session - 60 tool calls at 300k are
  ~$3.60 of cache read on the main ($0.20/M on Fable 5.2 and Opus 5.5 alike) before anything is produced, against ~$1 for an Opus 5.5 agent that starts
  at 30k.
- The COMPARISON is therefore: expected requests x the *agent's* growing context (fresh, small) against
  expected requests x **this session's live context, taken from the cost meter's `avg $ per request`**,
  never from a guess - while the band is visible the meter injects no figures, so read the saved line
  `~/.claude/logs/cost-meter/$CLAUDE_CODE_SESSION_ID.txt` (one Bash call) for the cost statement. The cheaper path is taken. Fable 5.2 is the most expensive model in the lineup: the
  main session dispatches, briefs and audits; implementation, data reading and analysis go to the
  cheapest tier that can do them (Opus 5.5 for judgement, Sonnet 5.5 for mechanical).
- **Audit in place; do not re-read through a second agent.** Read the diff and the files once, then
  audit them in the session that holds them; re-launching an agent that has to read them again pays
  the read twice, and chopping the session mid-audit pays it again on the rebuild. On cost alone an audit belongs on
  the cheaper model (Opus 5.5: $8/M 1h cache write and $20/M output against Fable 5.2's $16 and $40, the same
  $0.20/M re-read); Fable is chosen for an audit for quality, or when the session is already on it and the
  re-cache of a switch would not repay within the requests left.
- `hooks/cost-meter.py` injects the live figure on every prompt - session total, main vs agents, last
  turn, context, average per request. Quote the figure in the cost line. Never propose a handoff - not on
  spend, not on context size, not near the auto-compact window: compaction is accepted,
  while a handoff chops the work and the rebuild repeats it. The main context is kept small by sending
  reading and bulk work to workflows and agents.
- The figure is also reported when the run *finishes*: model, effort, requests, context and the dollar
  figure computed the same way, labelled as an estimate, with the usage page as the truth.

## A subagent does the work; it does not re-delegate
An agent given a brief carries it out itself. It must not spawn a child to do the brief for it, on
any tier, high or low. A re-delegation costs the brief twice, moves the work to a tier the caller did not price,
and orphans the run: when the agent's parent turn has already ended, the child runs unsupervised and the caller
has to recover it by hand.
State this in every brief that could be read as "arrange for this to happen": the agent does the
work in its own turn and returns the result, and if it cannot, it says so instead of delegating.

**Enforced, not advised:** `hooks/agent-guard.py` runs PreToolUse on `Agent` and DENIES,
in every permission mode including bypassPermissions, (a) any launch whose `model` is missing or is
not one of haiku/sonnet/opus/fable, (b) any `Agent` call made from inside a subagent, and (c) a `model` that
differs from a pinned agent's frontmatter tier (the launch value would override the pin). The env
backstop `CLAUDE_CODE_SUBAGENT_MODEL` is `claude-haiku-5-5`, so anything that ever slips past
the hook is cheap and visibly useless rather than silently expensive. A denial is not a thing to work
around: route the agent and launch it again.
