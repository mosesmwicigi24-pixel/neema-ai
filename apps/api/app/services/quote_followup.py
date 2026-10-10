"""Quote → follow-up: the price Neema gave, and then silence.

30 days of evidence (2026-10-10): 1,582 conversations went quiet right after
Neema quoted a price, and only 8% ever heard from her again — the deal scribe
planned a follow-up only when Neema promised something or the customer named
a time. An unanswered quote planned nothing. Follow-ups that WERE sent got a
reply within 72 h 39% of the time.

This module plans ONE follow-up per deal when a turn's reply quoted a stock
item at a price taken from that turn's own catalogue results, and the
customer then says nothing:

  · timed ~4 h after the quote, moved out of quiet hours (20:00–08:00
    Nairobi), and never planned when that lands outside Meta's 24-hour
    customer-service window (with an hour's margin) — no template, no nag;
  · the text is composed HERE, in code, from the quoted rows — the item
    names and figures of the quote, in its currency, nothing else — and ends
    with one question that moves to the order ("Shall I reserve it?"),
    Swahili + English when the customer wrote Swahili;
  · cancelled when the customer replies first (scribe time AND send time),
    never planned for a human-held thread, never when an order was placed,
    never stacked: one pending action per deal (a newer quote replaces the
    older one; a promise-based follow-up is never overridden by it).

Rides the existing actions pipeline (services/actions.py): the 60 s leader-
locked loop sends it when AGENT_INITIATIVE is on and the sensitivity gate
passes, otherwise it waits visibly for a human tap. QUOTE_FOLLOW_UP_ENABLED
switches the planning off without a deploy.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone

from sqlalchemy import func as sa_func, or_, select

from app.core import money

_log = logging.getLogger("neema.deals")

QUOTE_KIND = "quote_follow_up"
QUOTE_FOLLOW_UP_HOURS = 4
WINDOW_HOURS = 24
# Never land in the last hour of the window — the send may take a tick or two.
WINDOW_MARGIN = timedelta(hours=1)
CHANNELS = ("whatsapp", "messenger", "instagram")
MAX_ITEMS = 3

# A figure the reply SAYS as money: "KES 7,000", "Ksh 7000", "$70", "$4.50",
# "7,000/=", "7000 shillings". Bare numbers ("2 trays", "size 42") are not quotes.
_MONEY_RE = re.compile(
    r"(?:\b(?:kes|kshs?|ksh\.|sh|usd|zmw)\.?\s*|\$\s*)(\d[\d,]*(?:\.\d+)?)"
    r"|(\d[\d,]*(?:\.\d+)?)\s*(?:/=|\b(?:kes|kshs?|shillings?|bob|usd|dollars?|zmw)\b)",
    re.IGNORECASE)


def _reply_figures(reply: str) -> list[float]:
    out = []
    for m in _MONEY_RE.finditer(reply or ""):
        raw = (m.group(1) or m.group(2) or "").replace(",", "")
        try:
            out.append(float(raw))
        except ValueError:
            pass
    return out


def _positive(v) -> float | None:
    x = money.exact(v)
    return float(x) if isinstance(x, (int, float)) and x > 0 else None


def extract_quote(tools: list | None, reply: str) -> list[dict]:
    """[{name, price, currency}] — the stock items this turn's reply priced.

    Ground truth is the turn's own `search_catalog` results: a row counts only
    when it is a stock item (not made to order), a full match (not a partial
    one the model was told to confirm first), carries a positive price, and
    that exact figure appears in the reply AS MONEY. Variants count by their
    own price; a played offer by its offer price. Nothing is ever inferred
    from the reply alone — no figure here was not in a tool result."""
    said = _reply_figures(reply)
    if not said or not tools:
        return []
    out: list[dict] = []
    seen: set[str] = set()

    def said_it(price: float) -> bool:
        return any(abs(price - f) < 0.005 for f in said)

    for entry in tools:
        if not isinstance(entry, dict) or entry.get("tool") != "search_catalog":
            continue
        res = entry.get("out")
        if not isinstance(res, dict):
            continue
        for row in res.get("results") or []:
            if not isinstance(row, dict) or row.get("made_to_order") or row.get("match") == "partial":
                continue
            name = " ".join(str(row.get("name") or "").split())[:80]
            ccy = str(row.get("currency") or res.get("currency") or "").upper()
            if not name or not ccy:
                continue
            candidates: list[tuple[str, float | None]] = [(name, _positive(row.get("price")))]
            offer = row.get("offer_available")
            if isinstance(offer, dict):
                candidates.append((name, _positive(offer.get("offer_price"))))
            for v in row.get("variants") or []:
                if isinstance(v, dict) and v.get("label"):
                    vname = f"{name} ({' '.join(str(v['label']).split())[:40]})"
                    candidates.append((vname, _positive(v.get("price"))))
                    if v.get("offer_price") is not None:
                        candidates.append((vname, _positive(v.get("offer_price"))))
            for label, price in candidates:
                if price is None or not said_it(price) or label.lower() in seen:
                    continue
                seen.add(label.lower())
                out.append({"name": label, "price": money.exact(price), "currency": ccy})
                break                                  # one line per catalogue row
    return out[:MAX_ITEMS]


def _join(parts: list[str], word: str) -> str:
    if len(parts) <= 1:
        return "".join(parts)
    return ", ".join(parts[:-1]) + f" {word} " + parts[-1]


def compose(quote: list[dict], *, name: str | None = None, swahili: bool = False) -> str:
    """The follow-up, composed from the quote and nothing else.

    Short, warm, names the item(s) at the price(s) already given — same
    currency, the figures untouched — and ends with ONE question that moves
    to the order. Swahili first, then the English, when they wrote Swahili."""
    items = [q for q in quote if q.get("name") and q.get("price") is not None][:MAX_ITEMS]
    if not items:
        return ""
    hi = f" {name}" if name else ""
    it = "it" if len(items) == 1 else "them"
    en_items = _join([f"the {q['name']} at {money.fmt(q['price'], q['currency'])}"
                      for q in items], "and")
    if not swahili:
        return (f"Hi{hi} 🙏 Just following up on {en_items} I shared earlier. "
                f"Shall I reserve {it} for you?")
    sw_items = _join([f"{q['name']} kwa {money.fmt(q['price'], q['currency'])}"
                      for q in items], "na")
    return (f"Habari{hi} 🙏 Nafuatilia tu bei niliyokutajia: {sw_items}. Nikuwekee?\n"
            f"(Just following up on {en_items} — shall I reserve {it} for you?)")


def reason_for(quote: list[dict]) -> str:
    what = "; ".join(f"{q['name']} {money.fmt(q['price'], q['currency'])}" for q in quote)
    return f"Quote follow-up: Neema quoted {what} and the customer has not replied"[:500]


def plan_due(last_inbound: datetime | None, now: datetime,
             hours: float = QUOTE_FOLLOW_UP_HOURS) -> datetime | None:
    """When to follow up — or None when no good moment exists inside the
    24-hour window (never planned to land after it closes)."""
    from app.services.hub_events import is_quiet_hours, next_morning_utc
    if last_inbound is None:
        return None
    if last_inbound.tzinfo is None:
        last_inbound = last_inbound.replace(tzinfo=timezone.utc)
    due = now + timedelta(hours=hours)
    if is_quiet_hours(due):
        due = next_morning_utc(due)
    if due > last_inbound + timedelta(hours=WINDOW_HOURS) - WINDOW_MARGIN:
        return None
    return due


def first_name(display_name: str | None) -> str | None:
    tok = ((display_name or "").strip().split() or [""])[0]
    return tok if 2 <= len(tok) <= 20 and tok.isalpha() else None


async def order_placed_recently(db, conv, now: datetime, hours: int = WINDOW_HOURS) -> bool:
    from app.models.order_event import OrderEvent
    conds = []
    if getattr(conv, "person_id", None) is not None:
        conds.append(OrderEvent.person_id == conv.person_id)
    if conv.channel == "whatsapp" and conv.wa_id:
        conds.append(OrderEvent.wa_id == conv.wa_id)
    if not conds:
        return False
    n = (await db.execute(select(sa_func.count()).select_from(OrderEvent).where(
        or_(*conds), OrderEvent.created_at >= now - timedelta(hours=hours)))).scalar_one()
    return bool(n)


def _ordered_this_turn(tools: list | None) -> bool:
    for e in tools or []:
        if isinstance(e, dict) and e.get("tool") == "create_order":
            out = e.get("out")
            if isinstance(out, dict) and not out.get("error"):
                return True
    return False


async def customer_replied_since(db, conv, since: datetime) -> bool:
    from app.models.message import Message, MsgDirection
    n = (await db.execute(select(sa_func.count()).select_from(Message).where(
        Message.conversation_id == conv.id,
        Message.direction == MsgDirection.inbound,
        Message.created_at > since))).scalar_one()
    return bool(n)


def _reachable(conv) -> bool:
    if conv.channel not in CHANNELS:
        return False
    if conv.channel == "whatsapp":
        from app.core.phone import is_plausible_phone
        return bool(conv.wa_id) and is_plausible_phone(conv.wa_id)
    return bool(conv.external_id)


async def _pending(db, deal_id):
    from app.models.agent_action import AgentAction
    return (await db.execute(select(AgentAction).where(
        AgentAction.deal_id == deal_id,
        AgentAction.status.in_(("planned", "needs_approval"))))).scalars().all()


async def cancel_pending(db, deal, why: str) -> int:
    """Veto the deal's pending quote follow-up(s) — the customer spoke."""
    n = 0
    for row in await _pending(db, deal.id):
        if row.kind == QUOTE_KIND:
            row.status = "vetoed"
            row.reason = f"{row.reason or ''} [{why}]"[:1000]
            n += 1
    return n


async def on_turn(db, conv, deal, *, quote: list[dict], inbound_text: str,
                  tools: list | None, reply: str = "",
                  now: datetime | None = None) -> str:
    """File a turn's quote. Returns what happened (for logs and tests):
    'planned' or the reason nothing was planned. Never commits — the scribe
    owns the transaction."""
    from app.core.config import settings
    from app.models.agent_action import AgentAction
    from app.models.conversation import InterceptMode
    from app.services.hub_events import _last_inbound_at
    now = now or datetime.now(timezone.utc)
    # The customer spoke: an older quote's nudge is answered by this turn.
    if (inbound_text or "").strip():
        await cancel_pending(db, deal, "customer replied")
    if not quote:
        return "no quote"
    if not settings.quote_follow_up_enabled:
        return "disabled"
    if conv.intercept_mode != InterceptMode.ai:
        return "thread not in AI mode"
    if not _reachable(conv):
        return "channel not reachable"
    if deal.status != "open" or (deal.stage or "") in ("won", "proposal"):
        return "deal settled"
    if _ordered_this_turn(tools) or await order_placed_recently(db, conv, now):
        return "order placed"
    pending = [r for r in await _pending(db, deal.id) if r.kind != QUOTE_KIND]
    if pending:
        return "another follow-up already pending"
    due = plan_due(await _last_inbound_at(db, conv), now)
    if due is None:
        return "no moment left inside the 24h window"
    # A newer quote replaces the older nudge: one pending per deal, and its
    # created_at is THIS quote (the send-time "did they reply since?" check).
    await cancel_pending(db, deal, "superseded by a newer quote")
    name = None
    if conv.person_id is not None:
        from app.models.person import Person
        person = await db.get(Person, conv.person_id)
        name = first_name(getattr(person, "display_name", None))
    from app.agent.voice import looks_swahili
    swahili = looks_swahili(inbound_text) or looks_swahili(reply)
    db.add(AgentAction(deal_id=deal.id, conversation_id=conv.id, due_at=due,
                       kind=QUOTE_KIND, reason=reason_for(quote),
                       draft=compose(quote, name=name, swahili=swahili)))
    return "planned"


async def stale_reason(db, conv, action, *, in_window: bool,
                       now: datetime | None = None) -> str | None:
    """At send time: why this quote follow-up must NOT go (it is vetoed,
    not parked) — None when it still stands."""
    from app.models.conversation import InterceptMode
    now = now or datetime.now(timezone.utc)
    if conv.intercept_mode != InterceptMode.ai:
        return "thread is not in AI mode"
    created = action.created_at
    if created is not None and created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    if created is not None and await customer_replied_since(db, conv, created):
        return "customer replied"
    if await order_placed_recently(db, conv, now):
        return "order placed"
    if not in_window:
        return "24h window closed"
    if not (action.draft or "").strip():
        return "no composed text"
    return None
