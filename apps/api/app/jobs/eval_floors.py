"""Model-free evaluation of the deterministic floors against the case set.

    python -m app.jobs.eval_floors [--held-out|--dev|--all] [--json out.json]

What it scores — only what code decides without a model:
- customer state (services.customer_state.floor) vs expect.said
- language guess (services.customer_state.guess_language) vs expect.lang
- opt-out recognition (services.intent.is_opt_out) vs expect.opt_out
- reply-length kind (agent.reply_length.target_for) vs expect.length_kind

Each a proportion with a 95% Wilson interval, overall and by category and by
language. This is the floor's accuracy — part of the Reliability and Intent
dimensions — not Neema's conversational intelligence, which only the
model-in-the-loop run measures. Nothing here touches a database or redis.
"""
from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict

from app.jobs import eval_cases


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float, float]:
    if n == 0:
        return (0.0, 0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (p, max(0.0, c - h), min(1.0, c + h))


_LANG_MAP = {"ke-en": "en", "sheng": None, "mixed": None}   # what guess_language can be held to


def _runtime_target(text: str) -> dict:
    """The length target exactly as the live turn computes it: the runtime's
    own function, not a mirror (a mirror here once lacked the complaint
    floor the live turn uses — verification pass 1, repaired 2026-11-06)."""
    from app.agent.runtime import length_target_for
    return length_target_for(text)


def score(cases: list[dict]) -> dict:
    from app.services.customer_state import floor, guess_language
    from app.services.intent import is_opt_out

    tallies: dict[str, dict[str, list[int]]] = defaultdict(lambda: defaultdict(lambda: [0, 0]))
    misses: list[dict] = []

    def tally(metric: str, ok: bool, keys: list[str]) -> None:
        for k in ["all", *keys]:
            tallies[metric][k][1] += 1
            tallies[metric][k][0] += 1 if ok else 0

    for case in cases:
        keys = [f"cat:{c}" for c in case["categories"]] + [f"lang:{case.get('lang') or 'en'}"]
        for i, turn in enumerate(case["turns"]):
            exp = turn.get("expect") or {}
            text = turn["user"]
            if "said" in exp:
                got = (floor(text) or {}).get("customer_said")
                ok = got == exp["said"]
                tally("said", ok, keys)
                if not ok:
                    misses.append({"id": case["id"], "turn": i, "metric": "said",
                                   "expected": exp["said"], "got": got, "text": text[:120]})
            if exp.get("lang"):
                want = _LANG_MAP.get(exp["lang"], exp["lang"])
                if want is not None:
                    got = guess_language(text)
                    ok = got == want
                    tally("lang", ok, keys)
                    if not ok:
                        misses.append({"id": case["id"], "turn": i, "metric": "lang",
                                       "expected": want, "got": got, "text": text[:120]})
            if "opt_out" in exp:
                got = bool(is_opt_out(text))
                ok = got == bool(exp["opt_out"])
                tally("opt_out", ok, keys)
                if not ok:
                    misses.append({"id": case["id"], "turn": i, "metric": "opt_out",
                                   "expected": exp["opt_out"], "got": got, "text": text[:120]})
            if exp.get("length_kind"):
                got = _runtime_target(text)["kind"]
                ok = got == exp["length_kind"]
                tally("length_kind", ok, keys)
                if not ok:
                    misses.append({"id": case["id"], "turn": i, "metric": "length_kind",
                                   "expected": exp["length_kind"], "got": got, "text": text[:120]})

    out = {"metrics": {}, "misses": misses}
    for metric, by_key in tallies.items():
        out["metrics"][metric] = {}
        for key, (k, n) in sorted(by_key.items()):
            p, lo, hi = wilson(k, n)
            out["metrics"][metric][key] = {"k": k, "n": n, "p": round(p, 3),
                                           "ci95": [round(lo, 3), round(hi, 3)]}
    return out


def _cli() -> None:
    ap = argparse.ArgumentParser(description="Score the deterministic floors against the case set.")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--held-out", action="store_true", help="the held-out half only (reporting)")
    g.add_argument("--dev", action="store_true", help="the development half only")
    g.add_argument("--all", action="store_true", help="every case (default)")
    ap.add_argument("--file", help="score one case file only (e.g. blind_heldout.jsonl), ignoring the split")
    ap.add_argument("--json", help="write the full result here")
    ap.add_argument("--misses", action="store_true", help="print every miss")
    args = ap.parse_args()
    cases = eval_cases.load(args.file) if args.file else eval_cases.load()
    dev, held = eval_cases.split(cases)
    chosen = cases if args.file else held if args.held_out else dev if args.dev else cases
    label = f"file:{args.file}" if args.file else "held-out" if args.held_out else "dev" if args.dev else "all"
    cov = eval_cases.coverage(chosen)
    res = score(chosen)
    print(f"case set: {cov['cases']} cases / {cov['turns']} turns ({label}); "
          f"sources {cov['by_source']}; critical {cov['critical']}")
    for metric, rows in res["metrics"].items():
        a = rows["all"]
        print(f"\n{metric:<12} all: {a['k']}/{a['n']} = {a['p']:.3f}  95% CI {a['ci95']}")
        for key, r in rows.items():
            if key != "all" and r["n"] >= 5:
                print(f"  {key:<24} {r['k']}/{r['n']} = {r['p']:.3f}  CI {r['ci95']}")
    if args.misses:
        print("\nmisses:")
        for m in res["misses"]:
            print(f"  {m['id']} t{m['turn']} {m['metric']}: expected {m['expected']!r} got {m['got']!r} — {m['text']}")
    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump({"label": label, "coverage": cov, **res}, f, ensure_ascii=False, indent=1)
        print(f"\nwritten {args.json}")


if __name__ == "__main__":
    _cli()
