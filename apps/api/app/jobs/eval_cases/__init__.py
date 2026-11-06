"""The intelligence evaluation case set (directive §5, 2026-11-06).

One JSON object per line in every `*.jsonl` file in this folder. A case is a
scripted customer conversation with, per turn, the facts the system can be
held to. Two layers read it:

- `app.jobs.eval_floors` — model-free: the deterministic floors (customer
  state, language, opt-out, length target) against the gold labels. Runs
  anywhere, in seconds, no key.
- `app.jobs.agent_eval --cases` — model-in-the-loop: the real prompt, model
  and catalogue, sends disabled; objective assertions on the transcript and
  the business state, plus the judged dimensions exported for raters.

Schema (every key optional unless marked):
  id*           "cat-nnn", unique across files
  source*       "real-derived" (anonymised production thread) | "audit"
                (from the 5–6 Nov audits) | "independent" (authored without
                reading the implementation)
  categories*   list from CATEGORIES
  lang          expected language of the customer: en | sw | ke-en (Kenyan
                English) | sheng | fr | pt | hi | mixed
  country       ISO-2 for the throwaway contact (KE, TZ, UG, ZA, NG, US, GB, IN…)
  critical      true when a wrong outcome is a safety or financial error
  turns*        list of {user*, expect}
    expect.said        gold customer-state: one of STATES or null
    expect.lang        gold language of this message
    expect.opt_out     true when this message is an opt-out
    expect.next*       gold next action: answer | ask_one | quote | silence |
                       hold_ack | care_first | escalate | stop_ack | confirm_paid_check
    expect.length_kind gold reply-length kind: ack | short | question | default | complaint | detail
    expect.forbid      regexes that must not appear in the reply (case-insensitive)
    expect.require     regexes that must appear in the reply
    expect.figures     "hub-only" — every money figure must come from this turn's tool results
    expect.judge       dimensions a rater scores on this turn: emotion | sales | culture | natural
    expect.tool        a tool name that must (or with "!" must not) be called
  notes         why the case exists; what a good reply does
"""
from __future__ import annotations

import json
from pathlib import Path

CATEGORIES = (
    "simple-enquiry", "complex-enquiry", "price-objection", "org-purchase",
    "emotional", "cultural", "intent-change", "multi-request", "complaint",
    "delay", "mistake", "uncertain-info", "successful-sale", "unsuccessful-sale",
    "needs-silence", "multilingual", "code-switch", "tool-failure", "human-takeover",
    "delivery-uncertainty", "opt-out", "payment", "memory", "onboarding", "closing",
)
NEXT_ACTIONS = ("answer", "ask_one", "quote", "silence", "hold_ack", "care_first",
                "escalate", "stop_ack", "confirm_paid_check")
STATES = ("exploring", "quoting", "comparing", "consulting", "needs_time", "ready",
          "paid_claim", "complaint", "closing", "stop", None)
LENGTH_KINDS = ("ack", "short", "question", "default", "complaint", "detail")
LANGS = ("en", "sw", "ke-en", "sheng", "fr", "pt", "hi", "mixed")

HERE = Path(__file__).parent


def load(pattern: str = "*.jsonl") -> list[dict]:
    """Every case, validated, in file order. Raises on a malformed case so a
    bad label never scores silently."""
    cases: list[dict] = []
    seen: set[str] = set()
    for path in sorted(HERE.glob(pattern)):
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                case = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path.name}:{n}: {exc}") from None
            _validate(case, f"{path.name}:{n}")
            if case["id"] in seen:
                raise ValueError(f"{path.name}:{n}: duplicate id {case['id']}")
            seen.add(case["id"])
            case["_file"] = path.name
            cases.append(case)
    return cases


def _validate(case: dict, where: str) -> None:
    for key in ("id", "source", "categories", "turns"):
        if key not in case:
            raise ValueError(f"{where}: missing {key}")
    if case["source"] not in ("real-derived", "audit", "independent"):
        raise ValueError(f"{where}: bad source {case['source']}")
    bad = [c for c in case["categories"] if c not in CATEGORIES]
    if bad:
        raise ValueError(f"{where}: unknown categories {bad}")
    if case.get("lang") and case["lang"] not in LANGS:
        raise ValueError(f"{where}: unknown lang {case['lang']}")
    if not case["turns"]:
        raise ValueError(f"{where}: no turns")
    for i, turn in enumerate(case["turns"]):
        if not isinstance(turn, dict) or not (turn.get("user") or "").strip():
            raise ValueError(f"{where}: turn {i} has no user text")
        exp = turn.get("expect") or {}
        if "next" not in exp:
            raise ValueError(f"{where}: turn {i} has no expect.next")
        if exp["next"] not in NEXT_ACTIONS:
            raise ValueError(f"{where}: turn {i} bad next {exp['next']}")
        if "said" in exp and exp["said"] not in STATES:
            raise ValueError(f"{where}: turn {i} bad said {exp['said']}")
        if exp.get("length_kind") and exp["length_kind"] not in LENGTH_KINDS:
            raise ValueError(f"{where}: turn {i} bad length_kind")
        if exp.get("lang") and exp["lang"] not in LANGS:
            raise ValueError(f"{where}: turn {i} bad lang")


def split(cases: list[dict], *, seed: int = 20261106) -> tuple[list[dict], list[dict]]:
    """A fixed development / held-out split by id hash — the same every run,
    on every machine, whatever order the files are read in."""
    import hashlib
    dev, held = [], []
    for c in cases:
        h = int(hashlib.sha256(f"{seed}:{c['id']}".encode()).hexdigest(), 16)
        (held if h % 2 else dev).append(c)
    return dev, held


def coverage(cases: list[dict]) -> dict:
    out = {"cases": len(cases), "turns": sum(len(c["turns"]) for c in cases),
           "by_source": {}, "by_category": {}, "by_lang": {}, "critical": 0}
    for c in cases:
        out["by_source"][c["source"]] = out["by_source"].get(c["source"], 0) + 1
        for cat in c["categories"]:
            out["by_category"][cat] = out["by_category"].get(cat, 0) + 1
        lang = c.get("lang") or "en"
        out["by_lang"][lang] = out["by_lang"].get(lang, 0) + 1
        out["critical"] += 1 if c.get("critical") else 0
    return out
