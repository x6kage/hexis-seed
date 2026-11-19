"""Offline tests for scripts/session-cost.py: model-id parsing and the per-request prompt-length tier of Haiku 5.5."""

import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("session_cost", SCRIPTS / "session-cost.py")
assert spec and spec.loader
cost = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cost)
TMP = tempfile.mkdtemp()


def record(model, msg_id, read, write, out, inp=10):
    usage = {
        "input_tokens": inp,
        "cache_read_input_tokens": read,
        "cache_creation_input_tokens": write,
        "cache_creation": {"ephemeral_5m_input_tokens": 0, "ephemeral_1h_input_tokens": write},
        "output_tokens": out,
    }
    return {"type": "assistant", "message": {"id": msg_id, "model": model, "usage": usage}}


def transcript(name, records):
    path = os.path.join(TMP, name + ".jsonl")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("".join(json.dumps(r) + "\n" for r in records))
    return path


class SessionCost(unittest.TestCase):
    def test_pricing_table_parses(self):
        self.assertEqual(cost.rates()[1], cost.PRICING)

    def test_model_ids(self):
        for model, fam in (("claude-haiku-5-5", "haiku-5-5"), ("claude-haiku-4-5-20251001", "haiku-4-5")):
            st = cost.scan(transcript(fam, [record(model, "m1", 0, 1_000, 10)]), cost.blank())
            self.assertEqual(list(st["fams"]), [fam])

    def test_haiku_5_5_under_threshold_is_low_tier(self):
        s = cost.summarise([transcript("low", [record("claude-haiku-5-5", "m1", 60_000, 39_990, 1_000)])])
        self.assertEqual(list(s["rows"]), ["haiku-5-5"])
        self.assertAlmostEqual(s["usd"], (10 * 0.1 + 39_990 * 0.2 + 60_000 * 0.01 + 1_000 * 0.5) / 1e6)

    def test_haiku_5_5_over_threshold_counts_cache_reads(self):
        recs = [
            record("claude-haiku-5-5", "m1", 99_000, 1_000, 500),
            record("claude-haiku-5-5", "m1", 99_000, 1_000, 800),
        ]
        s = cost.summarise([transcript("high", recs)])
        self.assertEqual(list(s["rows"]), ["haiku-5-5>100k"])
        self.assertEqual(s["rows"]["haiku-5-5>100k"]["output"], 800)
        self.assertAlmostEqual(s["usd"], (10 * 0.5 + 1_000 * 1.0 + 99_000 * 0.05 + 800 * 2.5) / 1e6)

    def test_haiku_4_5_unchanged(self):
        s = cost.summarise([transcript("old", [record("claude-haiku-4-5-20251001", "m1", 99_000, 1_000, 800)])])
        self.assertEqual(list(s["rows"]), ["haiku-4-5"])
        self.assertAlmostEqual(s["usd"], (10 * 1.0 + 1_000 * 2.0 + 99_000 * 0.1 + 800 * 5.0) / 1e6)


if __name__ == "__main__":
    unittest.main()
