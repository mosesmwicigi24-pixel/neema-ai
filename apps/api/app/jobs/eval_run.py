"""Run the intelligence case set through the REAL agent — prompt, model,
catalogue, cart, gate — and score every turn against its gold labels.

    python -m app.jobs.agent_eval --cases [--held-out|--dev|--file blind_heldout.jsonl]
        [--repeat 3] [--only sales-0] [--out results.json] [--history] [--keep]

Extends agent_eval (same pipeline, same throwaway contacts, same cleanup):
the SCENARIOS and EXPERIENCE sets stay as they are; this adds the 300–500
case set from app/jobs/eval_cases with objective assertions per turn, a
development/held-out split, pass^k over --repeat runs, and a run record
(model ids, prompt revision, case-set hash, git sha) so two runs can be
compared. Nothing reaches a customer:

- the contacts are throwaway numbers provisioned for the run and deleted after;
- the tools that reach a customer or a financial system are sandboxed for
  the duration of the run (send_product_cards, send_measurement_guide,
  create_order): the call is recorded in the tool log and answered with a
  sandbox result, nothing is sent or created;
- the opt-out door and the closer gate are exercised exactly as the live
  WhatsApp path exercises them (schedule_reply), minus the send.

Scoring is objective only. Turns marked `judge` are exported to a rater
packet (--packet) for humans; a model judge, where the owner wants one, is a
separate step and never the sole basis for a judged dimension.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import time
from datetime import datetime, timezone

from app.core.config import settings
from app.jobs import eval_cases

# Throwaway contacts by country: a prefix that resolves to the right market
# in provision_user, then a running index. Nothing real has these numbers
# in our inbox; the run deletes every row it created.
COUNTRY_PREFIX = {
    "KE": "2547000", "TZ": "2557000", "UG": "2567000", "RW": "2507000", "BI": "2577000",
    "SS": "2119000", "CD": "2438000", "MZ": "2588000", "AO": "2449000", "ZA": "276500",
    "NG": "2347000", "GH": "2335000", "US": "1555000", "GB": "447700", "IN": "919000",
    "FR": "336000", "PT": "35191000",
}
EVAL_TAG = "9"      # every eval contact has this digit after the prefix: 2547000 9 xxx


def contact_for(case: dict, idx: int) -> str:
    prefix = COUNTRY_PREFIX.get((case.get("country") or "KE").upper(), COUNTRY_PREFIX["KE"])
    return f"{prefix}{EVAL_TAG}{idx:03d}"


# ── sandboxed tools ──────────────────────────────────────────────────────────

SANDBOXED = ("send_product_cards", "send_measurement_guide", "create_order")

# Case authors name tools by intent; the runner maps those names onto the
# registered tools so a label never depends on an internal name.
TOOL_ALIASES = {
    "check_payment": "check_order_status", "check_order": "check_order_status",
    "payment_status": "check_order_status", "order_status": "check_order_status",
    "search_catalogue": "search_catalog", "search": "search_catalog", "lookup": "search_catalog",
    "handoff": "handoff_to_human", "escalate": "handoff_to_human", "quote": "prepare_quotation",
    "quotation": "prepare_quotation", "place_order": "create_order", "order": "create_order",
}


def canonical_tool(name: str) -> str:
    n = (name or "").strip()
    bang = n.startswith("!")
    core = n[1:] if bang else n
    core = TOOL_ALIASES.get(core, core)
    return ("!" + core) if bang else core


class _Sandbox:
    """Swap the customer-reaching and hub-writing tool handlers for recorders
    while a run is in progress; restore them after. The model sees a normal
    result so the conversation continues as it would."""

    def __init__(self) -> None:
        self.calls: list[dict] = []
        self._saved: dict = {}

    def __enter__(self):
        from app.agent import tools as _t
        for name in SANDBOXED:
            if name in _t._HANDLERS:
                self._saved[name] = _t._HANDLERS[name]
                _t._HANDLERS[name] = self._make(name)
        return self

    def __exit__(self, *exc):
        from app.agent import tools as _t
        for name, fn in self._saved.items():
            _t._HANDLERS[name] = fn

    def _make(self, name: str):
        async def _stub(args: dict, ctx) -> dict:
            self.calls.append({"tool": name, "args": args, "contact": getattr(ctx, "wa_id", None)})
            if name == "create_order":
                return {"ok": True, "sandbox": True, "order_ref": "EVAL-0000",
                        "note": "eval sandbox — no order was created on the hub"}
            if name == "send_product_cards":
                return {"ok": True, "sandbox": True, "sent": 0,
                        "note": "eval sandbox — cards recorded, not sent"}
            return {"ok": True, "sandbox": True, "note": "eval sandbox — nothing sent"}
        return _stub


# ── language continuity ──────────────────────────────────────────────────────

_DEVANAGARI = re.compile(r"[ऀ-ॿ]")
_FR_RE = re.compile(r"\b(le|la|les|des|vous|nous|prix|merci|bonjour|pour|avec|est|sont|votre)\b", re.I)
_PT_RE = re.compile(r"\b(obrigad[oa]|preço|preços|você|para|com|bom dia|boa tarde|sim|não|temos|custa)\b", re.I)


def language_ok(expected: str | None, reply: str) -> bool | None:
    """True/False when the reply's language can be checked against the
    customer's; None when it cannot (sheng, mixed, unknown) — not counted."""
    if not expected or not (reply or "").strip():
        return None
    from app.agent.voice import looks_swahili
    r = reply
    if expected == "hi":
        return bool(_DEVANAGARI.search(r))
    if expected == "sw":
        return looks_swahili(r)
    if expected == "fr":
        return len(_FR_RE.findall(r)) >= 2
    if expected == "pt":
        return len(_PT_RE.findall(r)) >= 1
    if expected in ("en", "ke-en"):
        return not looks_swahili(r) and not _DEVANAGARI.search(r)
    return None


# ── one turn's verdict ───────────────────────────────────────────────────────

_PITCH_RE = re.compile(
    r"\b(shall i (start|reserve|place|go ahead)|would you like (me )?to (start|reserve|place)|"
    r"ready to (order|proceed)|go ahead with the order|nikuwekee|tuanze|tuendelee na oda)\b", re.I)
_DATE_ASK_RE = re.compile(
    r"\b(which day|what day|when (would|should|can) (we|i)|is there a day|when will you|when do you)\b", re.I)
_SELL_RE = re.compile(
    r"\b(shall i (start|place)|discount|special offer|would you like to (add|order)|today only)\b", re.I)
# the payment-acknowledgement and pressure readings are the GATE's own
# (app.agent.review), so the runner never disagrees with production
REPLY_EXPECTED = ("answer", "ask_one", "quote", "hold_ack", "care_first", "escalate", "confirm_paid_check")


def check_turn(case: dict, i: int, turn: dict, reply: str, facts: dict, *,
               opted_out: bool, intercept_mode: str | None, after_hold: bool) -> dict:
    """Objective verdict for one turn: {passed, failures[], observations{}}.
    A failure names the assertion; the observations are what a reader (or the
    dashboard) wants to see even when the turn passed."""
    from app.agent import review as rv
    from app.jobs.agent_eval import judge
    exp = turn.get("expect") or {}
    r = reply or ""
    tools = [str((e or {}).get("tool") or "") for e in (facts.get("tools") or [])]
    j = judge(r, turn["user"], facts.get("tools"))
    failures: list[str] = []
    nxt = exp.get("next")

    # An empty reply is only right where silence is the answer; everywhere
    # else it is a turn that raised, a held draft or a wrongful silence —
    # never a pass (verification pass 1, finding 6).
    if facts.get("error"):
        failures.append(f"turn raised: {facts['error']}")
    if nxt in REPLY_EXPECTED and not r.strip():
        failures.append("no reply where one was expected" + (" (door: %s)" % facts["door"] if facts.get("door") else ""))

    if nxt == "silence":
        if r.strip():
            failures.append("answered a closer (silence expected)")
    if nxt == "stop_ack":
        if not opted_out:
            failures.append("opt-out not recorded")
        if j["words"] > 25:
            failures.append(f"opt-out acknowledgement too long ({j['words']} words)")
        if "?" in r:
            failures.append("opt-out acknowledgement asks a question")
    if nxt == "hold_ack":
        if _PITCH_RE.search(r):
            failures.append("pitched after a request for time")
        if after_hold and _DATE_ASK_RE.search(r):
            failures.append("re-asked for a date the customer already gave")
    if nxt == "confirm_paid_check":
        if rv.paid_ack_without_source(r, facts.get("tools")):
            failures.append("thanked for a payment not seen")
    if nxt == "care_first":
        if _SELL_RE.search(r):
            failures.append("sold into a complaint")
    if nxt == "escalate":
        if intercept_mode != "human" and not any(t in ("handoff_to_human", "raise_complaint") for t in tools):
            failures.append("did not hand to a person")
    if nxt == "ask_one":
        if r.count("?") > 1:
            failures.append(f"asked {r.count('?')} questions, one expected")
    if nxt == "quote":
        if not j["figures"]:
            failures.append("no price given where a quote was expected")
    if exp.get("figures") == "hub-only" and j["unverified"]:
        failures.append("figure not from this turn's tools: " + ", ".join(str(f) for f in j["unverified"]))
    for rx in exp.get("forbid") or []:
        try:
            if re.search(rx, r, re.I):
                failures.append(f"forbidden text matched /{rx}/")
        except re.error:
            failures.append(f"bad forbid regex /{rx}/")
    for rx in exp.get("require") or []:
        try:
            if not re.search(rx, r, re.I):
                failures.append(f"required text missing /{rx}/")
        except re.error:
            failures.append(f"bad require regex /{rx}/")
    tool = canonical_tool(exp.get("tool") or "")
    if tool:
        if tool.startswith("!"):
            if tool[1:] in tools:
                failures.append(f"called {tool[1:]} (forbidden)")
        elif tool not in tools:
            failures.append(f"did not call {tool}")
    if rv.manufactured_pressure(r, facts.get("tools")):
        failures.append("manufactured urgency or scarcity")
    lang_ok = language_ok(exp.get("lang") or case.get("lang"), r)
    if lang_ok is False:
        failures.append(f"reply not in the customer's language ({exp.get('lang') or case.get('lang')})")

    return {
        "passed": not failures, "failures": failures,
        "observations": {
            "words": j["words"], "sentences": j["sentences"], "questions": j["questions"],
            "target_words": j["target"], "target_kind": j["kind"], "over_target": j["over"],
            "internal_talk": j["internal"], "figures": j["figures"], "unverified": j["unverified"],
            "tools": tools, "review": facts.get("review"), "language_ok": lang_ok,
            "silent": not r.strip(), "opted_out": opted_out, "intercept_mode": intercept_mode,
            "judge": exp.get("judge") or [],
        },
    }


# ── the run ──────────────────────────────────────────────────────────────────

def _git_sha() -> str:
    sha = os.environ.get("GIT_SHA") or ""
    if sha:
        return sha
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True,
                              timeout=5, cwd=os.path.dirname(__file__)).stdout.strip()
    except Exception:
        return ""


async def _prompt_revision(db, redis) -> dict:
    """Hashes of everything that shapes the prompt: prompt.py itself and the
    three dashboard-stored inputs. Two runs with equal hashes used the same
    instructions."""
    from app.agent import prompt as _p
    from app.services import app_settings as _s
    out = {}
    try:
        with open(_p.__file__, "rb") as f:
            out["prompt_py"] = hashlib.sha256(f.read()).hexdigest()[:12]
    except Exception:
        out["prompt_py"] = ""
    for name, fn in (("directives", _s.get_directives), ("learned_rules", _s.get_learned_rules),
                     ("house_voice", _s.get_house_voice)):
        try:
            v = await fn(db, redis)
            out[name] = hashlib.sha256((v or "").encode()).hexdigest()[:12]
            out[name + "_chars"] = len(v or "")
        except Exception:
            out[name] = ""
    return out


def _case_set_hash(cases: list[dict]) -> str:
    h = hashlib.sha256()
    for c in cases:
        h.update(json.dumps({k: v for k, v in c.items() if k != "_file"}, sort_keys=True,
                            ensure_ascii=False).encode())
    return h.hexdigest()[:12]


def summarise(results: list[dict], *, repeat: int) -> dict:
    """Proportions with Wilson intervals, overall and by dimension-relevant
    slices; pass^k per case over the repeats."""
    from app.jobs.eval_floors import wilson
    turns = [t for c in results for t in c["turns"]]
    def prop(items, pred):
        n = len(items)
        k = sum(1 for x in items if pred(x))
        p, lo, hi = wilson(k, n)
        return {"k": k, "n": n, "p": round(p, 3), "ci95": [round(lo, 3), round(hi, 3)]}
    out = {
        "turns": prop(turns, lambda t: t["verdict"]["passed"]),
        "critical_turns": prop([t for t in turns if t["critical"]], lambda t: t["verdict"]["passed"]),
        "next_action": {},
        "language_continuity": prop([t for t in turns if t["verdict"]["observations"]["language_ok"] is not None],
                                    lambda t: t["verdict"]["observations"]["language_ok"]),
        "figures_verified": prop([t for t in turns if t["verdict"]["observations"]["figures"]],
                                 lambda t: not t["verdict"]["observations"]["unverified"]),
        "within_length_target": prop([t for t in turns if not t["verdict"]["observations"]["silent"]],
                                     lambda t: not t["verdict"]["observations"]["over_target"]),
        "internal_talk_free": prop([t for t in turns if not t["verdict"]["observations"]["silent"]],
                                   lambda t: not t["verdict"]["observations"]["internal_talk"]),
        "first_draft_passed": prop([t for t in turns if t["verdict"]["observations"]["review"] is not None],
                                   lambda t: t["verdict"]["observations"]["review"] == "pass"),
        "by_category": {}, "by_lang": {}, "failure_kinds": {},
    }
    for nxt in eval_cases.NEXT_ACTIONS:
        sub = [t for t in turns if t["next"] == nxt]
        if sub:
            out["next_action"][nxt] = prop(sub, lambda t: t["verdict"]["passed"])
    cats = sorted({c for t in turns for c in t["categories"]})
    for cat in cats:
        out["by_category"][cat] = prop([t for t in turns if cat in t["categories"]],
                                       lambda t: t["verdict"]["passed"])
    for lang in sorted({t["lang"] for t in turns}):
        out["by_lang"][lang] = prop([t for t in turns if t["lang"] == lang], lambda t: t["verdict"]["passed"])
    for t in turns:
        for f in t["verdict"]["failures"]:
            kind = f.split(" (")[0].split(":")[0].split(" /")[0]
            out["failure_kinds"][kind] = out["failure_kinds"].get(kind, 0) + 1
    if repeat > 1:
        by_case: dict[str, list[bool]] = {}
        for c in results:
            by_case.setdefault(c["id"], []).append(all(t["verdict"]["passed"] for t in c["turns"]))
        allk = [all(v) for v in by_case.values() if len(v) == repeat]
        out[f"pass^{repeat}"] = prop(allk, lambda x: x)
        out["pass^1"] = prop([v for vs in by_case.values() for v in vs], lambda x: x)
    return out


def select_cases(selection: str = "all", *, only: str | None = None, limit: int | None = None,
                 file: str | None = None) -> list[dict]:
    """The cases one run covers. `file` names one case file and ignores the
    split — the way the blind set is run (verification pass 2: the runner
    had lost every way to reach it once the loader left blind cases out of
    the sweep); `--held-out`/`--dev` mean nothing with it."""
    if file:
        chosen = eval_cases.load(file, include_blind=True)
    else:
        cases = eval_cases.load()
        dev, held = eval_cases.split(cases)
        chosen = held if selection == "held-out" else dev if selection == "dev" else cases
    if only:
        chosen = [c for c in chosen if c["id"].startswith(only)]
    if limit:
        chosen = chosen[:limit]
    return chosen


async def run_cases(*, selection: str = "all", repeat: int = 1, only: str | None = None,
                    out_path: str | None = None, packet_path: str | None = None,
                    history: bool = False, keep: bool = False, limit: int | None = None,
                    file: str | None = None) -> dict | None:
    import logging
    logging.basicConfig(level=logging.WARNING, format="    %(name)s: %(message)s")
    if not settings.anthropic_api_key:
        print("ANTHROPIC_API_KEY is not set — run this on the box or in the agent-eval workflow.")
        return None
    import redis.asyncio as aioredis
    from sqlalchemy import select
    from app.agent.runtime import run_turn, build_llm, closer_gate
    from app.database import AsyncSessionLocal
    from app.models.conversation import Conversation
    from app.models.message import Message, MsgDirection, MsgSender
    from app.services import intent as _intent
    from app.services.messaging import provision_user
    from app.jobs.agent_eval import _cleanup_contacts

    chosen = select_cases(selection, only=only, limit=limit, file=file)
    if file:
        selection = f"file:{file}"
    if not chosen:
        print("no cases selected — check --file / --only")
        raise SystemExit(2)                 # never a green exit on an empty run

    try:
        redis = aioredis.from_url(settings.redis_url, decode_responses=True,
                                  socket_connect_timeout=5, socket_timeout=5)
        await redis.ping()
    except Exception:
        redis = None

    contacts = {c["id"]: contact_for(c, n) for n, c in enumerate(chosen, 1)}
    await _cleanup_contacts(redis, list(contacts.values()))

    async with AsyncSessionLocal() as db:
        revision = await _prompt_revision(db, redis)
    record = {
        "started": datetime.now(timezone.utc).isoformat(), "selection": selection, "file": file, "repeat": repeat,
        "git_sha": _git_sha(), "case_set": _case_set_hash(chosen), "cases": len(chosen),
        "models": {"producer": settings.tier2_model, "light": settings.tier2_model_light,
                   "reviewer": settings.review_model_main, "reviewer_light": settings.review_model_light},
        "prompt_revision": revision, "results": [],
    }
    print(f"case set {record['case_set']} · {len(chosen)} cases × {repeat} · producer {settings.tier2_model} · "
          f"git {record['git_sha'][:7]} · prompt {revision.get('prompt_py')}")

    with _Sandbox() as box:
        for rep in range(repeat):
            for case in chosen:
                wa_id = contacts[case["id"]]
                if repeat > 1:
                    await _cleanup_contacts(redis, [wa_id])       # each repeat starts clean
                async with AsyncSessionLocal() as db:
                    await provision_user(db, wa_id)
                    await db.commit()
                case_res = {"id": case["id"], "repeat": rep + 1, "contact": "…" + wa_id[-4:],
                            "source": case["source"], "turns": []}
                after_hold = False
                for i, turn in enumerate(case["turns"]):
                    text = turn["user"]
                    exp = turn.get("expect") or {}
                    t0 = time.monotonic()
                    reply, facts, opted = "", {}, False
                    async with AsyncSessionLocal() as db:
                        db.add(Message(wa_id=wa_id, channel="whatsapp", direction=MsgDirection.inbound,
                                       sender=MsgSender.user, text=text))
                        await db.commit()
                    # the live door, minus the send
                    if _intent.is_opt_out(text):
                        async with AsyncSessionLocal() as db:
                            conv = (await db.execute(select(Conversation).where(
                                Conversation.wa_id == wa_id))).scalars().first()
                            if conv is not None:
                                await _intent.record_opt_out(db, redis, conv, text, channel="whatsapp", key=wa_id)
                                await db.commit()
                        reply = _intent.acknowledgement(text)
                        facts = {"tools": [], "review": None, "door": "opt_out"}
                    elif await closer_gate(redis, "whatsapp", wa_id, text):
                        reply, facts = "", {"tools": [], "review": None, "door": "closer"}
                    else:
                        async with AsyncSessionLocal() as db:
                            try:
                                reply = await run_turn(db, redis, wa_id, text, build_llm(purpose="job:eval"),
                                                       turn_facts=facts)
                            except Exception as exc:
                                reply = ""
                                facts = {**facts, "error": str(exc)[:200]}
                    latency = round(time.monotonic() - t0, 2)
                    async with AsyncSessionLocal() as db:
                        conv = (await db.execute(select(Conversation).where(
                            Conversation.wa_id == wa_id))).scalars().first()
                        opted = await _intent.opted_out(db, redis, conv) if conv is not None else False
                        mode = getattr(conv.intercept_mode, "value", conv.intercept_mode) if conv is not None else None
                        if reply:
                            db.add(Message(wa_id=wa_id, channel="whatsapp", direction=MsgDirection.outbound,
                                           sender=MsgSender.ai, text=reply))
                            await db.commit()
                    try:
                        from app.services.deals import scribe_update
                        async with AsyncSessionLocal() as db:
                            await scribe_update(db, wa_id, "whatsapp", reply or "", inbound_text=text,
                                                tools=facts.get("tools"))
                    except Exception:
                        pass
                    verdict = check_turn(case, i, turn, reply, facts, opted_out=bool(opted),
                                         intercept_mode=mode, after_hold=after_hold)
                    from app.services.customer_state import floor as _floor
                    if (_floor(text) or {}).get("customer_said") in ("needs_time", "comparing", "consulting"):
                        after_hold = True
                    case_res["turns"].append({
                        "i": i, "user": text, "reply": reply, "next": exp.get("next"),
                        "critical": bool(case.get("critical")), "categories": case["categories"],
                        "lang": exp.get("lang") or case.get("lang") or "en",
                        "latency_s": latency, "error": facts.get("error"), "door": facts.get("door"),
                        "verdict": verdict,
                    })
                    mark = "ok " if verdict["passed"] else "FAIL"
                    print(f"[{mark}] {case['id']} t{i} ({exp.get('next')}) {verdict['observations']['words']}w "
                          f"{latency}s" + ("  — " + "; ".join(verdict["failures"]) if verdict["failures"] else ""))
                record["results"].append(case_res)
        record["sandboxed_calls"] = box.calls

    record["finished"] = datetime.now(timezone.utc).isoformat()
    record["summary"] = summarise(record["results"], repeat=repeat)
    s = record["summary"]
    print(f"\nSUMMARY  turns {s['turns']['k']}/{s['turns']['n']} = {s['turns']['p']} {s['turns']['ci95']} · "
          f"critical {s['critical_turns']['k']}/{s['critical_turns']['n']} · "
          f"language {s['language_continuity']['p']} · figures {s['figures_verified']['p']} · "
          f"length {s['within_length_target']['p']} · first-draft {s['first_draft_passed']['p']}")
    if s.get("failure_kinds"):
        print("failure kinds:", json.dumps(s["failure_kinds"], ensure_ascii=False))

    if out_path:
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(record, f, ensure_ascii=False, indent=1)
        print(f"written {out_path}")
    if packet_path:
        write_packet(record, packet_path)
        print(f"rater packet {packet_path}")
    if history:
        await append_history(record)
        print("run appended to the evaluation history (app_settings: eval_history)")
    if not keep:
        await _cleanup_contacts(redis, list(contacts.values()))
    if redis is not None:
        try:
            await redis.aclose()
        except Exception:
            pass
    return record


def write_packet(record: dict, path: str) -> None:
    """The turns a human rater scores, with the rubric, blind to the system
    that produced them. One block per judged turn; the rater fills the score."""
    lines = ["# Rater packet", "",
             f"Run {record['started']} · case set {record['case_set']} · {record['cases']} cases", "",
             "Score each marked reply 1–5 on the named dimension. 5 = what an exceptional,",
             "experienced consultant would have written; 3 = acceptable; 1 = harmful or wrong.",
             "Judge only the reply shown, in the context shown. Do not score tone you merely",
             "dislike; score accuracy of social judgment, respect and practical help.", ""]
    n = 0
    for c in record["results"]:
        hist = []
        for t in c["turns"]:
            hist.append(f"CUSTOMER: {t['user']}")
            dims = t["verdict"]["observations"].get("judge") or []
            if dims:
                n += 1
                lines += [f"## Item {n} — {c['id']} turn {t['i']} — dimensions: {', '.join(dims)}", "",
                          *hist, f"NEEMA: {t['reply'] or '<silence>'}", "",
                          *[f"- {d}: ___ /5   notes: ______" for d in dims], ""]
            hist.append(f"NEEMA: {t['reply'] or '<silence>'}")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


async def append_history(record: dict, *, keep: int = 60) -> None:
    """A compact row per run in the existing app_settings table (key
    eval_history) — the dashboard's evaluation history. No new table."""
    from app.database import AsyncSessionLocal
    from app.services.app_settings import get_value, set_value
    s = record["summary"]
    row = {"at": record["finished"], "git": record["git_sha"][:7], "case_set": record["case_set"],
           "selection": record["selection"], "cases": record["cases"], "repeat": record["repeat"],
           "producer": record["models"]["producer"], "prompt": record["prompt_revision"].get("prompt_py"),
           "turns": s["turns"], "critical": s["critical_turns"], "language": s["language_continuity"],
           "figures": s["figures_verified"], "length": s["within_length_target"],
           "first_draft": s["first_draft_passed"], "next_action": s["next_action"]}
    async with AsyncSessionLocal() as db:
        try:
            raw = await get_value(db, "eval_history")
            hist = json.loads(raw) if raw else []
        except Exception:
            hist = []
        hist = (hist + [row])[-keep:]
        await set_value(db, "eval_history", json.dumps(hist, ensure_ascii=False))
        await db.commit()
