"""List the user's own prompts that mention any of the given keywords, across every session transcript under
~/.claude/projects, oldest first, so a brief can carry every remark he made about an asset - including ones made
in another session or before a compaction, which a brief built from recent prompts misses.

Usage: python scripts/user-asks.py [--since YYYY-MM-DD] [--width N] KEYWORD [KEYWORD ...]
"""

import argparse
import glob
import io
import json
import os
import sys

SKIP = ("<", "This session is being continued", "Another Claude session sent")


def prompts(path):
    with open(path, encoding="utf-8", errors="ignore") as fh:
        for line in fh:
            if '"user"' not in line:
                continue
            try:
                d = json.loads(line)
            except ValueError:
                continue
            if d.get("type") != "user" or d.get("isMeta") or d.get("isSidechain"):
                continue
            c = d.get("message", {}).get("content")
            if isinstance(c, list):
                c = " ".join(x.get("text", "") for x in c if isinstance(x, dict) and x.get("type") == "text")
            if isinstance(c, str) and c and not c.startswith(SKIP):
                yield d.get("timestamp", ""), c


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("keywords", nargs="+")
    ap.add_argument("--since", default="")
    ap.add_argument("--width", type=int, default=600)
    a = ap.parse_args()
    # the console code page (cp1252) cannot print his prompts
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    root = os.path.join(os.path.expanduser("~"), ".claude", "projects")
    rows, seen = [], set()
    for path in glob.glob(os.path.join(root, "*", "*.jsonl")):
        session = os.path.basename(path)[:8]
        for ts, text in prompts(path):
            if ts < a.since or not any(k in text for k in a.keywords) or text[:120] in seen:
                continue
            seen.add(text[:120])
            rows.append((ts, session, text))
    for ts, session, text in sorted(rows):
        print(f"{ts[:16]} {session} | {text[: a.width].replace(chr(10), ' / ')}")
    print(f"{len(rows)} prompt(s)", file=sys.stderr)


if __name__ == "__main__":
    main()
