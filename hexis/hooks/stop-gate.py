"""Stop hook. Blocks the turn when this session edited files without rewriting the project's memory/PROGRESS.md (or,
in a project without one, without appending to its memory/STATE.md), or when it changed code in a project that has a test runner and never ran it. Scans the transcript incrementally."""

import json
import os
import re

import _common

EDIT_TOOLS = ("Edit", "Write", "MultiEdit", "NotebookEdit")
SHELL_TOOLS = ("Bash", "PowerShell")
PROGRESS_FILE = re.compile(r"progress\.md", re.IGNORECASE)
WRITE = re.compile(
    r"Set-Content|Out-File|sed -i|\bcp\s|Copy-Item|\.write\(|\bopen\([^)]*['\"][wax]|>>?\s*(?!&|/dev/null|NUL\b|nul\b)\S",
    re.IGNORECASE,
)
STATE_APPEND = re.compile(r"STATE\.md.*>>|>>.*STATE\.md", re.IGNORECASE | re.DOTALL)
OWN_WRITE = re.compile(r"/\.claude(/|\s|$)|/projects/[^/\s]+/memory\b|/temp/claude/|scratchpad", re.IGNORECASE)
RUNNERS = re.compile(
    r"\b(cargo test|pytest|python -m pytest|python3 -m pytest|npm test|pnpm test|yarn test|bun test|bun run test|bun run check|make check|go test|dotnet test|ctest|make test|mvn test|gradle test|gradlew test|jest|vitest|rspec|phpunit|swift test|zig build test|mix test)\b"
)
MARKERS = (
    ("Cargo.toml", "cargo test"),
    ("package.json", "bun test"),  # Bun only; `bun run test` when the project declares one
    ("pyproject.toml", "pytest"),
    ("pytest.ini", "pytest"),
    ("setup.py", "pytest"),
    ("go.mod", "go test ./..."),
    ("CMakeLists.txt", "ctest"),
    ("Makefile", "make test"),
    ("build.gradle", "gradle test"),
    ("pom.xml", "mvn test"),
    ("Package.swift", "swift test"),
    ("build.zig", "zig build test"),
    ("mix.exs", "mix test"),
    ("Gemfile", "rspec"),
)
GLOB_MARKERS = ((".csproj", "dotnet test"), (".sln", "dotnet test"))
NOT_CODE = ("md", "txt", "rst", "json", "yaml", "yml", "toml", "csv", "ini", "cfg", "lock", "svg", "png")


def norm(p):
    return (p or "").replace("\\", "/")


def is_own_config(path):
    low = norm(path).lower()
    home = norm(os.path.expanduser("~")).lower()
    return low.startswith(home + "/.claude/") or OWN_WRITE.search(low) is not None


def package_test(d):
    """`bun run test` when package.json declares a test script, else `bun test` (Bun's own runner)."""
    try:
        with open(os.path.join(d, "package.json"), encoding="utf-8") as fh:
            scripts = json.load(fh).get("scripts") or {}
    except Exception:  # noqa: BLE001 - an unreadable package.json falls back to Bun's runner
        scripts = {}
    return "bun run test" if "test" in scripts else "bun test"


def project_root(path):
    d = os.path.dirname(norm(path))
    while d and d.rstrip("/") != os.path.dirname(d).rstrip("/"):
        q = os.path.join(d, ".claude", "quality.json")
        if os.path.isfile(q):
            try:
                with open(q, encoding="utf-8") as fh:
                    q_ = json.load(fh)
                cmd = q_.get("check") or q_.get("test")  # hexis-commit declares "check"
            except Exception:  # noqa: BLE001 - a corrupt quality.json just means no test command found here
                cmd = None
            if cmd:
                return d, cmd
        for name, cmd in MARKERS:
            if os.path.isfile(os.path.join(d, name)):
                return d, package_test(d) if name == "package.json" else cmd
        try:
            entries = os.listdir(d)
        except Exception:  # noqa: BLE001 - an unreadable directory just has no marker files
            entries = []
        for ext, cmd in GLOB_MARKERS:
            if any(e.endswith(ext) for e in entries):
                return d, cmd
        d = os.path.dirname(d)
    return None, None


def scan(transcript, st):
    with open(transcript, "rb") as fh:
        fh.seek(st["offset"])
        data = fh.read()
    cut = data.rfind(b"\n") + 1
    st["offset"] += cut
    for line in data[:cut].decode("utf-8", "replace").splitlines():
        if '"tool_use"' not in line:
            continue
        try:
            o = json.loads(line)
        except Exception:  # noqa: BLE001, S112 - a malformed transcript line is skipped, not fatal
            continue
        for c in (o.get("message") or {}).get("content") or []:
            if not isinstance(c, dict) or c.get("type") != "tool_use":
                continue
            st["n"] += 1
            name, inp = c.get("name"), c.get("input") or {}
            path = inp.get("file_path") or inp.get("notebook_path") or ""
            cmd = inp.get("command") or ""
            if name in EDIT_TOOLS and path:
                if norm(path).lower().endswith("/memory/state.md"):
                    st["state"] = st["n"]
                elif norm(path).lower().endswith("/memory/progress.md"):
                    st["progress"] = st["n"]
                elif not is_own_config(path):
                    st["edit"], st["path"] = st["n"], norm(path)
                    st["count"] += 1
                    if os.path.splitext(path)[1].lstrip(".").lower() not in NOT_CODE:
                        st["code"], st["code_path"] = st["n"], norm(path)
                        # the project's declared command counts as a test run from the first edit on, not only
                        # after a block has named it
                        st["test_cmd"] = project_root(path)[1] or st["test_cmd"]
            elif name in SHELL_TOOLS and cmd:
                if STATE_APPEND.search(cmd):
                    st["state"] = st["n"]
                elif PROGRESS_FILE.search(cmd) and WRITE.search(cmd):
                    st["progress"] = st["n"]  # a sed/python/redirect rewrite counts like an Edit
                elif WRITE.search(cmd) and not OWN_WRITE.search(norm(cmd)):
                    st["edit"], st["path"] = st["n"], "shell: " + cmd.strip().splitlines()[0][:80]
                    st["count"] += 1
                if RUNNERS.search(cmd) or (st["test_cmd"] and st["test_cmd"] in cmd):
                    st["test"] = st["n"]
    return st


def main(payload):
    if payload.get("stop_hook_active"):
        return None
    transcript = payload.get("transcript_path") or ""
    if not os.path.isfile(transcript):
        return None
    side = transcript + ".stopgate.json"
    st = {
        "offset": 0,
        "n": 0,
        "edit": 0,
        "path": "",
        "count": 0,
        "code": 0,
        "code_path": "",
        "state": 0,
        "progress": 0,
        "test": 0,
        "test_cmd": "",
        "blocked": 0,
    }
    if os.path.isfile(side):
        try:
            with open(side, encoding="utf-8") as fh:
                st.update(json.load(fh))
        except Exception:  # noqa: BLE001, S110 - a corrupt sidecar just starts the state over
            pass
    scan(transcript, st)

    reasons = []
    progress = _common.progress_path(payload)
    if progress and os.path.isfile(progress):
        if st["edit"] and st["progress"] < st["edit"]:
            reasons.append(
                f"This session edited {st['count']} files (last: {st['path']}) after the last rewrite of "
                f"PROGRESS.md. Rewrite {progress} so Now, Open and Next describe the state after this work; "
                "apply decisions and lessons to knowledge/, decisions/ or the rules, and put a finding that "
                "cannot be applied yet into ~/.claude/inbox/ with an expiry, then finish."
            )
    elif st["edit"] and st["state"] < st["edit"]:
        reasons.append(
            f"This session edited {st['count']} files (last: {st['path']}) after the last STATE.md line. "
            f"Append the facts/decisions/pending items of this work to {_common.state_path(payload)} "
            "(format: - YYYY-MM-DD HH:MM kind: text), then finish."
        )
    if st["code"] and st["blocked"] < st["code"]:
        root, cmd = project_root(st["code_path"] or payload.get("cwd") or "")
        if root and st["test"] < st["code"]:
            st["test_cmd"] = cmd
            st["blocked"] = st["code"]
            reasons.append(
                f"Code under {root} was changed (last: {st['code_path']}) and no test run happened after it. "
                f"Run `{cmd}` in {root} and report its result, or say why the suite cannot run here, then finish."
            )
    try:
        with open(side, "w", encoding="utf-8") as fh:
            json.dump(st, fh)
    except Exception:  # noqa: BLE001, S110 - a failed sidecar write just means the state is not persisted this time
        pass
    if reasons:
        return json.dumps({"decision": "block", "reason": " ".join(reasons)})
    return None


_common.run("stop-gate.py", main)
