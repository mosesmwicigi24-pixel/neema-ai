"""THE POLICY LAYER — company rules that do not depend on the model obeying
(owner's directive, 2026-11-20: "No important company policy should depend
solely on Neema remembering or voluntarily obeying an instruction").

The audit (docs/intelligence/enforcement) found 830 rules, 62 of them hard
enforced, and that the reply gate runs only on live answers: everything Neema
starts herself, and "team answer through Neema", met two rules or none.

This module is ONE place the commercial rules are defined, with permanent
ids, and ONE function every outbound route calls:

    findings = policy.evaluate(text, route=..., tool_log=..., said=..., ...)
    outcome  = await policy.record(redis, findings, route=..., channel=..., key=...)

What it decides from is the RECORD, not the wording alone: a discount is
allowed when the offer was granted in this turn (the tool log) or a colleague
stated it; an order is "placed" when create_order succeeded; a number is ours
when it is in the configured official lines or the customer's own messages.
Wording finds the claim; the record decides whether it is true.

MODES (settings.policy_mode):
  shadow   — every decision is recorded; no message is changed. The default,
             so false alarms are seen before anything is held.
  enforce  — a finding whose policy is listed in settings.policy_enforce (or
             every critical finding when that list is "*") holds the message:
             the route's existing hold path is used, nothing is rewritten here.

Nothing here is shown to a customer.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone

from app.core.config import settings

_log = logging.getLogger("neema.policy")

RULES_VERSION = "2026-11-20.1"

# route names (docs/intelligence/enforcement/D_COVERAGE_MATRIX.md)
LIVE, INITIATED, HUB_EVENT, TEAM_ANSWER, ORDER_TOOL = (
    "live_turn", "initiated", "hub_event", "team_answer", "create_order")

# id → (title, severity, the decision of 2026-11-20 it implements)
POLICIES: dict[str, tuple[str, str, str]] = {
    "FIN-02": ("A discount exists only as a recorded offer", "critical", "D1"),
    "FIN-03": ("Refunds, remakes and replacements are never promised or refused by Neema", "critical", "D2"),
    "FIN-04": ("Payment is completed before delivery", "critical", "D3"),
    "FIN-05": ("Only our official numbers are given", "critical", ""),
    "ORD-01": ("An order is created only on the customer's yes", "critical", "D4"),
    "ORD-02": ("An order is 'placed' only when the order step succeeded", "critical", ""),
    "FUL-01": ("No delivery date or production time without a source", "high", "D6"),
    "FUL-02": ("Repairs: our items, 14 days, never 'for life'", "high", "D5"),
    "ACT-01": ("A promise to ask the team needs the team to have been asked", "high", "D7"),
    "ACT-03": ("A check-in needs a time the customer named", "high", "D8"),
    "FIN-01": ("Every figure has a source", "critical", ""),
    "PRD-02": ("A near-match row's price is not the item's price", "critical", ""),
    # the existing reply gate's outcomes, recorded here so one report shows all
    "GATE": ("The reply gate's own verdict (agent/review.py)", "medium", ""),
    # route guards (bypass and duplicate-send findings of the audit)
    "RTE-01": ("A customer who said stop is not messaged", "critical", ""),
    "RTE-02": ("One instruction sends one message", "high", ""),
}


def guards_active() -> bool:
    return bool(getattr(settings, "policy_guards_active", False))


def finding(pid: str, reason: str, excerpt: str = "") -> dict:
    return {"policy": pid, "severity": POLICIES[pid][1], "reason": reason, "excerpt": excerpt}

_NEG = r"(?:\bno\b|\bnot\b|n't|\bnever\b|\bcannot\b|\bwithout\b|\bhakuna\b|\bsi\b|\bhatu\w*)"


def _negated(text: str, start: int, span: int = 36) -> bool:
    """Is the claim at `start` denied in the words just before it?"""
    before = re.sub(r"\bno (?:problem|worries|trouble|doubt)\b", " ", text[max(0, start - span - 12):start],
                    flags=re.IGNORECASE)
    return bool(re.search(_NEG + r"[^.?!\n]{0,%d}$" % span, before, re.IGNORECASE))


def _excerpt(text: str, m: re.Match) -> str:
    a, b = max(0, m.start() - 20), min(len(text), m.end() + 20)
    return " ".join(text[a:b].split())[:90]


# ── FIN-03 refunds, remakes, replacements ────────────────────────────────────
_REFUND_PROMISE_RE = re.compile(
    r"\b(?:we(?:'ll| will| shall| can| are going to)|i(?:'ll| will| can| shall)|you(?:'ll| will)|"
    r"tuta\w*|nita\w*|uta\w*)\b[^.?!\n]{0,60}?"
    r"\b(refund\w*|reimburs\w*|money back|your money|replac\w+|re-?mak\w+|re-?ship\w*|re-?send\w*|"
    r"another one|a new one|rudish\w*|pesa zako)\b"
    r"|\b(?:your )?refund (?:is|has been|was|will be) (?:approved|processed|sent|issued|on its way|done)\b"
    r"|\b(?:full|partial) refund\b[^.?!\n]{0,30}\b(?:for you|to you|today|tomorrow|shortly)\b",
    re.IGNORECASE)
_REFUND_REFUSAL_RE = re.compile(
    r"\b(?:we (?:do not|don't|cannot|can't|never)|there (?:is|are) no|no)\s+(?:give |offer |do |issue )?refunds?\b"
    r"|\bnot (?:eligible|entitled) (?:for|to) a refund\b|\bnon-?refundable\b",
    re.IGNORECASE)
# the one thing Neema may say: it is with the person who decides
_REFUND_HANDOFF_RE = re.compile(
    r"\b(?:colleague|team|manager|person|mwenzangu)\b[^.?!\n]{0,60}\b(?:decid\w+|review\w*|confirm\w*|"
    r"look\w* (?:into|at)|handl\w+|come back|follow up|ataamua|atakujibu)", re.IGNORECASE)

# ── FIN-02 a discount in words ───────────────────────────────────────────────
_DISCOUNT_RE = re.compile(
    r"\b\d{1,2}(?:\.\d)?\s?%\s*(?:off|discount|less|punguzo)\b"
    r"|\b(?:discount|punguzo)\s+(?:of|ya)\s+\d"
    r"|\b(?:i|we)(?:'ll| will| can| could)\s+(?:give|offer|do|apply|take|knock|reduce|lower|bring)\b[^.?!\n]{0,40}"
    r"\b(?:discount|off|down|reduc\w+|lower|less|special price|better price|punguzo)\b"
    r"|\b(?:i|we)(?:'ll| will| can| could)\s+(?:reduce|lower|knock|drop)\s+(?:it|the price|that)\b"
    r"|\b(?:special|reduced|discounted) price\b|\b(?:better|lower) price for you\b"
    r"|\bjust for you\b[^.?!\n]{0,30}\b(?:\$|kes|ksh|usd|zmw|zar|gbp)",
    re.IGNORECASE)

# ── FIN-04 pay on delivery ───────────────────────────────────────────────────
_POD_RE = re.compile(
    r"\b(?:pay(?:ment)?|cash|paid|lipa|malipo)\b[^.?!\n]{0,24}\b(?:on|upon|at|after)\s+(?:delivery|arrival|receipt|receiving)\b"
    r"|\bpay (?:when|once|after) (?:it|you|the \w+)\s+(?:arrives?|receive|get|is delivered)"
    r"|\b(?:COD|cash on delivery|pay on delivery)\b"
    r"|\blipa (?:baada ya|ukipokea|ukifika)", re.IGNORECASE)
# Paying at the shop on collection: allowed only once the owner approves it
# (settings.policy_pay_at_collection).
_PAY_AT_COLLECTION_RE = re.compile(
    r"\bpay(?:ment)?\b[^.?!\n]{0,30}\b(?:when|once|as) you (?:collect|pick)|"
    r"\bpay(?:ment)?\b[^.?!\n]{0,20}\b(?:at|on|upon) (?:collection|pick-?up)\b|"
    r"\bpay (?:at|in) (?:the|our) shop\b|\blipa dukani\b", re.IGNORECASE)
_COLLECT_RE = re.compile(r"\b(?:collect\w*|pick\w* ?up|at (?:the|our) shop|in (?:the|our) shop|dukani)\b", re.IGNORECASE)

# ── FIN-05 numbers ───────────────────────────────────────────────────────────
_PHONE_RE = re.compile(r"(?<![\w.,$])(\+?\d[\d \-().]{7,17}\d)(?![\w%])")
_MONEY_BEFORE_RE = re.compile(r"(?:\$|kes|ksh|usd|zmw|zar|gbp|eur|ugx|tzs|k)\s*$", re.IGNORECASE)


def _last9(digits: str) -> str:
    return digits[-9:]


def official_numbers() -> set[str]:
    """Our own lines, as configured — last nine digits (a Kenyan line is the
    same line written +254…, 254… or 0…)."""
    out = set()
    for name in ("whatsapp_handoff_number", "whatsapp_handoff_alt",
                 "official_mpesa_numbers", "official_airtel_numbers"):
        for part in str(getattr(settings, name, "") or "").split(","):
            d = re.sub(r"\D", "", part)
            if len(d) >= 9:
                out.add(_last9(d))
    return out


def phone_numbers(text: str) -> list[str]:
    """Phone-like numbers in a text: 10–13 digits written as one number, not
    preceded by a currency (a price is not a phone)."""
    found = []
    for m in _PHONE_RE.finditer(text or ""):
        raw = m.group(1)
        d = re.sub(r"\D", "", raw)
        if not 10 <= len(d) <= 13:
            continue
        if _MONEY_BEFORE_RE.search(text[max(0, m.start() - 6):m.start()]):
            continue
        if not (raw.strip().startswith("+") or d.startswith(("0", "254", "255", "256", "260", "27", "234", "1", "44"))):
            continue
        found.append(d)
    return found


# ── ORD-02 "your order is placed" ────────────────────────────────────────────
_ORDER_PLACED_RE = re.compile(
    r"\b(?:your|the) order (?:is|has been|was|is now) (?:placed|created|confirmed|booked|through|in the system)\b"
    r"|\b(?:i|we)(?:'ve| have)? (?:placed|created|booked|put through) (?:your|the) order\b"
    r"|\border (?:number|no\.?|#)\s*(?:is\s*)?#?[A-Z-]{0,6}\d[A-Z0-9-]{2,}"
    r"|\boda yako imewekwa\b", re.IGNORECASE)

# ── FUL-02 repairs ───────────────────────────────────────────────────────────
_FOR_LIFE_RE = re.compile(
    r"\b(?:repair\w*|alter\w*|maintain\w*|mend\w*|fix\w*|guarantee\w*|warrant\w*)\b[^.?!\n]{0,40}\b(?:for life|lifetime|forever|any ?time|always)\b"
    r"|\b(?:lifetime|life-long)\s+(?:repair\w*|alteration\w*|guarantee|warranty)\b", re.IGNORECASE)

# ── FUL-01 dates and durations ───────────────────────────────────────────────
_WHEN = (r"(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday|tomorrow|today|tonight|kesho|leo|"
         r"\d{1,2}\s*(?:-|–|to)\s*\d{1,2}\s+(?:working |business )?(?:days?|weeks?|siku|wiki)|"
         r"(?:a|one|two|three|four|five|six|seven|ten|\d{1,2})\s+(?:working |business )?(?:days?|weeks?|hours?|siku|wiki)|"
         r"next week|this week|end of (?:the )?week|(?:the )?\d{1,2}(?:st|nd|rd|th))")
_DATE_PROMISE_RE = re.compile(
    r"\b(?:deliver\w*|arriv\w*|ready|dispatch\w*|ship\w*|reach you|get to you|complete\w*|finish\w*|"
    r"takes?|will take|itafika|itakuwa tayari)\b[^.?!\n]{0,40}?\b(?:by|on|in|within|about|around|ndani ya)?\s*(" + _WHEN + r")\b",
    re.IGNORECASE)

_DURATION_RE = re.compile(r"\d{1,2}\s*(?:-|–|to)\s*\d{1,2}\s+(?:working |business )?(?:days?|weeks?)", re.IGNORECASE)
_KNOWN_TIMES: list[str] | None = None


def stated_times() -> list[str]:
    """The durations Neema's own instructions state as company fact (DHL
    transit and the like). A reply repeating one of these has its source."""
    global _KNOWN_TIMES
    if _KNOWN_TIMES is None:
        try:
            import inspect
            from app.agent import prompt as _prompt
            _KNOWN_TIMES = sorted({" ".join(m.group(0).lower().replace("–", "-").split())
                                   for m in _DURATION_RE.finditer(inspect.getsource(_prompt))})
        except Exception:
            _KNOWN_TIMES = []
    return _KNOWN_TIMES


# ── ACT-01 "let me confirm with the team" ────────────────────────────────────
_WILL_ASK_RE = re.compile(
    r"\b(?:let me|i(?:'ll| will| am going to)|i'm going to|nita\w*)\s+(?:just\s+)?(?:confirm|check|ask|verify|find out|uliza|thibitisha)\b"
    r"[^.?!\n]{0,40}\b(?:with|from)?\s*(?:the |my |our )?(?:team|colleague\w*|workshop|tailor\w*|manager|timu|mwenzangu)\b"
    r"|\ba colleague (?:will|is going to) (?:confirm|check|get back|come back|reach out|follow up)\b"
    r"|\bi have (?:raised|passed|flagged) (?:it|this)\b", re.IGNORECASE)
_ASKED_TOOLS = ("check_availability", "handoff_to_human", "raise_complaint", "update_cart", "schedule_check_in")

# ── ORD-01 the customer's yes ────────────────────────────────────────────────
_YES_RE = re.compile(
    r"\b(?:yes|yeah|yep|ok(?:ay)?|sure|go ahead|proceed|please do|do it|confirm(?:ed)?|place (?:it|the order)|"
    r"i(?:'ll| will) take (?:it|them|that)|i want (?:it|them|to order|to buy)|send (?:me )?the (?:link|bill|invoice)|"
    r"how (?:do|can) i pay|let(?:'s| us) (?:do it|go|proceed)|book it|order it|"
    r"ndio|ndiyo|sawa|endelea|nataka|nitumie|tuma (?:link|bili)|nalipaje|haya|oui|d'accord|sim)\b",
    re.IGNORECASE)


_NAMED_TIME_RE = re.compile(
    r"\b(?:" + _WHEN + r"|next (?:month|year|sunday|monday|tuesday|wednesday|thursday|friday|saturday)|"
    r"(?:in|after|within) (?:a|an|one|two|three|\d{1,2}) (?:day|week|month|hour)s?|"
    r"(?:end|start|beginning|middle) of (?:the |this |next )?(?:week|month|year)|"
    r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\w*|"
    r"later (?:today|this week|this month)|in the (?:morning|afternoon|evening)|"
    r"(?:after|before) (?:the )?(?:service|sunday|christmas|easter|payday|salary)|"
    r"wiki ijayo|mwezi ujao|jioni|asubuhi|baadaye leo)\b", re.IGNORECASE)


def customer_named_a_time(said: list[str] | tuple[str, ...] | None) -> bool:
    """Did the customer say WHEN to come back to them? Read from their words."""
    return any(_NAMED_TIME_RE.search(s) for s in (said or ()) if s)


def unsourced_figures(text: str, sources: list[str]) -> list[float]:
    """Money figures in `text` that appear in none of `sources` (the brief a
    message was composed from, the conversation, a colleague's facts)."""
    from app.agent.review import money_figures
    have: set[float] = set()
    for s in sources:
        try:
            have.update(money_figures(str(s or "")))
            # a bare number in a brief or a hub event is a source too
            have.update(float(n.replace(",", "")) for n in re.findall(r"(?<![\w.])\d[\d,]*(?:\.\d+)?", str(s or ""))
                        if n.replace(",", "").replace(".", "").isdigit())
        except Exception:
            pass
    return [f for f in money_figures(text or "") if not any(abs(f - h) < 0.51 for h in have)]


def partial_only_figures(text: str, seen: list, partial_ids, currency: str = "USD") -> list[float]:
    """Figures in `text` that belong ONLY to rows that matched some of the
    customer's words (audit C11): the price of a near-match, quoted."""
    from app.agent.review import _row_figures, money_figures
    part, full = set(), set()
    for p in seen or ():
        try:
            (part if p.get("id") in (partial_ids or ()) else full).update(_row_figures(p, currency))
        except Exception:
            pass
    only = {f for f in part if not any(abs(f - g) < 0.51 for g in full)}
    return [f for f in money_figures(text or "") if any(abs(f - o) < 0.51 for o in only)]


def customer_agreed(said: list[str] | tuple[str, ...] | None, last: int = 3) -> bool:
    """Do the customer's (or a colleague's) recent words carry a yes? Read
    from the record — `said` newest first, as tools._said_in_record gives it."""
    recent = [s for s in (said or ()) if s][:last]
    return any(_YES_RE.search(s) for s in recent)


def _tool_ok(tool_log: list | None, name: str) -> bool:
    for e in tool_log or ():
        if isinstance(e, dict) and e.get("tool") == name:
            out = e.get("out")
            if isinstance(out, dict) and not out.get("error") and out.get("ok") is not False:
                return True
    return False


def _tool_ran(tool_log: list | None, names) -> bool:
    return any(isinstance(e, dict) and e.get("tool") in names for e in tool_log or ())


def _in(haystacks, needle: str) -> bool:
    n = " ".join(needle.lower().split())
    return any(n in " ".join(str(h).lower().split()) for h in haystacks if h)


def evaluate(text: str | None, *, route: str, tool_log: list | None = None,
             said: list[str] | None = None, source_text: str = "",
             status_known: bool = False) -> list[dict]:
    """The policy findings in one outbound text. `said` = the customer's and
    colleagues' recent words (they may state a number, a date, a discount);
    `source_text` = anything authoritative this route was composed FROM (a
    colleague's facts, a hub event, tool results as text). Each finding:
    {"policy", "severity", "reason", "excerpt"}."""
    t = text or ""
    out: list[dict] = []
    if not t.strip():
        return out
    sources = list(said or ()) + [source_text or ""]
    try:
        sources.append(json.dumps([e.get("out") for e in (tool_log or ()) if isinstance(e, dict)],
                                  default=str, ensure_ascii=False))
    except Exception:
        pass

    def add(pid: str, reason: str, m: re.Match | None = None, excerpt: str = "") -> None:
        if any(f["policy"] == pid for f in out):
            return
        out.append({"policy": pid, "severity": POLICIES[pid][1], "reason": reason,
                    "excerpt": excerpt or (_excerpt(t, m) if m else "")})

    # FIN-03 — a promise is a finding unless a colleague stated it in the source
    m = _REFUND_PROMISE_RE.search(t)
    if m and not _negated(t, m.start()) and not _REFUND_HANDOFF_RE.search(t[max(0, m.start() - 80):m.end() + 80]) \
            and not re.search(r"\b(?:refund|replace|remake|reship|rudish)", source_text or "", re.IGNORECASE):
        add("FIN-03", "promises a refund, remake or replacement that no colleague has decided", m)
    m = _REFUND_REFUSAL_RE.search(t)
    if m and not re.search(r"refund", source_text or "", re.IGNORECASE):
        add("FIN-03", "refuses a refund — that is a colleague's decision too", m)

    # FIN-02 — allowed when the offer was granted this turn, or a colleague/the source states it
    m = _DISCOUNT_RE.search(t)
    if m and not _negated(t, m.start()) and not _tool_ok(tool_log, "apply_offer") \
            and not re.search(r"\b(?:discount|offer|% ?off|punguzo|reduc)", source_text or "", re.IGNORECASE):
        add("FIN-02", "states a discount with no recorded offer", m)

    # FIN-04 — never, except payment at collection in the shop (D3)
    m = _POD_RE.search(t)
    if m and not _negated(t, m.start()) and not (
            getattr(settings, "policy_pay_at_collection", False) and _COLLECT_RE.search(t)):
        add("FIN-04", "agrees to payment on delivery", m)
    # payment at collection is its own claim, and needs an approved policy
    if not getattr(settings, "policy_pay_at_collection", False):
        m = _PAY_AT_COLLECTION_RE.search(t)
        if m and not _negated(t, m.start()):
            add("FIN-04", "offers payment at collection, which has no approved policy", m)

    # FIN-05 — every phone-like number is ours, or one the record already holds
    ours = official_numbers()
    known = {_last9(d) for s in sources for d in phone_numbers(str(s))}
    for d in phone_numbers(t):
        if _last9(d) not in ours and _last9(d) not in known:
            add("FIN-05", "gives a phone number that is not one of our official lines",
                excerpt="…" + d[-4:])
            break

    # ORD-02 — "placed" needs the order step to have succeeded (or a known status)
    m = _ORDER_PLACED_RE.search(t)
    if m and re.match(r"\s*(?:the moment|once|when|as soon as|after|if)\b", t[m.end():], re.IGNORECASE):
        m = None                      # "is placed once you confirm" is a condition, not a claim
    if m and not status_known and not _negated(t, m.start()) and not _tool_ok(tool_log, "create_order") \
            and not _tool_ran(tool_log, ("check_order_status",)):
        add("ORD-02", "says an order is placed with no successful order step in this turn", m)

    # FUL-02
    m = _FOR_LIFE_RE.search(t)
    if m and not _negated(t, m.start()):
        add("FUL-02", "describes repairs or a guarantee as for life", m)

    # FUL-01 — the day or duration must be in the record (a tool, the customer, a colleague)
    for m in _DATE_PROMISE_RE.finditer(t):
        when = m.group(1)
        if _negated(t, m.start()) or _in(sources, when) \
                or " ".join(when.lower().replace("–", "-").split()) in stated_times():
            continue
        add("FUL-01", f"gives a time ({when}) that no tool, colleague or customer stated", m)
        break

    # FIN-01 — on the routes Neema composes from a brief (she starts the
    # message, or re-words a colleague's facts) every figure has a source
    if route in (INITIATED, HUB_EVENT, TEAM_ANSWER):
        try:
            loose = unsourced_figures(t, sources)
            if loose:
                add("FIN-01", "states a figure that is in neither the brief nor the conversation",
                    excerpt=", ".join(f"{x:g}" for x in loose[:3]))
        except Exception:
            pass

    # ACT-01 — the team must actually have been asked
    if route == LIVE:
        m = _WILL_ASK_RE.search(t)
        if m and not _tool_ran(tool_log, _ASKED_TOOLS):
            add("ACT-01", "promises to ask the team, but no step that tells the team ran", m)
    return out


def mode() -> str:
    return "enforce" if str(getattr(settings, "policy_mode", "shadow")).strip().lower() == "enforce" else "shadow"


def enforced(findings: list[dict]) -> list[dict]:
    """The findings that hold a message under the current settings."""
    if mode() != "enforce":
        return []
    listed = {p.strip().upper() for p in str(getattr(settings, "policy_enforce", "") or "").split(",") if p.strip()}
    if "*" in listed:
        return [f for f in findings if f["severity"] == "critical"]
    return [f for f in findings if f["policy"] in listed]


TALLY_KEY = "policy:tally:{day}"
RECENT_KEY = "policy:recent"
RECENT_MAX = 300


async def record(redis, findings: list[dict], *, route: str, channel: str = "", key: str = "",
                 outcome: str | None = None, ref: str = "") -> str:
    """Log every decision: policy id, rule version, route, outcome, reason.
    Outcome: 'prevented' (held), 'corrected', 'escalated', 'allowed'
    (explicit exception) or 'detected' (shadow: seen, not prevented).
    Returns the outcome recorded. Never raises."""
    if not findings:
        return "clear"
    held = [] if outcome else enforced(findings)
    result = outcome or ("prevented" if held else "detected")
    tail = str(key or "")[-4:]
    for f in findings:
        _log.info("policy %s v%s route=%s channel=%s to=…%s outcome=%s — %s",
                  f["policy"], RULES_VERSION, route, channel, tail, result, f["reason"])
    if redis is None:
        return result
    try:
        now = datetime.now(timezone.utc)
        day = now.strftime("%Y-%m-%d")
        for f in findings:
            await redis.hincrby(TALLY_KEY.format(day=day), f"{f['policy']}|{route}|{result}", 1)
            await redis.lpush(RECENT_KEY, json.dumps({
                "at": now.isoformat(timespec="seconds"), "policy": f["policy"], "version": RULES_VERSION,
                "route": route, "channel": channel, "to": "…" + tail, "ref": str(ref or "")[:60],
                "outcome": result, "reason": f["reason"], "excerpt": f.get("excerpt", "")}, ensure_ascii=False))
        await redis.expire(TALLY_KEY.format(day=day), 45 * 86400)
        await redis.ltrim(RECENT_KEY, 0, RECENT_MAX - 1)
    except Exception as exc:
        _log.info("policy record skipped: %s", exc)
    return result


async def report(redis, days: int = 7) -> dict:
    """Which policies are found, where, and what happened — for the dashboard."""
    out = {"mode": mode(), "version": RULES_VERSION, "days": [], "recent": [],
           "policies": {k: {"title": v[0], "severity": v[1]} for k, v in POLICIES.items()}}
    if redis is None:
        return out
    try:
        from datetime import timedelta
        now = datetime.now(timezone.utc)
        for i in range(days):
            day = (now - timedelta(days=i)).strftime("%Y-%m-%d")
            raw = await redis.hgetall(TALLY_KEY.format(day=day)) or {}
            rows = []
            for k, v in raw.items():
                k = k.decode() if isinstance(k, bytes) else str(k)
                p, route, outcome = (k.split("|") + ["", "", ""])[:3]
                rows.append({"policy": p, "route": route, "outcome": outcome,
                             "count": int(v.decode() if isinstance(v, bytes) else v)})
            if rows:
                out["days"].append({"day": day, "rows": sorted(rows, key=lambda r: -r["count"])})
        for item in await redis.lrange(RECENT_KEY, 0, 49) or []:
            try:
                out["recent"].append(json.loads(item.decode() if isinstance(item, bytes) else item))
            except Exception:
                pass
    except Exception as exc:
        _log.info("policy report unreadable: %s", exc)
    return out
