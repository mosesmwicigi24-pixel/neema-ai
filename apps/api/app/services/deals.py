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

# The CUSTOMER's stated timeline ("I'll confirm after the church meeting") —
# needs BOTH a commitment verb and a time hint, or we'd nag over pleasantries.
_CUSTOMER_PROMISE_RE = re.compile(
    r"\b(?:i(?:'ll| will)|we(?:'ll| will)|nita|tuta)\s?"
    r"(?:confirm|get back|let you know|revert|respond|reply|check|decide|send|pay"
    r"|need|order|buy|take)",
    re.IGNORECASE)
_TIME_HINT_RE = re.compile(
    r"\b(tomorrow|kesho|tonight|this evening|later today|"
    r"after (?:the |our )?(?:meeting|service|church|committee)|"
    r"next week|weekend|monday|tuesday|wednesday|thursday|friday|saturday|sunday|"
    # Replenishment timelines ("we'll need them in two weeks", "wiki mbili")
    r"in (?:a|one|two|three|1|2|3) weeks?|after (?:a|one|two|three|1|2|3) weeks?|"
    r"wiki (?:moja|mbili|tatu)|in (?:a|one|1) month|next month|end (?:of )?month|month end)\b",
    re.IGNORECASE)
_WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday",
             "saturday", "sunday")


def detect_own_promise(reply: str) -> str | None:
    """The promise sentence when Neema committed to come back with something."""
    m = _PROMISE_RE.search(reply or "")
    return m.group(0).strip() if m else None


def next_weekday_nbo(day_name: str, now_nbo: datetime) -> datetime:
    """The NEXT occurrence of a named weekday, computed from the day of speech
    (owner rule): "Sunday" said ON a Sunday means next week's Sunday, said on a
    Friday means in two days. Never a past day, never today."""
    days = (_WEEKDAYS.index(day_name.lower()) - now_nbo.weekday()) % 7 or 7
    return now_nbo + timedelta(days=days)


def detect_customer_promise(text: str, *, now: datetime | None = None) -> tuple[datetime, str] | None:
    """(due_at_utc, the hint) when the CUSTOMER named a timeline.

    Time maths (owner rule, 2026-08-13): a NAMED DAY is anchored to the day
    they said it, and the check-in lands ON that day — in the EVENING (18:00
    Nairobi), after the church service / committee / group they were waiting
    on — matching what Neema tells them ("I'll check in with you on Sunday").
    A weekday beats a vaguer hint in the same sentence: "I'll confirm after
    church on Sunday" schedules for Sunday, not tomorrow. Un-dayed hints keep
    the morning-after shape — never before their moment."""
    t = text or ""
    if not (_CUSTOMER_PROMISE_RE.search(t) and (m := _TIME_HINT_RE.search(t))):
        return None
    hint = m.group(1).lower()
    now_utc = now or datetime.now(timezone.utc)
    now_nbo = now_utc + timedelta(hours=3)
    # The most specific anchor wins: a weekday named ANYWHERE in the message
    # overrides a leftmost vaguer hint ("after church on Sunday" → Sunday).
    wd = re.search(r"\b(?<!last )(" + "|".join(_WEEKDAYS) + r")\b", t, re.IGNORECASE)
    if wd and hint not in _WEEKDAYS:
        hint = wd.group(1).lower()

    def _at(base, hour):
        return base.replace(hour=hour, minute=0, second=0, microsecond=0)

    _wk = {"a": 1, "one": 1, "1": 1, "moja": 1, "two": 2, "2": 2, "mbili": 2,
           "three": 3, "3": 3, "tatu": 3}
    weeks = re.match(r"(?:in|after|wiki)\s+(\w+)\s*weeks?|wiki\s+(\w+)", hint)
    if hint in ("later today", "tonight", "this evening"):
        due_nbo = _at(now_nbo, 18) if now_nbo.hour < 18 else now_nbo + timedelta(hours=3)
    elif weeks and _wk.get(weeks.group(1) or weeks.group(2)):
        due_nbo = _at(now_nbo + timedelta(days=7 * _wk[weeks.group(1) or weeks.group(2)]), 10)
    elif hint in ("in a month", "in one month", "in 1 month", "next month",
                  "end month", "month end", "end of month"):
        due_nbo = _at(now_nbo + timedelta(days=30), 10)
    elif hint == "next week":
        due_nbo = _at(now_nbo + timedelta(days=7), 10)
    elif hint == "weekend":
        days = (5 - now_nbo.weekday()) % 7 or 7        # next Saturday
        due_nbo = _at(now_nbo + timedelta(days=days), 10)
    elif hint in _WEEKDAYS:
        # ON their named day, evening — after the service/meeting they cited,
        # and the same day Neema promises in her reply.
        due_nbo = _at(next_weekday_nbo(hint, now_nbo), 18)
    else:                                              # tomorrow / kesho / after the meeting
        due_nbo = _at(now_nbo + timedelta(days=1), 10)
    return due_nbo - timedelta(hours=3), hint


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


async def scribe_update(db, key: str, channel: str, reply: str,
                        inbound_text: str = "") -> None:
    """File the turn: cart → items/title/stage, promises (Neema's own AND the
    customer's stated timeline) → blocking/next_action + a planned-action row
    the B2 scheduler executes. Creates the deal on first buying signal; silent
    otherwise — greetings don't deserve deal rows."""
    try:
        from app.agent import cart as cartmod
        from app.models.deal import Deal
        from app.services.actions import upsert_follow_up

        conv = await _conversation_of(db, key, channel)
        if conv is None:
            return

        cart = await cartmod.get_cart(db, key, channel=channel)
        items = list((cart or {}).get("items") or [])
        promise = detect_own_promise(reply)
        cust = detect_customer_promise(inbound_text)

        deal = await open_deal_for(db, conversation_id=conv.id)
        if deal is None:
            if not items and not promise and not cust:
                return                      # nothing worth owning yet
            deal = Deal(conversation_id=conv.id, person_id=conv.person_id)
            db.add(deal)
            await db.flush()                # id needed for the action row

        if items:
            deal.items_snapshot = [
                {"name": i.get("name"), "qty": i.get("qty") or i.get("quantity") or 1,
                 "price": i.get("price")} for i in items][:20]
            names = [str(i.get("name") or "") for i in items if i.get("name")]
            deal.title = (", ".join(names)[:290]) or deal.title
        deal.stage = derive_stage(len(items), deal.stage or "new")

        if promise:
            due = datetime.now(timezone.utc) + timedelta(hours=PROMISE_FOLLOW_UP_HOURS)
            deal.blocking = f"Neema owes the customer: {promise[:200]}"
            deal.next_action = {"kind": "follow_up", "owner": "ai",
                                "due_at": due.isoformat(), "note": promise[:200]}
            await upsert_follow_up(db, deal, due_at=due, kind="follow_up",
                                   reason=f"Neema promised: {promise}")
        elif cust:
            due, hint = cust
            deal.blocking = f"Waiting on the customer ({hint})"
            deal.next_action = {"kind": "customer_promise", "owner": "ai",
                                "due_at": due.isoformat(), "note": f"they said: {hint}"}
            await upsert_follow_up(db, deal, due_at=due, kind="customer_promise",
                                   reason=f"Customer said they'd respond ({hint}) — "
                                          "warm check-in if they haven't")
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
