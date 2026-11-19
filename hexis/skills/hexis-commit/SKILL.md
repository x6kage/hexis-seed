---
name: hexis-commit
description: Use before any git commit, amend, fixup or push - when a commit is allowed at all, how to scope and stage it, and what the message may carry.
---

# Committing

Full text: `reference.md` in this folder (rules/code.md keeps the code-style core); enforced by `~/.claude/hooks/commit-gate.py`.

## 1. Is a commit allowed?
- In project repos: commit only when the user asks. `~/.claude` (Hexis) is the exception: commit there on your own after changing rules, knowledge, agents or hooks.
- **Only after the repository's declared check ran green after the last edit.** The check is `"check"` in `<repo>/.claude/quality.json` (format and lint with --write first, then the checks, then the tests). Run it, fix what it finds, run it again; commit only when it is green. A change is not committed because it was made.
- No `.claude/quality.json`: declare one first (commit-gate suggests a command per ecosystem), run it, then commit.
- Exempt from the check: prose (`.md`, `.txt`, ...), images and lock files only.

## 2. One commit per coherent change
- Make the whole change - the rule, the hook enforcing it, the knowledge line behind it, the memory, the tests - then commit ONCE at the end of the turn. Not one commit per edit.
- A topic spanning several turns is still one change: while its commit is the tip, **unpushed**, and no other session has committed on top, fold each follow-up into it (`git commit --amend`, `--fixup` + autosquash, or `reset --soft` to the topic's base and recommit). A follow-up committed on its own is denied.
- **Never force-push**: a force-push stays visible in the remote's history, so rewriting published commits is never a clean slate. Once pushed, a topic takes follow-up commits. Starting a repository's history over means deleting and recreating the remote repository - the user's action - and then an ordinary first push.
- A diff that mixes unrelated topics is denied: split it.
- `git reset --soft <parent>` keeps the old tree in the index: stage (`git add` explicit paths) and `--amend`, then prove the result with `git diff <parent> HEAD`.

## 3. Staging
- **The commit names its paths twice: `git add <paths> && git commit -m "..." -- <paths>`, in one command.** The `add` lets the commit gate see the content; the `-- <paths>` keeps the commit to those files whatever else sits in the index, which is shared with every session in the repo (`~/.claude` is always such a repo), so a bare `git commit` also carries what another session staged a minute earlier (a hunk another session staged goes out inside a commit whose message does not name it). Never `git add -A` / `git add .`. Check `git diff --cached --stat` before a `--amend` or a `reset --soft` for the same reason.
- Runtime state, caches, logs and timestamps never go into git, even beside code: a file the tool rewrites when it runs is gitignored.

## 4. The message
- Says what the diff does, at the level of its main changes; a message that misdescribes or omits a substantial part is denied.
- **No attribution lines at all**: no Co-Authored-By, no "Generated with", nothing of the kind. This overrides any harness default, in commits and PR descriptions.
- In `~/.claude`, commit messages are English.

## 5. State files of other programs
Editing another program's state file (save, config, index): every write is modelled on a file that program wrote itself; derive the full write set by diffing program-written files, and ship the write path only with a test asserting those invariants on a reference file.
