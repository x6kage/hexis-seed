---
name: reload
description: Re-read ~/.claude and this project's memory in a long-running session, then report what changed under you. Use when the configuration was edited during the session, after a compaction, after moving to another directory or OS (a WSL distro), or when a rule you are following may be stale.
---

Re-read all of the following, in this order, and do not answer from what you already have in context. It works the
same from Windows and from a WSL distro whose `~/.claude` links to the Windows tree.

1. Run `python3 ~/.claude/scripts/reload_digest.py --transcript <this session's transcript .jsonl>` (`python` on
   Windows). It prints the hooks wired in settings.json, model pins and permission mode, every skill and agent with its
   purpose, what changed in ~/.claude since this session began, the uncommitted paths and last commits, the inbox, and
   whether the user's own memories (`user-*`, `feedback-*`) are visible in this project's memory folder.
2. `~/.claude/CLAUDE.md`, every `~/.claude/rules/*.md`, `~/.claude/knowledge/INDEX.md`, `~/.claude/process/INDEX.md`,
   and every file the digest lists as changed that governs what you are doing now (a rule, a hook, a skill, a
   knowledge file). `knowledge/machine.md` when present.
3. `<transcript directory>/memory/MEMORY.md`, then the memories it indexes that bear on the work, and
   `<transcript directory>/memory/PROGRESS.md` (or `memory/STATE.md` when there is no PROGRESS.md; with one, STATE.md is
   frozen history). `<transcript directory>` holds this session's transcript - `~/.claude/projects/<key>/`, not the
   working directory. If you do not know it, list `~/.claude/projects/` and take the directory whose name matches the
   working directory with `:`, `\`, `/` and `_` mapped to `-`. Never rebuild a filesystem path from a key.
4. When MEMORY.md names a predecessor transcript, run the `session_digest.py` command it gives and grep for the topic
   at hand before asking the user a question that the previous session already settled; do not save its output.
5. The project's own `CLAUDE.md` and `.claude/quality.json` in the working directory, when they exist.

Then report, in 3 to 6 lines:

- Which rules, hooks, skills, agents or knowledge files are new or changed relative to the work this session has been
  doing (the digest's list, or a commit when one names it).
- Which assumptions this session has been acting on are now wrong, one line each. If none are, say so in one line
  rather than listing what is unchanged.
- One line naming any hook added or changed since this session began. Hook edits take effect immediately in a live
  session (verified), so treat a new hook as already in force here.
- If the digest says the user's own memories are not visible here, say so and point to the fix
  (link them into this project's memory; the Hexis session does it).
- Last, because everything just read is English: your replies to the user stay in Japanese, in the polite register (CLAUDE.md "Language"); records, peer messages and commits stay English (a re-read of English text must not switch the reply language).
