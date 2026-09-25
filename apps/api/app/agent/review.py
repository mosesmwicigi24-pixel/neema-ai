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
    r"RWF|MWK|BWP|ETB|GBP|£|EUR|€)\s?(?P<a>\d[\d,]*(?:\.\d+)?k?))"
    r"|(?:(?P<b>\d[\d,]*(?:\.\d+)?k?)\s?(?:(?P<c2>USD|KES|KSHS?|ZMW|ZAR|rands?|NGN|naira|GHS|cedis?|UGX|"
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
        raw = str(v).replace(",", "").strip()
        mult = 1.0
        if raw[-1:].lower() == "k":          # "22k" is 22,000
            raw, mult = raw[:-1], 1000.0
        f = float(raw) * mult
    except (TypeError, ValueError):
        return None
    return f if f > 0 else None


_NUMBER_WORDS = {
    "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
    "ten": 10, "eleven": 11, "twelve": 12, "dozen": 12, "fifteen": 15, "twenty": 20,
    "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "hundred": 100, "thousand": 1000,
    "pair": 2, "couple": 2,
    "mbili": 2, "tatu": 3, "nne": 4, "tano": 5, "sita": 6, "saba": 7, "nane": 8, "tisa": 9,
    "kumi": 10, "ishirini": 20, "thelathini": 30, "arobaini": 40, "hamsini": 50, "mia": 100,
    "elfu": 1000,
}


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
    """Bare counts in the text (money figures removed): "2 trays", "100 cups",
    "two sets", "a pair", "tatu"."""
    stripped = _MONEY_RE.sub(" ", text or "")
    qs: list[int] = []
    for m in re.finditer(r"\b(\d{1,6})\b", stripped):
        q = int(m.group(1))
        if 1 < q <= 100000 and q not in qs:
            qs.append(q)
    for w in re.findall(r"[a-z]+", stripped.lower()):
        q = _NUMBER_WORDS.get(w)
        if q and q not in qs:
            qs.append(q)
    return qs


def _row_figures(p: dict, currency: str = "USD") -> set[float]:
    """The prices ONE hub row can honestly put in a reply — exactly what the
    writer is shown (tools._to_display): its KES; its USD (the hub's own when
    it has one, else KES at the house rate); ZMW at the house rate only for
    a Zambian customer; any per-currency price; its variants'."""
    out: set[float] = set()
    usd_rate = float(settings.usd_kes_rate or 100)
    zmw_rate = float(settings.zmw_kes_rate or 5)

    def _add_pair(kes, usd):
        k, u = _num(kes), _num(usd)
        if k:
            out.add(k)
            if not u:
                out.add(round(k / usd_rate, 2))
            if (currency or "").upper() == "ZMW":
                out.add(round(k / zmw_rate, 2))
        if u:
            out.add(u)
            if not k:
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
        out |= _row_figures(r, currency)
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
    """Exact: to the cent below a hundred ($3.50 is not $4), to the unit above
    it (a whole-unit rounding of a conversion, R1,972 for R1,971.60, passes),
    and never looser than 0.05% ("KES 22,100" for a KES 22,000 tray fails)."""
    unit = 0.5 if abs(b) >= 100 else 0.0051
    return abs(a - b) <= max(unit, 0.0005 * abs(b))


def _usd_of(base: set[float], seen: list) -> set[float]:
    """The USD figures a foreign-currency conversion starts from: the hub's
    own USD price, else KES at the house rate — never both."""
    out: set[float] = set()
    for p in seen or []:
        u = _num(p.get("price_usd"))
        k = _num(p.get("price") or p.get("price_kes"))
        if u:
            out.add(u)
        elif k:
            out.add(round(k / float(settings.usd_kes_rate or 100), 2))
        for v in (p.get("variants") or []):
            u = _num(v.get("price_usd"))
            if u:
                out.add(u)
    return out


def allowed_figures(seen: list, *, known: set[float] | frozenset[float] = frozenset(),
                    facts: set[float] | frozenset[float] = frozenset(),
                    comment: str = "", answer: str = "",
                    fx: dict | None = None, currency: str = "USD") -> set[float]:
    """Every figure the reply may honestly state.

    ANCHORS are the money this turn stands on: the rows' prices (as the
    writer sees them), a quantity multiple of one, a half of one (a
    deposit), the FACTS — numbers a tool returned, figures already said in
    this conversation — and, when they asked for their own money, the USD
    price at today's rate. KNOWN figures are the owner's own instructions
    (shipping). A sum counts only when it is two rows together, or a PRICE
    or FACT plus a small fee (a known figure no bigger than a quarter of
    it): "KES 22,000 + KES 350 delivery = KES 22,350". Never two loose
    figures, never a fee on a half or a conversion — the stress battery
    found "R2,300" explained as a conversion plus a stray instruction
    figure."""
    base: set[float] = set()
    for p in seen or []:
        base |= _row_figures(p, currency)
    qs = quantities(comment) + quantities(answer)
    fee_anchors: set[float] = set(base) | {round(f, 2) for f in (facts or ())}
    for b in base:
        for q in qs:
            fee_anchors.add(round(b * q, 2))
    anchors: set[float] = set(fee_anchors)
    for b in base:
        anchors.add(round(b / 2, 2))
        for q in qs:
            anchors.add(round(b * q / 2, 2))
    # Their own money at TODAY'S rate (services/fx): the USD price times the
    # rate, its quantity multiples and its half.
    usd_base = _usd_of(base, seen)
    for rate in (fx or {}).values():
        try:
            r = float(rate)
        except (TypeError, ValueError):
            continue
        if r <= 0:
            continue
        for u in usd_base:
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
    # a price or a fact plus a fee
    fees = [f for f in (set(known or ()) | set(facts or ())) if f > 0]
    for x in list(fee_anchors)[:200]:
        for fee in fees:
            if fee <= 0.25 * x:
                allowed.add(round(x + fee, 2))
    return allowed


def unverified_figures(answer: str, seen: list, comment: str = "",
                       known_figures: set[float] | frozenset[float] = frozenset(),
                       facts: set[float] | frozenset[float] = frozenset(),
                       fx: dict | None = None, currency: str = "USD") -> list[float]:
    """The money figures in the reply that NOTHING explains."""
    figures = money_figures(answer)
    if not figures:
        return []
    allowed = allowed_figures(seen, known=set(known_figures or ()), facts=set(facts or ()),
                              comment=comment, answer=answer, fx=fx, currency=currency)
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
        for fam, rx in _HOUSE_ASKED.items():
            if rx.search(comment):
                asked_fams.add(fam)
        fams = [f for f in fams if f not in asked_fams]
    return fams if len(fams) > 1 else []


_HOUSE_ASKED = {
    "USD": re.compile(r"(?<![A-Za-z])(?:dollars?|usd|\$)(?![A-Za-z])", re.IGNORECASE),
    "KES": re.compile(r"(?<![A-Za-z])(?:shillings?|shilingi|ksh|kes|bob)(?![A-Za-z])", re.IGNORECASE),
    "ZMW": re.compile(r"(?<![A-Za-z])(?:kwacha|zmw)(?![A-Za-z])", re.IGNORECASE),
}


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


def products_named(answer: str, seen: list) -> list[dict]:
    """Every looked-up row the reply NAMES (a name inside another's — "Chalice
    Cup -Medium" inside "Golden Chalice Cup with Paten Set" — counts once,
    the longer)."""
    a = " ".join((answer or "").lower().split())
    named = [p for p in (seen or [])
             if " ".join(str(p.get("name") or "").lower().split()) in a and p.get("name")]
    named.sort(key=lambda p: -len(str(p.get("name") or "")))
    out: list[dict] = []
    for p in named:
        n = " ".join(str(p.get("name") or "").lower().split())
        if any(n in " ".join(str(q.get("name") or "").lower().split()) for q in out):
            continue
        out.append(p)
    return out


def product_named(answer: str, seen: list) -> dict | None:
    """The looked-up row the reply actually sells: the one it NAMES (longest
    name wins), else the ONE row whose price it quotes — a reply that
    describes "the glass communion set… in silver tones is $180" without the
    hub's name is still selling the Silver Communion Tray. None when the
    reply names none and prices none (or several)."""
    named = products_named(answer, seen)
    if named:
        return named[0]
    figures = money_figures(answer)
    if not figures:
        return None
    priced = []
    for p in seen or []:
        if any(_close(f, v) for f in figures for v in _row_figures(p, "ZMW")):
            if all(p.get("name") != q.get("name") for q in priced):
                priced.append(p)
    return priced[0] if len(priced) == 1 else None


# A question about WHERE we are, or a shop in their country, must be answered
# (owner, 2026-09-25: "Where is your location…", "Do you have shops in South
# Africa?" both went unanswered). The answer names a place, a shop or the
# courier — anything else left it hanging.
_WHERE_ASK_RE = re.compile(
    r"(?:\bwhere\s+(?:are|is|r)\s+(?:you|your|u|the\s+shop)\b|\byour\s+(?:location|address)\b|"
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


def foreign_links(answer: str, tool_results: list | None, known_text: str = "",
                  transcript: list | None = None) -> list[str]:
    urls = _URL_RE.findall(answer or "")
    if not urls:
        return []
    pool = (known_text or "") + " " + " ".join(
        json.dumps((e or {}).get("out"), default=str) for e in (tool_results or []))
    pool += " " + " ".join(t for _r, t in transcript_text(transcript, limit=40))
    return [u for u in urls if u.rstrip(".,") not in pool]


# An order-status claim needs an order tool behind it, or our own earlier
# word — never a guess that soothes.
_STATUS_CLAIM_RE = re.compile(
    r"\b(?:(?:your|the)\s+(?:order|parcel|package|item|delivery)|it|order\s*#?\s*\d+)\s+"
    r"(?:(?:has|had)\s+(?:already\s+)?(?:been\s+)?(?:shipped|dispatched|sent\s+out|delivered)|"
    r"was\s+(?:shipped|dispatched|delivered)|is\s+(?:already\s+)?on\s+its\s+way)"
    r"|(?:your|the)\s+tracking\s+number\s+is\b|tracking\s+number\s*:\s*[A-Z0-9]"
    r"|(?:agizo|kifurushi|oda)\s+(?:lako|yako)\s+(?:imetumwa|imeshatumwa|imefika|imeshafika|iko\s+njiani)",
    re.IGNORECASE)
_ORDER_TOOLS = {"check_order_status", "create_order", "prepare_quotation"}


def status_without_source(answer: str, tool_results: list | None, transcript: list | None) -> bool:
    if not _STATUS_CLAIM_RE.search(answer or ""):
        return False
    if any(str((e or {}).get("tool") or "") in _ORDER_TOOLS for e in (tool_results or [])):
        return False
    return not any(role == "assistant" and _STATUS_CLAIM_RE.search(t)
                   for role, t in transcript_text(transcript, limit=40))


HARD_KINDS = ("figure", "item", "link", "status", "photos", "variants")

# "I can't send photos from here" is FALSE on every chat channel — the cards
# tool sends them (owner, 2026-09-25: the photos went out and the very next
# line said they could not). A public comment cannot carry a photo; there the
# rule stands down.
_NO_PHOTOS_RE = re.compile(
    r"\b(?:can(?:no|')t|cannot|unable\s+to|not\s+able\s+to|no\s+way\s+to|couldn'?t)\s+"
    r"(?:send|share|attach|show|upload|post)\s+(?:you\s+|any\s+|more\s+|the\s+)?"
    r"(?:photos?|pictures?|pics?|images?|picha)\b|"
    r"\b(?:photos?|pictures?|images?)\s+(?:can(?:no|')t|cannot)\s+be\s+(?:sent|shared)\b|"
    r"\bsi(?:wezi|tuwezi)\s+kutuma\s+picha\b",
    re.IGNORECASE)
_PHOTOS_SENT_RE = re.compile(
    r"\b(?:here\s+(?:are|is)\s+(?:the\s+|some\s+|a\s+)?(?:photos?|pictures?|pics?|images?)|"
    r"(?:sent|shared|attached)\s+(?:you\s+)?(?:the\s+|some\s+)?(?:photos?|pictures?|pics?|images?)|"
    r"(?:photos?|pictures?)\s+(?:above|below|attached)|hizi\s+ndizo\s+picha)\b",
    re.IGNORECASE)


def cards_sent(tool_results: list | None) -> int:
    """How many product cards / photos the turn's tools delivered."""
    n = 0
    for e in tool_results or []:
        if str((e or {}).get("tool") or "") != "send_product_cards":
            continue
        out = (e or {}).get("out") or {}
        if isinstance(out, dict) and out.get("ok"):
            n += int(out.get("sent_cards") or 0) + int(out.get("album_photos") or 0)
    return n


def actions_text(tool_results: list | None) -> str:
    """What the turn's tools ALREADY DID — the rewrite refers to these as
    done, and never claims it cannot do what was just done."""
    lines = []
    for e in tool_results or []:
        name = str((e or {}).get("tool") or "")
        out = (e or {}).get("out") or {}
        if not isinstance(out, dict) or out.get("error"):
            continue
        inp = (e or {}).get("input") or {}
        if name == "send_product_cards" and out.get("ok"):
            n = int(out.get("sent_cards") or 0) + int(out.get("album_photos") or 0)
            what = ", ".join(str(x) for x in (inp.get("products") or inp.get("names") or [])[:4]) \
                or "the product"
            lines.append(f"- {n} photo card(s) of {what} were SENT to them — say 'here are the "
                         "photos'; never say you cannot send photos" if n else
                         f"- no photo card of {what} could be sent this turn — describe it in "
                         "words and offer the link; never say you cannot send photos")
        elif name == "update_cart" and out.get("ok", True):
            lines.append("- the cart was updated (its total is a fact above)")
        elif name == "create_order":
            lines.append("- the order was CREATED" + (f" — link: {out.get('order_url')}" if out.get("order_url") else ""))
        elif name == "capture_contact":
            lines.append("- their contact details were saved")
        elif name == "handoff_to_human":
            lines.append("- a colleague was alerted to this conversation")
        elif name == "schedule_check_in":
            lines.append("- a follow-up was scheduled")
        elif name == "apply_offer":
            lines.append("- the offer was applied (its figures are facts above)")
        elif name == "raise_complaint":
            lines.append("- the complaint was logged for the team")
        elif name == "send_measurement_guide":
            lines.append("- the measurement guide was sent to them")
    return "\n".join(lines)


# "All sizes are the same price" — never said (owner, 2026-09-25: the collar's
# sizes are priced apart, 8-inch $3.50, 10-inch $4; the hub's placeholder made
# Neema say they were all $10). FALSE outright when the variants differ.
_SAME_PRICE_RE = re.compile(
    r"\b(?:all\s+(?:the\s+)?(?:sizes?|colou?rs?|variants?|options?|of\s+them)\s+(?:are|is|at|cost|come\s+at)?\s*"
    r"(?:the\s+)?same\s+price|same\s+price\s+(?:for|across|in)\s+(?:all|every|any)\s+(?:sizes?|colou?rs?|variants?|options?)|"
    r"regardless\s+of\s+(?:the\s+)?(?:size|colou?r)|(?:whatever|any)\s+(?:the\s+)?(?:size|colou?r)\s+(?:you|they)\s+(?:pick|choose|want)\b[^.]{0,30}same|"
    r"bei\s+(?:ni\s+)?(?:moja|sawa)\s+kwa\s+(?:saizi|rangi)\s+zote)",
    re.IGNORECASE)
# A range is SAID ("from $3.50 by size", "KES 12,000 to 15,000", "$4–$6") — a
# hyphen inside "10-inch" is not one.
_RANGE_RE = re.compile(
    r"\b(?:from|kuanzia|kutoka|between|up\s+to|starting\s+(?:at|from)|range|by\s+(?:size|colou?r))\b"
    r"|\d\s*(?:to|[–-])\s*(?:US\$|\$|USD|KES|KSH)?\s?\d",
    re.IGNORECASE)


def variants_of(row: dict | None) -> list[tuple[str, float | None, float | None]]:
    """(label, KES, USD) per DISTINCT variant of a hub row."""
    out: list[tuple[str, float | None, float | None]] = []
    seen: set = set()
    from app.core.variants import variant_label
    for v in (row or {}).get("variants") or []:
        label = str(v.get("label") or variant_label((row or {}).get("name"), v) or "")
        k, u = _num(v.get("price_kes") or v.get("price")), _num(v.get("price_usd"))
        key = (label.lower(), k, u)
        if key in seen:
            continue
        seen.add(key)
        out.append((label, k, u))
    return out


def variant_prices_differ(row: dict | None, currency: str = "USD") -> bool:
    vs = variants_of(row)
    col = 2 if (currency or "USD").upper() == "USD" else 1
    prices = {v[col] for v in vs if v[col]}
    if len(prices) <= 1:
        col = 1 if col == 2 else 2
        prices = {v[col] for v in vs if v[col]}
    return len(prices) > 1


def _label_tokens(label: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", (label or "").lower()))


def _distinctive(row: dict | None) -> list[tuple[str, set[str], float | None, float | None]]:
    """Each variant with the tokens that tell it from its siblings ("10" for
    '10 inch' when every label says 'inch'; 'navy' for a colour)."""
    vs = variants_of(row)
    if not vs:
        return []
    common = set.intersection(*[_label_tokens(lab) for lab, _k, _u in vs]) if len(vs) > 1 else set()
    out = []
    for label, k, u in vs:
        toks = _label_tokens(label) - common
        out.append((label, toks or _label_tokens(label), k, u))
    return out


def _variant_words(row: dict | None) -> set[str]:
    """The words that name a variant (sizes, colours) — '8', 'inch', 'navy'…"""
    words: set[str] = set()
    for label, _k, _u in variants_of(row):
        words |= _label_tokens(label)
    return words


def _mentions(text: str, toks: set[str]) -> bool:
    low = (text or "").lower()
    return bool(toks) and all(re.search(r"(?<![a-z0-9])" + re.escape(t) + r"(?![a-z0-9])", low) for t in toks)


def variant_issues(ask: str, answer: str, row: dict | None, currency: str = "USD") -> list[dict]:
    """The variant findings for the row the reply sells: the "same price for
    all" claim (hard when false), a named variant quoted at another
    variant's price (hard), one flat price for a product whose variants are
    priced apart (soft: say 'from … by size' or name the variant)."""
    out: list[dict] = []
    if not row or not variants_of(row):
        return out
    differ = variant_prices_differ(row, currency)
    if _SAME_PRICE_RE.search(answer or ""):
        out.append({"kind": "variants", "hard": differ,
                    "text": ("it says all sizes / colours are the same price — they are NOT: "
                             "this product's variants carry their own prices; quote the range "
                             "or the variant they choose" if differ else
                             "it says all sizes / colours are the same price — never say that: "
                             "ask which size / colour they want and quote that one")})
        return out
    figures = money_figures(answer)
    if not differ or not figures:
        return out
    dv = _distinctive(row)
    # the money figures are stripped first: the "10" in "$10" names no size
    bare_answer = _MONEY_RE.sub(" ", answer or "")
    bare_ask = _MONEY_RE.sub(" ", ask or "")
    in_answer = [v for v in dv if _mentions(bare_answer, v[1])]
    in_ask = [v for v in dv if _mentions(bare_ask, v[1])]
    target = in_answer[0] if len(in_answer) == 1 else (in_ask[0] if not in_answer and len(in_ask) == 1 else None)
    if target is not None:
        label, _t, k, u = target
        own = {x for x in (k, u) if x}
        if k:
            own.add(round(k / float(settings.usd_kes_rate or 100), 2))
        if u:
            own.add(round(u * float(settings.usd_kes_rate or 100), 2))
        if own and not any(_close(f, o) for f in figures for o in own):
            said = ", ".join(_fmt(f) for f in figures)
            out.append({"kind": "variants", "hard": True,
                        "text": f"the {label} variant is priced " + " / ".join(
                            x for x in ((f"KES {_fmt(k)}" if k else ""), (f"USD {_fmt(u)}" if u else "")) if x)
                        + f" — not {said}"})
        return out
    if not _RANGE_RE.search(answer or ""):
        out.append({"kind": "variants", "hard": False,
                    "text": "one flat price for a product whose sizes / colours are priced "
                            "apart — say 'from <the cheapest> by size' and ask which, or "
                            "quote the variant they named"})
    return out


def rule_findings(comment: str, answer: str, seen: list,
                  known_figures: set[float] | frozenset[float] = frozenset(), *,
                  tool_results: list | None = None, transcript: list | None = None,
                  known_text: str = "", fx: dict | None = None,
                  currency: str = "USD", mode: str = "dm") -> list[dict]:
    """The deterministic findings on a draft, each with its weight:
    {"kind", "text", "hard"}. HARD findings — a figure from nowhere, the
    wrong item priced, a link no tool gave, an order status with no source —
    are the ones that may hold a reply; SOFT ones ask for a rewrite and then
    stand aside (owner, 2026-09-25: "change from gating to double
    verifying" — a reply is corrected, not strangled)."""
    out: list[dict] = []
    # The facts: a tool's numbers, figures already said in this conversation,
    # and the customer's own figure in THIS message ("my budget is KES 15,000").
    facts = figures_in_results(tool_results) | transcript_figures(transcript) \
        | {round(v, 2) for v in money_figures(comment)}
    bad = unverified_figures(answer, seen, comment, known_figures, facts=facts, fx=fx,
                             currency=currency)
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
    # THE ITEM: every row the reply names is read against the ask; the finding
    # stands only when NONE of them fits ("the Golden Communion Tray is $220,
    # or the Silver at $180 if you prefer" offers what they asked). It is
    # HARD when the reply quotes money — the wrong item PRICED is the live
    # miss — and soft when it merely mentions a row.
    named_rows = products_named(answer, seen)
    if not named_rows:
        one = product_named(answer, seen)
        named_rows = [one] if one is not None else []
    conflicts = [item_issues(comment, r, answer) for r in named_rows]
    if named_rows and all(conflicts):
        for t in conflicts[0]:
            out.append({"kind": "item", "hard": bool(money_figures(answer)), "text": t})
    if where_unanswered(comment, answer):
        out.append({"kind": "where", "hard": False,
                    "text": "their question about where we are / a shop in their country is "
                    "unanswered — say Nairobi, Kenya, no shop there, DHL delivers to them"})
    links = foreign_links(answer, tool_results, known_text, transcript)
    if links:
        out.append({"kind": "link", "hard": True,
                    "text": "a link no tool gave: " + ", ".join(links[:3])
                    + " — only links a tool returned may be sent"})
    if status_without_source(answer, tool_results, transcript):
        out.append({"kind": "status", "hard": True,
                    "text": "an order-status claim (shipped / on its way / delivered) with no "
                    "check_order_status behind it — check the order, never assume"})
    sold = named_rows[0] if named_rows else None
    if sold is not None:
        out.extend(variant_issues(comment, answer, sold, currency))
    if mode != "comment":
        sent = cards_sent(tool_results)
        if _NO_PHOTOS_RE.search(answer or ""):
            out.append({"kind": "photos", "hard": bool(sent),
                        "text": (f"it says it cannot send photos — but {sent} photo card(s) were "
                                 "just SENT this turn: say 'here are the photos' and give the "
                                 "item's details" if sent else
                                 "it says it cannot send photos — it CAN, on this channel "
                                 "(send_product_cards): never say so; describe the item and "
                                 "its price, and the photos can follow")})
        elif not sent and _PHOTOS_SENT_RE.search(answer or ""):
            out.append({"kind": "photos", "hard": False,
                        "text": "it says photos were sent, but no photo card went out this turn"})
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
                             known_text=known_text, fx=fx, currency=currency, mode=mode)
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
    done = actions_text(tool_results)
    where = "posted under the comment" if mode == "comment" else "sent to the customer"
    photos_rule = ("" if mode == "comment" else
                   "You CAN send photos on this channel (send_product_cards did, or can): NEVER "
                   "write 'I can't send photos from here' — say 'here are the photos' when they "
                   "went out, else describe the item and its price and let the photos follow; ")
    return (
        f"[REVIEWER — your draft was HELD BACK before it was {where}. It failed "
        f"verification: {why}.\n\n"
        f"THE FACTS YOU MAY STATE (the hub's rows, in {currency}; nothing else is a price):\n"
        f"{rows_text(seen, currency)}\n"
        + (f"Other facts from this turn's tools:\n{other}\n" if other else "")
        + (f"WHAT THIS TURN ALREADY DID (refer to these as done — they will not run again):\n{done}\n"
           if done else "")
        + _fx_text(fx, comment)
        + f'\nYour held draft: "{" ".join((draft or "").split())[:900]}"\n\n'
        "Write the corrected reply NOW — the reply only, nothing else. Do not call a tool "
        "for this rewrite: everything listed above already happened, so speak of it as "
        "done. Rules: the item is exactly what they asked for (their finish, their kind — "
        "if we do not have it, say so plainly and offer the nearest from the rows "
        "above with its price); every figure is one of the facts above, in ONE "
        "currency (plus the one they asked for by name, at today's rate above, if "
        "any); answer every question they asked — and nothing they did not ask "
        "(where we are is Nairobi, Kenya; a shop in their country — none, DHL "
        "delivers — ONLY if they asked); never re-ask a detail they already gave; "
        "never invent a pack size, a capacity, an order status, a delivery time or "
        f"an exchange rate; never promise to 'confirm' a figure with the team; {photos_rule}"
        "keep the warmth and the closing question; write in their language.]"
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


_FEE_CONTEXT_RE = re.compile(
    r"delivery\s+(?:fee|charge|cost|is|:)|(?:fee|charge|cost)\s+(?:for|of)\s+delivery|if\s+delivery|"
    r"courier\s+(?:fee|charge)|postage|packaging\s+(?:fee|charge)|within\s+(?:nairobi|kenya)",
    re.IGNORECASE)


def prompt_figures(currency: str = "USD") -> frozenset[float]:
    """The money figures the owner's own instructions state ABOUT SHIPPING,
    DELIVERY AND FEES — a reply may repeat them without a hub row. Every
    currency block of the prompt is read ("KES 350 within Nairobi" is a
    fact whatever money this customer is quoted in), but an EXAMPLE price
    in the prompt ("'This gown is $130.'") is not a fact — the stress
    battery let "$130" through for a $120 cassock on its account."""
    key = "fees"
    if key not in _prompt_figures_cache:
        figs: set[float] = set()
        try:
            from app.agent.prompt import build_system_prompt
            from app.agent.runtime import _public_comment_addendum
            for ccy in ("KES", "USD", "ZMW"):
                text = build_system_prompt(currency=ccy) + _public_comment_addendum(ccy)
                for m in _MONEY_RE.finditer(text):
                    window = text[max(0, m.start() - 70): m.end() + 70]
                    if _FEE_CONTEXT_RE.search(window):
                        v = _num(m.group("a") or m.group("b"))
                        if v:
                            figs.add(v)
        except Exception:
            pass
        _prompt_figures_cache[key] = frozenset(figs)
    return _prompt_figures_cache[key]
