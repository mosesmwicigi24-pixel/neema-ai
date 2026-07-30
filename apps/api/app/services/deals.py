"""The deal scribe — rules-first bookkeeping after every agent turn.

The selling prompt is never burdened with filing: after Neema replies, this
scribe updates the conversation's ONE open deal from hard artifacts:
  · items_snapshot + title ← the live person-scoped cart
  · stage ← derived (cart → qualified; order pending → proposal; paid → won,
    stamped by the Phase A event hook)
  · blocking + next_action ← Neema's own promises in the reply ("let me
    check/confirm and get back") become a 3-hour AI follow-up commitment —
    the seed Phase B2's scheduler will execute.

Best-effort everywhere: scribe failures never touch the customer reply.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

_log = logging.getLogger("neema.deals")

# Neema's own "I owe you an answer" phrasings — her promise creates the
# commitment. Conservative on purpose: false positives nag customers.
_PROMISE_RE = re.compile(
    r"\b(i(?:'| wi)ll (?:check|confirm|find out|enquire|inquire|verify|ask)"
    r"(?:[^.!\n]{0,80}?)(?:get back|revert|let you know|update you)?"
    r"|let me (?:check|confirm|find out|enquire|verify)[^.!\n]{0,80})",
    re.IGNORECASE)

PROMISE_FOLLOW_UP_HOURS = 3


def detect_own_promise(reply: str) -> str | None:
    """The promise sentence when Neema committed to come back with something."""
    m = _PROMISE_RE.search(reply or "")
    return m.group(0).strip() if m else None


def derive_stage(cart_items: int, current: str) -> str:
    """Forward-only derivation (won/lost are terminal; operator edits win)."""
    if current in ("won", "lost", "proposal"):
        return current
    if cart_items > 0:
        return "qualified"
    return current or "new"


async def open_deal_for(db, conversation_id=None, person_id=None):
    from app.models.deal import Deal
    q = select(Deal).where(Deal.status == "open")
    if conversation_id is not None:
        q = q.where(Deal.conversation_id == conversation_id)
    elif person_id is not None:
        q = q.where(Deal.person_id == person_id)
    else:
        return None
    return (await db.execute(q.order_by(Deal.updated_at.desc()).limit(1))
            ).scalar_one_or_none()


async def guidance_for(db, key: str, channel: str) -> str:
    """Per-deal operator guidance for the prompt — '' when none."""
    try:
        conv = await _conversation_of(db, key, channel)
        if conv is None:
            return ""
        deal = await open_deal_for(db, conversation_id=conv.id)
        g = (deal.guidance or "").strip() if deal else ""
        return g[:400]
    except Exception:
        return ""


async def _conversation_of(db, key: str, channel: str):
    from app.models.conversation import Conversation
    if channel == "whatsapp":
        return (await db.execute(select(Conversation).where(
            Conversation.wa_id == key))).scalar_one_or_none()
    return (await db.execute(select(Conversation).where(
        Conversation.channel == channel,
        Conversation.external_id == key))).scalar_one_or_none()


async def scribe_update(db, key: str, channel: str, reply: str) -> None:
    """File the turn: cart → items/title/stage, promise → blocking/next_action.
    Creates the deal on first buying signal (a cart or a promise); silent
    otherwise — greetings don't deserve deal rows."""
    try:
        from app.agent import cart as cartmod
        from app.models.deal import Deal

        conv = await _conversation_of(db, key, channel)
        if conv is None:
            return

        cart = await cartmod.get_cart(db, key, channel=channel)
        items = list((cart or {}).get("items") or [])
        promise = detect_own_promise(reply)

        deal = await open_deal_for(db, conversation_id=conv.id)
        if deal is None:
            if not items and not promise:
                return                      # nothing worth owning yet
            deal = Deal(conversation_id=conv.id, person_id=conv.person_id)
            db.add(deal)

        if items:
            deal.items_snapshot = [
                {"name": i.get("name"), "qty": i.get("qty") or i.get("quantity") or 1,
                 "price": i.get("price")} for i in items][:20]
            names = [str(i.get("name") or "") for i in items if i.get("name")]
            deal.title = (", ".join(names)[:290]) or deal.title
        deal.stage = derive_stage(len(items), deal.stage or "new")

        if promise:
            deal.blocking = f"Neema owes the customer: {promise[:200]}"
            deal.next_action = {
                "kind": "follow_up", "owner": "ai",
                "due_at": (datetime.now(timezone.utc)
                           + timedelta(hours=PROMISE_FOLLOW_UP_HOURS)).isoformat(),
                "note": promise[:200],
            }
        await db.commit()
    except Exception as exc:
        _log.info("deal scribe skipped for %s: %s", key, exc)
        try:
            await db.rollback()
        except Exception:
            pass


async def mark_won_for_conversation(db, conversation_id) -> None:
    """Phase A hookup: a paid order closes the conversation's open deal as won."""
    try:
        deal = await open_deal_for(db, conversation_id=conversation_id)
        if deal is not None:
            deal.stage = "won"
            deal.status = "won"
            deal.blocking = None
            deal.next_action = None
            await db.commit()
    except Exception:
        try:
            await db.rollback()
        except Exception:
            pass
