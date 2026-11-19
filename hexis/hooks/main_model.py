"""The model tier a session's main conversation runs on right now, read from the tail of its transcript.

A hook payload names the session's effort but not its model, and the cost meter's sidecar moves only on a user prompt
(a `/model` switch shows there one turn late), so a hook that must know the main model at the moment of a tool call
reads the newest main-chain assistant record instead."""

import json
import os

TIERS = ("fable", "opus", "sonnet", "haiku")
TAILS = (1 << 19, 1 << 23)  # bytes read from the end: 512 KB, then 8 MB when long records hid every assistant line


def tier(payload):
    """'fable', 'opus', 'sonnet' or 'haiku' for the session's newest main-chain reply; '' when it cannot be read."""
    path = payload.get("transcript_path") or ""
    try:
        size = os.path.getsize(path)
    except OSError:
        return ""
    for span in TAILS:
        found = _newest(path, max(0, size - span))
        if found or span >= size:
            return found
    return ""


def _newest(path, start):
    try:
        with open(path, "rb") as fh:
            fh.seek(start)
            lines = fh.read().decode("utf-8", "replace").splitlines()
    except OSError:
        return ""
    for line in reversed(lines[1:] if start else lines):  # a read that starts mid-file opens on a partial line
        if '"assistant"' not in line:
            continue
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if not isinstance(rec, dict) or rec.get("type") != "assistant" or rec.get("isSidechain"):
            continue
        model = str((rec.get("message") or {}).get("model") or "").lower()
        hit = next((t for t in TIERS if t in model), "")
        if hit:  # a synthetic record names no tier: keep looking at older ones
            return hit
    return ""
