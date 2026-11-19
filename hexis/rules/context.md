# Context and persistence

- Memory files, `PROGRESS.md`, `STATE.md`, `inbox/`, `knowledge/` and `decisions/` are written in English as
  **self-contained restatements at full resolution**: keep the force, the scope, the exceptions and the precise terms,
  so a session holding only the line reaches the same decision. Never copy the user's sentence, in either language;
  identifiers, paths, commands, in-game terms and UI labels stay verbatim.
- Every timestamp written into a record is read from the machine (`date`) in that turn, never carried forward or
  estimated.
- After a compaction the summary is a hint only: work from PROGRESS.md (or STATE.md) and re-check the filesystem, and
  say so when a file does not have what you need instead of filling the gap from recollection.
- Where each record goes, the PROGRESS / STATE / inbox forms, graduation and superseded memories: the session-start
  injection and the skill `hexis-records`, pushed on the first record write of a session; full text in
  `skills/hexis-records/reference.md`.
