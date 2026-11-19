# Running a project on Linear

The Linear workspace in `scripts/linear_ops.json`. Team ERG holds every Hexis-driven product as a Linear Project
(Hexis, ...). Everything here is done with `python ~/.claude/scripts/linear_ops.py [--project P] <command>`
(config `scripts/linear_ops.json`), which writes as the Claude app. Sessions use the `linear-mcp` MCP (Vercel, /claude); the CLI keeps what touches local files (release, sync-state, brief/report files).
The rules are in `rules/linear.md` (the access limit) and `skills/hexis-linear/` (policy; full text in its reference.md).

## The shape of a project
- **Milestone = one release version** (`v0.24`, `v0.25`, ...), plus `運用` for the tooling around the work
  and `非リリース` for work that ships no version. An issue carries exactly one milestone.
- **Label = theme** (workspace-wide; team-scoped label creation is refused for the app). Themes never
  become milestones.
- **Cycle = one week**, once cycles are enabled on the team (`cycle-open` / `cycle-status`). None exist yet.
- **Delegate = Claude** on every issue Claude works on. **Assignee = the user** only after a handoff.
- **Title and every comment are Japanese**; ids and paths stay as they are.

## Description versus comment
- The **description** is the spec, rewritten at most once, when the work starts: 目的 / 対象 / 仕様 / 検証 /
  元の依頼 (the user's own words, kept verbatim at the bottom).
- A **comment** is the running record: one per settled finding, per state change, per release. It names
  the evidence - the file and line, the test names and counts, the SHA.
- Issues the user must decide or verify in game carry 【判断】 / 【ゲーム内検証】 in the title.

## Done, handed off, canceled
- `done ERG-n "<comment>"`: finished and verified here.
- `handoff ERG-n "<what they must do>"`: the remaining step is the user's. It comments the step, makes the user
  the assignee and keeps Claude as the delegate. That assignment is the notification. Say it in the reply
  too.
- `cancel ERG-n --reason "<why>"`: no longer applies. Never delete.
- A state the user set is authoritative; never move an issue back because STATE.md lags.

## Inbox
`inbox` lists the app's unread notifications (the user's @claude mentions, assignments, replies) and marks
them read (`--peek` leaves them unread). Each one is input on its issue: answer and act there.

## STATE.md and Linear
`sync-state` prints the still-open `pending[pNN]` lines of this project's STATE.md that no issue covers. It
creates nothing. File the real work with `new`; session bookkeeping stays in STATE.md. It reads only STATE.md pendings, not PROGRESS.md `## Open`.

## A release
1. `release-check <milestone>` lists what is not closed and exits 1 if anything is. Nothing ships while it
   does.
2. Ship: tests green, the version bumped once for the set, binaries copied out.
3. `release <pipeline> --version X.Y.Z --sha <8 hex> --notes "<one Japanese line>" --issues ERG-a,ERG-b
   [--milestone M] [--tag]`. It:
   - creates the Linear Release in the pipeline (for example a Scheduled pipeline with stages Canceled /
     Planned / In Progress / Released);
   - links the issues and comments `vX.Y.Z で配置` on each;
   - writes the `VERSION_HISTORY.md` heading.
   A patch shipped mid-milestone is the same command with `--issues` only. Re-running changes nothing.
4. Unverified until the first live release: whether a Scheduled pipeline accepts a release created
   directly in the Released stage.
