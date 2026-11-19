---
name: hexis-linear
description: Use before any Linear action - a linear-mcp tool, a linear_ops command, filing, updating, handing off or reading issues - and when planning to track work there. Carries the Linear access limit and the operating policy.
---

# Linear

Full text: `reference.md` in this folder, `~/.claude/process/linear-ops.md`.

## 0. Linear is open
Linear is open for reads and writes under the policy below. Each project's issues live under its ERG project (Hexis, the research lane, and one per product); milestones carry per-project names, so pass UUIDs where a name is ambiguous. Outside Hexis, `hooks/tracker-lock.py` still denies the tools until it is retired.

**Plane is frozen:** nothing is written to Plane any more.

## Operating policy
The Linear workspace in `scripts/linear_ops.json`; team ERG = Hexis-driven work (products are Linear Projects). Sessions use the `linear-mcp` MCP; agents use `python ~/.claude/scripts/linear_ops.py`.
- **Agents are the delegate, never the assignee.** The user becomes assignee only when the next step is theirs, through `handoff ERG-n "<what to do>"`; that assignment is the notification, so no extra @mention. Say it in the reply too.
- **Mentions** only when a comment needs the user without handing the issue over. The user's `@claude` arrives in `inbox` and is input to act on, on that issue.
- **One topic per issue**; the conversation happens on the issue.
- **Never delete an issue.** One that no longer applies is closed with `cancel ERG-n --reason ...`.
- **The issue is the brief**: requirements (背景 / 要件 / 受け入れ条件 / 範囲外 / 想定 tier / 見積り) go into the description before any agent launch, and the brief text travels INLINE in the Agent prompt - never a one-line launch pointing at a brief file.
- **One agent run = one sub-issue** under the parent (`new "<what this run does>" --parent ERG-n`); the agent reports on it (`progress ... --report-file`); the session closes it.
- **Every completion report to the user is paired, in the same turn, with the Linear update.**
- **Milestones = release versions** (v0.24, ...) plus 運用 / 非リリース; one milestone per issue. Themes are workspace-wide labels, never milestones.
- **In Progress** only while an agent or the session is actively working on it.
- Titles and comments are Japanese; ids and paths stay as they are. Description = spec (rewritten at most once, when work starts), comments = running record naming the evidence.
- Done: `done ERG-n "<comment>"` when finished and verified here. A state the user set is authoritative.
- **Releases** through Linear Releases (`release <pipeline> --version X.Y.Z --sha <8hex> --issues ...`), after `release-check <milestone>` exits 0; `VERSION_HISTORY.md` is still written.
- A peer consultation gets positions only; any Linear write is "on the user's go" unless that go is on record. The shape of the user's project (parents, phases) is asked of the user, never asserted.
