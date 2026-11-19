"""The quality gate of this repository (~/.claude), one command before every commit:

    python scripts/check.py

Python: the fixers write first (ruff format, ruff check --fix), then pyright, then the unittest suites. TypeScript: one
`bun test` per project; its bunfig.toml preload runs `biome check --write` and `tsc --noEmit` before the tests
(Bun and Biome only, `bun test` is the entry). Every stage prints one line. The run exits 1 when any stage fails, and a missing tool is a failure, never a skip. hooks/commit-gate.py denies
a commit of code the session edited unless this command ran green after the last edit (.claude/quality.json)."""

import os
import shutil
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOME = os.path.expanduser("~")
TS_PROJECTS = ("mcp/linear_mcp",)
PY_SUITES = ("scripts/tests", "mcp/linear_claude")
TAIL = 40


def find(name):
    """A tool on PATH, or where winget and bun put it when this process started before the install."""
    for path in (
        shutil.which(name),
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "WinGet", "Links", name + ".exe"),
        os.path.join(HOME, ".bun", "bin", name + ".exe"),
        os.path.join(HOME, ".bun", "bin", name),
    ):
        if path and os.path.isfile(path):
            return path
    return None


def stage(results, label, tool, args, cwd=ROOT):
    exe = sys.executable if tool == "python" else find(tool)
    if not exe:
        results.append((label, False, 0.0, f"{tool} is not installed"))
        return
    start = time.monotonic()
    r = subprocess.run(
        [exe, *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False
    )
    output = (r.stdout + r.stderr).strip()
    results.append((label, r.returncode == 0, time.monotonic() - start, output))


def main():
    results = []
    stage(results, "ruff format", "ruff", ["format"])
    stage(results, "ruff check --fix", "ruff", ["check", "--fix"])
    stage(results, "pyright", "pyright", [])
    for suite in PY_SUITES:
        stage(results, "unittest " + suite, "python", ["-m", "unittest", "discover", "-s", suite, "-p", "test_*.py"])
    for project in TS_PROJECTS:
        stage(results, "bun test " + project, "bun", ["test"], os.path.join(ROOT, project))
    failed = [r for r in results if not r[1]]
    for label, ok, seconds, _ in results:
        print("{} {} ({:.1f}s)".format("PASS" if ok else "FAIL", label, seconds))
    for label, _, _, output in failed:
        print("\n--- {} ---\n{}".format(label, "\n".join(output.splitlines()[-TAIL:])))
    print("\ncheck: {}".format(f"FAILED ({len(failed)} of {len(results)} stages)" if failed else "passed"))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
