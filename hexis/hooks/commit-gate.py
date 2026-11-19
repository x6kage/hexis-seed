"""PreToolUse hook (Jev first) on `git commit`: before a commit is written, Jev reads the staged diff, the message and
the recent history, and the commit is denied when it would break the commit rules the user has had to repeat
(skill hexis-commit): one commit per coherent change, follow-ups folded into their topic commit while it is unpushed, a
message that says what the diff does, no attribution lines. Code decides what code can (attribution lines, an empty
diff); Jev judges the judgement calls and is logged only (TIER). Fail-open: a git or Jev error lets the commit through.
Added at the user's go: one-line commits had to be squashed by hand."""

import json
import os
import re
import shlex
import subprocess
from typing import cast

import _common
import jev_client

# `git [-C path] [-c key=value ...] commit`: a `-c` before `commit` hid the commit from the first version.
COMMIT = re.compile(r"(?:^|[;&|(]\s*|\s)git((?:\s+-[cC]\s+(?:\"[^\"]+\"|'[^']+'|\S+))*)\s+commit\b")
GIT_DIR = re.compile(r"-C\s+(\"[^\"]+\"|'[^']+'|\S+)")
# Every `cd` before the commit, the last one wins (a `cd` in the middle of a command was missed).
CD = re.compile(r"(?:^|[;&|]\s*)cd\s+(\"[^\"]+\"|'[^']+'|\S+)\s*(?:&{1,2}|;|$)")
MESSAGE = re.compile(r"(?:\s-[a-zA-Z]*m|--message)(?:\s+|=)(\"(?:[^\"\\]|\\.)*\"|'[^']*'|\S+)")  # -m, -qm, -am
ADD = re.compile(r"git(?:\s+-C\s+\S+)?\s+add\s+([^;&|]+)")
MOVES_INDEX = re.compile(
    r"git(?:\s+-C\s+\S+)?\s+(?:reset|checkout|switch|restore|stash|rm|mv|merge|cherry-pick|"
    r"revert|pull|rebase)\b"
)
NEW_FILE_CHARS = 4000
FIXUP = re.compile(r"--fixup(?:=|\s+)(?:amend:|reword:)?(\$\([^)]*\)|\S+)")
# A --fixup target written as a shell variable or substitution is only text before the command runs: `$H` from
# `H=$(git log ... -1)` left the topic check silently skipped for every such fixup. Such a target is
# resolved by running the same read-only git command here; anything else unresolvable is denied, not skipped.
READONLY_GIT = ("log", "rev-parse", "rev-list", "show", "describe")
ATTRIBUTION = re.compile(r"co-authored-by|generated with|🤖", re.IGNORECASE)
DIFF_CHARS = 60_000
TIMEOUT = 8.0
# Verified before committed (skill hexis-commit, "Is a commit allowed?"), for every language: a file this session edited is
# committed only after the repository's own check command - declared in <repo>/.claude/quality.json as "check": format
# and lint with --write, then the checks, then the tests - ran green after the last edit. Only prose, images and lock
# files are exempt. Code decides this; Jev is not asked.
EXEMPT = {"md", "markdown", "txt", "rst", "adoc", "png", "jpg", "jpeg", "gif", "webp", "svg", "ico", "pdf", "lock"}
EDIT_TOOLS = ("Edit", "Write", "MultiEdit", "NotebookEdit")
FAILED = re.compile(
    r"\bFAILED\b|\b[1-9]\d* failed\b|Traceback \(most recent call last\)|^Exit code [1-9]", re.MULTILINE
)
# What to declare when a repository has none: write-first fixers, then the checks, then the tests, per ecosystem.
SUGGEST = (
    ("Cargo.toml", "cargo fmt && cargo clippy --fix --allow-dirty && cargo clippy -- -D warnings && cargo test"),
    ("deno.json", "deno fmt && deno lint && deno check . && deno test"),
    # Bun + Biome only: `bun test` is the entry; a bunfig.toml preload runs `biome check --write`
    # and `tsc --noEmit` before the tests. No Vitest, no ESLint.
    ("package.json", "bun test"),
    ("pyproject.toml", "ruff format && ruff check --fix && pyright && pytest"),
    ("go.mod", "gofmt -w . && go vet ./... && golangci-lint run && go test ./..."),
    (".sln", "dotnet format && dotnet build -warnaserror && dotnet test"),
    (".csproj", "dotnet format && dotnet build -warnaserror && dotnet test"),
    ("CMakeLists.txt", "clang-format -i (sources) && cmake --build build && clang-tidy -p build (sources) && ctest"),
    ("build.gradle", "gradle spotlessApply check"),
    ("build.gradle.kts", "gradle spotlessApply check"),
    ("pom.xml", "mvn spotless:apply verify"),
    ("Package.swift", "swift format -i -r . && swift build && swift test"),
    ("build.zig", "zig fmt . && zig build test"),
    ("mix.exs", "mix format && mix credo && mix test"),
    ("Gemfile", "rubocop -a && bundle exec rspec"),
    ("composer.json", "php-cs-fixer fix && phpstan && phpunit"),
)
# Jev policy (no Jev question meets a block bar yet): the Jev questions below
# are judged and logged as "would-deny" under "log"; "block" may refuse. The code checks (declared check green, one
# git commit per command, attribution, visible diff, resolvable fixup) refuse as before.
TIER = "log"
BLOCK_AT = {"mismatch": 0.75, "mixed": 0.75, "follow_up": 0.7}
FITS_TOPIC_BELOW = 0.3
QUESTIONS = {
    "mixed": (
        (
            "Does `staged_diff` combine two or more unrelated changes - different topics that each stand on their own and "
            "belong in separate commits?"
        ),
        {
            "true": "The diff holds changes for separate purposes that do not depend on each other.",
            "false": "All of the diff serves one purpose, including its tests, docs and wiring.",
        },
    ),
}
MESSAGE_QUESTIONS = {
    "mismatch": (
        (
            "Does `message` misdescribe `staged_diff` - claim something the diff does not do, or leave out a substantial "
            "part of what it does?"
        ),
        {
            "true": "The message and the diff disagree about what changed.",
            "false": "The message describes what the diff does, at the level of its main changes.",
        },
    ),
}
FOLLOW_UP_QUESTIONS = {
    "follow_up": (
        (
            "`recent_commits[0]` is the newest commit and has not been pushed. Is `staged_diff` a follow-up to that same "
            "topic - a fix, a tweak, a test or a doc for it - that should be folded into that commit instead of committed "
            "on its own?"
        ),
        {
            "true": "The diff continues or corrects the newest commit's topic.",
            "false": "The diff is a different topic from the newest commit.",
        },
    ),
}
FIXUP_QUESTIONS = {
    "fits_topic": (
        "`target_commit` is the commit this change will be squashed into. Does `staged_diff` belong to its topic?",
        {
            "true": "The diff continues or corrects the target commit's topic.",
            "false": "The diff is about something else than the target commit.",
        },
    ),
}


def out(reason):
    return json.dumps(
        {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": reason,
            }
        }
    )


def unquote(s):
    return s[1:-1] if len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'" else s


def native(path):
    """A Git Bash path (/c/Users/..., ~/...) as a path Python on Windows can open."""
    path = os.path.expanduser(unquote(path))
    m = re.match(r"^/([a-zA-Z])/(.*)$", path)
    return f"{m.group(1).upper()}:/{m.group(2)}" if m else path


def git(cwd, *args):
    r = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=10,
        check=False,
    )
    return r.stdout if r.returncode == 0 else None


def pending_adds(cwd, head):
    """The part of the commit that a `git add` earlier in the SAME command will stage: at PreToolUse time it has not
    run yet, so the index alone would show an empty or partial diff (`git add X && git commit ...`)."""
    paths, everything = [], False
    for m in ADD.finditer(head):
        for arg in m.group(1).split():
            arg = unquote(arg)
            if arg in ("-A", "--all", ".", ":/"):
                everything = True
            elif not arg.startswith("-"):
                paths.append(native(arg))
    if everything:
        return "\n" + (git(cwd, "diff", "HEAD", "--stat", "--patch") or "") + untracked(cwd, [])
    if not paths:
        return ""
    return "\n" + (git(cwd, "diff", "HEAD", "--stat", "--patch", "--", *paths) or "") + untracked(cwd, paths)


def fixup_rev(cwd, head, token):
    """The revision a --fixup target names: a literal (hash, HEAD~1) as is; `$(git ...)` or `$VAR` assigned by
    `VAR=$(git ...)` earlier in the same command, by running that read-only git command; else None."""
    token = token.strip("\"'")
    inner = None
    if token.startswith("$("):
        inner = token[2:-1]
    elif token.startswith("$"):
        var = token.strip("${}")
        m = re.search(r"(?:^|[;&|\s])" + re.escape(var) + r"=\$\(([^)]*)\)", head)
        inner = m.group(1) if m else None
        if inner is None:
            return None
    else:
        return token
    try:
        args = shlex.split(inner)
    except ValueError:
        return None
    if len(args) < 2 or args[0] != "git" or args[1] not in READONLY_GIT:
        return None
    resolved = (git(cwd, *args[1:]) or "").split()
    return resolved[0] if resolved else None


def untracked(cwd, paths):
    """New files are invisible to `git diff HEAD`; show their head so the gate sees them too."""
    listing = git(cwd, "ls-files", "--others", "--exclude-standard", "--", *paths) or ""
    out = []
    for rel in listing.splitlines()[:20]:
        try:
            with open(os.path.join(cwd, rel), encoding="utf-8", errors="replace") as fh:
                out.append(f"new file: {rel}\n{fh.read(NEW_FILE_CHARS)}")
        except Exception:  # noqa: BLE001 - an unreadable new file still gets listed, just without its content
            out.append("new file: " + rel)
    return ("\n" + "\n".join(out)) if out else ""


def key(path):
    return os.path.normcase(os.path.abspath(native(path)))


def checked(name):
    """A file the check has to cover: anything with an extension that is not prose, an image or a lock file."""
    base = os.path.basename(name)
    return "." in base.lstrip(".") and base.rsplit(".", 1)[-1].lower() not in EXEMPT


def declared_check(top):
    try:
        with open(os.path.join(top, ".claude", "quality.json"), encoding="utf-8") as fh:
            return (json.load(fh).get("check") or "").strip() or None
    except (OSError, ValueError, AttributeError):
        return None


def suggestion(top):
    try:
        entries = os.listdir(top)
    except OSError:
        return None
    for marker, command in SUGGEST:
        if any(e == marker or (marker.startswith(".") and e.endswith(marker)) for e in entries):
            return f"{marker} found, e.g. `{command}`"
    return None


def unverified(transcript_path, cwd, head, staged_all):
    """The deny reason when a file this session edited is about to be committed without the repository's check
    having run green after the last edit; else None. Edits made through a shell command or by a subagent are not
    visible here."""
    top = (git(cwd, "rev-parse", "--show-toplevel") or "").strip()
    if not transcript_path or not top:
        return None
    names = (git(cwd, "diff", "HEAD" if staged_all else "--cached", "--name-only") or "").split("\n")
    everything = any(unquote(a) in ("-A", "--all", ".", ":/") for m in ADD.finditer(head) for a in m.group(1).split())
    if everything:
        names += (git(cwd, "diff", "HEAD", "--name-only") or "").split("\n")
        names += (git(cwd, "ls-files", "--others", "--exclude-standard") or "").split("\n")
    staged = {key(os.path.join(top, n)): n for n in names if n and checked(n)}
    for m in ADD.finditer(head):
        for arg in m.group(1).split():
            p = native(unquote(arg))
            if not p.startswith("-") and checked(p):
                staged[key(p if os.path.isabs(p) else os.path.join(cwd, p))] = p
    if not staged:
        return None
    uses, results = [], {}
    try:
        with open(transcript_path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if '"tool_use"' not in line and '"tool_result"' not in line:
                    continue
                try:
                    content = (json.loads(line).get("message") or {}).get("content") or []
                except Exception:  # noqa: BLE001, S112 - a malformed transcript line is skipped, not fatal
                    continue
                for c in content if isinstance(content, list) else []:
                    if not isinstance(c, dict):
                        continue
                    if c.get("type") == "tool_use":
                        uses.append(c)
                    elif c.get("type") == "tool_result":
                        body = c.get("content")
                        if isinstance(body, list):
                            body = "\n".join(b.get("text", "") for b in body if isinstance(b, dict))
                        results[c.get("tool_use_id")] = (bool(c.get("is_error")), str(body or ""))
    except OSError:
        return None
    last, edited = -1, None
    for i, c in enumerate(uses):
        inp = c.get("input") or {}
        path = inp.get("file_path") or inp.get("notebook_path")
        if c.get("name") in EDIT_TOOLS and path and key(path) in staged:
            last, edited = i, staged[key(path)]
    if edited is None:
        return None
    check = declared_check(top)
    if not check:
        hint = suggestion(top)
        return (
            "Commit gate (skill hexis-commit, when to commit): {} was edited in this session and {} declares no check "
            'command. Declare one in .claude/quality.json as {{"check": "..."}} - format and lint with --write '
            "first, then the checks, then the tests{} - run it, fix what it finds, and commit when it is green."
        ).format(edited, top, f" ({hint})" if hint else "")
    want = check.replace("\\", "/")
    for c in uses[last + 1 :]:
        cmd = ((c.get("input") or {}).get("command") or "").replace("\\", "/")
        if c.get("name") not in ("Bash", "PowerShell") or want not in cmd:
            continue
        error, body = results.get(c.get("id"), (True, ""))
        if not error and not FAILED.search(body):
            return None
    return (
        f"Commit gate (skill hexis-commit, when to commit): {edited} was edited in this session and the repository's check "
        f"(`{check}`) has not run green since its last edit. Run it, fix what it finds, run it again, and commit only "
        "then - a change is not committed because it was made."
    )


def main(payload):
    if payload.get("tool_name") not in ("Bash", "PowerShell"):
        return None
    command = (payload.get("tool_input") or {}).get("command") or ""
    m = COMMIT.search(command)
    if not m:
        return None
    cwd = payload.get("cwd") or os.getcwd()
    git_dir = GIT_DIR.search(m.group(1) or "")
    cds = CD.findall(command[: m.start()])
    if git_dir:
        cwd = native(git_dir.group(1))
    elif cds:
        cwd = native(cds[-1])
    head, tail = command[: m.start()], " " + command[m.end() :]
    # The gate runs once, BEFORE the command: it cannot see what an earlier reset/checkout/stash/rm/mv in the same
    # command does to the index or HEAD, nor judge a second commit. A regroup of three commits in one command goes
    # through unseen. Such commands are split; a `git add` before the commit is handled by pending_adds.
    if len(COMMIT.findall(command)) > 1 or MOVES_INDEX.search(head):
        return out(
            "Commit gate: run this commit as its own command, after the reset/checkout/stash or the other "
            "commits have run, so the gate can see what it commits (one `git commit` per command; a `git add` "
            "in the same command is fine)."
        )
    messages = [unquote(x) for x in MESSAGE.findall(tail)]
    message = "\n\n".join(messages)
    if ATTRIBUTION.search(message):
        return out(
            "Commit gate: the message carries an attribution line; commit messages never do (skill hexis-commit)."
        )
    try:
        fixup = FIXUP.search(tail)
        amend = "--amend" in tail
        staged_all = re.search(r"(?:^|\s)(?:-a\b|--all\b|-[a-zA-Z]*a[a-zA-Z]*\b)", tail) is not None
        diff = git(cwd, "diff", "HEAD" if staged_all else "--cached", "--stat", "--patch") or ""
        diff += pending_adds(cwd, head)
        if not diff.strip():
            if amend or not git(cwd, "rev-parse", "--git-dir"):
                return None  # a message-only amend, or not a repository: git itself will say so
            # Empty at hook time: either nothing to commit (git fails anyway) or the content is written by an earlier
            # part of this same command (python, sed, printf) - which the gate cannot see. An amend written that way
            # goes through unchecked. Deny rather than pass what cannot be seen.
            return out(
                "Commit gate: nothing is staged yet when the gate runs, so it cannot see what this commit will "
                "contain - files written by an earlier part of the same command are invisible to it. Write the "
                "files first, then run `git add ... && git commit ...` as its own command."
            )
        reason = unverified(payload.get("transcript_path"), cwd, head, staged_all)
        if reason:
            jev_client.log(
                "commit-gate", None, "deny-unverified", 0, command, cwd, "", session=payload.get("session_id") or ""
            )
            return out(reason)
        recent = (git(cwd, "log", "-5", "--format=%h %s") or "").splitlines()
        upstream = git(cwd, "rev-parse", "--abbrev-ref", "@{u}")
        unpushed = git(cwd, "rev-list", "--count", "@{u}..HEAD") if upstream else None
        head_unpushed = (not upstream) or (unpushed is not None and unpushed.strip() not in ("", "0"))
        state = {"staged_diff": diff[:DIFF_CHARS], "message": message, "recent_commits": recent}
        questions = dict(QUESTIONS)
        if message:
            questions.update(MESSAGE_QUESTIONS)
        target = None
        if fixup:
            rev = fixup_rev(cwd, head, fixup.group(1))
            if not rev:
                return out(
                    f"Commit gate: the --fixup target {fixup.group(1)} cannot be resolved before the command runs, so the "
                    "gate cannot check that the change belongs to it. Give a hash or HEAD~n, or set it in the "
                    "same command with VAR=$(git log ...|git rev-parse ...)."
                )
            target = git(cwd, "log", "-1", "--format=%h %s%n%n%b", rev)
        if target:
            state["target_commit"] = target.strip()
            questions.update(FIXUP_QUESTIONS)
        elif not fixup and not amend and recent and head_unpushed:
            questions.update(FOLLOW_UP_QUESTIONS)
    except Exception:  # noqa: BLE001 - a failed git/state probe just skips the Jev question, never blocks the commit
        return None
    jev_client.TIMEOUT = TIMEOUT
    ps, ms = jev_client.timed_nouls(state, questions)
    session = payload.get("session_id") or ""
    if ps is None:
        jev_client.log("commit-gate", None, "error", ms, command, cwd, "", session=session)
        return None
    ps = cast(dict[str, float], ps)  # every question here is a Noul; jev_client.nouls's return type also covers Choice
    problems, hits = [], []
    labels = {
        "mixed": "the staged diff mixes unrelated changes - split it into one commit per topic",
        "mismatch": "the message does not describe what the diff does",
        "follow_up": "this continues the newest, unpushed commit's topic - fold it in (git commit --amend, or "
        "--fixup and an autosquash rebase) instead of adding a commit",
    }
    for qid, label in labels.items():
        if qid in ps and ps[qid] >= BLOCK_AT[qid]:
            problems.append(f"{label} ({jev_client.tag(qid, ps[qid])})")
            hits.append(qid)
    if "fits_topic" in ps and ps["fits_topic"] < FITS_TOPIC_BELOW:
        problems.append(
            "the change does not belong to the commit it is being folded into ({})".format(
                jev_client.tag("fits_topic", ps["fits_topic"])
            )
        )
        hits.append("fits_topic")
    decision = "allow" if not problems else "deny" if TIER == "block" else "would-deny"
    jev_client.log(
        "commit-gate",
        max(v for v in ps.values()),
        decision,
        ms,
        command,
        cwd,
        "",
        ps,
        session=session,
        flags=hits,
    )
    if decision != "deny":
        return None
    return out("Jev commit gate (skill hexis-commit, one commit per coherent change): " + "; ".join(problems) + ".")


_common.run("commit-gate.py", main)
