"""TypeSafe Jev client for the hooks: several Noul and Choice questions per call (evaluated in parallel, so one
call costs the same latency - docs.typesafe.ai/patterns/fan-out), a timeout, None on any error so a Jev outage never
blocks the user. Also reads the transcript tail, keeps the per-session readings and writes the calibration log the Jev
hooks share."""

import json
import os
import re
import threading
import time
import urllib.error
import urllib.request

URL = "https://api.typesafe.ai/v1/systemone"
# The deciding version is PINNED while the hook thresholds are being calibrated (not "latest decides": the user asked
# for proposals judged on evidence, their own decisions included, and thresholds tuned on one version can shift under the next - TypeSafe and third-party guides both say pin when
# tuning). jev-latest runs as a shadow; when it resolves to a new version, model_change_note() says so once, and
# the recent decisions are replayed under it (scripts/jev-replay.py --model) before the pin moves - or, cheaper and
# on the same inputs, the shadow answers already in the log are compared at each hook's bar.
# jev-1.14.0 is pinned on the user's order: 73 live rows with a 1.14.0 shadow showed 1 flip in 44 gated comparisons
# against 1.13.0 (misread clear 0.11->0.13).
MODEL = "jev-1.14.0"
LATEST = "jev-latest"
SHADOW = (LATEST, "jev-preview")  # asked in parallel and logged only; see nouls()
LAST_SHADOW = None
SHADOW_GRACE = 0.5  # seconds the shadows get after the decider has answered
LAST_MODEL = None  # the version `MODEL` resolved to on the last call
# Most calls take 0.2-1.5 s, but a burst of 15 concurrent calls had three take 4.6, 5.6 and 6.5 s - no
# 429, no rate-limit headers. A timeout makes a gate silently allow, so the default leaves room for such spikes.
TIMEOUT = 8.0
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KEY_FILE = os.path.join(ROOT, "secrets", "typesafe_hexis_api_key.txt")
LOG = os.path.join(ROOT, "logs", "jev-hooks.jsonl")
READINGS = os.path.join(ROOT, "logs", "jev-readings")  # one JSON list per session: Jev's reading of each user input
MODEL_FILE = os.path.join(ROOT, "logs", "jev-model.txt")  # the version the deciding alias last resolved to
KEEP_READINGS = 10
TAIL_BYTES = 2_000_000
COMPACT_SUMMARY = "This session is being continued"
SKIP_PREFIXES = ("<command-", "<local-command", "<task-notification", "<system-reminder")


def _answer(a):
    """A Noul answer is P(yes); a Choice answer is [choice, confidence]."""
    if a.get("type") == "choice" or "choice" in a:
        return [a["choice"], round(float(a.get("confidence") or 0), 3)]
    return float(a["noul"])


LAST_ERROR = None  # why the last deciding call failed, for the log
RETRY_STATUS = (429, 529)  # docs.typesafe.ai/api: retry these with backoff instead of immediately


def _call(key, model, state, qs, retry=False):
    """(resolved model name, {id: answer}) from one request, or None on any failure. With `retry`, a 429/529 is
    retried once after a short backoff - the deciding call only; a shadow is not worth the extra load."""
    global LAST_ERROR
    body = json.dumps({"state": state, "model": model, "questions": qs}).encode("utf-8")
    for attempt in range(2 if retry else 1):
        try:
            req = urllib.request.Request(
                URL,
                data=body,
                method="POST",
                headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                data = json.loads(resp.read())
            return data.get("model") or model, {qid: _answer(a) for qid, a in data["answers"].items()}
        except urllib.error.HTTPError as e:
            if retry:
                LAST_ERROR = f"http {e.code}"
            if e.code in RETRY_STATUS and attempt == 0 and retry:
                time.sleep(0.8)
                continue
            return None
        except Exception as e:  # noqa: BLE001 - a failed Jev call answers None, the caller's fail-open path
            if retry:
                LAST_ERROR = type(e).__name__
            return None
    return None


def nouls(state, questions):
    """{id: answer} from the pinned MODEL, or None on any failure. `questions` maps an id to
    (instructions, criteria-or-None) for a Noul, or ("choice", instructions, {option: description}) for a Choice.
    The same questions go in parallel to the SHADOW aliases, whose answers are kept in LAST_SHADOW for the log only -
    they never decide anything, but they show how a newer Jev would have judged the same case, so a better release is
    noticed and the pin moved after re-calibration."""
    global LAST_SHADOW, LAST_MODEL, LAST_ERROR, LAST_INPUT
    LAST_SHADOW, LAST_MODEL, LAST_ERROR = None, None, None
    LAST_INPUT = {"state": state, "questions": questions}
    try:
        with open(KEY_FILE, encoding="utf-8") as fh:
            key = fh.read().strip()
        qs = {}
        for qid, spec in questions.items():
            if spec[0] == "choice":
                qs[qid] = {"type": "choice", "instructions": spec[1], "criteria": spec[2]}
                continue
            instructions, criteria = spec
            qs[qid] = {"type": "noul", "instructions": instructions}
            if criteria:
                qs[qid]["criteria"] = criteria
        # Shadows run on daemon threads and get SHADOW_GRACE after the decider returns: they must neither delay the
        # decision nor keep the hook process alive (a pool waited for the slowest shadow).
        shadow_out = {}

        def shadow(m):
            r = _call(key, m, state, qs)
            if r:
                shadow_out[m] = {"model": r[0], "ps": r[1]}

        threads = [threading.Thread(target=shadow, args=(m,), daemon=True) for m in SHADOW]
        for t in threads:
            t.start()
        decider = _call(key, MODEL, state, qs, retry=True)
        deadline = time.perf_counter() + SHADOW_GRACE
        for t in threads:
            t.join(max(0.0, deadline - time.perf_counter()))
        LAST_SHADOW = dict(shadow_out)
        if not decider:
            return None
        LAST_MODEL = decider[0]
        return decider[1]
    except Exception:  # noqa: BLE001 - a failed Jev call answers None, the caller's fail-open path
        return None


def version():
    """The Jev version that answered the last call ('1.13.0'), so a printed score is never read as a version."""
    return (LAST_MODEL or MODEL).replace("jev-", "")


def tag(qid, p):
    """How a score is shown to the session: 'Jev 1.13.0: dropped 0.81' ('Jev 0.81' reads as a
    version number)."""
    return f"Jev {version()}: {qid} {p:.2f}"


def timed_nouls(state, questions):
    t = time.perf_counter()
    ps = nouls(state, questions)
    return ps, int((time.perf_counter() - t) * 1000)


def log(hook, p, decision, ms, text, cwd="", source="", ps=None, session="", flags=None):
    """`p` is the answer the decision was taken on; `ps` every answer of the call, so the arms that only log
    (not yet acted on) can be calibrated separately and are never averaged with the acting one. `flags` names the
    log-tier checks that would have stopped the call. The text itself is NOT stored: the transcript
    already holds it, and `session` + `ts` find it there."""
    row = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "hook": hook,
        "model": LAST_MODEL or MODEL,
        "p": p,
        "ps": ps,
        "decision": decision,
        "ms": ms,
        "cwd": cwd,
        "source": source,
        "session": session,
        "chars": len(text or ""),
        "shadow": LAST_SHADOW,
        "error": LAST_ERROR,
    }
    if flags:
        row["flags"] = flags
    try:
        os.makedirs(os.path.dirname(LOG), exist_ok=True)
        with open(LOG, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    except Exception:  # noqa: BLE001, S110 - the Jev decision log is best-effort, never worth blocking the hook over
        pass
    if decision in FIRED:
        save_input(row)


# Inputs of FIRED decisions only, kept locally for INPUT_DAYS so a fire can be relabelled later (the user's choice;
# the no-text rule still holds for every other call). Secrets redacted.
FIRED = {"deny", "prompt", "flag", "block", "would-deny", "would-block", "would-prompt"}
INPUTS = os.path.join(ROOT, "logs", "jev-inputs")
INPUT_DAYS = 30
LAST_INPUT = None
SECRET = re.compile(
    r"(?:sk-[A-Za-z0-9_\-]{8,}|lin_(?:api|oauth)_[A-Za-z0-9]{8,}|gh[pousr]_[A-Za-z0-9]{8,}"
    r"|Bearer\s+\S+|-----BEGIN [A-Z ]+-----|[A-Za-z0-9+/_\-]{40,})"
)


def _redact(obj):
    if isinstance(obj, str):
        return SECRET.sub("[redacted]", obj)
    if isinstance(obj, dict):
        return {k: _redact(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_redact(v) for v in obj]
    return obj


def save_input(row):
    """Write the last call's input next to its log row, then drop day folders older than INPUT_DAYS. Best-effort."""
    try:
        day = row["ts"][:10]
        folder = os.path.join(INPUTS, day)
        os.makedirs(folder, exist_ok=True)
        name = f"{row['hook']}-{row['ts'][11:19].replace(':', '')}-{(row.get('session') or 'none')[:8]}.json"
        with open(os.path.join(folder, name), "w", encoding="utf-8") as fh:
            json.dump(_redact({"row": row, "input": LAST_INPUT}), fh, ensure_ascii=False)
        cutoff = time.strftime("%Y-%m-%d", time.localtime(time.time() - INPUT_DAYS * 86400))
        for d in os.listdir(INPUTS):
            if len(d) == 10 and d < cutoff:
                for f in os.listdir(os.path.join(INPUTS, d)):
                    os.remove(os.path.join(INPUTS, d, f))
                os.rmdir(os.path.join(INPUTS, d))
    except Exception:  # noqa: BLE001, S110 - the input journal is best-effort, never worth blocking the hook over
        pass


def latest_version():
    """The version jev-latest resolved to on the last call: the decider's when it is the alias, else its shadow's."""
    if MODEL == LATEST:
        return LAST_MODEL
    return ((LAST_SHADOW or {}).get(LATEST) or {}).get("model")


def model_change_note():
    """One line when jev-latest resolved to a different version than last recorded, else ''."""
    current = latest_version()
    if not current:
        return ""
    path = MODEL_FILE
    try:
        with open(path, encoding="utf-8") as fh:
            seen = fh.read().strip()
    except Exception:  # noqa: BLE001 - a missing or unreadable model-file just means no previous version was seen
        seen = ""
    if seen == current:
        return ""
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(current)
    except Exception:  # noqa: BLE001 - a failed write just means the model-change note fires again next time
        return ""
    if not seen:
        return ""
    return (
        f" Jev latest moved from {seen} to {current} (the hooks still decide on {MODEL}): replay recent decisions under it with "
        "scripts/jev-replay.py and re-check the thresholds before moving the pin."
    )


def save_reading(session, reading):
    """Append Jev's typed reading of one user input to the session's file, so later hooks use it instead of asking
    Jev again (Jev first: the reading is made once, where the input arrives)."""
    if not session:
        return
    try:
        os.makedirs(READINGS, exist_ok=True)
        path = os.path.join(READINGS, session + ".json")
        rows = recent_readings(session, KEEP_READINGS - 1)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(rows + [dict(reading, ts=time.strftime("%Y-%m-%dT%H:%M:%S%z"))], fh, ensure_ascii=False)
    except Exception:  # noqa: BLE001, S110 - saving the reading is best-effort, never worth blocking the hook over
        pass


def recent_readings(session, n):
    try:
        with open(os.path.join(READINGS, session + ".json"), encoding="utf-8") as fh:
            return json.load(fh)[-n:] if n > 0 else []
    except Exception:  # noqa: BLE001 - a missing or corrupt readings file just means no prior readings
        return []


def _text(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
    return ""


def opens_turn(d):
    """True when a transcript row is a user entry that can open a turn: a human prompt, a notification or a peer
    session's message. Tool results are filtered by the callers (they carry no text block). Not these: sidechain rows,
    meta rows other than a peer message (isMeta with turnOrigin "peer" is how a peer message is written, and a peer
    entry counts whether or not isMeta is set), and the compaction summary, which the harness writes with
    turnOrigin "peer" and a timestamp older than the message that triggered it; it never opens a turn, so the peer
    message before it stays the turn's opening entry."""
    if d.get("type") != "user" or d.get("isSidechain"):
        return False
    if d.get("isCompactSummary") or _text((d.get("message") or {}).get("content")).startswith(COMPACT_SUMMARY):
        return False
    return d.get("turnOrigin") == "peer" or not d.get("isMeta")


def turns(transcript_path):
    """(role, text) for real user prompts and assistant text in the transcript tail; tool traffic and meta skipped.
    A message the user sends while a turn is running is NOT a user entry: it is recorded as
    {"type": "attachment", "attachment": {"type": "queued_command", "prompt": ..., "humanTurn": true}} and absorbed
    mid-turn - reading only user entries misses every such message."""
    out = []
    try:
        with open(transcript_path, "rb") as fh:
            fh.seek(0, 2)
            size = fh.tell()
            fh.seek(max(0, size - TAIL_BYTES))
            data = fh.read()
    except Exception:  # noqa: BLE001 - a missing or unreadable transcript just yields no turns
        return out
    lines = data.split(b"\n")
    if len(data) < size:
        lines = lines[1:]
    for raw in lines:
        try:
            d = json.loads(raw)
        except Exception:  # noqa: BLE001, S112 - a malformed transcript line is skipped, not fatal
            continue
        role = d.get("type")
        att = d.get("attachment") if role == "attachment" else None
        if att and att.get("type") == "queued_command" and att.get("commandMode", "prompt") == "prompt":
            text = (att.get("prompt") or "").strip() if isinstance(att.get("prompt"), str) else ""
            if text and not text.startswith(SKIP_PREFIXES):
                out.append(("user", text))
            continue
        if role not in ("user", "assistant") or d.get("isMeta") or d.get("isSidechain"):
            continue
        text = _text((d.get("message") or {}).get("content")).strip()
        if not text or (role == "user" and text.startswith(SKIP_PREFIXES)):
            continue
        out.append((role, text))
    return out
