"""Hub → Neema event agency (docs/AGENTIC_PARTNER_PLAN.md, Phase A).

Neema finally HEARS what her actions caused. The hub (and our own M-Pesa
reconciler) reports order lifecycle events; the split is law:

  CELEBRATIONS ARE HERS — paid / production_started / shipped / delivered →
  an instant, personally-composed message (announce mode: read-only turn over
  the real conversation, so it sounds like Neema, not a template).

  DISAPPOINTMENTS ARE YOURS — delayed / partial payment / refund request →
  conversation flips to human, a ready draft lands as an internal note, and
  the dashboard is pinged. The human sends; Neema never delivers bad news.

Cross-cutting laws enforced here:
  · 24h window — outside it: approved template (WA_EVENT_TEMPLATE) or a human
    notification. Never a free-form policy breach.
  · Quiet hours (08:00–20:00 Nairobi) — celebrations defer to morning via a
    redis zset drained by `deferred_loop` (leader-locked, multi-worker safe).
  · Idempotent — every event id processed once; a paid celebration also takes
    a per-order guard so hub + M-Pesa double-reporting can't double-thank.

The whole phase is INERT until HUB_EVENTS_SECRET is set.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.core.config import settings

_log = logging.getLogger("neema.hubevents")

CELEBRATE = {"order.paid", "order.production_started", "order.shipped", "order.delivered"}
ESCALATE = {"order.delayed", "payment.partial", "refund.requested"}

DEFER_ZSET = "hubevents:deferred"
LEADER_KEY = "hubevents:leader"
# Liveness stamp, set on every verified event: the after-sale self-check probe
# reads it to tell a genuinely quiet week apart from a dead hub→Neema webhook.
LAST_EVENT_KEY = "hubevents:last_at"

# What Neema is told happened — she composes the actual message herself, in the
# conversation's own language and register (announce mode = read-only turn).
_EVENT_BRIEF = {
    "order.paid":
        "Their payment{amount} for order {order} has just been received successfully. "
        "Thank them warmly and tell them what happens next (production/preparation "
        "begins; we'll keep them posted).",
    "order.production_started":
        "The workshop has just STARTED PRODUCTION on their order {order}. Share the "
        "good news in one warm line.",
    "order.shipped":
        "Their order {order} has just been SHIPPED{tracking}. Tell them it's on the "
        "way and how to follow it.",
    "order.delivered":
        "Their order {order} shows as DELIVERED. Send warm aftercare: hope it serves "
        "them beautifully, we're here for adjustments, and — gently, once — that "
        "a short review or photo would bless us.",
}
_ESCALATE_REASON = {
    "order.delayed": "Order delayed — a human should tell the customer personally",
    "payment.partial": "Partial payment received — a human should reconcile with the customer",
    "refund.requested": "Refund requested — human judgement required",
}


def _nairobi_hour(now: datetime | None = None) -> int:
    return ((now or datetime.now(timezone.utc)) + timedelta(hours=3)).hour


def is_quiet_hours(now: datetime | None = None) -> bool:
    h = _nairobi_hour(now)
    return h < 8 or h >= 20


def next_morning_utc(now: datetime | None = None) -> datetime:
    """The next 08:00 Nairobi, as UTC — when a deferred celebration fires."""
    now = now or datetime.now(timezone.utc)
    nbo = now + timedelta(hours=3)
    morning = nbo.replace(hour=8, minute=0, second=0, microsecond=0)
    if nbo.hour >= 8:
        morning += timedelta(days=1)
    return morning - timedelta(hours=3)


def brief_for(event: dict) -> str | None:
    tmpl = _EVENT_BRIEF.get(event.get("type") or "")
    if not tmpl:
        return None
    amount = event.get("amount")
    currency = event.get("currency") or "KES"
    tracking = event.get("tracking")
    return tmpl.format(
        order=event.get("order_number") or "their order",
        amount=f" of {currency} {amount:,}" if isinstance(amount, (int, float)) else "",
        tracking=f" (tracking: {tracking})" if tracking else "",
    )


async def _conversation_for_phone(db, phone: str):
    """Newest conversation for this phone's PERSON (any channel) — WhatsApp
    match first (wa_id == E.164 digits), then the identity spine."""
    from app.core.phone import to_e164
    from app.models.conversation import Conversation
    from app.models.person import Identity, Identifier
    e164 = to_e164(phone or "", "KE")
    if not e164:
        return None
    wa_key = e164.lstrip("+")
    conv = (await db.execute(select(Conversation).where(
        Conversation.wa_id == wa_key))).scalar_one_or_none()
    if conv is not None:
        return conv
    person_id = None
    ident = (await db.execute(select(Identity).where(
        Identity.channel == "whatsapp", Identity.external_id == wa_key))).scalar_one_or_none()
    if ident is not None:
        person_id = ident.person_id
    else:
        idf = (await db.execute(select(Identifier).where(
            Identifier.type == "phone", Identifier.value == e164))).scalar_one_or_none()
        if idf is not None:
            person_id = idf.person_id
    if person_id is None:
        return None
    return (await db.execute(
        select(Conversation).where(Conversation.person_id == person_id)
        .order_by(Conversation.last_message_at.desc().nullslast()).limit(1)
    )).scalar_one_or_none()


async def _last_inbound_at(db, conv) -> datetime | None:
    from app.models.message import Message, MsgDirection
    where = ((Message.wa_id == conv.wa_id) if conv.channel == "whatsapp" else
             ((Message.channel == conv.channel) & (Message.external_id == conv.external_id)))
    return (await db.execute(
        select(Message.created_at).where(
            where, Message.direction == MsgDirection.inbound)
        .order_by(Message.created_at.desc()).limit(1))).scalar_one_or_none()


async def _within_window(db, conv) -> bool:
    last = await _last_inbound_at(db, conv)
    if last is None:
        return False
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - last) < timedelta(hours=24)


def _recipient_of(conv) -> str:
    return conv.wa_id if conv.channel == "whatsapp" else conv.external_id


async def _compose_announcement(db, redis, conv, brief: str) -> str:
    """Announce mode: a read-only turn over the REAL conversation, so the
    message is Neema's own voice, in the customer's language — not a template."""
    from app.agent import runtime
    key = conv.wa_id if conv.channel == "whatsapp" else conv.external_id
    text = ("[SYSTEM EVENT — not a customer message. Compose the ONE short, warm "
            "message Neema should send them right now about this. No questions "
            f"unless truly natural, no re-selling.] {brief}")
    return (await runtime.run_turn(
        db, redis, wa_id=key, user_text=text, llm=runtime.build_llm(),
        channel=conv.channel,
        external_id=(None if conv.channel == "whatsapp" else conv.external_id),
        read_only=True)).strip()


async def _notify_agents(redis, title: str, body: str, conv=None) -> None:
    if redis is None:
        return
    payload = {"event": "notification", "type": "hub_event",
               "title": title, "body": body[:200]}
    if conv is not None:
        payload["conv_id"] = str(conv.id)
        payload["wa_id"] = conv.wa_id or conv.external_id
    try:
        await redis.publish("ws:channel:agents:all", json.dumps(payload))
    except Exception:
        pass


async def _celebrate(db, redis, conv, event: dict) -> dict:
    from app.services import n8n_bridge as svc
    brief = brief_for(event)
    if not brief:
        return {"handled": False, "reason": "unknown_event"}

    # A paid order closes the conversation's open deal as WON (B1 hook) —
    # regardless of how or when the thank-you goes out.
    if event.get("type") == "order.paid":
        try:
            from app.services.deals import mark_won_for_conversation
            await mark_won_for_conversation(db, conv.id)
        except Exception:
            pass

    # The tailor's call-back: six days after delivery, ask how it fits. Planned
    # here (whatever send mode the delivery news itself takes) and executed by
    # the initiative scheduler with its own window/quiet-hour rules.
    if event.get("type") == "order.delivered":
        try:
            await _plan_fit_check(db, redis, conv, event)
        except Exception:
            _log.warning("fit-check planning failed for %s", event.get("order_number"))

    # Quiet hours FIRST — deferring must never burn the celebration guard, or
    # the morning drain finds its own footprint and swallows the thank-you.
    if is_quiet_hours():
        await defer(redis, event)
        return {"handled": True, "deferred": "quiet_hours"}

    # Paid events can arrive from BOTH the hub and the M-Pesa reconciler —
    # one thank-you per order, whoever reports first.
    if event.get("type") == "order.paid" and redis is not None:
        guard = f"celebrated:paid:{event.get('order_number') or _recipient_of(conv)}"
        try:
            if not await redis.set(guard, "1", nx=True, ex=86400):
                return {"handled": False, "reason": "already_celebrated"}
        except Exception:
            pass

    # The thank-you carries their receipt — proof of payment in one tap.
    receipt = ""
    if event.get("type") == "order.paid":
        receipt = await _receipt_link_for(db, redis, event)
        if receipt:
            brief += (f" Include their receipt link plainly in the message: "
                      f"{receipt}")

    in_window = await _within_window(db, conv)
    recipient = _recipient_of(conv)

    # Meta allows POST_PURCHASE_UPDATE outside the 24h window for exactly this:
    # automated updates about an order the customer already placed (payment
    # received, in production, shipped, delivered). Messenger only — Instagram
    # supports no tag but HUMAN_AGENT, which automation must never claim. So a
    # Messenger customer hears "your order shipped" the day it ships, not only
    # if they happened to write to us yesterday (owner, 2026-08-19).
    post_purchase = (conv.channel == "messenger"
                     and (event.get("type") or "").startswith("order."))

    if in_window or post_purchase:
        text = await _compose_announcement(db, redis, conv, brief)
        if not text:
            return {"handled": False, "reason": "compose_failed"}
        if conv.channel == "whatsapp":
            wamid = await svc._send_waba(recipient, text)
            await svc.save_outbound_message(db, redis, recipient, text, waba_msg_id=wamid)
        else:
            from app.services.meta_send import send_to_channel
            await send_to_channel(conv.channel, recipient, text,
                                  tag=(None if in_window else "POST_PURCHASE_UPDATE"))
            await svc.save_outbound_channel_message(db, redis, conv.channel, recipient, text)
        _log.info("hub event %s → celebrated %s to %s", event.get("type"),
                  "in-window" if in_window else "via POST_PURCHASE_UPDATE", recipient)
        return {"handled": True, "sent": "freeform" if in_window else "post_purchase_tag"}

    if conv.channel == "whatsapp" and settings.wa_event_template:
        name = (getattr(conv, "contact_name", None) or "").split(" ")[0] or "there"
        status_word = {
            "order.paid": "payment received — thank you! Production begins",
            "order.production_started": "in production at our workshop",
            "order.shipped": "shipped and on its way to you",
            "order.delivered": "delivered — we hope it serves you beautifully",
        }.get(event.get("type") or "", "updated")
        if receipt:
            status_word += f". Receipt: {receipt}"
        params = [name, event.get("order_number") or "your order", status_word]
        tpl = await svc.send_wa_template(recipient, settings.wa_event_template,
                                         settings.wa_event_lang, params)
        await svc.save_outbound_message(
            db, redis, recipient, f"[template {settings.wa_event_template}] {brief}",
            waba_msg_id=(((tpl or {}).get("messages") or [{}])[0].get("id") or None))
        return {"handled": True, "sent": "template"}

    await _notify_agents(
        redis, "💰 " + (event.get("type") or "hub event"),
        f"{event.get('order_number') or ''}: outside the 24h window and no event "
        f"template — send the good news manually. ({brief})", conv)
    return {"handled": True, "sent": "notified_human"}


async def _receipt_link_for(db, redis, event: dict) -> str:
    """A SHORT link to the customer's receipt (the hub /pay page in its paid
    state), to ride along with the payment thank-you. Resolved from the order
    row Neema stored at push time and shortened through the existing
    /api/o/{ref} redirect so the chat shows a clean link, not a token monster.
    Returns '' when anything is missing — the thank-you sends regardless."""
    try:
        from sqlalchemy import select
        number = (event.get("order_number") or "").strip()
        if not number:
            return ""
        from app.models.order_event import OrderEvent
        row = (await db.execute(
            select(OrderEvent).where(OrderEvent.hub_order_number == number)
            .order_by(OrderEvent.created_at.desc()).limit(1))).scalar_one_or_none()
        target = ((row.hub_payment_url or "") if row else "").strip()
        if not target:
            return ""
        base = (settings.media_public_url or "").rstrip("/")
        if redis is None or not base:
            return target
        import secrets
        ref = secrets.token_hex(3).upper()
        await redis.set(f"waref:{ref}", json.dumps({"target": target}),
                        ex=90 * 24 * 3600)
        return f"{base}/api/o/{ref}"
    except Exception:
        return ""


FIT_CHECK_DAYS = 6


async def _plan_fit_check(db, redis, conv, event: dict) -> None:
    """Plan the after-delivery fit check — the relationship moment of a
    made-to-measure business. One per order (redis guard); rides the existing
    AgentAction scheduler, so approval gates and quiet hours apply there."""
    from app.models.agent_action import AgentAction
    number = event.get("order_number") or ""
    if redis is not None:
        try:
            if not await redis.set(f"fitcheck:{number or _recipient_of(conv)}", "1",
                                   nx=True, ex=30 * 86400):
                return
        except Exception:
            pass
    db.add(AgentAction(
        deal_id=None, conversation_id=conv.id,
        due_at=datetime.now(timezone.utc) + timedelta(days=FIT_CHECK_DAYS),
        kind="fit_check",
        reason=(f"Order {number} was delivered {FIT_CHECK_DAYS} days ago — ask "
                "warmly whether it fits and serves well, and offer our free "
                "adjustment if anything needs it. Care, not selling.")))
    await db.commit()


async def _escalate(db, redis, conv, event: dict) -> dict:
    from datetime import datetime as _dt
    from app.models.conversation import InterceptMode
    from app.models.intercept import Intercept, InterceptAction
    from app.models.message import Message, MsgDirection, MsgSender

    reason = _ESCALATE_REASON.get(event.get("type") or "", "Hub event needs a human")

    if conv.intercept_mode != InterceptMode.human:
        conv.intercept_mode = InterceptMode.human
        conv.assigned_agent_id = None
        conv.intercept_since = _dt.now(timezone.utc)
        db.add(Intercept(conversation_id=conv.id, agent_id=None,
                         action=InterceptAction.intercept, note=reason))

    # A ready draft, saved as an internal NOTE (never reaches the model or the
    # customer) — the human reads, edits, sends.
    draft = ""
    try:
        brief = (f"{reason}. Order {event.get('order_number') or ''}. "
                 "Draft the empathetic message a human could send — "
                 "acknowledge specifically, no false promises.")
        draft = await _compose_announcement(db, redis, conv, brief)
    except Exception:
        pass
    note_text = f"⚠️ {reason}" + (f"\n\nSuggested reply (edit before sending):\n{draft}" if draft else "")
    db.add(Message(
        channel=conv.channel, wa_id=conv.wa_id,
        external_id=getattr(conv, "external_id", None),
        person_id=conv.person_id, conversation_id=conv.id,
        direction=MsgDirection.outbound, sender=MsgSender.human_agent,
        text=note_text, media_type="note",
    ))
    await db.commit()

    await _notify_agents(redis, "⚠️ " + reason,
                         f"{event.get('order_number') or ''} — conversation is ready "
                         "for pickup with a suggested reply attached.", conv)
    if redis is not None:
        try:
            await redis.publish(f"ws:channel:{conv.id}", json.dumps({
                "type": "intercept_changed", "conversationId": str(conv.id),
                "mode": "human", "assignedAgentId": None,
                "eventKind": "intercept", "eventReason": reason}))
        except Exception:
            pass
    return {"handled": True, "escalated": True}


async def handle_event(db, redis, event: dict) -> dict:
    """Route one event. Never raises — the webhook must always ack."""
    try:
        etype = event.get("type") or ""
        eid = str(event.get("id") or "")
        # A price/product edit in the hub must reach Neema NOW, not when the
        # 10-minute catalogue cache expires (owner rule: memory changes when
        # the price changes). The hub fires catalog.updated on product save;
        # busting the working cache makes the very next quote re-fetch. The
        # 7-day last-good mirror is left alone — it refreshes on that load,
        # and during an outage a stale price beats no catalogue at all.
        if etype in ("catalog.updated", "product.updated"):
            if redis is not None:
                try:
                    await redis.delete("hub:catalog")
                    await redis.set(LAST_EVENT_KEY,
                                    datetime.now(timezone.utc).isoformat(),
                                    ex=30 * 86400)
                except Exception:
                    pass
            _log.info("hub %s — catalogue cache busted; next quote is fresh", etype)
            return {"handled": True, "action": "catalog_cache_busted"}
        if not eid or (etype not in CELEBRATE and etype not in ESCALATE):
            return {"handled": False, "reason": "unknown_event"}
        if redis is not None:
            try:
                # Stamp before dedup — a retried duplicate still proves the
                # hub→Neema wiring is alive.
                await redis.set(LAST_EVENT_KEY,
                                datetime.now(timezone.utc).isoformat(), ex=30 * 86400)
            except Exception:
                pass
        if redis is not None:
            try:
                if not await redis.set(f"hubevent:seen:{eid}", "1", nx=True, ex=7 * 86400):
                    return {"handled": False, "reason": "duplicate"}
            except Exception:
                pass
        conv = await _conversation_for_phone(db, event.get("customer_phone") or "")
        if conv is None:
            await _notify_agents(redis, "Hub event — no conversation",
                                 f"{etype} for {event.get('order_number') or '?'} "
                                 f"({event.get('customer_phone') or 'no phone'}) — "
                                 "no matching customer thread.")
            return {"handled": False, "reason": "no_conversation"}
        if etype in CELEBRATE:
            return await _celebrate(db, redis, conv, event)
        return await _escalate(db, redis, conv, event)
    except Exception as exc:
        _log.exception("hub event handling failed: %s", exc)
        return {"handled": False, "reason": "error"}


# ── Quiet-hours deferral ─────────────────────────────────────────────────────


async def defer(redis, event: dict) -> None:
    if redis is None:
        return
    try:
        due = next_morning_utc().timestamp()
        await redis.zadd(DEFER_ZSET, {json.dumps(event): due})
        _log.info("hub event %s deferred to morning", event.get("id"))
    except Exception:
        pass


async def drain_due(redis) -> int:
    """Handle every deferred event whose morning has come. Leader-locked by the
    caller's loop; each event re-enters handle_event (idempotency keys already
    burned are fine — celebrate guards are separate)."""
    from app.database import AsyncSessionLocal
    if redis is None:
        return 0
    now = datetime.now(timezone.utc).timestamp()
    try:
        due = await redis.zrangebyscore(DEFER_ZSET, 0, now)
    except Exception:
        return 0
    n = 0
    for raw in due or []:
        try:
            await redis.zrem(DEFER_ZSET, raw)
            event = json.loads(raw if isinstance(raw, str) else raw.decode())
            event["_deferred"] = True
            async with AsyncSessionLocal() as db:
                # bypass the seen-key (already burned on first receipt)
                if event.get("type") in CELEBRATE:
                    conv = await _conversation_for_phone(db, event.get("customer_phone") or "")
                    if conv is None:
                        _log.warning("deferred event %s dropped — no conversation "
                                     "for %s", event.get("id"), event.get("customer_phone"))
                        continue
                    out = await _celebrate(db, redis, conv, event)
                    _log.info("deferred event %s → %s", event.get("id"), out)
                    n += 1
        except Exception as exc:
            _log.warning("deferred event failed: %s", exc)
    return n


async def deferred_loop(redis) -> None:
    """Runs for the process lifetime; only the leader drains (multi-worker)."""
    while True:
        try:
            await asyncio.sleep(60)
            if redis is None or not settings.hub_events_secret:
                continue
            if is_quiet_hours():
                continue
            got = await redis.set(LEADER_KEY, "1", nx=True, ex=55)
            if not got:
                continue
            await drain_due(redis)
        except asyncio.CancelledError:
            return
        except Exception as exc:
            _log.warning("deferred loop tick failed: %s", exc)
