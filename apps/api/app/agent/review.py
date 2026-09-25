"""THE GATE BEFORE POSTING (owner, 2026-09-25).

Live, under one communion post: "How much are gold trays with holes to place
tot glasses? Do you have shops in South Africa?" was answered with the silver
set at $180 and no word about South Africa; "Where is your location, do you
have some holycommunion cups" was answered with the Golden Chalice Cup with
Paten Set at $650 and no location. The owner: "Someone is asking for golden
trays and you give silver… Put a gate to review before posting accurate
information to avoid on the fly mistakes… Every post should be verified before
posting for accuracy and correct figures."

This module is that gate. Every PUBLIC reply passes it before it posts:

1. THE RULES (deterministic, always on):
   - every money figure in the reply is a hub price of a row the turn looked
     up (`search_catalog` results), its conversion at the house rate, a
     quantity multiple of one, a half (a deposit), or a figure the owner's
     own instructions state (shipping) — anything else is a figure from
     nowhere and fails;
   - the item the reply names is the item they asked for: the FINISH they
     asked (gold is not silver, glass is not plastic) and the KIND (communion
     cups are the small cups the tray holds — plastic, silver, glass,
     pre-packed — never a chalice; a chalice only when they say chalice; a
     tray is not cups).
2. THE REVIEWER (one light-model line, switchable): reads the comment, the
   hub rows looked up, the post's product and the draft, and fails a wrong
   item, a wrong figure or a question left unanswered.

A draft that fails is written once more with the reviewer's notes in hand;
a second failure never posts: the customer gets an honest holding line in
the thread and a colleague gets the comment with the reviewer's reasons.
"""
from __future__ import annotations

import logging
import re

from app.core.config import settings

_log = logging.getLogger("neema.review")

# ── money figures ────────────────────────────────────────────────────────────

_MONEY_RE = re.compile(
    r"(?:(?:US\$|\$|USD|KES|KSHS?|ZMW|ZK)\s?(?P<a>\d[\d,]*(?:\.\d+)?))"
    r"|(?:(?P<b>\d[\d,]*(?:\.\d+)?)\s?(?:(?:USD|KES|KSHS?|ZMW|dollars?|shillings?|bob)\b|/=))",
    re.IGNORECASE)


def _num(v) -> float | None:
    try:
        f = float(str(v).replace(",", ""))
    except (TypeError, ValueError):
        return None
    return f if f > 0 else None


def money_figures(text: str) -> list[float]:
    """Every amount stated as MONEY in the text — a currency mark before or
    after it ($40, USD 40, KES 19,000, Ksh 500, 500/=, 40 dollars). A bare
    number ("40 cups") is a count, not a price."""
    out: list[float] = []
    for m in _MONEY_RE.finditer(text or ""):
        v = _num(m.group("a") or m.group("b"))
        if v is not None and v not in out:
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


def _close(a: float, b: float) -> bool:
    return abs(a - b) <= max(0.011, 0.005 * abs(b))


def unverified_figures(answer: str, seen: list, comment: str = "",
                       known_figures: set[float] | frozenset[float] = frozenset()) -> list[float]:
    """The money figures in the reply that NO looked-up hub row explains —
    not a row's price, not its conversion, not a quantity multiple of one
    (the comment's or the reply's own counts), not a half of one (a
    deposit), not a figure the owner's instructions state."""
    figures = money_figures(answer)
    if not figures:
        return []
    base: set[float] = set()
    for p in seen or []:
        base |= _row_figures(p)
    allowed: set[float] = set(base) | set(known_figures or ())
    qs = quantities(comment) + quantities(answer)
    for b in base:
        allowed.add(round(b / 2, 2))
        for q in qs:
            allowed.add(round(b * q, 2))
    bad = []
    for f in figures:
        if not any(_close(f, a) for a in allowed):
            bad.append(f)
    return bad


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


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z]+", (text or "").lower())


_TOT_GLASSES_RE = re.compile(r"\btots?\s+glass(?:es)?\b", re.IGNORECASE)


def finishes_of(text: str) -> set[str]:
    # "tot glasses" are the small cups, not a glass finish
    return {_FINISH_WORD[w] for w in _words(_TOT_GLASSES_RE.sub(" cups ", text or ""))
            if w in _FINISH_WORD}


def kinds_of(text: str) -> set[str]:
    return {_KIND_WORD[w] for w in _words(text) if w in _KIND_WORD}


def item_issues(ask: str, product: dict | None) -> list[str]:
    """Why this hub row is NOT what the comment asked for — a different
    finish, a chalice for cups (or cups for a chalice), cups for a tray.
    Empty when the row fits or the comment names no finish and no kind."""
    name = str((product or {}).get("name") or "")
    if not name or not (ask or "").strip():
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
    r"\b(?:where\s+(?:are|is|r)\s+(?:you|your|u|the\s+shop)|your\s+location|location\s*\?|"
    r"located|based\s+in|(?:shops?|stores?|branch(?:es)?|outlets?|offices?)\s+in\s+[A-Za-z]|"
    r"in\s+(?:south\s+africa|nigeria|zambia|uganda|tanzania|ghana|zimbabwe|botswana|malawi|"
    r"rwanda|usa|america|uk|london|kenya|nairobi)\s*\??\s*$|mko\s+wapi|uko\s+wapi|"
    r"duka\s+(?:lenu|lako)\s+liko)",
    re.IGNORECASE)
_WHERE_ANSWER_RE = re.compile(
    r"\b(?:nairobi|kenya|dhl|deliver|delivery|ship|shipping|courier|located|based|"
    r"branch|shop\s+in|no\s+shop|our\s+shop|workshop|tuko|tunapeleka|tunasafirisha)\b",
    re.IGNORECASE)


def where_unanswered(comment: str, answer: str) -> bool:
    return bool(_WHERE_ASK_RE.search(comment or "")) and not _WHERE_ANSWER_RE.search(answer or "")


def rule_issues(comment: str, answer: str, seen: list,
                known_figures: set[float] | frozenset[float] = frozenset()) -> list[str]:
    """The deterministic verdict on a draft: figures from nowhere, the wrong
    item for the ask. Empty = the rules pass it (the reviewer may still not)."""
    issues: list[str] = []
    bad = unverified_figures(answer, seen, comment, known_figures)
    if bad:
        looked = ", ".join(f"{p.get('name')} (KES {p.get('price')} / USD {p.get('price_usd')})"
                           for p in (seen or [])[:6]) or "no hub row was looked up"
        issues.append("unverified figure(s) " + ", ".join(_fmt(f) for f in bad)
                      + " — not the hub price of any row looked up this turn: " + looked)
    named = product_named(answer, seen)
    if named is not None:
        issues.extend(item_issues(comment, named))
    if where_unanswered(comment, answer):
        issues.append("their question about where we are / a shop in their country is "
                      "unanswered — say Nairobi, Kenya, no shop there, DHL delivers to them")
    return issues


def _fmt(f: float) -> str:
    return f"{int(f):,}" if float(f).is_integer() else f"{f:,.2f}"


# ── the reviewer ─────────────────────────────────────────────────────────────

_VERDICT_RE = re.compile(r"verdict\s*=\s*(pass|fail)", re.IGNORECASE)
_ISSUES_RE = re.compile(r"issues\s*=\s*(.*)$", re.IGNORECASE | re.DOTALL)


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


def _rows_text(seen: list, currency: str) -> str:
    lines = []
    for p in (seen or [])[:8]:
        price = p.get("price_usd") if currency == "USD" else p.get("price")
        unit = "USD" if currency == "USD" else "KES"
        d = " ".join(str(p.get("description") or "").split())[:140]
        lines.append(f"- {p.get('name')} — {unit} {price}" + (f" — {d}" if d else ""))
    return "\n".join(lines) or "- (none — the draft looked nothing up)"


async def reviewer_verdict(comment: str, answer: str, seen: list, *,
                           post_product: str = "", currency: str = "USD",
                           redis=None) -> dict | None:
    """One light-model line on the draft. None when the reviewer is off, the
    budget is stopped, or the model fails — the rules' verdict then stands."""
    if not settings.comment_reply_review:
        return None
    try:
        from app.services import ai_budget
        if redis is not None and await ai_budget.mode(redis) == "stop":
            return None
    except Exception:
        pass
    prompt = (
        "You are the REVIEWER at a Christian clergy and communion store. A colleague "
        "drafted a PUBLIC reply to a customer's comment. Check it against the hub rows "
        "below and answer on ONE line in exactly this shape:\n"
        "verdict=<pass|fail> | issues=<the problems, separated by ';', or ->\n\n"
        "FAIL when any of these is true:\n"
        "1. WRONG ITEM — the reply names or prices something other than what they asked "
        "for: a different finish (they asked GOLD, it gives SILVER), a different kind "
        "(they asked communion CUPS — the small cups a tray holds — and it gives a "
        "CHALICE; they asked a TRAY and it gives cups), or a product they never asked "
        "about. A reply that says plainly we do not have the exact one and offers the "
        "nearest at its hub price PASSES.\n"
        "2. WRONG FIGURE — a price that is not the hub price of that row in the currency "
        "shown, or an invented pack size, capacity, colour, material or delivery time.\n"
        "3. UNANSWERED — a question in the comment gets no answer: where we are (Nairobi, "
        "Kenya), whether we have a shop in their country, delivery to them, a price they "
        "asked for.\n"
        "PASS otherwise. Never fail for tone, warmth, length or emoji.\n\n"
        f"The post is about: {post_product or 'unknown'}\n"
        f"Hub rows the colleague looked up ({currency}):\n{_rows_text(seen, currency)}\n"
        f'Customer\'s comment: "{" ".join((comment or "").split())[:400]}"\n'
        f'Draft reply: "{" ".join((answer or "").split())[:900]}"\n'
        "Answer with the one line only."
    )
    try:
        from app.agent.runtime import build_llm
        llm = build_llm(model=settings.tier2_model_light)
        resp = await llm.complete(
            system="You verify a shop's replies before they post. One line only, in the shape asked.",
            messages=[{"role": "user", "content": prompt}], tools=[])
        return parse_verdict(resp.text or "")
    except Exception as exc:
        _log.info("reply reviewer unavailable: %s", exc)
        return None


async def review_reply(comment: str, answer: str, seen: list, *,
                       post_product: str = "", currency: str = "USD",
                       known_figures: set[float] | frozenset[float] = frozenset(),
                       redis=None) -> dict:
    """The gate's verdict on one draft: {"ok", "issues", "by"}. The rules
    first (a rule failure is final for this draft); then the reviewer."""
    issues = rule_issues(comment, answer, seen, known_figures)
    if issues:
        return {"ok": False, "issues": issues, "by": "rules"}
    v = await reviewer_verdict(comment, answer, seen, post_product=post_product,
                               currency=currency, redis=redis)
    if v is None:
        return {"ok": True, "issues": [], "by": "rules"}
    if v["ok"]:
        return {"ok": True, "issues": [], "by": "reviewer"}
    return {"ok": False, "issues": v["issues"] or ["the reviewer rejected the draft"],
            "by": "reviewer"}


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
