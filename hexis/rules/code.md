# Code
- Match the existing style of the codebase. No unrequested refactors, comments, or "improvements".
- No defensive boilerplate, no speculative abstractions, no error handling for cases that can't happen.
- If the fix is a one-liner, give me the one-liner.
- In project repos, commit only when I ask (`~/.claude` itself is the exception: commit there on your own). How and
  when a commit is made - the declared check green first, one commit per coherent change, explicit paths, no
  attribution - is the skill `hexis-commit`, pushed on the first commit of a session and enforced by
  `hooks/commit-gate.py`; full text in `skills/hexis-commit/reference.md`.
- **Separation of responsibilities - never write code without it, in any project** (one class
  that owns market state, strategy ticks, fills, settlement, ledger and telemetry in a multi-thousand-line file
  saturates one core and forces a rewrite):
  - Decompose by responsibility before code grows: one responsibility per module and per class, narrow interfaces
    between them; no file over ~600 lines, no class owning more than one responsibility. Code that would cross a
    limit is split before it lands, not after.
  - Every implementation brief names the module boundaries the change must respect (where the new code lives).
    An implementer asked to grow a file already over the limit extracts first - this is the one refactor that needs
    no separate request, because the growth itself is the request.
  - qa-gate and every review check structure as well as behaviour (file and class size, responsibilities per class,
    whether a change was bolted onto a god object).
  - Existing oversized files are not rewritten wholesale on this rule alone; they are split where the next change
    touches them. In Hexis that is mcp/linear_mcp/src/linear.ts (1,395) and scripts/linear_ops.py (972); test files are exempt
    from the line limit.
- Editing another program's state file (a save, a config, an index): every write is modelled on a
  file that program wrote itself. Derive the full write set (the row and the counters/counts/lists
  around it) by diffing program-written files, ship the write path only with a test that asserts
  those invariants on a reference file, and never report such a file as fine from row-level
  validity alone.
