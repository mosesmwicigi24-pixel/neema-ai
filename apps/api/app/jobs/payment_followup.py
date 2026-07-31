"""Payment follow-up: the order is placed, the link was sent, nobody ever chases.

An order that reaches a payment link is the closest thing to money in the system —
the customer already said yes. When the payment doesn't land, today nothing
happens at all. This sweep finds those orders and sends ONE gentle reminder with
the same payment link.

Deliberately MANUAL and never on a timer — an outbound campaign must be an
explicit human decision. Defaults to a dry run; pass --send to actually send:

    docker compose -f docker-compose.yml -f docker-compose.vps.yml \\
        exec -T api python -m app.jobs.payment_followup            # preview only
    docker compose -f docker-compose.yml -f docker-compose.vps.yml \\
        exec -T api python -m app.jobs.payment_followup --send     # SEND live

Guardrails, because chasing money is the easiest way to annoy a good customer:
  · NEVER NAG SOMEONE WHO PAID — the hub is re-checked LIVE for every order right
    before we write anything, and a payment that landed silently is reconciled
    into our local record instead of chased. If the hub can't confirm the status,
    we say nothing: uncertainty is not a reason to ask someone for money.
  · 24h WINDOW ONLY — free-form messaging window, so no template and no
    unsolicited marketing.
  · GRACE PERIOD — at least 2h since the order; nobody is chased minutes later.
  · QUIET HOURS — nothing outside 08:00-20:00 Nairobi.
  · AI MODE ONLY — if a human took the conversation over, it's theirs.
  · ONCE PER ORDER — a redis guard keyed by the hub order id.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.core.config import settings
from app.database import AsyncSessionLocal
# Full model set so SQLAlchemy's mapper registry is complete in a standalone job.
import app.models.agent      # noqa: F401
import app.models.intercept  # noqa: F401
import app.models.person     # noqa: F401
import app.models.user       # noqa: F401
from app.models.conversation import Conversation, ConvStatus, InterceptMode
from app.models.order_event import OrderEvent

_log = logging.getLogger("neema.payment_followup")

WINDOW_HOURS = 24        # never message outside the free-form window
GRACE_HOURS = 2          # give them room to pay before we say anything
QUIET_START, QUIET_END = 8, 20
_GUARD_TTL = 14 * 24 * 3600      # one reminder per order

# Hub payment states that mean MONEY HAS LANDED — never chase these.
PAID_STATES = {"paid", "completed", "settled", "success", "successful", "complete"}


def _nairobi_hour(now: datetime | None = None) -> int:
    return ((now or datetime.now(timezone.utc)) + timedelta(hours=3)).hour


def within_quiet_hours(now: datetime | None = None) -> bool:
    return QUIET_START <= _nairobi_hour(now) < QUIET_END


def is_paid(status: str | None) -> bool:
    """True when the hub says this order is settled. Deliberately strict: only an
    explicit paid-like state counts, so 'unpaid'/'partial'/None never reads as paid."""
    s = (status or "").strip().lower()
    return s in PAID_STATES


async def _make_redis():
    import redis.asyncio as aioredis
    try:
        r = aioredis.from_url(settings.redis_url, decode_responses=True,
                              socket_connect_timeout=5, socket_timeout=5)
        await r.ping()
        return r
    except Exception:
        _log.warning("redis unavailable — running without the once-per-order guard")
        return None


async def _conversation_for(db, order: OrderEvent) -> tuple[Conversation | None, str | None]:
    """(conversation, recipient) for an order.

    OrderEvent.wa_id is always the PHONE (orders are keyed on it so a Messenger
    buyer's order is found again on WhatsApp) — but a Meta conversation's handle
    is the PSID/IGSID. Comparing phone to PSID never matched, so every
    Meta-channel unpaid order was silently skipped. Resolve Meta conversations
    through the PERSON instead, and return the right recipient for the channel."""
    ch = order.channel or "whatsapp"
    if ch == "whatsapp":
        conv = (await db.execute(
            select(Conversation).where(Conversation.channel == ch,
                                       Conversation.wa_id == order.wa_id)
        )).scalars().first()
        return conv, (conv.wa_id if conv else None)
    if order.person_id is not None:
        conv = (await db.execute(
            select(Conversation).where(Conversation.channel == ch,
                                       Conversation.person_id == order.person_id)
        )).scalars().first()
        if conv is not None:
            return conv, (conv.external_id or conv.wa_id)
    # Fallback: the buyer's phone may ALSO have a WhatsApp thread — remind there.
    conv = (await db.execute(
        select(Conversation).where(Conversation.channel == "whatsapp",
                                   Conversation.wa_id == order.wa_id)
    )).scalars().first()
    return conv, (conv.wa_id if conv else None)


async def find_unpaid(db, redis=None) -> list[dict]:
    """Orders with a payment link, placed inside the window, still unpaid — with
    the hub re-checked live so a customer who already paid is NEVER chased."""
    from app.core import hub_client

    now = datetime.now(timezone.utc)
    fresh = now - timedelta(hours=WINDOW_HOURS)
    grace = now - timedelta(hours=GRACE_HOURS)
    orders = (await db.execute(
        select(OrderEvent).where(
            OrderEvent.hub_payment_url.isnot(None),
            OrderEvent.hub_order_id.isnot(None),
            OrderEvent.created_at >= fresh,
            OrderEvent.created_at <= grace,
        ).order_by(OrderEvent.created_at.desc()))).scalars().all()

    out: list[dict] = []
    for o in orders:
        if is_paid(o.payment_status):
            continue                                   # already settled locally
        # LIVE re-check — the local mirror can be stale, and chasing someone who
        # has paid is worse than not chasing at all.
        live = None
        try:
            live = await hub_client.fetch_order_status(o.hub_order_id, redis)
        except Exception:
            live = None
        if live is None:
            continue                                   # can't confirm → say nothing
        if is_paid(live.get("payment_status")):
            # Reconcile quietly: they paid, our mirror just hadn't caught up.
            o.payment_status = "paid"
            await db.commit()
            continue
        conv, recipient = await _conversation_for(db, o)
        if conv is None or recipient is None \
                or conv.intercept_mode != InterceptMode.ai \
                or conv.status != ConvStatus.open:
            continue                                   # human-handled / closed
        out.append({"order": o, "conv": conv, "to": recipient})
    return out


def compose(order: OrderEvent, name: str | None = None) -> str:
    """The reminder. Short, warm, no pressure — and the SAME link we already gave
    them, never a new one."""
    who = f" {name.split()[0]}" if name else ""
    num = f" {order.hub_order_number}" if order.hub_order_number else ""
    cur = order.hub_currency or order.currency or "KES"
    total = order.hub_total if order.hub_total is not None else order.subtotal
    amount = f"{cur} {float(total):,.0f}" if total is not None else ""
    return (
        f"Hi{who} 🙏 Just checking in on your order{num}"
        + (f" ({amount})" if amount else "") + ".\n\n"
        "Whenever you're ready, you can complete payment here:\n"
        f"{order.hub_payment_url}\n\n"
        "Any trouble with the link — or anything you'd like to change — just tell me."
    )


async def _handle(redis, row: dict, *, send: bool) -> dict:
    from app.services import n8n_bridge as svc
    from app.services.meta_send import send_to_channel
    from app.models.user import User

    order, conv, to = row["order"], row["conv"], row["to"]
    is_wa = (conv.channel or "whatsapp") == "whatsapp"
    res = {"channel": conv.channel, "to": to, "order": order.hub_order_number or order.hub_order_id,
           "amount": str(order.hub_total or order.subtotal or ""),
           "text": "", "sent": False, "skipped": None, "error": None}

    if send and redis is not None:
        try:
            ok = await redis.set(f"payfollow:{order.hub_order_id}", "1",
                                 nx=True, ex=_GUARD_TTL)
            if not ok:
                res["skipped"] = "already reminded"
                return res
        except Exception:
            pass

    name = None
    try:
        async with AsyncSessionLocal() as db:
            u = (await db.execute(select(User).where(User.wa_id == to))).scalar_one_or_none()
            name = u.name if u else None
    except Exception:
        pass

    text = compose(order, name)
    res["text"] = text[:200]
    if not send:
        return res

    try:
        if is_wa:
            wamid = await svc._send_waba(to, text)
            async with AsyncSessionLocal() as db2:
                await svc.save_outbound_message(db2, redis, to, text, waba_msg_id=wamid)
        else:
            await send_to_channel(conv.channel, to, text)
            async with AsyncSessionLocal() as db2:
                await svc.save_outbound_channel_message(db2, redis, conv.channel, to, text)
        res["sent"] = True
    except Exception as e:
        res["error"] = f"send failed: {str(e)[:160]}"
    return res


async def run(send: bool, ignore_quiet_hours: bool = False) -> dict:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    redis = await _make_redis()
    async with AsyncSessionLocal() as db:
        rows = await find_unpaid(db, redis)

    mode = "LIVE SEND" if send else "DRY RUN (no messages sent)"
    _log.info("── payment follow-up · %s ───────────────────────────", mode)
    _log.info("%d unpaid order(s) confirmed live with the hub (>%dh old, inside %dh, AI mode)",
              len(rows), GRACE_HOURS, WINDOW_HOURS)

    if send and not ignore_quiet_hours and not within_quiet_hours():
        _log.warning("quiet hours (%02d:00-%02d:00 Nairobi) — nothing sent. "
                     "Use --ignore-quiet-hours to override.", QUIET_START, QUIET_END)
        send = False

    sent = failed = skipped = 0
    for row in rows:
        r = await _handle(redis, row, send=send)
        if r["skipped"]:
            skipped += 1
            tag = f"SKIP ({r['skipped']})"
        elif r["error"]:
            failed += 1
            tag = f"FAIL — {r['error']}"
        elif r["sent"]:
            sent += 1
            tag = "SENT"
        else:
            tag = "DRAFT"
        _log.info("[%s] %-9s %s\n    order: %s (%s)\n    text : %s",
                  tag, r["channel"], r["to"], r["order"], r["amount"], r["text"])

    _log.info("── done: %d order(s) · %d reminded · %d skipped · %d failed ──",
              len(rows), sent, skipped, failed)
    if redis is not None:
        try:
            await redis.aclose()
        except Exception:
            pass
    return {"candidates": len(rows), "sent": sent, "skipped": skipped, "failed": failed}


if __name__ == "__main__":
    ap = argparse.ArgumentParser(
        description="Remind customers whose order has an unpaid payment link (<=24h).")
    ap.add_argument("--send", action="store_true",
                    help="actually send. Without this flag it only previews (dry run).")
    ap.add_argument("--ignore-quiet-hours", action="store_true",
                    help="send even outside 08:00-20:00 Nairobi time.")
    args = ap.parse_args()
    asyncio.run(run(send=args.send, ignore_quiet_hours=args.ignore_quiet_hours))
