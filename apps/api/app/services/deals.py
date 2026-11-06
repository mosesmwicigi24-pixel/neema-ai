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
# "check" is NOT "check in / check back / check up": "I'll check in with you on
# the 30th" is the customer's own date (schedule_check_in books it), and read
# as a promise it sent "checking in as promised" 3 hours later — 61 of 184
# promise follow-ups in 30 days (owner review, 2026-10-29).
_CHECK = r"check(?!\s+(?:in|back|up)\b)"
_PROMISE_RE = re.compile(
    rf"\b(i(?:'| wi)ll (?:{_CHECK}|confirm|find out|enquire|inquire|verify|ask)"
    r"(?:[^.!\n]{0,80}?)(?:get back|revert|let you know|update you)?"
    rf"|let me (?:{_CHECK}|confirm|find out|enquire|verify)[^.!\n]{{0,80}})",
    re.IGNORECASE)

PROMISE_FOLLOW_UP_HOURS = 3

# The CUSTOMER's stated timeline ("I'll confirm after the church meeting") —
# needs BOTH a commitment verb and a time hint, or we'd nag over pleasantries.
_CUSTOMER_PROMISE_RE = re.compile(
    r"\b(?:i(?:'ll| will)|we(?:'ll| will)|nita|tuta)\s?"
    r"(?:confirm|get back|let you know|revert|respond|reply|check|decide|send|pay"
    r"|need|order|buy|take|contact|call|message|text|write|remind|communicate"
    r"|come back|be in touch|consult|ask|discuss|talk|wasiliana|piga)",
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


def snapshot_items(items: list) -> list[dict]:
    """The deal's lines with their PRICES — cart lines carry `unit_price`
    (the `price` key read before was never there, so every deal total was
    0 and the KES 50,000 human-approval gate never fired)."""
    out = []
    for i in (items or [])[:20]:
        price = i.get("unit_price")
        if price in (None, ""):
            price = i.get("price")
        try:
            price = float(price) if price not in (None, "") else None
        except (TypeError, ValueError):
            price = None
        out.append({"name": i.get("name"), "qty": i.get("qty") or i.get("quantity") or 1,
                    "price": price})
    return out


async def scribe_update(db, key: str, channel: str, reply: str,
                        inbound_text: str = "", tools: list | None = None) -> None:
    """File the turn: cart → items/title/stage, promises (Neema's own AND the
    customer's stated timeline) → blocking/next_action + a planned-action row
    the B2 scheduler executes. A reply that PRICED a stock item (from this
    turn's tool results, `tools`) with no promise in play plans the quote
    follow-up (services/quote_followup.py). Creates the deal on first buying
    signal; silent otherwise — greetings don't deserve deal rows."""
    try:
        from app.agent import cart as cartmod
        from app.models.deal import Deal
        from app.services import quote_followup
        from app.services.actions import upsert_follow_up

        conv = await _conversation_of(db, key, channel)
        if conv is None:
            return

        cart = await cartmod.get_cart(db, key, channel=channel)
        items = list((cart or {}).get("items") or [])
        promise = detect_own_promise(reply)
        cust = detect_customer_promise(inbound_text)
        quote = quote_followup.extract_quote(tools, reply)

        from app.services import customer_state
        reading = customer_state.floor(inbound_text)
        # A request for time or a payment claim is a deal worth owning even
        # before a cart: the hold and the claim need a deal row to live on.
        holding = bool(reading and reading.get("customer_said") in customer_state.HOLD_STATES + ("paid_claim",))

        deal = await open_deal_for(db, conversation_id=conv.id)
        if deal is None:
            if not items and not promise and not cust and not quote and not holding:
                # Nothing worth owning yet — still remember their language and
                # what they said, on the person.
                await customer_state.after_turn(db, conv, None, inbound_text=inbound_text,
                                                reply=reply, reading=reading)
                return
            deal = Deal(conversation_id=conv.id, person_id=conv.person_id)
            db.add(deal)
            await db.flush()                # id needed for the action row

        if items:
            deal.items_snapshot = snapshot_items(items)
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
        else:
            outcome = await quote_followup.on_turn(
                db, conv, deal, quote=quote, inbound_text=inbound_text,
                tools=tools, reply=reply)
            if quote:
                _log.info("quote follow-up for %s/%s: %s", channel, conv.id, outcome)
        await db.commit()
        # What the customer's words mean for what we do next (Stage 3): a hold,
        # their language, a payment claim — on the deal and the person. Its own
        # try: a failure here never loses the scribe's work above.
        try:
            await customer_state.after_turn(db, conv, deal, inbound_text=inbound_text, reply=reply,
                                            reading=reading, llm=customer_state.note_llm())
        except Exception as exc:
            _log.info("customer state skipped for %s: %s", key, exc)
    except Exception as exc:
        _log.info("deal scribe skipped for %s: %s", key, exc)
        try:
            await db.rollback()
        except Exception:
            pass


TEAM_CHECK_DAYS = 7


def team_check_open(deal, *, now: datetime | None = None) -> str | None:
    """The item the team was asked to confirm and has not yet — or None.
    Stored on the deal by check_availability (tools.py); cleared when a
    colleague answers (the team-answer endpoint, a human reply in the thread);
    expires after TEAM_CHECK_DAYS so a forgotten check never freezes a deal."""
    nxt = getattr(deal, "next_action", None) or {}
    if not isinstance(nxt, dict) or nxt.get("kind") != "team_check":
        return None
    since = nxt.get("since")
    try:
        at = datetime.fromisoformat(since) if since else None
    except (TypeError, ValueError):
        at = None
    if at is not None and at.tzinfo is None:
        at = at.replace(tzinfo=timezone.utc)
    if at is not None and (now or datetime.now(timezone.utc)) - at > timedelta(days=TEAM_CHECK_DAYS):
        return None
    return (nxt.get("item") or "").strip() or None


async def open_team_check(db, conv, item: str) -> None:
    """Record that the team owes this customer a confirmation (audit F,
    2026-11-05): until it arrives, no automated sales follow-up goes to this
    thread and the model is told not to close on the item. Creates the deal
    on first need. Commits."""
    item = " ".join((item or "").split())[:160]
    if not item or conv is None:
        return
    from app.models.deal import Deal
    deal = await open_deal_for(db, conversation_id=conv.id)
    if deal is None:
        deal = Deal(conversation_id=conv.id, person_id=getattr(conv, "person_id", None))
        db.add(deal)
        await db.flush()
    deal.blocking = f"Team confirming: {item}"
    deal.next_action = {"kind": "team_check", "owner": "human", "item": item,
                        "since": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    await db.commit()


async def clear_team_check(db, conversation_id, *, by: str = "team") -> bool:
    """A colleague answered: the check is closed. Commits. True when one was open."""
    deal = await open_deal_for(db, conversation_id=conversation_id)
    if deal is None or team_check_open(deal) is None:
        return False
    deal.blocking = None
    deal.next_action = {"kind": "team_check_closed", "owner": by,
                        "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    await db.commit()
    return True


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
