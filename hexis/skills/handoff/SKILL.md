---
name: handoff
description: Close a session cleanly - bring PROGRESS.md (or, without it, STATE.md) up to date with everything verified this session, re-read the configuration, and print a handoff prompt for the next session. Use before ending, compacting or switching projects.
argument-hint: "[graduate, or an optional one-line focus, e.g. loader DLL]"
---

Work in three steps. The argument, when given, is the focus: it narrows "Read first" and "Next action" only, never what you record. The single argument `graduate` runs step 1's graduation part and its marker only, and prints nothing else; it does not apply to a project that has PROGRESS.md.

**1. Record.** If `<transcript directory>/memory/PROGRESS.md` exists, rewrite it and do not touch STATE.md, which is frozen history there: `# Progress`, `Updated: YYYY-MM-DD HH:MM` from `date`, `## Now` (the current state, with absolute paths where they matter), `## Open` (one bullet per open item naming whose decision it is; an optional `[slug]` at the start is a machine handle, never shown to the user), `## Next` (the single next step), nothing else, under 80 lines. Every decision and lesson of this session is applied to `~/.claude/knowledge/` (plus `knowledge/INDEX.md`), `~/.claude/decisions/` or the rules directly; a finding that cannot be applied yet goes to `~/.claude/inbox/YYYY-MM-DD-<topic>.md` with `expires: YYYY-MM-DD` as its first line. Put the session cost below in `## Now`. Then go to step 2.

Otherwise append to `<transcript directory>/memory/STATE.md`, where `<transcript directory>` is the directory that holds this session's transcript file - `~/.claude/projects/<key>/`, never the working directory and never a path rebuilt from the key. Create `memory/` if missing. Use the line format `- YYYY-MM-DD HH:MM <kind>: <text>`:
- every fact verified this session, with its absolute path, hash or command (`fact`, `path`, `hash`, `cmd`);
- every decision, with the why (`decision`);
- every pending item, naming whose decision it is (`pending[pNN]`, taking the `next id` the SessionStart context gave and counting up from there);
- everything ruled out, so it is never redone (`ruled-out`), and what was finished (`done`). A pending item that is now settled is closed by a `done[pNN]:` or `ruled-out[pNN]:` line carrying its id; without an id, repeat the pending line's first 30 characters so the pairing still works.

Also record what this session cost, as one `fact` line: run `python ~/.claude/scripts/session-cost.py <this session's transcript.jsonl> --subagents` and append its total, request count and per-request average - `- YYYY-MM-DD HH:MM fact: session cost $X.XX over N requests (main $Y, agents $Z), avg $A per request`.

Then **graduate**: for every fact and decision line written since the last `graduated` marker that is still true, promote it - project state to the project's memory file plus its `MEMORY.md` index line, cross-project facts to `~/.claude/knowledge/<topic>.md` plus `knowledge/INDEX.md`, why-decisions to `~/.claude/decisions/` - and then append one line `- YYYY-MM-DD HH:MM graduated: through <YYYY-MM-DD HH:MM>`, the timestamp being that of the last line covered. Only lines at or before a marker may ever be archived, so a STATE.md that is never graduated only grows.

**2. Re-read.** Run the `reload` skill's reread - `~/.claude/CLAUDE.md`, every `rules/*.md`, `knowledge/INDEX.md`, `knowledge/machine.md`, `process/INDEX.md`, the project's `memory/MEMORY.md` and `memory/PROGRESS.md` (or `memory/STATE.md` without it), and `git -C ~/.claude log --oneline -15` - so the handoff reflects the rules as they are now, not as they were when the session started.

**3. Print the prompt.** English, under 60 lines, inside ONE fenced code block (```text … ```) so it can be copied in one go, in exactly this shape, for the user to paste into a new session:

- A title line, in exactly this shape: `<YYYY-MM-DD HH:MM> <project directory> - <3-6 word topic>`, without the
  word "handoff": the app names a new session from its first message, and every pasted handoff came out as
  "Hexis Admin Handoff", which the user dislikes (a timestamp, or no title, is preferred).
  The timestamp is mandatory and comes from the machine clock, `date +'%Y-%m-%d %H:%M'` - never from the
  session's own sense of time, which drifts from the filesystem by hours. It is what makes one session
  distinguishable from the next in a list of sessions with the same project name, so it is never omitted,
  never shortened to a date, and never replaced by a topic alone.
- `Rename` - the line right after the title: `First, rename this session to "<the closing session's name>" with
  mcp__ccd_session_mgmt__set_session_title (session_id "self").` - the name other sessions know the closing session
  by (ListAgents shows it; for ~/.claude it is "Hexis Admin"). The user archives the old session and keeps one per
  lineage, so the new one simply takes the same name. The tool renames the calling session and
  replaces an app-generated title without asking.
- `Cost` - one line: what the session being closed cost, as recorded in step 1, so the next session knows the price of this work and what it may spend.
- `Read first` - the absolute path of `PROGRESS.md` (or `STATE.md` without it), of `MEMORY.md`, of the project's `CLAUDE.md`, and at most three other files, each with one clause saying why.
- `State` - `done` and `ruled out`, one line each, with absolute paths, and `pending` as one line per still-open item - each `## Open` bullet of PROGRESS.md, or each STATE pending with its `[pNN]` id.
- `Next action` - the single first thing to do and the exact command to run.
- `Do not` - the mistakes recorded in the `feedback-*` memories that touch this work, quoted one line each.
- `Model routing` - which tier does what for this work, per `rules/agents.md`.

The prompt may contain nothing that exists only in this session's context. If a fact is not yet in `PROGRESS.md` (or `STATE.md`) or a knowledge file, write it there first and reference the file.
