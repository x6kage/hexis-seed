# Context and persistence

## Written records are English restatements, at full resolution
Memory files, `PROGRESS.md`, `STATE.md` (project and global), `inbox/`, `knowledge/` and `decisions/` are written in English.
This is not translation and not transcription: the line is a **self-contained English restatement**
that carries what was decided, why, and how it applies, so a session that never saw the conversation
acts on it correctly from the line alone. Never copy the user's sentence, in either language.

The restatement must not lose resolution. Understanding already happens in English, so there is no
reason for the record to be vaguer than the input was:

- **Keep the force.** "Kill it", "never", "at the die level" stay that strong. A rule restated as a
  suggestion is a different rule.
- **Keep the scope and the exceptions.** What it covers, what it excludes, what the trigger is. Drop
  none of it because the sentence gets long.
- **Keep the distinctions**, including ones that are awkward in English. When a term is the precise
  one, keep it verbatim and gloss it rather than paraphrasing it away.
- **Test it before saving:** could a later session, holding only this line, reach the same decision?
  If not, it is too short or too soft, not too long.
- **Verbatim in their original form**, never translated: in-game terms, identifiers, hashes, paths,
  commands, file names, Plane work item titles, UI labels.

This restates the CLAUDE.md language rule and `rules/output.md` ("never quote my words back at me") with the
fidelity bar attached: the user's own sentences are never copied into memory files or STATE lines.
- **The timestamp on a STATE.md line or a PROGRESS.md `Updated:` line is read from the machine, never carried
  forward.** Run `date` (or read a fresh commit's `%ci`) before the first write of a turn and use that clock. Never
  extrapolate from the previous line, from the handoff's stamp or from how long the turn felt: a
  session can sit idle for hours between turns, and extrapolated stamps then put work hours away from when it was
  done, across a gap nobody notices.
  A log whose clock is invented is worse than no log, because the next session trusts the order.
- My context compacts at up to 1M tokens and the summary is lossy, so nothing lives in your head. In a project that has `~/.claude/projects/<dir>/memory/PROGRESS.md`, that file is the working note: rewrite it whenever the state changes, so that it holds the current state (`## Now`), every open item (`## Open`) and the next step (`## Next`) and nothing else, under 80 lines; it is injected whole at every session start, and the Stop hook blocks a turn that edited files without rewriting it. Decisions and lessons are applied on the spot to `knowledge/`, `decisions/` or the rules instead of being logged; a finding that cannot be applied yet goes to `~/.claude/inbox/YYYY-MM-DD-<topic>.md` with `expires: YYYY-MM-DD` as its first line, and is consolidated into `knowledge/` or dropped, then deleted. That project's STATE.md is frozen history, read only when a detail is needed. In a project without PROGRESS.md: append every verified fact, decision, path, hash, command that worked and pending item to this project's `~/.claude/projects/<dir>/memory/STATE.md` (format `- YYYY-MM-DD HH:MM <kind>: <text>`, kinds `fact|decision|path|hash|cmd|pending|ruled-out|done|graduated`) at the moment you learn it. The SessionStart hook replays its tail at every session start plus every still-open `pending[pNN]` line and every `decision` since the last `graduated: through <stamp>` marker, and the Stop hook blocks a turn that edited files without recording anything. Give each new pending the `next id` that context names, close a settled one with `done[pNN]` / `ruled-out[pNN]`, and append the `graduated` marker when you promote a stretch of lines - nothing is archived above it. Cross-project facts also go to `knowledge/`, why-decisions to `decisions/`, project state to that project's docs; procedure in `process/handoff.md`. After a compaction the summary is a hint only: work from PROGRESS.md (or STATE.md) and re-check the filesystem, and say so when a file does not have what you need instead of filling the gap from recollection.
- When a rule or a feedback memory is superseded, the memory file AND its MEMORY.md index line are rewritten or deleted in the same turn. A SUPERSEDED footer under an unchanged index line is contamination: the index is what every session loads, so the old rule is what the session acts on.

## From CLAUDE.md "Layout of ~/.claude"
- `projects/<dir>/memory/PROGRESS.md` is the project's working note: ONE file describing the current state, rewritten (never appended) whenever the state changes - `# Progress`, `Updated: YYYY-MM-DD HH:MM` from the machine clock, `## Now`, `## Open` (one bullet per open item; an optional `[slug]` at its start is a machine handle, never shown to the user), `## Next`, nothing else, under 80 lines. The SessionStart hook injects it whole plus the `inbox/` entries; the Stop hook blocks a turn that edited files without rewriting it.
- Decisions and lessons are applied on the spot to `knowledge/`, `decisions/` or the rules, not logged. A finding that cannot be applied yet goes to `inbox/` as one short file `YYYY-MM-DD-<topic>.md` whose first line is `expires: YYYY-MM-DD`; it is consolidated into `knowledge/` or dropped, then deleted.
- In a project that has PROGRESS.md, `memory/STATE.md` is frozen history: read it only when a detail is needed, never append to it. A project without PROGRESS.md still runs on STATE.md as follows. `projects/<dir>/memory/STATE.md` is the running record of the session's work: append-only lines `- YYYY-MM-DD HH:MM <kind>: <text>` with kind one of `fact|decision|path|hash|cmd|pending|ruled-out|done|graduated`, written the moment something is verified, not at the end. A pending line carries an id - `- 2026-09-20 09:15 pending[p12]: ...` - and is closed by any later line with the same id (`done[p12]`, `ruled-out[p12]`); an id-less pending is closed by a later `done` whose text starts with its first 30 characters. The SessionStart hook gives the next free id and injects three blocks at every session start (startup, clear, fork, resume, compact): `Recent` (the last 60 lines), `Open` (every still-open pending not already shown) and `Decisions since graduation` (every `decision` after the last marker), so nothing open ever scrolls out of view. The Stop hook blocks the turn when this session edited files and nothing was appended.
- In a STATE.md project, facts and decisions graduate out of STATE.md to a project memory file, `knowledge/` or `decisions/`, and the promotion is recorded as `- YYYY-MM-DD HH:MM graduated: through <YYYY-MM-DD HH:MM>`. That marker is the only thing that lets the hook archive: past 400 lines it moves only lines at or before the last marker, so an un-graduated STATE.md grows instead of losing its history, and past 15 open items, 20 un-graduated decisions or 300 lines the injection asks for `/handoff graduate`.
