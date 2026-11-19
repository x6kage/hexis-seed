"""Daily, model-free check for a new Claude model ID. Run by the Task Scheduler task "Model lineup check"
(scripts/register-model-lineup-task.ps1); no model is called.

    python scripts/model-lineup-check.py [--dry-run] [--page FILE] [--settings F] [--pricing F] [--inbox DIR] [--state F] [--log F]

It reads the compare table of the models overview page, takes the IDs in it as the current lineup, and compares them with the IDs
this setup already knows (settings.json pins and `model`, the rows of knowledge/model-pricing.md). A change that was not noted
before writes inbox/YYYY-MM-DD-model-lineup.md, which the next Hexis session lists at start and acts on. Exit 0 on no change or a note
written, 2 on a fetch or parse failure (three in a row write a note that says the check itself is failing).

Probe: https://platform.claude.com/docs/en/models/overview serves 378 kB of HTML that does carry the IDs, but the same
URL with `Accept: text/markdown` (and the `.md` form) serves 19.7 kB of markdown with the compare table as a pipe table and the
legacy models as one `Legacy models (still available): [name](.../models/<slug>/overview), ...` line (names and links, no IDs, so
a legacy ID is `claude-<slug>`). `?format=md` is ignored by the server (HTML again). The forms are tried in the order below.
"""

import argparse
import json
import re
import sys
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
URL = "https://platform.claude.com/docs/en/models/overview"
FORMS = (
    (URL, {"Accept": "text/markdown"}),
    (URL + ".md", {}),
    (URL + "?format=md", {}),
)
UA = "Mozilla/5.0 hexis-model-lineup-check"
ID_RE = re.compile(r"claude-[a-z]+-\d+(?:-\d+)?(?:-\d{8})?")
SLUG_RE = re.compile(r"/models/([a-z0-9-]+)/overview")
LEGACY_MARK = "Legacy models"
EXPIRY_DAYS = 14
FAIL_NOTE_AFTER = 3
PIN_KEYS = (
    "ANTHROPIC_DEFAULT_OPUS_MODEL",
    "ANTHROPIC_DEFAULT_SONNET_MODEL",
    "ANTHROPIC_DEFAULT_HAIKU_MODEL",
    "CLAUDE_CODE_SUBAGENT_MODEL",
)


def fetch_page() -> tuple[str, str]:
    """The first form of the page that carries model IDs: (text, form description)."""
    last = "no form tried"
    for url, extra in FORMS:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, **extra})
            with urllib.request.urlopen(req, timeout=30) as r:
                text = r.read().decode("utf-8", "replace")
        except OSError as e:  # network, DNS, HTTP status: try the next form
            last = f"{url}: {e}"
            continue
        if ID_RE.search(text):
            return text, url + (" Accept=" + extra["Accept"] if extra else "")
        last = f"{url}: no model IDs in {len(text)} chars"
    raise RuntimeError(last)


def parse_page(text: str) -> tuple[set[str], set[str], str]:
    """(current IDs, legacy IDs, scope) - the current IDs come from the part before the legacy marker."""
    cut = text.find(LEGACY_MARK)
    head, tail, scope = (
        (text[:cut], text[cut:], "compare table") if cut >= 0 else (text, "", "whole page (no legacy marker)")
    )
    current = set(ID_RE.findall(head))
    legacy = {"claude-" + s for s in SLUG_RE.findall(tail.split("\n", 1)[0])}
    return current, legacy, scope


def known_ids(settings: Path, pricing: Path) -> tuple[set[str], set[str]]:
    """(all known IDs, the IDs settings.json pins)."""
    cfg = json.loads(settings.read_text(encoding="utf-8"))
    pins = {cfg.get("env", {}).get(k, "") for k in PIN_KEYS}
    pins.add(cfg.get("model", "").split("[")[0])
    pins = {p for p in pins if p.startswith("claude-")}
    priced: set[str] = set()
    for line in pricing.read_text(encoding="utf-8").splitlines():
        if line.startswith("|"):
            priced.update(ID_RE.findall(line))
    return pins | priced, pins


def is_legacy(model_id: str, legacy: set[str]) -> bool:
    return any(re.fullmatch(re.escape(legacy_id) + r"(-\d{8})?", model_id) for legacy_id in legacy)


def note_body(new: list[str], moved: list[str], form: str, fetched: str) -> str:
    lines = [f"Model lineup change seen by scripts/model-lineup-check.py on {fetched}.", ""]
    lines.append("New current IDs (not in settings.json or knowledge/model-pricing.md): " + (", ".join(new) or "none"))
    lines.append("Known IDs that moved to the legacy list: " + (", ".join(moved) or "none"))
    lines += [
        "",
        f"Source: {URL} (fetched {fetched} as {form}).",
        "",
        "Procedure:",
        "1. The user runs `pwsh -File ~/claude-autoupdate.ps1 -Update` first (desktop app and CLI update, one UAC prompt):",
        "   the desktop app does not auto-update (blocked by policy, knowledge/machine.md updater line), and a new model cannot be used here before it.",
        "2. The Hexis session verifies the IDs and prices on https://platform.claude.com/docs/en/about-claude/pricing, probes `claude -p --model <id>`, then updates",
        "   settings.json pins, CLAUDE.md Models, knowledge/model-pricing.md, scripts/session-cost.py (+ tests), knowledge/model-routing.md,",
        "   rules/agents.md and rules/output.md tier names, and skills/hexis-routing/SKILL.md.",
        "3. Delete this file when done.",
        "",
    ]
    return "\n".join(lines)


def fail_note_body(failures: int, reason: str, now: str) -> str:
    return (
        f"scripts/model-lineup-check.py has failed {failures} runs in a row (last {now}): {reason}\n\n"
        "The daily model lineup check cannot see new models while this lasts. Look at logs/model-lineup-check.log; the page "
        f"layout ({URL}) or the network may have changed. Delete this file when the check runs again.\n"
    )


def write_note(inbox: Path, slug: str, today: datetime, body: str) -> Path:
    inbox.mkdir(parents=True, exist_ok=True)
    stem = f"{today:%Y-%m-%d}-{slug}"
    path = inbox / f"{stem}.md"
    n = 2
    while path.exists():
        path = inbox / f"{stem}-{n}.md"
        n += 1
    expiry = f"{today + timedelta(days=EXPIRY_DAYS):%Y-%m-%d}"
    path.write_text(f"expires: {expiry}\n\n{body}", encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--page", type=Path, help="read the page from this file instead of fetching it (tests)")
    ap.add_argument("--settings", type=Path, default=ROOT / "settings.json")
    ap.add_argument("--pricing", type=Path, default=ROOT / "knowledge" / "model-pricing.md")
    ap.add_argument("--inbox", type=Path, default=ROOT / "inbox")
    ap.add_argument("--state", type=Path, default=ROOT / "logs" / "model-lineup-check.json")
    ap.add_argument("--log", type=Path, default=ROOT / "logs" / "model-lineup-check.log")
    args = ap.parse_args(argv)

    now = datetime.now().astimezone()
    stamp = now.strftime("%Y-%m-%d %H:%M:%S")
    state = json.loads(args.state.read_text(encoding="utf-8")) if args.state.exists() else {}
    failures = int(state.get("failures", 0))

    def log(msg: str) -> None:
        print(msg)
        if not args.dry_run:
            args.log.parent.mkdir(parents=True, exist_ok=True)
            with args.log.open("a", encoding="utf-8") as f:
                f.write(f"{stamp} {msg}\n")

    def save() -> None:
        if not args.dry_run:
            args.state.parent.mkdir(parents=True, exist_ok=True)
            args.state.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")

    try:
        text, form = (args.page.read_text(encoding="utf-8"), str(args.page)) if args.page else fetch_page()
        current, legacy, scope = parse_page(text)
        if not current:
            raise RuntimeError("no current model IDs parsed")
        known, pins = known_ids(args.settings, args.pricing)
    except (RuntimeError, OSError, ValueError) as e:
        failures += 1
        state.update(last_run=stamp, failures=failures)
        log(f"FAIL ({failures} in a row): {e}")
        if failures >= FAIL_NOTE_AFTER and not state.get("failing_noted"):
            if args.dry_run:
                print("would write a failing note")
            else:
                write_note(args.inbox, "model-lineup-check-failing", now, fail_note_body(failures, str(e), stamp))
            state["failing_noted"] = True
        save()
        return 2

    seen_before = set(state.get("last_current", []))
    new = sorted(current - known)
    moved = sorted(i for i in known if is_legacy(i, legacy) and (i in seen_before or i in pins))
    noted = state.get("last_noted", {"new": [], "legacy": []})
    key = {"new": new, "legacy": moved}
    wrote = None
    if (new or moved) and key != noted:
        body = note_body(new, moved, form, stamp)
        if args.dry_run:
            print("would write inbox note:\n" + body)
            wrote = "dry-run"
        else:
            wrote = write_note(args.inbox, "model-lineup", now, body).name
    state.update(last_run=stamp, last_current=sorted(current), last_noted=key, failures=0, failing_noted=False)
    save()
    log(
        f"ok scope={scope} current={len(current)} legacy={len(legacy)} new={new} legacy_moves={moved} note={wrote or 'none'}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
