"""THE GATE BEFORE POSTING (owner, 2026-09-25) — every reply, every channel.

Live, under one communion post: "How much are gold trays with holes to place
tot glasses? Do you have shops in South Africa?" was answered with the silver
set at $180 and no word about South Africa; "Where is your location, do you
have some holycommunion cups" was answered with the Golden Chalice Cup with
Paten Set at $650 and no location. The owner: "Someone is asking for golden
trays and you give silver… Put a gate to review before posting accurate
information to avoid on the fly mistakes… Every post should be verified before
posting for accuracy and correct figures." Then: "Extend the gate to WhatsApp,
Chat, Messenger, Facebook. Make it very intelligent."

This module is that gate. Every reply Neema composes for a customer — a
public comment, a WhatsApp / Messenger / Instagram / TikTok message, the
website chat — passes it inside `runtime.run_turn` before it is sent:

1. THE RULES (deterministic, always on):
   - every money figure in the reply is explained by this turn's GROUND
     TRUTH — a hub price of a row the turn looked up, a number a tool
     returned (a cart total, an order total, an offer price), a figure the
     owner's own instructions state (shipping), a figure already said in
     this conversation, a house-rate conversion, a quantity multiple, a
     half (a deposit) or a sum of two of those — anything else is a figure
     from nowhere;
   - the item the reply sells is the item they asked for: the FINISH (gold
     is not silver; stainless / steel are the Silver line) and the KIND
     (communion cups are the small cups the tray holds — never a chalice
     unless they say chalice; a tray is not cups) — unless the reply says
     plainly that we do not have that one and offers the nearest;
   - a where-question is answered; one currency per reply; no link that no
     tool or instruction gave; no order-status claim ("shipped") without an
     order tool or an earlier word from us.
2. THE REVIEWER (one model line, switchable): reads the conversation, the
   ground truth, the draft, and fails a wrong item, a wrong figure, an
   unanswered question, a contradiction of the conversation (re-asking what
   they already said), an invented detail, or the wrong language. Money and
   order turns are reviewed by the main model; the rest by the light one.

A draft that fails is REWRITTEN once — not blindly retried: the writer gets
the reasons AND the facts (the hub rows for what they actually asked, fetched
by the gate itself; every tool result of the turn) and writes again without
tools, so nothing is ordered or sent twice. A second failure never reaches
the customer: they get an honest holding line, and a colleague gets the
conversation flagged with the reviewer's reasons and the draft.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone

from app.core.config import settings

_log = logging.getLogger("neema.review")

# ── money figures ────────────────────────────────────────────────────────────

_MONEY_RE = re.compile(
    r"(?:(?<![A-Za-z])(?P<c1>US\$|\$|USD|KES|KSHS?|ZMW|ZK|ZAR|R(?=\s?\d)|NGN|₦|GHS|GH₵|UGX|USH|TZS|TSH|"
    r"RWF|MWK|BWP|ETB|GBP|£|EUR|€)\s?(?P<a>\d[\d,]*(?:\.\d+)?))"
    r"|(?:(?P<b>\d[\d,]*(?:\.\d+)?)\s?(?:(?P<c2>USD|KES|KSHS?|ZMW|ZAR|rands?|NGN|naira|GHS|cedis?|UGX|"
    r"TZS|RWF|MWK|BWP|pula|ETB|birr|GBP|pounds?|EUR|euros?|dollars?|shillings?|bob)\b|(?P<c3>/=)))",
    re.IGNORECASE)
_CURRENCY_FAMILY = {"$": "USD", "US$": "USD", "USD": "USD", "DOLLAR": "USD", "DOLLARS": "USD",
                    "KES": "KES", "KSH": "KES", "KSHS": "KES", "SHILLING": "KES",
                    "SHILLINGS": "KES", "BOB": "KES", "/=": "KES",
                    "ZMW": "ZMW", "ZK": "ZMW",
                    "ZAR": "ZAR", "R": "ZAR", "RAND": "ZAR", "RANDS": "ZAR",
                    "NGN": "NGN", "₦": "NGN", "NAIRA": "NGN",
                    "GHS": "GHS", "GH₵": "GHS", "CEDI": "GHS", "CEDIS": "GHS",
                    "UGX": "UGX", "USH": "UGX", "TZS": "TZS", "TSH": "TZS",
                    "RWF": "RWF", "MWK": "MWK", "BWP": "BWP", "PULA": "BWP",
                    "ETB": "ETB", "BIRR": "ETB",
                    "GBP": "GBP", "£": "GBP", "POUND": "GBP", "POUNDS": "GBP",
                    "EUR": "EUR", "€": "EUR", "EURO": "EUR", "EUROS": "EUR"}


def _num(v) -> float | None:
    try:
        f = float(str(v).replace(",", ""))
    except (TypeError, ValueError):
        return None
    return f if f > 0 else None


def money_with_currency(text: str) -> list[tuple[str, float]]:
    """Every amount stated as MONEY in the text with its currency family —
    a currency mark before or after it ($40, USD 40, KES 19,000, Ksh 500,
    500/=, 40 dollars). A bare number ("40 cups") is a count, not a price."""
    out: list[tuple[str, float]] = []
    for m in _MONEY_RE.finditer(text or ""):
        v = _num(m.group("a") or m.group("b"))
        if v is None:
            continue
        mark = (m.group("c1") or m.group("c2") or m.group("c3") or "").upper()
        fam = _CURRENCY_FAMILY.get(mark, "USD")
        out.append((fam, v))
    return out


def money_figures(text: str) -> list[float]:
    out: list[float] = []
    for _fam, v in money_with_currency(text):
        if v not in out:
            out.append(v)
    return out


def quantities(text: str) -> list[int]:
    """Bare counts in the text (money figures removed): "2 trays", "100 cups"."""
    stripped = _MONEY_RE.sub(" ", text or "")
    qs: list[int] = []
    for m in re.finditer(r"\b(\d{1,6})\b", stripped):
        q = int(m.group(1))
        if 1 < q <= 100000 and q not in qs:
            qs.append(q)
    return qs


def _row_figures(p: dict) -> set[float]:
    """The prices ONE hub row can honestly put in a reply: its KES and USD,
    any per-currency price, its variants', and the house-rate conversions."""
    out: set[float] = set()
    usd_rate = float(settings.usd_kes_rate or 100)
    zmw_rate = float(settings.zmw_kes_rate or 5)

    def _add_pair(kes, usd):
        k, u = _num(kes), _num(usd)
        if k:
            out.add(k)
            out.add(round(k / usd_rate, 2))
            out.add(round(k / zmw_rate, 2))
        if u:
            out.add(u)
            out.add(round(u * usd_rate, 2))
    _add_pair(p.get("price") or p.get("price_kes"), p.get("price_usd"))
    for v in (p.get("prices") or {}).values():
        f = _num(v)
        if f:
            out.add(f)
    for vr in (p.get("variants") or []):
        _add_pair(vr.get("price_kes") or vr.get("price"), vr.get("price_usd"))
        for v in (vr.get("prices") or {}).values():
            f = _num(v)
            if f:
                out.add(f)
    for r in (p.get("bundle_rows") or []):
        out |= _row_figures(r)
    return out


def figures_in_results(tool_results: list | None) -> set[float]:
    """Every number a tool RETURNED this turn — the turn's ground truth: a
    cart total, an order total, an offer price, a variant's price, a
    figure inside a tool's own text. Numeric values anywhere in the result,
    plus money-marked figures in its strings."""
    out: set[float] = set()

    def _walk(o):
        if isinstance(o, bool):
            return
        if isinstance(o, (int, float)):
            f = _num(o)
            if f:
                out.add(round(f, 2))
        elif isinstance(o, str):
            for v in money_figures(o):
                out.add(round(v, 2))
        elif isinstance(o, dict):
            for v in o.values():
                _walk(v)
        elif isinstance(o, (list, tuple)):
            for v in o:
                _walk(v)
    for entry in tool_results or []:
        _walk((entry or {}).get("out"))
    return out


def transcript_text(transcript: list | None, limit: int = 8) -> list[tuple[str, str]]:
    """The last turns of a conversation as (role, text) — string contents
    only; tool blocks and images are skipped."""
    rows: list[tuple[str, str]] = []
    for m in transcript or []:
        c = m.get("content")
        if isinstance(c, list):
            c = " ".join(str(p.get("text") or "") for p in c
                         if isinstance(p, dict) and p.get("type") == "text")
        t = " ".join(str(c or "").split())
        if t:
            rows.append((str(m.get("role") or "user"), t))
    return rows[-limit:]


def transcript_figures(transcript: list | None) -> set[float]:
    """Money figures already said in this conversation — by them or by us."""
    out: set[float] = set()
    for _role, t in transcript_text(transcript, limit=40):
        for v in money_figures(t):
            out.add(round(v, 2))
    return out


def _close(a: float, b: float) -> bool:
    return abs(a - b) <= max(0.011, 0.005 * abs(b))


def _usd_of(base: set[float], seen: list) -> set[float]:
    """The USD figures among the rows' prices — the ones a foreign-currency
    conversion starts from."""
    out: set[float] = set()
    for p in seen or []:
        u = _num(p.get("price_usd"))
        if u:
            out.add(u)
        k = _num(p.get("price") or p.get("price_kes"))
        if k:
            out.add(round(k / float(settings.usd_kes_rate or 100), 2))
        for v in (p.get("variants") or []):
            u = _num(v.get("price_usd"))
            if u:
                out.add(u)
    return out


def allowed_figures(seen: list, *, known: set[float] | frozenset[float] = frozenset(),
                    facts: set[float] | frozenset[float] = frozenset(),
                    comment: str = "", answer: str = "",
                    fx: dict | None = None) -> set[float]:
    """Every figure the reply may honestly state.

    ANCHORS are the money this turn stands on: the rows' prices (and their
    conversions), a quantity multiple of one, a half of one (a deposit), and
    the FACTS — numbers a tool returned, figures already said in this
    conversation. KNOWN figures are the owner's own instructions (shipping).
    A sum counts only when it is two rows together, or an anchor plus a
    small fee (a known or fact figure no bigger than a quarter of it):
    "KES 22,000 + KES 350 delivery = KES 22,350". Never two loose figures
    added — the first simulation let "KES 20,000" through as 13,000 + 7,000
    and "$95" as 45 + 50."""
    base: set[float] = set()
    for p in seen or []:
        base |= _row_figures(p)
    qs = quantities(comment) + quantities(answer)
    anchors: set[float] = set(base)
    for b in base:
        anchors.add(round(b / 2, 2))
        for q in qs:
            anchors.add(round(b * q, 2))
            anchors.add(round(b * q / 2, 2))
    anchors |= {round(f, 2) for f in (facts or ())}
    # A foreign currency the customer asked for, at TODAY'S rate (services/fx):
    # the USD price times the rate, its quantity multiples and its half.
    for rate in (fx or {}).values():
        try:
            r = float(rate)
        except (TypeError, ValueError):
            continue
        if r <= 0:
            continue
        for u in _usd_of(base, seen) | {f for f in (facts or ()) if f in _usd_of(base, seen)}:
            conv = round(u * r, 2)
            anchors.add(conv)
            anchors.add(round(conv / 2, 2))
            for q in qs:
                anchors.add(round(conv * q, 2))
    allowed: set[float] = set(anchors) | {round(k, 2) for k in (known or ())}
    # two rows together
    rows_prices = sorted(base)[:60]
    for i, x in enumerate(rows_prices):
        for y in rows_prices[i + 1:]:
            allowed.add(round(x + y, 2))
    # an anchor plus a fee
    fees = [f for f in (set(known or ()) | set(facts or ())) if f > 0]
    for x in list(anchors)[:200]:
        for fee in fees:
            if fee <= 0.25 * x:
                allowed.add(round(x + fee, 2))
    return allowed


def unverified_figures(answer: str, seen: list, comment: str = "",
                       known_figures: set[float] | frozenset[float] = frozenset(),
                       facts: set[float] | frozenset[float] = frozenset(),
                       fx: dict | None = None) -> list[float]:
    """The money figures in the reply that NOTHING explains."""
    figures = money_figures(answer)
    if not figures:
        return []
    allowed = allowed_figures(seen, known=set(known_figures or ()), facts=set(facts or ()),
                              comment=comment, answer=answer, fx=fx)
    return [f for f in figures if not any(_close(f, a) for a in allowed)]


def two_currencies(answer: str, comment: str = "") -> list[str]:
    """ONE currency per reply (owner, 2026-09-05): the families of money in it
    — except the one THEY asked for by name ("in rands?"), which may stand
    beside the USD price it converts (the prompt's one exception)."""
    fams: list[str] = []
    for fam, _v in money_with_currency(answer):
        if fam not in fams:
            fams.append(fam)
    if len(fams) > 1 and comment:
        from app.services.fx import currency_asked
        asked = currency_asked(comment)
        asked_fams = {f for f, _v in money_with_currency(comment)} | ({asked} if asked else set())
        fams = [f for f in fams if f not in asked_fams]
    return fams if len(fams) > 1 else []


# ── the item they asked for ──────────────────────────────────────────────────

# The finish is part of the identity (owner, 2026-09-25: "someone is asking for
# golden trays and you give silver"). Stainless / steel are the owner's words
# for the Silver line (prompt: PRODUCT TERMINOLOGY).
FINISHES: dict[str, tuple[str, ...]] = {
    "gold": ("gold", "golden", "gilded", "dhahabu"),
    "silver": ("silver", "stainless", "steel", "fedha"),
    "brass": ("brass",),
    "wooden": ("wooden", "wood", "mbao"),
    "aluminium": ("aluminium", "aluminum"),
    "glass": ("glass", "glasses", "kioo"),
    "plastic": ("plastic", "plastiki"),
}
_FINISH_WORD = {w: f for f, words in FINISHES.items() for w in words}

# The kind of thing: communion CUPS are the small cups; a CHALICE only when
# they say so (owner, 2026-09-25: "when someone asks for Holy Communion Cups
# without specifying chalice, give the plastic, stainless and glass cups").
KINDS: dict[str, tuple[str, ...]] = {
    "chalice": ("chalice", "chalices", "goblet", "goblets", "paten"),
    "cup": ("cup", "cups", "glasses", "tots", "vikombe"),
    "tray": ("tray", "trays", "trei"),
    "set": ("set", "sets"),
}
_KIND_WORD = {w: k for k, words in KINDS.items() for w in words}
_TOT_GLASSES_RE = re.compile(r"\btots?\s+glass(?:es)?\b", re.IGNORECASE)


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z]+", (text or "").lower())


def finishes_of(text: str) -> set[str]:
    # "tot glasses" are the small cups, not a glass finish
    return {_FINISH_WORD[w] for w in _words(_TOT_GLASSES_RE.sub(" cups ", text or ""))
            if w in _FINISH_WORD}


def kinds_of(text: str) -> set[str]:
    return {_KIND_WORD[w] for w in _words(text) if w in _KIND_WORD}


# A reply that SAYS we do not have the one they asked and offers the nearest
# is honest — the finish rule stands down for it (the reviewer still reads it).
_SUBSTITUTE_RE = re.compile(
    r"\b(?:(?:don'?t|do not|doesn'?t|does not|no longer|not)\s+(?:currently\s+)?(?:have|stock|make|carry|sell|come)"
    r"|not\s+available|isn'?t\s+available|unavailable|only\s+(?:comes?|available|in|have)|instead"
    r"|the\s+(?:closest|nearest)|hatuna|haipo|haipatikani|badala)\b",
    re.IGNORECASE)


def acknowledges_substitute(answer: str) -> bool:
    return bool(_SUBSTITUTE_RE.search(answer or ""))


def item_issues(ask: str, product: dict | None, answer: str = "") -> list[str]:
    """Why this hub row is NOT what the comment asked for — a different
    finish, a chalice for cups (or cups for a chalice), cups for a tray.
    Empty when the row fits, the ask names no finish and no kind, or the
    reply says plainly we do not have that one."""
    name = str((product or {}).get("name") or "")
    if not name or not (ask or "").strip():
        return []
    if answer and acknowledges_substitute(answer):
        return []
    issues: list[str] = []
    asked_f, have_f = finishes_of(ask), finishes_of(name)
    if asked_f and have_f and not (asked_f & have_f):
        issues.append(f"they asked for {' / '.join(sorted(asked_f))}; '{name}' is "
                      f"{' / '.join(sorted(have_f))} — the finish they asked for is the item")
    asked_k, have_k = kinds_of(ask), kinds_of(name)
    if "chalice" in have_k and "cup" in asked_k and "chalice" not in asked_k:
        issues.append(f"they asked for communion cups — the small cups the tray holds "
                      f"(plastic, silver, glass, pre-packed); '{name}' is a chalice")
    elif "chalice" in asked_k and have_k and "chalice" not in have_k:
        issues.append(f"they asked for a chalice; '{name}' is not one")
    elif asked_k and have_k and not (asked_k & have_k) and "set" not in have_k:
        issues.append(f"they asked for a {'/'.join(sorted(asked_k))}; '{name}' is a "
                      f"{'/'.join(sorted(have_k))}")
    return issues


def product_named(answer: str, seen: list) -> dict | None:
    """The looked-up row the reply actually sells: the one it NAMES (longest
    name wins), else the ONE row whose price it quotes — a reply that
    describes "the glass communion set… in silver tones is $180" without the
    hub's name is still selling the Silver Communion Tray. None when the
    reply names none and prices none (or several)."""
    a = " ".join((answer or "").lower().split())
    best = None
    for p in seen or []:
        n = " ".join(str(p.get("name") or "").lower().split())
        if n and n in a and (best is None or len(n) > len(str(best.get("name") or ""))):
            best = p
    if best is not None:
        return best
    figures = money_figures(answer)
    if not figures:
        return None
    priced = []
    for p in seen or []:
        if any(_close(f, v) for f in figures for v in _row_figures(p)):
            if all(p.get("name") != q.get("name") for q in priced):
                priced.append(p)
    return priced[0] if len(priced) == 1 else None


# A question about WHERE we are, or a shop in their country, must be answered
# (owner, 2026-09-25: "Where is your location…", "Do you have shops in South
# Africa?" both went unanswered). The answer names a place, a shop or the
# courier — anything else left it hanging.
_WHERE_ASK_RE = re.compile(
    r"(?:\bwhere\s+(?:are|is|r|do)\s+(?:you|your|u|the\s+shop|we|i)\b|\byour\s+(?:location|address)\b|"
    r"\blocation\s*\?|\b(?:are\s+you|r\s+u|you\s+are)\s+(?:located|based)\b|"
    r"\b(?:do\s+you\s+have|have\s+you|is\s+there|any)\s+(?:a\s+|an\s+)?(?:shops?|stores?|branch(?:es)?|outlets?|offices?)\s+in\s+[A-Za-z]|"
    r"\b(?:shops?|stores?|branch(?:es)?|outlets?|offices?)\s+in\s+[A-Za-z][A-Za-z ]{1,30}\?|"
    r"\bmko\s+wapi\b|\buko\s+wapi\b|\bduka\s+(?:lenu|lako)\s+liko\b)",
    re.IGNORECASE)
_WHERE_ANSWER_RE = re.compile(
    r"\b(?:nairobi|kenya|dhl|deliver|delivery|ship|shipping|courier|located|based|"
    r"branch|shop\s+in|no\s+shop|our\s+shop|workshop|tuko|tunapeleka|tunasafirisha)\b",
    re.IGNORECASE)


def where_unanswered(comment: str, answer: str) -> bool:
    return bool(_WHERE_ASK_RE.search(comment or "")) and not _WHERE_ANSWER_RE.search(answer or "")


# A link the reply hands out must have come from a tool (an order link, a
# product page, a payment link) or the owner's instructions — never typed
# from memory.
_URL_RE = re.compile(r"https?://[^\s)>\]\"']+", re.IGNORECASE)


def foreign_links(answer: str, tool_results: list | None, known_text: str = "") -> list[str]:
    urls = _URL_RE.findall(answer or "")
    if not urls:
        return []
    pool = (known_text or "") + " " + " ".join(
        json.dumps((e or {}).get("out"), default=str) for e in (tool_results or []))
    return [u for u in urls if u.rstrip(".,") not in pool]


# An order-status claim needs an order tool behind it, or our own earlier
# word — never a guess that soothes.
_STATUS_CLAIM_RE = re.compile(
    r"\b(?:has\s+(?:been\s+)?(?:shipped|dispatched|sent\s+out|delivered)|is\s+on\s+its\s+way|"
    r"was\s+(?:shipped|dispatched|delivered)|tracking\s+number|imetumwa|imefika|iko\s+njiani)\b",
    re.IGNORECASE)
_ORDER_TOOLS = {"check_order_status", "create_order", "prepare_quotation"}


def status_without_source(answer: str, tool_results: list | None, transcript: list | None) -> bool:
    if not _STATUS_CLAIM_RE.search(answer or ""):
        return False
    if any(str((e or {}).get("tool") or "") in _ORDER_TOOLS for e in (tool_results or [])):
        return False
    return not any(role == "assistant" and _STATUS_CLAIM_RE.search(t)
                   for role, t in transcript_text(transcript, limit=40))


HARD_KINDS = ("figure", "item", "link", "status")


def rule_findings(comment: str, answer: str, seen: list,
                  known_figures: set[float] | frozenset[float] = frozenset(), *,
                  tool_results: list | None = None, transcript: list | None = None,
                  known_text: str = "", fx: dict | None = None) -> list[dict]:
    """The deterministic findings on a draft, each with its weight:
    {"kind", "text", "hard"}. HARD findings — a figure from nowhere, the
    wrong item priced, a link no tool gave, an order status with no source —
    are the ones that may hold a reply; SOFT ones ask for a rewrite and then
    stand aside (owner, 2026-09-25: "change from gating to double
    verifying" — a reply is corrected, not strangled)."""
    out: list[dict] = []
    facts = figures_in_results(tool_results) | transcript_figures(transcript)
    bad = unverified_figures(answer, seen, comment, known_figures, facts=facts, fx=fx)
    if bad:
        looked = ", ".join(f"{p.get('name')} (KES {p.get('price')} / USD {p.get('price_usd')})"
                           for p in (seen or [])[:6]) or "no hub row was looked up"
        out.append({"kind": "figure", "hard": True,
                    "text": "unverified figure(s) " + ", ".join(_fmt(f) for f in bad)
                    + " — not the hub price of any row looked up this turn, nor a figure "
                    "any tool returned: " + looked})
    fams = two_currencies(answer, comment)
    if fams:
        out.append({"kind": "currency", "hard": False,
                    "text": "two currencies in one reply (" + ", ".join(fams)
                    + ") — quote ONE, the customer's own"})
    named = product_named(answer, seen)
    if named is not None:
        for t in item_issues(comment, named, answer):
            out.append({"kind": "item", "hard": True, "text": t})
    if where_unanswered(comment, answer):
        out.append({"kind": "where", "hard": False,
                    "text": "their question about where we are / a shop in their country is "
                    "unanswered — say Nairobi, Kenya, no shop there, DHL delivers to them"})
    links = foreign_links(answer, tool_results, known_text)
    if links:
        out.append({"kind": "link", "hard": True,
                    "text": "a link no tool gave: " + ", ".join(links[:3])
                    + " — only links a tool returned may be sent"})
    if status_without_source(answer, tool_results, transcript):
        out.append({"kind": "status", "hard": True,
                    "text": "an order-status claim (shipped / on its way / delivered) with no "
                    "check_order_status behind it — check the order, never assume"})
    return out


def rule_issues(comment: str, answer: str, seen: list,
                known_figures: set[float] | frozenset[float] = frozenset(), *,
                tool_results: list | None = None, transcript: list | None = None,
                known_text: str = "", fx: dict | None = None) -> list[str]:
    """The deterministic verdict on a draft, as text. Empty = the rules pass
    it (the reviewer may still not)."""
    return [f["text"] for f in rule_findings(comment, answer, seen, known_figures,
                                             tool_results=tool_results, transcript=transcript,
                                             known_text=known_text, fx=fx)]


def _fmt(f: float) -> str:
    return f"{int(f):,}" if float(f).is_integer() else f"{f:,.2f}"


# ── the reviewer ─────────────────────────────────────────────────────────────

_VERDICT_RE = re.compile(r"verdict\s*=\s*(pass|fail)", re.IGNORECASE)
_ISSUES_RE = re.compile(r"issues\s*=\s*(.*)$", re.IGNORECASE | re.DOTALL)
# Turns where quality is money are reviewed by the main model.
_MONEY_TURN_RE = re.compile(
    r"\b(?:order|orders|pay|paid|payment|deposit|m-?pesa|invoice|refund|total|checkout|"
    r"ship|shipped|deliver|delivered|tracking|lipa|malipo|agizo)\b", re.IGNORECASE)


def parse_verdict(text: str) -> dict | None:
    """'verdict=fail | issues=a; b' → {"ok": False, "issues": ["a", "b"]}."""
    t = " ".join((text or "").split())
    m = _VERDICT_RE.search(t)
    if not m:
        return None
    ok = m.group(1).lower() == "pass"
    issues: list[str] = []
    mi = _ISSUES_RE.search(t)
    if mi and not ok:
        raw = mi.group(1).strip().strip("|").strip()
        issues = [s.strip(" .") for s in raw.split(";") if s.strip(" .-")]
    return {"ok": ok, "issues": issues}


def rows_text(seen: list, currency: str) -> str:
    lines = []
    for p in (seen or [])[:8]:
        price = p.get("price_usd") if currency == "USD" else p.get("price")
        unit = "USD" if currency == "USD" else "KES"
        d = " ".join(str(p.get("description") or "").split())[:140]
        lines.append(f"- {p.get('name')} — {unit} {price}" + (f" — {d}" if d else ""))
    return "\n".join(lines) or "- (none — the draft looked nothing up)"


def tools_text(tool_results: list | None, limit: int = 6) -> str:
    """Other tool results of the turn, compact — the cart, an order, an
    availability check — so the reviewer and the rewrite see the same truth."""
    lines = []
    for e in (tool_results or [])[-limit:]:
        name = str((e or {}).get("tool") or "")
        if name in ("search_catalog", "remember", "send_product_cards"):
            continue
        try:
            body = json.dumps((e or {}).get("out"), default=str)
        except Exception:
            body = str((e or {}).get("out"))
        lines.append(f"- {name}: {body[:400]}")
    return "\n".join(lines)


def conversation_text(transcript: list | None, limit: int = 8) -> str:
    lines = []
    for role, t in transcript_text(transcript, limit=limit):
        who = "Customer" if role == "user" else "Neema"
        lines.append(f"{who}: {t[:260]}")
    return "\n".join(lines)


def _reviewer_model(comment: str, answer: str) -> str:
    if _MONEY_TURN_RE.search((comment or "") + " " + (answer or "")):
        return settings.tier2_model
    return settings.tier2_model_light


async def reviewer_verdict(comment: str, answer: str, seen: list, *,
                           post_product: str = "", currency: str = "USD",
                           redis=None, transcript: list | None = None,
                           tool_results: list | None = None,
                           mode: str = "comment") -> dict | None:
    """One model line on the draft. None when the reviewer is off, the
    budget is stopped, or the model fails — the rules' verdict then stands."""
    if not settings.reply_review:
        return None
    if mode == "comment" and not settings.comment_reply_review:
        return None
    try:
        from app.services import ai_budget
        if redis is not None and await ai_budget.mode(redis) == "stop":
            return None
    except Exception:
        pass
    where = ("a PUBLIC reply to a customer's comment under a post"
             if mode == "comment" else "a reply in a private chat with a customer")
    convo = conversation_text(transcript) if mode != "comment" else ""
    other = tools_text(tool_results)
    prompt = (
        "You are the REVIEWER at a Christian clergy and communion store. A colleague "
        f"drafted {where}. Check it against the facts below and answer on ONE line in "
        "exactly this shape:\n"
        "verdict=<pass|fail> | issues=<the problems, separated by ';', or ->\n\n"
        "FAIL when any of these is true:\n"
        "1. WRONG ITEM — the reply names or prices something other than what they asked "
        "for: a different finish (they asked GOLD, it gives SILVER), a different kind "
        "(they asked communion CUPS — the small cups a tray holds — and it gives a "
        "CHALICE; they asked a TRAY and it gives cups), or a product they never asked "
        "about. A reply that says plainly we do not have the exact one and offers the "
        "nearest at its hub price PASSES.\n"
        "2. WRONG FIGURE — a price that is not the hub price of that row in the currency "
        "shown, a total no tool returned, or an invented pack size, capacity, colour, "
        "material or delivery time.\n"
        "3. UNANSWERED — a question in their message gets no answer: where we are "
        "(Nairobi, Kenya), whether we have a shop in their country, delivery to them, "
        "a price they asked for.\n"
        + ("4. CONTRADICTS THE CONVERSATION — it re-asks a detail they already gave "
           "(colour, size, quantity, city, name), or contradicts what we said earlier.\n"
           "5. INVENTED — availability, stock, an order status (shipped, on its way) or a "
           "payment received that no tool result or earlier message supports. (A "
           "colleague reaching out, a delivery being arranged, a price to be confirmed "
           "are ordinary promises, not inventions.)\n"
           "6. WRONG LANGUAGE — they wrote in Swahili and the reply is English, or the "
           "reverse (a mix is fine).\n" if mode != "comment" else "")
        + "PASS otherwise. Never fail for tone, warmth, length or emoji.\n\n"
        + (f"The post is about: {post_product or 'unknown'}\n" if mode == "comment" else "")
        + f"Hub rows the colleague looked up ({currency}):\n{rows_text(seen, currency)}\n"
        + (f"Other tool results this turn:\n{other}\n" if other else "")
        + (f"The conversation so far (last turns):\n{convo}\n" if convo else "")
        + f'Customer\'s message: "{" ".join((comment or "").split())[:400]}"\n'
        f'Draft reply: "{" ".join((answer or "").split())[:900]}"\n'
        "Answer with the one line only."
    )
    try:
        from app.agent.runtime import build_llm
        llm = build_llm(model=_reviewer_model(comment, answer))
        resp = await llm.complete(
            system="You verify a shop's replies before they are sent. One line only, in the shape asked.",
            messages=[{"role": "user", "content": prompt}], tools=[])
        return parse_verdict(resp.text or "")
    except Exception as exc:
        _log.info("reply reviewer unavailable: %s", exc)
        return None


async def review_reply(comment: str, answer: str, seen: list, *,
                       post_product: str = "", currency: str = "USD",
                       known_figures: set[float] | frozenset[float] = frozenset(),
                       redis=None, transcript: list | None = None,
                       tool_results: list | None = None, mode: str = "comment",
                       known_text: str = "", fx: dict | None = None) -> dict:
    """DOUBLE VERIFICATION of one draft: the rules (deterministic) AND the
    reviewer (a model's reading) both read it, and their findings merge —
    {"ok", "issues", "hard", "soft", "by"}. `hard` are the findings that may
    hold a reply (a figure or item from nowhere, a link, a status claim);
    `soft` ask for a rewrite and then stand aside. The reviewer's findings
    are always soft: a model's opinion improves a reply, it never strangles
    one (owner, 2026-09-25)."""
    findings = rule_findings(comment, answer, seen, set(known_figures or ()),
                             tool_results=tool_results, transcript=transcript,
                             known_text=known_text, fx=fx)
    hard = [f["text"] for f in findings if f["hard"]]
    soft = [f["text"] for f in findings if not f["hard"]]
    by = "rules" if findings else ""
    v = await reviewer_verdict(comment, answer, seen, post_product=post_product,
                               currency=currency, redis=redis, transcript=transcript,
                               tool_results=tool_results, mode=mode)
    if v is not None and not v["ok"]:
        soft.extend(v["issues"] or ["the reviewer rejected the draft"])
        by = (by + "+reviewer").strip("+")
    if v is not None and v["ok"] and not findings:
        by = "reviewer"
    issues = hard + soft
    return {"ok": not issues, "issues": issues, "hard": hard, "soft": soft, "by": by or "rules"}


def review_notes(issues: list[str]) -> str:
    """What the writer is told for the second draft."""
    why = "; ".join(i.strip() for i in (issues or []) if i.strip()) or "it did not pass verification"
    return (
        "(A REVIEWER HELD BACK YOUR PREVIOUS DRAFT before it posted — it failed "
        f"verification: {why}. Write the reply again, from the hub: search_catalog "
        "the EXACT item they asked for — their finish and their kind (gold is not "
        "silver; 'communion cups' are the small cups the tray holds — plastic, silver, "
        "glass, pre-packed — never a chalice unless they say chalice; a tray is not "
        "cups); quote ONLY prices search_catalog returned, in one currency; answer "
        "EVERY question they asked (where we are — Nairobi, Kenya; a shop in their "
        "country — none, we deliver there by DHL; delivery; the price). If we do not "
        "have the exact item, say so plainly and offer the nearest with its hub price. "
        "Never post a guess.)"
    )


def rewrite_block(issues: list[str], draft: str, seen: list, currency: str,
                  tool_results: list | None, mode: str = "comment",
                  fx: dict | None = None, comment: str = "") -> str:
    """The reviewer's message to the writer for the ONE rewrite: the reasons,
    the facts (every hub row in hand, every other tool result), the draft —
    and the instruction to write the corrected reply only, from these facts,
    with no tool (nothing is ordered or sent twice)."""
    why = "; ".join(i.strip() for i in (issues or []) if i.strip()) or "it did not pass verification"
    other = tools_text(tool_results, limit=8)
    where = "posted under the comment" if mode == "comment" else "sent to the customer"
    return (
        f"[REVIEWER — your draft was HELD BACK before it was {where}. It failed "
        f"verification: {why}.\n\n"
        f"THE FACTS YOU MAY STATE (the hub's rows, in {currency}; nothing else is a price):\n"
        f"{rows_text(seen, currency)}\n"
        + (f"Other facts from this turn's tools:\n{other}\n" if other else "")
        + _fx_text(fx, comment)
        + f'\nYour held draft: "{" ".join((draft or "").split())[:900]}"\n\n'
        "Write the corrected reply NOW — the reply only, nothing else, no tool. "
        "Rules: the item is exactly what they asked for (their finish, their kind — "
        "if we do not have it, say so plainly and offer the nearest from the rows "
        "above with its price); every figure is one of the facts above, in ONE "
        "currency (plus the one they asked for by name, at today's rate above, if "
        "any); answer every question they asked — and nothing they did not ask "
        "(where we are is Nairobi, Kenya; a shop in their country — none, DHL "
        "delivers — ONLY if they asked); never re-ask a detail they already gave; "
        "never invent a pack size, a capacity, an order status, a delivery time or "
        "an exchange rate; never promise to 'confirm' a figure with the team; keep "
        "the warmth and the closing question; write in their language.]"
    )


def _fx_text(fx: dict | None, comment: str) -> str:
    """Today's rate for the currency they asked, for the rewrite."""
    if not fx or not comment:
        return ""
    from app.services.fx import currency_asked
    code = currency_asked(comment)
    if not code or code not in fx:
        return ""
    return f"Today's rate (a fact): 1 USD = {float(fx[code]):g} {code} — convert from the USD price only.\n"


# ── the tally: what the gate did today (health, the team's eye) ──────────────

def _day_key() -> str:
    return "review:" + datetime.now(timezone.utc).strftime("%Y-%m-%d")


async def record_verdict(redis, outcome: str, channel: str = "") -> None:
    """pass / rewritten / soft (sent with notes) / held, per UTC day (kept
    three days), best-effort."""
    if redis is None or outcome not in ("pass", "rewritten", "soft", "held"):
        return
    try:
        key = _day_key()
        await redis.hincrby(key, outcome, 1)
        if channel:
            await redis.hincrby(key, f"{outcome}:{channel}", 1)
        await redis.expire(key, 3 * 24 * 3600)
    except Exception:
        pass


async def held_recently(redis, channel: str, key: str, hours: int = 6) -> bool:
    """Was this person already given a holding line in the last `hours`? A
    colleague is already flagged; a second "let me confirm" in a row reads
    like a wall (owner, 2026-09-25). Marks the hold when it is not."""
    if redis is None:
        return False
    try:
        return not bool(await redis.set(f"review:hold:{channel}:{key}", "1", nx=True,
                                        ex=hours * 3600))
    except Exception:
        return False


async def read_verdicts(redis) -> dict:
    """{"pass": n, "rewritten": n, "soft": n, "held": n} for today, {} when unknown."""
    if redis is None:
        return {}
    try:
        raw = await redis.hgetall(_day_key())
    except Exception:
        return {}
    out: dict = {}
    for k, v in (raw or {}).items():
        ks = k.decode() if isinstance(k, bytes) else str(k)
        try:
            out[ks] = int(v)
        except (TypeError, ValueError):
            continue
    return out


_prompt_figures_cache: dict[str, frozenset[float]] = {}


def prompt_figures(currency: str = "USD") -> frozenset[float]:
    """The money figures the owner's own instructions state (shipping and the
    like) — a reply may repeat them without a hub row."""
    key = (currency or "USD").upper()
    if key not in _prompt_figures_cache:
        try:
            from app.agent.prompt import build_system_prompt
            from app.agent.runtime import _public_comment_addendum
            text = build_system_prompt(currency=key) + _public_comment_addendum(key)
            _prompt_figures_cache[key] = frozenset(money_figures(text))
        except Exception:
            _prompt_figures_cache[key] = frozenset()
    return _prompt_figures_cache[key]
