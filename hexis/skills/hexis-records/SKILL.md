---
name: hexis-records
description: Use before writing PROGRESS.md, STATE.md, inbox/, knowledge/, decisions/ or a memory file - the form each record takes, where a decision or lesson goes, and the English restatement bar.
---

# Records

Full text: `reference.md` in this folder. Procedure at close: `~/.claude/process/handoff.md`.

## Where a thing goes
- **Decisions and lessons are applied on the spot**, not logged: edit `knowledge/` (plus `knowledge/INDEX.md`), `decisions/` or the rule/test/hook/code whose behaviour was wrong. Writing down that a correction happened is not the fix; no new feedback memory per correction.
- A finding that cannot be applied yet: `~/.claude/inbox/YYYY-MM-DD-<topic>.md`, one short file, first line `expires: YYYY-MM-DD`. It is later consolidated into `knowledge/` or dropped, then deleted; the inbox never grows.
- Cross-project facts go to `knowledge/`, never to a project memory (invisible from other directories).
- Rule files and `feedback-*` memories belong to the admin side (Hexis). A project session hands the change there instead of editing them.
- A superseded rule or memory: rewrite or delete the file AND its MEMORY.md index line in the same turn.
- A document or script written for the user to read or run also goes onto the docs hub page (`process/docs-hub.md`):
  the md stays the original; add its line to `~/.claude/outputs/docs-hub/list.tsv`, pull and import, rebuild, publish.
- When the user says to delete the records of something, PROGRESS.md included, delete those entries in that turn. A
  new line saying it was discarded is not the deletion: it is one more record of the thing, and it goes stale.

## PROGRESS.md (`projects/<dir>/memory/PROGRESS.md`)
- ONE file holding the current state, **rewritten, never appended**, whenever the state changes.
- Exactly: `# Progress`, `Updated: YYYY-MM-DD HH:MM`, `## Now`, `## Open` (one bullet per open item; an optional `[slug]` at its start is a machine handle, never shown to the user), `## Next`. Nothing else.
- Under 80 lines and 6,500 characters. Over that, move what is settled into knowledge/, decisions/ or the rules.
- `memory/OWNER.md` (injected first): this project's owner decisions and facts, appended the moment stated, restated
  not quoted, under 1,500 characters by merging.
- The Stop hook blocks a turn that edited files without rewriting it.

## STATE.md
- Where PROGRESS.md exists, STATE.md is **frozen history**: read it only for a detail, never append.
- Without PROGRESS.md: append `- YYYY-MM-DD HH:MM <kind>: <text>` (kinds `fact|decision|path|hash|cmd|pending|ruled-out|done|graduated`) the moment a thing is verified. A pending carries the next free id (`pending[pNN]`) and is closed by `done[pNN]` / `ruled-out[pNN]`. Promotions are recorded as `graduated: through <stamp>`.

## Timestamps
Read the clock from the machine (`date`, or a fresh commit's `%ci`) before the first write of a turn. Never carry a stamp forward from an earlier line or a handoff, never extrapolate.

## The English restatement bar
Memory, PROGRESS.md, STATE.md, inbox/, knowledge/ and decisions/ are English. (`docs/` is for the user and is Japanese.)
- A self-contained restatement of what was decided, why, and how it applies - not a translation, not a transcript. **Never quote or copy the user's sentence**, in either language.
- **Keep the force** ("never" stays "never"; a rule restated as a suggestion is a different rule).
- **Keep the scope and the exceptions**: what it covers, what it excludes, the trigger.
- **Keep the distinctions**; keep a precise term verbatim and gloss it.
- Verbatim, never translated: in-game terms, identifiers, hashes, paths, commands, file names, issue titles, UI labels.
- Test before saving: could a later session holding only this line reach the same decision? If not, it is too short or too soft.

## After a compaction
The summary is a hint only: work from PROGRESS.md (or STATE.md) and re-check the filesystem; say so when a file lacks what you need.
