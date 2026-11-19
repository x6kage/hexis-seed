# Linear operation

How every project is tracked.
The Linear workspace in `scripts/linear_ops.json`. Team:
- **Ergon (ERG):** all Hexis-driven work. Products are Linear Projects (Hexis, ...).

A research project holds the research lane (`process/research-lane.md`).

Tools:
- sessions: the `linear-mcp` MCP on Vercel (your deploy, registered in `~/.claude.json`; route `/claude` for Hexis, `/peer` for a second app identity; source `mcp/linear_mcp/`, spec `mcp/linear_claude/`);
- agents: `scripts/linear_ops.py`.

The procedure is in `process/linear-ops.md`.

- **Agents are the DELEGATE, never the assignee.** Claude takes an issue as its delegate (`linear_ops new`
  does this); the UI shows it in the assignee slot, marked as an agent. The human user becomes the
  assignee only when the next step is theirs, through `linear_ops handoff ERG-n "<what to do>"`. That
  assignment is their notification, so it is not used for anything else, and a handoff does not also
  @mention them.
- **Mentions carry attention and input.** Mention the user (by profile URL, `--mention`) only when a
  comment needs them without handing the issue over. The user's `@claude` on an issue arrives in the app's
  inbox (`linear_ops inbox`), and it is input to act on - on that issue.
- **The conversation happens on the issue, one topic per issue,** so a topic keeps its own context.
- **Never delete an issue.** One that no longer applies is closed with `linear_ops cancel ERG-n --reason ...`.
  The continuous numbering, cancellations included, is the record of the work.
- **The issue is the brief.** Requirements (背景 / 要件 / 受け入れ条件 / 範囲外 / 想定 tier / 見積り) go into
  the description before any agent launch. The brief text travels INLINE in the Agent prompt (the issue's
  text, pasted) - never a one-line launch pointing at a brief file: a file hides the brief
  from the Agent-launch hooks and the transcript and costs a Write plus the agent's Read of the same text.
  `hooks/brief-check.py` judges the inline brief against the user's own words at launch and keeps the checked
  text as the record (`logs/briefs/`); the brief file is made afterwards, never as the carrier.
- **One agent run = one sub-issue.** A large issue is the parent; each launch first creates a sub-issue under
  it (`linear_ops new "<what this run does>" --parent ERG-n`); the agent reports on it
  (`linear_ops progress ERG-n --report-file ...`); the session closes it.
- **Every completion report to the user is paired, in the same turn, with the Linear update.** The MCP is for
  the session, the CLI for agents.
- **Tier by `rules/agents.md`:** Sonnet 5 by default, Opus 5.5 only with a named trigger in the launch line.
- **Milestones = release versions** inside a product project (v0.24, v0.25, ...), plus 運用 / 非リリース.
  Themes are labels, and workspace-wide label groups are used.
- **Releases go through Linear Releases** (`linear_ops release <pipeline> --version X.Y.Z --sha <8hex> --issues
  ... [--milestone M]`). It replaces the Plane wiki デプロイ履歴 and the old `deploy` command.
  `VERSION_HISTORY.md` is still written.
- **In Progress means an agent or the session is actively working on it**; nothing else stays In Progress.
- **Plane is frozen:** nothing is written to Plane any more.
- **Outside Hexis no session touches Linear, reads included** - `hooks/tracker-lock.py` denies every linear-mcp / plane-mcp tool and
  linear_ops / plane_ops for any cwd outside the home directory (`~`) / `~/.claude`.
- **After a Claude Code restart**, a stopped background agent is resumed by message (its transcript
  survives) before anything is re-launched.
- **Rule files are the admin side's:** a project session applies a new rule in its replies and hands the change to
  the Hexis session; it does not edit `~/.claude/rules` itself.
