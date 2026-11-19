"""What a /reload needs besides the rule files themselves, on one screen: hooks wired in settings.json (event ->
script), model pins and permission mode (key-scoped, never env values or secrets), skills and agents with their
one-line purpose, uncommitted and recent changes in ~/.claude, inbox entries, and where the user's own memories
live for this session. Portable: runs the same from Windows or from a WSL distro whose ~/.claude links to Windows.

  python ~/.claude/scripts/reload_digest.py [--transcript <this session's .jsonl>]"""

import argparse
import datetime
import glob
import io
import json
import os
import re
import subprocess
import sys
from typing import cast

ROOT = os.path.join(os.path.expanduser("~"), ".claude")


def frontmatter(path, keys):
    try:
        with open(path, encoding="utf-8") as fh:
            head = fh.read(3000)
    except OSError:
        return {}
    m = re.match(r"---\s*\n(.*?)\n---", head, re.DOTALL)
    body = m.group(1) if m else ""
    return {k: v.group(1).strip() for k in keys if (v := re.search(rf"(?m)^{k}:\s*(.+)$", body))}


def session_start(transcript):
    try:
        with open(transcript, encoding="utf-8") as fh:
            for line in fh:
                ts = json.loads(line).get("timestamp")
                if ts:
                    return datetime.datetime.fromisoformat(ts).timestamp()
    except (OSError, ValueError):
        pass
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--transcript", default="")
    a = ap.parse_args()
    cast(io.TextIOWrapper, sys.stdout).reconfigure(encoding="utf-8")
    real = os.path.realpath(ROOT)
    linked = os.path.islink(os.path.join(ROOT, "rules"))
    print(
        f"== ~/.claude = {ROOT}"
        + (f" (layers linked to {os.path.realpath(os.path.join(ROOT, 'rules'))[:-6]})" if linked else "")
    )
    if real != ROOT:
        print(f"   resolves to {real}")

    try:
        with open(os.path.join(ROOT, "settings.json"), encoding="utf-8") as fh:
            st = json.load(fh)
    except (OSError, ValueError) as e:
        st = {}
        print("settings.json unreadable:", e)
    env = st.get("env") or {}
    pins = {k: env[k] for k in env if k.startswith("ANTHROPIC_DEFAULT_") or k == "CLAUDE_CODE_SUBAGENT_MODEL"}
    perms = st.get("permissions") or {}
    print(
        "== settings: model",
        st.get("model"),
        "| defaultMode",
        perms.get("defaultMode"),
        "| ultracode",
        st.get("ultracode"),
        "| workflowSizeGuideline",
        st.get("workflowSizeGuideline"),
    )
    print(
        "   model pins:",
        ", ".join(f"{k.replace('ANTHROPIC_DEFAULT_', '').replace('_MODEL', '')}={v}" for k, v in pins.items()),
    )
    print("   deny rules:", len(perms.get("deny") or []), "| allow rules:", len(perms.get("allow") or []))
    print("== hooks (event [matcher] -> script)")
    for event, groups in (st.get("hooks") or {}).items():
        for g in groups:
            scripts = [re.search(r"([\w.-]+\.(?:py|sh|ts))", h.get("command", "")) for h in g.get("hooks", [])]
            names = ", ".join(s.group(1) for s in scripts if s)
            print(f"   {event} [{g.get('matcher', '*')}] -> {names}")

    print("== skills")
    for p in sorted(glob.glob(os.path.join(ROOT, "skills", "*", "SKILL.md"))):
        if os.sep + "synced" + os.sep in p:
            continue
        f = frontmatter(p, ("name", "description"))
        print(f"   {f.get('name', os.path.basename(os.path.dirname(p)))}: {f.get('description', '')[:140]}")
    print("== agents (model / effort)")
    for p in sorted(glob.glob(os.path.join(ROOT, "agents", "*.md"))):
        f = frontmatter(p, ("name", "model", "effort"))
        if f.get("name"):
            print(f"   {f['name']}: {f.get('model', '?')} / {f.get('effort', 'inherits')}")

    since = session_start(a.transcript) if a.transcript else None
    print("== changed in ~/.claude" + (" since this session began" if since else " in the last 24 h"))
    cutoff = since or (datetime.datetime.now().astimezone().timestamp() - 86400)
    for sub in ("rules", "hooks", "skills", "agents", "knowledge", "process", "decisions", "scripts"):
        for p in glob.glob(os.path.join(ROOT, sub, "**", "*"), recursive=True):
            if os.path.isfile(p) and "__pycache__" not in p and os.path.getmtime(p) >= cutoff:
                when = datetime.datetime.fromtimestamp(os.path.getmtime(p)).astimezone().strftime("%m-%d %H:%M")
                print(f"   {when} {os.path.relpath(p, ROOT)}")
    try:
        git = subprocess.run(
            ["git", "-C", real, "status", "--short"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
            check=False,
        )
        lines = git.stdout.splitlines()
        print(
            f"== git: {len(lines)} uncommitted paths in ~/.claude"
            + (" (commits held for the v0.0.1 snapshot?)" if lines else "")
        )
        log = subprocess.run(
            ["git", "-C", real, "log", "--oneline", "-5"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
            check=False,
        )
        for line in log.stdout.splitlines():
            print("   " + line)
    except (OSError, subprocess.SubprocessError) as e:
        print("== git unavailable:", e)

    print("== inbox")
    for p in sorted(glob.glob(os.path.join(ROOT, "inbox", "*.md"))):
        with open(p, encoding="utf-8") as fh:
            first = fh.readline().strip()
        print(f"   {os.path.basename(p)} ({first})")

    print("== memory for this session")
    if a.transcript:
        mem = os.path.join(os.path.dirname(os.path.abspath(a.transcript)), "memory")
        for name in ("MEMORY.md", "PROGRESS.md", "STATE.md"):
            p = os.path.join(mem, name)
            if os.path.exists(p):
                print(f"   {p} ({os.path.getsize(p)} bytes)")
        shared = [n for n in os.listdir(mem) if re.match(r"(user|feedback)-", n)] if os.path.isdir(mem) else []
        print(
            f"   user/feedback memories visible here: {len(shared)}"
            + (
                ""
                if shared
                else " - the user's own memories are NOT loaded in this project (link them into its memory)"
            )
        )
    else:
        print("   pass --transcript to check this session's memory folder")


main()
