"""PreToolUse hook on Agent and Workflow, no Jev: a brief whose topic overlaps an entry of knowledge/INDEX.md that the
brief does not cite is stopped ONCE, naming the files to read. Every session consults the shared
records before acting - a brief, a design proposal or a "measure X" step first searches knowledge/ (the index and the
topic file) and the related project docs, cites what they settle, and asks for measurement only of the rest
(rules/research.md). This is the enforceable part of that rule.

The installed skills are a second index (sessions never used the skills on his account and built
everything by hand): a brief whose terms overlap an installed skill's description, without naming the skill or saying
why it is not used, is stopped the same way, naming the skill. Skills are read from the synced plugin dirs, the plugin
cache and the user skills, cached in logs/knowledge-check-skills.json keyed by directory mtimes.

Deterministic term matching against the index summaries, read once per call. The same launch sent again unchanged
passes, so a brief whose overlap is spurious costs one resend. Every evaluated launch is logged to
logs/knowledge-check.jsonl (the text itself is not stored). Fail-open: any error or a failed state write lets the
launch through."""

import glob
import json
import os
import re
import time

import _common

ROOT = _common.ROOT
INDEX = os.path.join(ROOT, "knowledge", "INDEX.md")
STATE_DIR = os.path.join(ROOT, "logs", "knowledge-check")
LOG = os.path.join(ROOT, "logs", "knowledge-check.jsonl")
PLUGINS_DIR = os.path.join(ROOT, "plugins")
USER_SKILLS_DIR = os.path.join(ROOT, "skills")
SKILL_CACHE = os.path.join(ROOT, "logs", "knowledge-check-skills.json")
WORKFLOWS_DIR = os.path.join(ROOT, "workflows")
# Distinct summary terms that make an overlap; a stem term alone is enough. Replayed over the last 30
# Agent/Workflow briefs of the home project: 2 stopped 26, 3 stopped 20; over ~40 % at 2 the threshold goes to 3.
MIN_TERMS = 3
SKILL_CACHE_VERSION = 1
# Plugin names that are ordinary words: replayed over the last 30 briefs, `design` sat in 10 of them
# (design audits, design files) and `sales`, `finance`, `engineering` are plain nouns, so none is a stem by itself.
NAME_STOP = frozenset(["design", "sales", "finance", "engineering"])
# Emphasis and function words that the skill descriptions write in capitals (MUST, ALL, FOR), or that open a clause.
DESC_STOP = frozenset(
    [
        "must",
        "mandatory",
        "all",
        "for",
        "from",
        "and",
        "only",
        "this",
        "that",
        "new",
        "any",
        "has",
        "not",
        "use",
        "when",
        "first",
        "general",
        "one",
        "add",
        "log",
        "push",
    ]
    # description terms found in 2 or more of the 20 distinct briefs among the last 30 (replayed): words
    # a brief uses whatever its topic, so they name no skill
    + [
        "sources",
        "read",
        "agent",
        "docs",
        "run",
        "path",
        "rule",
        "chat",
        "render",
        "data",
        "git",
        "screen",
        "small",
        "now",
        "css",
        "event",
        "call",
        "agents",
        "step",
        "mode",
        "english",
        "youtube",
        "default",
        "trigger",
        "browser",
        "search",
        "text",
        "http",
        "tools",
        "json",
        "audio",
        "create",
        "plain",
        "custom",
        "load",
        "content",
        "calls",
        "worker",
        "reddit",
        "client",
        "skills",
        "cpu",
        "voice",
        "jev",
        "next",
        "core",
        "sync",
        "powershell",
        "instance",
        "dpi",
        "palette",
        "studio",
        "cut",
        "markdown",
        "tables",
        "in-game",
        "play",
        "recording",
    ]
)
# Plugins whose descriptions carry no names (remotion: "Create a new Remotion video"): {plugin: (anchor words, extra
# words, extras needed)} - an overlap is one anchor and that many extras in the brief. Chosen on the replay of the
# last 30 briefs: the video-render briefs match remotion, the design audits match design, `pdf` alone matches the
# pdf plugins, and no brief without those words does.
SKILL_TOPICS = {
    "remotion": (
        frozenset(["video", "videos", "mp4", "remotion"]),
        frozenset(["render", "rendering", "frames", "animation", "composition", "captions", "ffmpeg", "mp4"]),
        2,
    ),
    "design": (
        frozenset(["design", "designs", "ui", "ux"]),
        frozenset(
            [
                "critique",
                "accessibility",
                "wcag",
                "a11y",
                "usability",
                "hierarchy",
                "palette",
                "typography",
                "contrast",
                "mockup",
                "figma",
                "review",
                "audit",
                "layout",
                "handoff",
            ]
        ),
        2,
    ),
    "pdf-viewer": (frozenset(["pdf", "pdfs"]), frozenset(), 0),
    "adobe-for-creativity": (frozenset(["pdf", "pdfs"]), frozenset(), 0),
}
USER_SKIP = frozenset(["handoff", "reload", "fan-out", "synced"])
FRONTMATTER = re.compile(r"^---\n(.*?)\n---", re.DOTALL)
SHOW_TERMS = 5
ENTRY = re.compile(r"^- \[([A-Za-z0-9._-]+\.md)\]\([^)]*\)\s*(?:—|-)\s*(.*)$")
TOKEN = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9_\-]*[A-Za-z0-9])?")
NUMERIC = re.compile(r"^[\d_\-]+$")
MAX_DF = 2  # a term in more index summaries than this names no one topic (OBS sits in two stream files and stays)
# Names and hyphenated prose that recur in briefs without naming a topic: capitalised generic words, model names (a
# brief names its agent's model), compound adjectives, and stem pieces as common as `github` or `pricing`.
STOP = frozenset(
    [
        "claude",
        "code",
        "hexis",
        "knowledge",
        "machine",
        "project",
        "projects",
        "session",
        "sessions",
        "user",
        "python",
        "windows",
        "japanese",
        "japan",
        "google",
        "anthropic",
        "fable",
        "opus",
        "sonnet",
        "haiku",
        "active",
        "build",
        "deny",
        "permissions",
        "delivered",
        "held",
        "refused",
        "unverified",
        "ids",
        "job",
        "gnu",
        "engine",
        "light",
        "media",
        "stereo",
        "chrome",
        "download",
        "actions",
        "rest",
        "scripts",
        "skill",
        "plugin",
        "sql",
        "url",
        "urls",
        "api",
        "cli",
        "mcp",
        "free",
        "tier",
        "desktop",
        "model",
        "models",
        "same",
        "get",
        "list",
        "rules",
        "without",
        "again",
        "cloud",
        "context",
        "budget",
        "usage",
        "disk",
        "template",
        "vendor",
        "comparison",
        "features",
        "ecosystem",
        "tooling",
        "languages",
        "access",
        "records",
        "routing",
        "pricing",
        "github",
        "follow-up",
        "read-only",
        "ad-hoc",
        "per-call",
        "per-model",
        "per-hook",
        "per-app-user",
        "re-reads",
        "cross-session",
        "main-session",
        "session-start",
        "auto-loaded",
        "auto-start",
        "fast-changing",
        "false-error",
        "two-pass",
        "non-word",
        "multi-view",
        "prompt-length",
        "paid-only",
        "spot-only",
        "python-only",
        "admin-only",
        "non-archived",
    ]
)


def parse_skill(path):
    """(name, description) from a SKILL.md frontmatter, or None. Handles plain, quoted and block-scalar descriptions."""
    with open(path, encoding="utf-8") as fh:
        m = FRONTMATTER.match(fh.read(8000).replace("\r\n", "\n"))
    if not m:
        return None
    name, desc, lines = "", [], m.group(1).split("\n")
    for i, line in enumerate(lines):
        if line.startswith("name:"):
            name = line[5:].strip().strip("\"'")
        elif line.startswith("description:"):
            first = line[12:].strip()
            if first and first[0] not in ">|":
                desc.append(first.strip("\"'"))
            for cont in lines[i + 1 :]:
                if cont[:1] not in (" ", "\t"):
                    break
                desc.append(cont.strip())
    return (name, " ".join(desc)) if name and desc else None


def skill_dirs():
    """[(plugin, skills dir)]: synced plugins, cached marketplace plugins, and the user skills (plugin "")."""
    found = []
    for root in sorted(glob.glob(os.path.join(PLUGINS_DIR, "synced", "*", "*", ""))) + sorted(
        glob.glob(os.path.join(PLUGINS_DIR, "cache", "*", "*", "*", ""))
    ):
        skills = os.path.join(root, "skills")
        if not os.path.isdir(skills):
            continue
        plugin = ""
        try:
            with open(os.path.join(root, ".claude-plugin", "plugin.json"), encoding="utf-8") as fh:
                plugin = json.load(fh).get("name") or ""
        except (OSError, ValueError):
            pass
        found.append((plugin or re.sub(r"~g\d+$", "", os.path.basename(os.path.dirname(root))), skills))
    return found + [("", USER_SKILLS_DIR)]


def scan_skills():
    """[[plugin, skill, description]], deduplicated by plugin and skill name. User skills skip the ones the hooks already
    push (hexis-*, handoff, reload, fan-out, synced)."""
    rows, seen = [], set()
    for plugin, skills in skill_dirs():
        for path in sorted(glob.glob(os.path.join(skills, "*", "SKILL.md"))):
            folder = os.path.basename(os.path.dirname(path))
            if not plugin and (folder.startswith("hexis-") or folder in USER_SKIP):
                continue
            try:
                parsed = parse_skill(path)
            except OSError:
                continue
            if parsed and (plugin, parsed[0]) not in seen:
                seen.add((plugin, parsed[0]))
                rows.append([plugin, parsed[0], parsed[1]])
    return rows


def skills_stamp():
    """Newest mtime over the plugin roots and skills dirs: a plugin added, removed or updated moves one of them."""
    stamp = 0.0
    for _plugin, skills in skill_dirs():
        for d in (skills, os.path.dirname(skills)):
            try:
                stamp = max(stamp, os.stat(d).st_mtime)
            except OSError:
                pass
    return stamp


def load_skill_entries():
    """The skill index entries (see load_skill_index), from logs/knowledge-check-skills.json while the stamp is
    unchanged: a hook call then costs a stat sweep and one JSON read, not 300 SKILL.md reads and a term pass."""
    stamp = skills_stamp()
    try:
        with open(SKILL_CACHE, encoding="utf-8") as fh:
            cached = json.load(fh)
        if cached.get("stamp") == stamp and cached.get("version") == SKILL_CACHE_VERSION:
            return [(p, set(stems), {s: set(t) for s, t in skills.items()}) for p, stems, skills in cached["entries"]]
    except (OSError, ValueError, KeyError):
        pass
    entries = load_skill_index(scan_skills())
    try:
        os.makedirs(os.path.dirname(SKILL_CACHE), exist_ok=True)
        flat = [[p, sorted(stems), {s: sorted(t) for s, t in skills.items()}] for p, stems, skills in entries]
        with open(SKILL_CACHE, "w", encoding="utf-8") as fh:
            json.dump({"version": SKILL_CACHE_VERSION, "stamp": stamp, "entries": flat}, fh, ensure_ascii=False)
    except OSError:
        pass
    return entries


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


def summary_terms(summary):
    """The names in a summary: tokens written with a capital, a digit, a hyphen or an underscore, or inside backticks.
    Plain lowercase prose (evidence, path, windows) recurs in any brief and says nothing about the topic."""
    ticked = {t for span in re.findall(r"`([^`]*)`", summary) for t in TOKEN.findall(span)}
    terms = set()
    for m in TOKEN.finditer(summary):
        raw = m.group(0)
        tok = raw.lower()
        if tok in STOP or NUMERIC.match(tok):
            continue
        named = raw != tok or any(c.isdigit() for c in tok) or "-" in tok or "_" in tok or raw in ticked
        if named and len(tok) >= 3:
            terms.add(tok)
    return terms


def load_index(path):
    """[(file, stem terms, summary terms)] from the index. A term is distinctive only when at most MAX_DF entries have
    it. One-hit stem terms are the whole stem and the stem pieces no other stem shares."""
    rows = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            m = ENTRY.match(line.strip())
            if m:
                stem = m.group(1)[:-3].lower()
                pieces = {p for p in stem.split("-") if len(p) >= 4 and p not in STOP}
                rows.append((m.group(1), stem, pieces, summary_terms(m.group(2)) | pieces))
    df = {}
    for _, _, _, terms in rows:
        for t in terms:
            df[t] = df.get(t, 0) + 1
    piece_df = {}
    for _, _, pieces, _ in rows:
        for p in pieces:
            piece_df[p] = piece_df.get(p, 0) + 1
    entries = []
    for name, stem, pieces, terms in rows:
        stems = ({stem} - STOP) | {p for p in pieces if piece_df[p] == 1}
        entries.append((name, stems, {t for t in terms if df[t] <= MAX_DF} - stems))
    return entries


def description_terms(desc):
    """summary_terms of a skill description, with the word that opens each sentence lowercased first (a capital there is
    grammar: Use, Create, Run) and the emphasis words of the descriptions (MUST, ALL, FOR) dropped."""
    text = re.sub(r"(^|[.!?:—]\s+)([A-Z])", lambda m: m.group(1) + m.group(2).lower(), desc)
    return summary_terms(text) - DESC_STOP


def load_skill_index(rows):
    """[(plugin, stems, {skill: terms})]: a plugin is one topic. The plugin name is a stem (one term suffices) unless it
    is an ordinary word (NAME_STOP); every description term must sit in at most MAX_DF plugins."""
    plugins = {}
    for plugin, skill, desc in rows:
        plugins.setdefault(plugin, {})[skill] = description_terms(desc)
    df = {}
    for skills in plugins.values():
        for t in set().union(*skills.values()):
            df[t] = df.get(t, 0) + 1
    entries = []
    for plugin, skills in plugins.items():
        stems = {plugin.lower()} - NAME_STOP - STOP if plugin else set()
        entries.append(
            (plugin, stems, {s: {t for t in terms if df[t] <= MAX_DF} - stems for s, terms in skills.items()})
        )
    return entries


def skill_cited(lower, plugin, skills):
    """The brief names the skill: `<plugin>:<skill>`, a hyphenated skill name, the plugin name next to skill or plugin,
    or `not using <name>`."""
    for skill in skills:
        s = re.escape(skill.lower())
        if plugin and re.search(rf"(?<![a-z0-9_-]){re.escape(plugin.lower())}:{s}(?![a-z0-9_-])", lower):
            return True
        if "-" in skill and re.search(rf"(?<![a-z0-9_:-]){s}(?![a-z0-9_-])", lower):
            return True
        if re.search(rf"not using {s}(?![a-z0-9_-])", lower):
            return True
    if not plugin:
        return False
    n = re.escape(plugin.lower())
    edge = r"(?<![a-z0-9_-])" + n + r"(?![a-z0-9_-])"
    near = rf"{edge}.{{0,24}}\b(?:skill|plugin)s?\b|\b(?:skill|plugin)s?\b.{{0,24}}{edge}|not using {edge}"
    return bool(re.search(near, lower))


def match_skills(text, entries, min_terms=MIN_TERMS):
    """({"<plugin>:<skill>": terms} for installed skills the brief overlaps without naming, [plugin named]). A plugin
    overlaps by its distinctive name, by min_terms description terms of one skill, or by its SKILL_TOPICS words."""
    toks = brief_tokens(text)
    lower = text.lower()
    hits, cited = {}, []
    for plugin, stems, skills in entries:
        found_stem = sorted(stems & toks)
        union = max((sorted(t & toks) for t in skills.values()), key=len, default=[])  # the best single skill
        topic = []
        if plugin in SKILL_TOPICS:
            anchors, extras, need = SKILL_TOPICS[plugin]
            if anchors & toks and len(extras & toks) >= need:
                topic = sorted(anchors & toks) + sorted(extras & toks)
        if not (found_stem or topic or len(union) >= min_terms):
            continue
        if skill_cited(lower, plugin, skills):
            cited.append(plugin)
            continue
        found = found_stem + topic + union
        best = max(sorted(skills), key=lambda s: (any(w in s for w in found), len(skills[s] & toks)))
        hits[(plugin + ":" if plugin else "") + best] = found
    return hits, cited


def brief_tokens(text):
    """Every token of the brief, lowercased, with hyphen and underscore parts added, so `obs-multi-rtmp` in a brief
    also counts as `obs`."""
    toks = set()
    for m in TOKEN.finditer(text):
        tok = m.group(0).lower()
        toks.add(tok)
        if "-" in tok or "_" in tok:
            toks.update(p for p in re.split(r"[-_]", tok) if p)
    return toks


def cites(text_lower, name):
    """The file is named: `knowledge/<stem>`, `<stem>.md`, or a hyphenated stem on its own. A bare one-word stem
    (`hooks`, `machine`) is a topic word, not a citation."""
    stem = re.escape(name[:-3].lower())
    bare = "|" + stem if "-" in name else ""
    return bool(re.search(rf"(?<![a-z0-9_-])(?:knowledge[/\\]{stem}|{stem}\.md{bare})(?![a-z0-9_-])", text_lower))


def match(text, entries, min_terms=MIN_TERMS):
    """(overlapping uncited {file: terms}, cited [file]) for a brief."""
    toks = brief_tokens(text)
    lower = text.lower()
    hits, cited = {}, []
    for name, stems, terms in entries:
        found_stem = sorted(stems & toks)
        found = sorted(terms & toks)
        if not found_stem and len(found) < min_terms:
            continue
        if cites(lower, name):
            cited.append(name)
        else:
            hits[name] = found_stem + found
    return hits, cited


def brief_of(tool, inp):
    if tool == "Agent":
        prompt = inp.get("prompt")
        return prompt if isinstance(prompt, str) else json.dumps(prompt, ensure_ascii=False)
    src = inp.get("script") or ""
    path = inp.get("scriptPath") or (os.path.join(WORKFLOWS_DIR, inp["name"] + ".js") if inp.get("name") else "")
    if not src and path:
        try:
            with open(os.path.expanduser(path), encoding="utf-8") as fh:
                src = fh.read()
        except OSError:
            src = ""
    args = inp.get("args")
    return src + ("\n\n" + args if isinstance(args, str) else "")


def log(decision, tool, session, cwd, chars, hits, cited, ms, skills=None, skills_cited=None):
    row = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "decision": decision,
        "tool": tool,
        "session": session,
        "cwd": cwd,
        "chars": chars,
        "matched": hits,
        "cited": cited,
        "skills": skills or {},
        "skills_cited": skills_cited or [],
        "ms": ms,
    }
    try:
        os.makedirs(os.path.dirname(LOG), exist_ok=True)
        with open(LOG, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    except Exception:  # noqa: BLE001, S110 - the log is best-effort, never worth blocking a launch over
        pass


def main(payload):
    tool = payload.get("tool_name")
    if tool not in ("Agent", "Workflow") or payload.get("agent_id"):
        return None
    start = time.perf_counter()
    text = brief_of(tool, payload.get("tool_input") or {})
    session = payload.get("session_id") or ""
    cwd = payload.get("cwd") or ""
    hits, cited = match(text, load_index(INDEX))
    skills, skills_cited = match_skills(text, load_skill_entries())
    ms = round((time.perf_counter() - start) * 1000, 2)
    if not hits and not skills:
        log("pass", tool, session, cwd, len(text), hits, cited, ms, skills, skills_cited)
        return None
    key = _common.once_key(tool + "\n" + text)
    if key in _common.once_seen(STATE_DIR, session):
        log("resend", tool, session, cwd, len(text), hits, cited, ms, skills, skills_cited)
        return None
    if not _common.once_mark(STATE_DIR, session, key, {"tool": tool, "files": sorted(hits), "skills": sorted(skills)}):
        log("would-deny", tool, session, cwd, len(text), hits, cited, ms, skills, skills_cited)
        return None
    log("deny", tool, session, cwd, len(text), hits, cited, ms, skills, skills_cited)
    parts = []
    if hits:
        named = ", ".join(
            "knowledge/{} (terms: {})".format(name, ", ".join(terms[:SHOW_TERMS]))
            for name, terms in sorted(hits.items())
        )
        parts.append(
            f"the brief touches topics the shared records already cover - {named}. Read them and cite what they settle in "
            "the brief (or say why they do not apply)"
        )
    if skills:
        named = ", ".join(
            "{} (terms: {})".format(name, ", ".join(terms[:SHOW_TERMS])) for name, terms in sorted(skills.items())
        )
        parts.append(
            f"the brief touches ground an installed skill covers - {named}. Name the skill you use as <plugin>:<skill>, or "
            "say in the brief why it does not apply"
        )
    return out(
        "Knowledge check: " + "; ".join(parts) + ", then send the launch again; the same launch sent unchanged passes."
    )


_common.run("knowledge-check.py", main)
