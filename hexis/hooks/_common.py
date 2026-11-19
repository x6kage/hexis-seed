"""Shared pieces for the ~/.claude hooks: fail-open entry point, evidence trace, project paths, STATE.md and PROGRESS.md parsing, skill push state, deny-once state."""

import hashlib
import io
import json
import os
import re
import sys
import time
from typing import cast

STATE_LINE = re.compile(r"^- (\d{4}-\d{2}-\d{2} \d{2}:\d{2}) ([a-z-]+)(?:\[(p\d+)\])?: ?(.*)$")
STAMP = re.compile(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}")
PREFIX = 30
OPEN_ITEM = re.compile(r"^- (?:\[([A-Za-z0-9._-]+)\] ?)?(.*)$")
EXPIRES = re.compile(r"^expires: (\d{4}-\d{2}-\d{2})")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILLS = os.path.join(ROOT, "skills")
SKILL_STATE = os.path.join(ROOT, "logs", "skill-push")  # one JSON per session: the skills pushed so far, per scope
SKILL_CHARS = 4000
FRONTMATTER = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)


SETTINGS = os.path.join(ROOT, "settings.json")
BAND_PLUGIN = "jev-band@hexis-mods"
MARKETPLACES = os.path.join(ROOT, "plugins", "known_marketplaces.json")  # per environment, never linked
BAND_SURFACES_DIR = os.path.join(ROOT, "logs", "jev-band")  # the mod writes each session's attached surfaces here
BAND_DRAWN_ON = ("terminal", "desktop")


def band_installed():
    """True when the jev-band plugin is enabled at user scope AND installed in this environment: it draws the Jev
    reading line and the cost line above the prompt from the hooks' own files, so no reply has to copy them. The
    marketplace check is per environment: a WSL distro whose ~/.claude links settings.json to the Windows tree reads
    the Windows enabledPlugins while its own plugins/ dir never had the plugin.
    Unreadable files count as absent, so the reply keeps carrying the lines rather than losing them."""
    try:
        with open(SETTINGS, encoding="utf-8") as fh:
            if (json.load(fh).get("enabledPlugins") or {}).get(BAND_PLUGIN) is not True:
                return False
        with open(MARKETPLACES, encoding="utf-8") as fh:
            return BAND_PLUGIN.split("@", 1)[1] in json.load(fh)
    except Exception:  # noqa: BLE001 - a missing or broken file means no band
        return False


def session_surfaces(session):
    """The surfaces attached to this session as the jev-band mod last wrote them, or None when it never wrote any
    (the mod is not loaded in this session)."""
    try:
        with open(os.path.join(BAND_SURFACES_DIR, (session or "nosession") + ".json"), encoding="utf-8") as fh:
            surfaces = json.load(fh).get("surfaces")
        return list(surfaces) if isinstance(surfaces, list) else None
    except Exception:  # noqa: BLE001 - a missing or broken file means the mod did not run here
        return None


def band_visible(session):
    """True when the user sees the two lines in the band: the plugin is installed here, its mod runs in this session,
    and no surface without a band (a phone over Remote Control, vscode) is attached - there the replies carry the lines
    (the mod cannot be seen on a phone; the minimum stays visible)."""
    if not band_installed():
        return False
    surfaces = session_surfaces(session)
    return surfaces is not None and all(s in BAND_DRAWN_ON for s in surfaces)


def run(name, fn):
    """Read the event, call fn(payload), print what it returns. Never raises: a crashing hook blocks the session."""
    raw, output = "", None
    try:
        # Hook stdin is UTF-8, but Python on this machine defaults to cp1252: a Japanese payload raised here and the
        # hook failed open silently - guard.py included.
        cast(io.TextIOWrapper, sys.stdin).reconfigure(encoding="utf-8")
        raw = sys.stdin.read()
        payload = json.loads(raw or "{}")
        output = remind_japanese(fn(payload), payload)
    except Exception:  # noqa: BLE001 - fail open on any error, or a crashing hook blocks the session
        output = None
        # Fail open, but never silently: a crash can leave a gate doing nothing, with no trace, until a missing log
        # line gives it away. The tool name, never the payload text, goes to the log.
        try:
            import time
            import traceback

            path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs", "hook-errors.log")
            os.makedirs(os.path.dirname(path), exist_ok=True)
            tool = (json.loads(raw or "{}") or {}).get("tool_name") if raw else ""
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(
                    "{} {} tool={}\n{}\n".format(
                        time.strftime("%Y-%m-%dT%H:%M:%S%z"), name, tool, traceback.format_exc()
                    )
                )
        except Exception:  # noqa: BLE001, S110 - the error trace itself must not raise
            pass
    trace(name, raw, output)
    if output:
        sys.stdout.write(output + "\n")
    sys.exit(0)


JA_REMINDER = " Whatever you write to the user after this stays Japanese (CLAUDE.md Language)."


def remind_japanese(output, payload):
    """A denial or a block is English the main session reads mid-turn, and the text after one drifted into English
    (31 of 33 English blocks came after a tool result in the same turn), so every one it reads
    ends with the language line. Subagents report in English by design and get none."""
    if not output or payload.get("agent_id"):
        return output
    if payload.get("hook_event_name") not in ("PreToolUse", "PostToolUse", "Stop"):
        return output
    try:
        out = json.loads(output)
    except ValueError:
        return output
    if not isinstance(out, dict):
        return output
    hso = out.get("hookSpecificOutput") or {}
    if hso.get("permissionDecision") == "deny" and isinstance(hso.get("permissionDecisionReason"), str):
        hso["permissionDecisionReason"] += JA_REMINDER
    elif out.get("decision") == "block" and isinstance(out.get("reason"), str):
        out["reason"] += JA_REMINDER
    else:
        return output
    return json.dumps(out)


def trace(name, raw, output):
    path = os.environ.get("CLAUDE_HOOK_TRACE")
    if not path:
        return
    try:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"hook": name, "input": raw, "output": output}) + "\n")
    except Exception:  # noqa: BLE001, S110 - a debug trace failing must not affect the hook it traces
        pass


def project_dir(payload):
    return os.path.dirname(payload.get("transcript_path") or "").replace("\\", "/")


def state_path(payload):
    d = project_dir(payload)
    return d + "/memory/STATE.md" if d else ""


def progress_path(payload):
    """The project's current-state note; a project that has it no longer appends to STATE.md."""
    d = project_dir(payload)
    return d + "/memory/PROGRESS.md" if d else ""


def owner_path(payload):
    """The project's owner decisions and owner facts, read before anything else."""
    d = project_dir(payload)
    return d + "/memory/OWNER.md" if d else ""


def inbox_dir():
    return os.path.expanduser("~").replace("\\", "/") + "/.claude/inbox"


def progress_open(lines):
    """`## Open` bullets of PROGRESS.md as (slug or None, text); indented lines continue the bullet above."""
    out, inside = [], False
    for line in lines:
        if line.startswith("## "):
            inside = line.strip() == "## Open"
            continue
        if not inside or not line.strip():
            continue
        m = OPEN_ITEM.match(line)
        if m:
            out.append([m.group(1), m.group(2).strip()])
        elif out and line[:1] in (" ", "\t"):
            out[-1][1] += " " + line.strip()
    return [tuple(o) for o in out]


def inbox_entries(today):
    """(name, expires, expired) for every inbox/ entry but the README; expires is '' when the first line lacks it."""
    d, out = inbox_dir(), []
    if not os.path.isdir(d):
        return out
    for name in sorted(os.listdir(d)):
        if not name.endswith(".md") or name.lower() == "readme.md":
            continue
        try:
            with open(os.path.join(d, name), encoding="utf-8") as fh:
                m = EXPIRES.match(fh.readline())
        except Exception:  # noqa: BLE001 - an unreadable inbox file just gets no expiry, not a crash
            m = None
        exp = m.group(1) if m else ""
        out.append((name, exp, bool(exp) and exp < today))
    return out


def global_state_path():
    """Cross-project STATE.md: how I work and what this machine is, injected at every session start."""
    return os.path.expanduser("~").replace("\\", "/") + "/.claude/STATE.md"


def parse_state(lines):
    """STATE.md lines to records {i, stamp, kind, id, text}; anything that is not `- <stamp> <kind>[pNN]: text` is skipped."""
    out = []
    for i, line in enumerate(lines):
        m = STATE_LINE.match(line)
        if m:
            out.append({"i": i, "stamp": m.group(1), "kind": m.group(2), "id": m.group(3), "text": m.group(4)})
    return out


def open_pending(records):
    """Pending records still open, newest first: an id is closed by any later line carrying it, an id-less one by a
    later done line whose text starts with the same 30 characters."""
    by_id, plain = {}, []
    for r in records:
        if r["id"]:
            if r["kind"] == "pending":
                by_id[r["id"]] = r
            else:
                by_id.pop(r["id"], None)
        elif r["kind"] == "pending":
            plain.append(r)
        elif r["kind"] == "done":
            plain = [p for p in plain if p["text"][:PREFIX] != r["text"][:PREFIX]]
    return sorted(list(by_id.values()) + plain, key=lambda r: r["i"], reverse=True)


def next_pending_id(records):
    return "p{}".format(max([int(r["id"][1:]) for r in records if r["id"]] or [0]) + 1)


def graduated_through(records):
    """Timestamp of the last `graduated: through <stamp>` marker: everything at or before it is promoted already."""
    for r in reversed(records):
        if r["kind"] == "graduated":
            m = STAMP.search(r["text"])
            return m.group(0) if m else ""
    return ""


def graduated_prefix(records, through, keep):
    """How many leading lines may be archived: up to the first record past <through>, the marker itself, or a kept one."""
    if not through:
        return 0
    held, cut = {r["i"] for r in keep}, 0
    for r in records:
        if r["stamp"] > through or r["kind"] == "graduated" or r["i"] in held:
            break
        cut = r["i"] + 1
    return cut


def skill_body(path, limit=SKILL_CHARS):
    """A SKILL.md without its frontmatter, capped at `limit` characters; None when the file cannot be read."""
    try:
        with open(path, encoding="utf-8") as fh:
            text = fh.read().replace("\r\n", "\n")
    except OSError:
        return None
    return FRONTMATTER.sub("", text, count=1).strip()[:limit]


def skill_meta(path):
    """(name, description) from a SKILL.md frontmatter; the name falls back to the directory name."""
    with open(path, encoding="utf-8") as fh:
        text = fh.read().replace("\r\n", "\n")
    m = FRONTMATTER.match(text)
    fields = dict(re.findall(r"^([A-Za-z_-]+):\s*(.*)$", m.group(1), re.MULTILINE)) if m else {}
    name = fields.get("name", "").strip().strip("\"'") or os.path.basename(os.path.dirname(path))
    return name, fields.get("description", "").strip().strip("\"'")


def _pushed_path(session):
    return os.path.join(SKILL_STATE, re.sub(r"[^A-Za-z0-9._-]", "_", session) + ".json")


def pushed_skills(session):
    """{scope: [skill names]} already pushed in this session; the scope is the agent_id, or `main`."""
    try:
        with open(_pushed_path(session), encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def mark_pushed(session, scope, name):
    """Record a pushed skill; True only when the record reached disk. Written to a temp file and renamed, so a
    concurrent hook never reads half a file."""
    if not session:
        return False
    try:
        data = pushed_skills(session)
        names = data.setdefault(scope, [])
        if name not in names:
            names.append(name)
        os.makedirs(SKILL_STATE, exist_ok=True)
        path = _pushed_path(session)
        tmp = f"{path}.{os.getpid()}.tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
        os.replace(tmp, path)
        return True
    except Exception:  # noqa: BLE001 - a failed skill-push write just means the skill is not marked pushed
        return False


def clear_pushed(session):
    if not session:
        return
    try:
        os.remove(_pushed_path(session))
    except OSError:
        pass


def once_key(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _once_path(state_dir, session):
    return os.path.join(state_dir, re.sub(r"[^A-Za-z0-9._-]", "_", session or "nosession") + ".json")


def once_seen(state_dir, session):
    """{key: record} of the calls a prompt-tier hook has already stopped once in this session."""
    try:
        with open(_once_path(state_dir, session), encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def once_mark(state_dir, session, key, record):
    """Record a stopped call so its resend passes; True only when the record reached disk. A prompt-tier hook stops
    a call only after this returned True: without the record the resend would be stopped again, so it passes."""
    try:
        data = once_seen(state_dir, session)
        data[key] = dict(record, ts=time.strftime("%Y-%m-%dT%H:%M:%S%z"))
        os.makedirs(state_dir, exist_ok=True)
        path = _once_path(state_dir, session)
        tmp = f"{path}.{os.getpid()}.tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
        os.replace(tmp, path)
        return True
    except Exception:  # noqa: BLE001 - without the record a resend would be stopped again, so the call passes
        return False
