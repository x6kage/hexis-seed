"""What a session cost: per-model-family token totals from a transcript and its subagents, priced with the table in
knowledge/model-pricing.md. Usable as a CLI, as summarise(paths), and incrementally against a .cost.json sidecar."""

import json
import os
import re
import sys

# Versioned family names, matched as substrings of the model id, longest first so "opus-5-5" wins over "opus-5".
# A model outside this list prices as "other" at the dearest column values (never free).
FAMILIES = (
    "fable-5-2",
    "fable-5-1",
    "opus-5-5",
    "opus-5",
    "sonnet-5-5",
    "sonnet-5",
    "haiku-5-5>100k",
    "haiku-5-5",
    "haiku-4-5",
)
# Families priced by prompt length, per request: a request whose prompt (input + cache read + cache write) exceeds the
# threshold is booked under the long key at its higher rates, even when part of the prompt is a cache hit.
LONG = {"haiku-5-5": ("haiku-5-5>100k", 100_000)}
# Older sidecars keyed rows by bare family; every one of those was this exact model.
LEGACY = {"fable": "fable-5-1", "opus": "opus-5", "sonnet": "sonnet-5", "haiku": "haiku-4-5"}
FALLBACK = {
    "fable-5-2": (8.0, 10.0, 16.0, 0.2, 40.0),
    "fable-5-1": (10.0, 12.5, 20.0, 0.25, 50.0),
    "opus-5-5": (4.0, 5.0, 8.0, 0.2, 20.0),
    "opus-5": (5.0, 6.25, 10.0, 0.5, 25.0),
    "sonnet-5-5": (2.0, 2.5, 4.0, 0.2, 10.0),
    "sonnet-5": (2.0, 2.5, 4.0, 0.2, 10.0),
    "haiku-5-5>100k": (0.5, 0.625, 1.0, 0.05, 2.5),
    "haiku-5-5": (0.1, 0.125, 0.2, 0.01, 0.5),
    "haiku-4-5": (1.0, 1.25, 2.0, 0.1, 5.0),
}
PRICING = os.path.expanduser("~").replace("\\", "/") + "/.claude/knowledge/model-pricing.md"
ROW = re.compile(
    r"^\|\s*([^|]+?)\s*\|\s*\$([\d.]+)\s*\|\s*\$([\d.]+)\s*/\s*\$([\d.]+)\s*\|\s*\$([\d.]+)\s*\|\s*\$([\d.]+)\s*\|"
)
FIELDS = ("n", "input", "write5", "write1h", "read", "output", "cold_n", "cold5", "cold1h")
# A write this big and more than twice what was read back is a cold re-cache: session start, idle past the TTL, a model
# or effort switch. `read == 0` alone missed the switches: the ~41k tool prefix is still read back after one, so a
# model switch (359k written) and an effort switch (372k written) went uncounted.
COLD_MIN = 20_000


def rates():
    """The five rates per family, read from the pricing table so the numbers have one home."""
    table = {}
    try:
        with open(PRICING, encoding="utf-8") as fh:
            for line in fh:
                m = ROW.match(line)
                fam = next((f for f in FAMILIES if f in m.group(1).lower()), None) if m else None
                if fam and m:
                    table[fam] = tuple(float(m.group(i)) for i in range(2, 7))
    except Exception:  # noqa: BLE001 - an unreadable or malformed pricing table falls back to FALLBACK below
        table = {}
    if set(table) == set(FALLBACK):
        return table, PRICING
    return dict(FALLBACK), "built-in fallback rates (knowledge/model-pricing.md not parsed)"


def rate_of(table, fam):
    """An unknown family is priced at the most expensive column values in the table, never free."""
    return table.get(fam) or tuple(max(c) for c in zip(*table.values(), strict=False))


def blank():
    return {"offset": 0, "last": ["", 0], "context": 0, "fam": "", "fams": {}}


def merge(into, fams):
    for fam, row in fams.items():
        fam = LEGACY.get(fam, fam)
        dst = into.setdefault(fam, dict.fromkeys(FIELDS, 0))
        for k in FIELDS:
            dst[k] = dst.get(k, 0) + row.get(k, 0)


def scan(path, st, dedupe=True):
    """New bytes only. One API response is written as one record per content block, all carrying the same usage and
    a growing output_tokens, so records of one message.id are counted once and only their output delta is added."""
    with open(path, "rb") as fh:
        fh.seek(st["offset"])
        data = fh.read()
    cut = data.rfind(b"\n") + 1
    st["offset"] += cut
    for line in data[:cut].decode("utf-8", "replace").splitlines():
        if '"output_tokens"' not in line:
            continue
        try:
            o = json.loads(line)
        except Exception:  # noqa: BLE001, S112 - a malformed transcript line is skipped, not fatal
            continue
        m = o.get("message")
        if o.get("type") != "assistant" or not isinstance(m, dict) or not m.get("usage"):
            continue
        u, out = m["usage"], m["usage"].get("output_tokens", 0)
        cc = u.get("cache_creation") or {}
        w5, w1 = cc.get("ephemeral_5m_input_tokens"), cc.get("ephemeral_1h_input_tokens", 0)
        if w5 is None:
            w5, w1 = u.get("cache_creation_input_tokens", 0), 0
        read = u.get("cache_read_input_tokens", 0)
        fam = next((f for f in FAMILIES if f in (m.get("model") or "")), "other")
        if fam in LONG and u.get("input_tokens", 0) + read + w5 + w1 > LONG[fam][1]:
            fam = LONG[fam][0]
        row = st["fams"].setdefault(fam, dict.fromkeys(FIELDS, 0))
        st["fam"] = fam
        key = m.get("id") or o.get("requestId") or o.get("uuid")
        if dedupe and key == st["last"][0]:
            row["output"] += max(0, out - st["last"][1])
            st["last"][1] = max(st["last"][1], out)
            continue
        row["n"] += 1
        if row["n"] == 1:
            row["first"] = w5 + w1  # the cold-start write, excluded from per-request new tokens
        row["input"] += u.get("input_tokens", 0)
        row["write5"] += w5
        row["write1h"] += w1
        row["read"] += read
        row["output"] += out
        if w5 + w1 >= COLD_MIN and w5 + w1 > 2 * read:
            row["cold_n"] = row.get("cold_n", 0) + 1
            row["cold5"] = row.get("cold5", 0) + w5
            row["cold1h"] = row.get("cold1h", 0) + w1
        st["last"] = [key, out]
        st["context"] = read + w5 + w1 or st["context"]
    return st


def price(fams):
    table, source = rates()
    rows, total = {}, 0.0
    for fam, row in sorted(fams.items()):
        r = rate_of(table, fam)
        usd = (
            row["input"] * r[0]
            + row["write5"] * r[1]
            + row["write1h"] * r[2]
            + row["read"] * r[3]
            + row["output"] * r[4]
        ) / 1e6
        rows[fam] = dict(
            row,
            usd=usd,
            cold_usd=(row.get("cold5", 0) * r[1] + row.get("cold1h", 0) * r[2]) / 1e6,
            cold_n=row.get("cold_n", 0),
        )
        total += usd
    return {"rows": rows, "usd": total, "requests": sum(r["n"] for r in fams.values()), "source": source}


def summarise(paths, dedupe=True):
    fams = {}
    for p in paths:
        st = blank()
        scan(p, st, dedupe)
        merge(fams, st["fams"])
    return price(fams)


def subagent_paths(transcript):
    root = transcript[:-6] + "/subagents" if transcript.endswith(".jsonl") else ""
    out = []
    for d, _, files in os.walk(root):
        out += [os.path.join(d, f).replace("\\", "/") for f in files if f.endswith(".jsonl")]
    return sorted(out)


def summarise_incremental(transcript, sidecar):
    """Same numbers from the bytes added since the last call, plus the derived figures a per-turn hook needs."""
    st = {"main": blank(), "agents": {}, "prev": 0.0}
    if os.path.isfile(sidecar):
        try:
            with open(sidecar, encoding="utf-8") as fh:
                st.update(json.load(fh))
        except Exception:  # noqa: BLE001, S110 - a corrupt sidecar just starts the running total over
            pass
    for blk in [st["main"]] + list(st["agents"].values()):
        if any(k in LEGACY for k in blk.get("fams", {})):
            fams = {}
            merge(fams, blk["fams"])
            blk["fams"] = fams
            blk["fam"] = LEGACY.get(blk.get("fam", ""), blk.get("fam", ""))
    scan(transcript, st["main"])
    for p in subagent_paths(transcript):
        scan(p, st["agents"].setdefault(p, blank()))
    main = price(st["main"]["fams"])
    agents = {}
    for a in st["agents"].values():
        merge(agents, a["fams"])
    agents = price(agents)
    fams = {}
    merge(fams, st["main"]["fams"])
    for a in st["agents"].values():
        merge(fams, a["fams"])
    all_ = price(fams)
    st["prev"], delta = all_["usd"], all_["usd"] - st["prev"]
    cold_now = sum(r.get("cold_n", 0) for r in main["rows"].values())
    prev_cold, st["prev_cold"] = st.get("prev_cold", 0), cold_now
    try:
        with open(sidecar, "w", encoding="utf-8") as fh:
            json.dump(st, fh)
    except Exception:  # noqa: BLE001, S110 - a failed sidecar write just means the running total is not persisted this time
        pass
    all_.update(
        main=main["usd"],
        agents=agents["usd"],
        delta=delta,
        context=st["main"]["context"],
        avg=all_["usd"] / all_["requests"] if all_["requests"] else 0.0,
        fam=st["main"].get("fam", ""),
        main_rows=main["rows"],
        prev_cold=prev_cold,
    )
    return all_


def table(s):
    head = ("model", "requests", "input", "cache w5", "cache w1h", "cache read", "output", "USD")
    out = ["{:<8} {:>9} {:>8} {:>11} {:>11} {:>13} {:>10} {:>9}".format(*head)]
    for fam, r in s["rows"].items():
        out.append(
            "{:<8} {:>9d} {:>8} {:>11} {:>11} {:>13} {:>10} {:>9.2f}".format(
                fam,
                r["n"],
                f"{r['input']:,}",
                f"{r['write5']:,}",
                f"{r['write1h']:,}",
                f"{r['read']:,}",
                f"{r['output']:,}",
                r["usd"],
            )
        )
    out.append(
        "{:<8} {:>9d} {:>8} {:>11} {:>11} {:>13} {:>10} {:>9.2f}".format(
            "total", s["requests"], "", "", "", "", "", s["usd"]
        )
    )
    out.append("rates: " + s["source"])
    return "\n".join(out)


def main(argv):
    args = [a for a in argv if not a.startswith("--")]
    if not args:
        print("usage: session-cost.py <transcript.jsonl> [--subagents] [--per-record] [--json]")
        return 2
    paths = list(args)
    if "--subagents" in argv:
        for a in args:
            paths += subagent_paths(a)
    s = summarise(paths, dedupe="--per-record" not in argv)
    print(json.dumps(s, indent=1) if "--json" in argv else table(s))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
