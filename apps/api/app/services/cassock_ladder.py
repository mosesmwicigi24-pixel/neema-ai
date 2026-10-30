"""The cassock ladder (owner, 2026-10-30).

A customer asking about "a product" under a red cassock was told "$210", then
"$170 for that variant" — two prices for one garment and no sight of the
sets. The owner: "I would prefer to have a clear indication of cassock set,
cassock, and complete cope and cassock set. We start for a cassock by saying
it's 13000, consider all other prices for different countries, then put a
follow-up post to say we have a cassock set which has a cassock, stole,
cincture belt, shirt and collar, and a cope cassock set which adds cope,
mitre and pectoral cross."

So a cassock is answered in two messages:
  1. Neema's own reply: the cassock's price, one figure, in their money;
  2. this follow-up, sent right after it: the Cassock Set and the Cope &
     Cassock Set, each with its hub price in the same money.

The follow-up is built here, not by the model: its prices are the hub rows'
own (the same display rule search_catalog quotes by), so the second message
can never contradict the first or the payment link. Once per customer a month
— a ladder repeated on every cassock question is noise.
"""
from __future__ import annotations

import logging
import re

from app.core.config import settings

_log = logging.getLogger("neema.ladder")

LADDER_TTL = 30 * 24 * 3600
_CASSOCK_RE = re.compile(r"\b(?:cassocks?|kasoki|soutanes?)\b", re.IGNORECASE)
_SET_RE = re.compile(r"\b(?:sets?|kit|full\s+outfit|complete)\b", re.IGNORECASE)


def _slugs() -> tuple[str, str]:
    raw = [s.strip() for s in (settings.cassock_ladder_slugs or "").split(",") if s.strip()]
    return (raw + ["", ""])[0], (raw + ["", ""])[1]


def _key(channel: str, contact: str) -> str:
    return f"ladder:cassock:{channel}:{contact}"


def is_single_cassock(row: dict | None) -> bool:
    """One cassock garment — never a set row (ours or the hub's)."""
    if not row:
        return False
    from app.services.post_catalog import is_set_row
    name = row.get("name") or ""
    if not _CASSOCK_RE.search(name) or _SET_RE.search(name) or is_set_row(row):
        return False
    return (row.get("slug") or "") not in _slugs()


def applies(seen: list[dict], user_text: str, reply: str) -> bool:
    """This turn priced a single cassock — and neither side is already
    talking about a set (a set ask is answered with the set, by the rules)."""
    from app.agent.review import money_figures
    if not reply or not _CASSOCK_RE.search(reply) or not money_figures(reply):
        return False
    if _SET_RE.search(reply) or _SET_RE.search(user_text or ""):
        return False
    return any(is_single_cassock(r) for r in (seen or []))


def message(catalog: list[dict], ctx, *, swahili: bool = False, bold: bool = True) -> str | None:
    """The follow-up, priced from the two hub rows in the customer's money.
    None when either row is missing or unpriced — never a ladder with a gap."""
    from app.agent.tools import _fmt_price, _to_display
    set_slug, cope_slug = _slugs()
    rows = {r.get("slug"): r for r in catalog or []}
    out = []
    for slug in (set_slug, cope_slug):
        row = rows.get(slug)
        if not row:
            return None
        v = _to_display(row.get("price_kes") or row.get("price"), ctx,
                        row.get("price_usd"), row.get("prices"))
        try:
            if v is None or float(v) <= 0:
                return None
        except (TypeError, ValueError):
            return None
        out.append(_fmt_price(v, getattr(ctx, "currency", "KES") or "KES"))
    set_price, cope_price = out
    text = _text(set_price, cope_price, swahili)
    # *bold* is WhatsApp's; Messenger and Instagram would show the asterisks.
    return text if bold else text.replace("*", "")


def _text(set_price: str, cope_price: str, swahili: bool) -> str:
    if swahili:
        return ("Pia unaweza kuichukua kama seti kamili:\n"
                f"• *Cassock Set — {set_price}:* kasoki pamoja na stola, mkanda (cincture "
                "belt), shati la kiaskofu na kola — tayari kwa ibada.\n"
                f"• *Cope & Cassock Set — {cope_price}:* Cassock Set nzima pamoja na kepu "
                "(cope), kofia ya askofu (mitre) na msalaba wa kifuani (pectoral cross).\n"
                "Ungependa ipi — kasoki peke yake, Cassock Set, au Cope & Cassock Set? "
                "Niambie rangi yako nianze oda yako.")
    return ("You can also take it as a complete set:\n"
            f"• *Cassock Set — {set_price}:* the cassock with a stole, cincture belt, clergy "
            "shirt and collar, ready for service.\n"
            f"• *Cope & Cassock Set — {cope_price}:* the full Cassock Set plus the cope, mitre "
            "and pectoral cross.\n"
            "Which would you like: the cassock alone, the Cassock Set, or the Cope & Cassock "
            "Set? Tell me your colour and I'll start your order.")


async def follow_up(redis, *, channel: str, contact: str, catalog: list[dict], ctx,
                    user_text: str, reply: str) -> str | None:
    """The second message for this turn, or None. Claims the month's slot only
    when there is a message to send."""
    if not settings.cassock_ladder or not applies(getattr(ctx, "seen_products", []) or [],
                                                  user_text, reply):
        return None
    from app.agent.voice import looks_swahili
    text = message(catalog, ctx, swahili=looks_swahili(user_text or ""),
                   bold=(channel == "whatsapp" and not str(contact).startswith("web_")))
    if not text:
        return None
    if redis is not None:
        try:
            if not await redis.set(_key(channel, contact), "1", ex=LADDER_TTL, nx=True):
                return None
        except Exception:
            pass
    return text
