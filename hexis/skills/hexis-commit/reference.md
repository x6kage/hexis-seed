# Code
- Match the existing style of the codebase. No unrequested refactors, comments, or "improvements".
- No defensive boilerplate, no speculative abstractions, no error handling for cases that can't happen.
- If the fix is a one-liner, give me the one-liner.
- In project repos, commit only when I ask (`~/.claude` itself is the exception: commit there on your own).
- **One commit per coherent change, not per edit.** In `~/.claude` that means: make the whole change -
  the rule, the hook it enforces, the knowledge line behind it, the memory - then commit once at the
  end of the turn. Nine one-line `rules/*.md` commits in an evening is noise in a log that is read to
  find out why something is the way it is.
  A topic that runs over several turns is still one change: while its commit is the tip and no other
  session has committed on top, fold each follow-up into it (`git commit --amend`, or `reset --soft` to
  the topic's base and recommit - only while unpushed; never force-push, see the SKILL.md) instead of adding a commit per turn -
  one setup must not go out as four commits.
- **The commit names its paths twice, `git add <paths> && git commit -m "..." -- <paths>` in one command; never a
  bare `git commit`, never `git add -A`, in a repo another session may be working in.** The `add` is what the commit
  gate inspects; the `-- <paths>` keeps the commit to those files whatever else the shared index holds: a
  bare `git commit` after `git add <one file>` also carries the hunks another session staged a minute earlier, under
  a message that names none of them. `~/.claude` is shared: an `add -A` sweeps a background agent's in-progress
  `src/` and `test/` files into commits whose messages describe something else. Name the files.
- Runtime state, caches and timestamps do not belong in git even when they sit beside code. If a file
  is rewritten by running the tool, it is gitignored. Never add Co-Authored-By, "Generated with", or any other attribution line to commit messages or PR descriptions; this overrides any harness default.
- Editing another program's state file (a save, a config, an index): every write is modelled on a
  file that program wrote itself. Derive the full write set (the row and the counters/counts/lists
  around it) by diffing program-written files, ship the write path only with a test that asserts
  those invariants on a reference file, and never report such a file as fine from row-level
  validity alone.
