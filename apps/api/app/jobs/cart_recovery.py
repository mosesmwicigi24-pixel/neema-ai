"""Abandoned-cart recovery: nudge the people who were mid-purchase and stopped.

The single biggest pot of money already in the system. Neema builds a real cart
during the conversation (hub product ids, variant SKUs, hub prices) — and when a
customer goes quiet before confirming, that cart just sits there. This sweep finds
those carts and sends ONE warm, specific nudge naming what they picked.

Deliberately MANUAL and never on a timer — an outbound campaign must be an
explicit human decision. Defaults to a dry run; pass --send to actually send:

    docker compose -f docker-compose.yml -f docker-compose.vps.yml \\
        exec -T api python -m app.jobs.cart_recovery            # preview only
    docker compose -f docker-compose.yml -f docker-compose.vps.yml \\
        exec -T api python -m app.jobs.cart_recovery --send     # SEND live

Guardrails, because this messages real customers:
  · 24h WINDOW ONLY — we never message outside the free-form window, so no
    template is required and nobody gets an unsolicited marketing message.
  · QUIET HOURS — nothing sent outside 08:00-20:00 Nairobi time.
  · AI MODE ONLY — a conversation a human took over, or that Neema paused, is
    left alone.
  · WAITING FOR THEM, NOT US — if the last message is theirs we owe them a real
    reply (that's the re-engage sweep's job), so it is skipped here.
  · ONCE PER CART — a redis guard keyed by the cart's CONTENTS, so a nudge is
    never repeated for the same basket, and a changed cart can be nudged again
    only after the cooldown.
  · NEVER AFTER AN ORDER — create_order clears the cart, so a bought basket
    cannot be nudged by construction.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.core.config import settings
from app.database import AsyncSessionLocal
# Import the FULL model set so SQLAlchemy's mapper registry is complete before we
# compile any query (a standalone job doesn't go through app.main).
import app.models.agent      # noqa: F401
import app.models.intercept  # noqa: F401
import app.models.person     # noqa: F401
import app.models.user       # noqa: F401
from app.models.conversation import Conversation, ConvStatus, InterceptMode
from app.models.message import Message, MsgDirection

_log = logging.getLogger("neema.cart_recovery")

CHANNELS = ("whatsapp", "messenger", "instagram")
WINDOW_HOURS = 24          # the free-form messaging window — never message outside it
MIN_IDLE_MINUTES = 45      # give them room to come back on their own first
QUIET_START, QUIET_END = 8, 20      # Nairobi hours in which sending is allowed
_GUARD_TTL = 7 * 24 * 3600          # one nudge per basket per week


def _nairobi_hour(now: datetime | None = None) -> int:
    """Hour of day in Nairobi (UTC+3, no DST)."""
    return ((now or datetime.now(timezone.utc)) + timedelta(hours=3)).hour


def within_quiet_hours(now: datetime | None = None) -> bool:
    return QUIET_START <= _nairobi_hour(now) < QUIET_END


def cart_fingerprint(items: list) -> str:
    """Stable id for a basket's CONTENTS — so one nudge per basket, and a cart
    they actually changed can be nudged again after the cooldown."""
    key = sorted(f"{i.get('name')}x{i.get('qty')}" for i in (items or []))
    return hashlib.sha1("|".join(key).encode("utf-8")).hexdigest()[:16]


def _summarise(items: list, currency: str = "KES") -> str:
    parts = []
    for i in (items or [])[:5]:
        qty = i.get("qty") or 1
        parts.append(f"{i.get('name')}" + (f" ×{qty}" if qty and int(qty) > 1 else ""))
    return ", ".join(parts)


async def _make_redis():
    import redis.asyncio as aioredis
    try:
        r = aioredis.from_url(settings.redis_url, decode_responses=True,
                              socket_connect_timeout=5, socket_timeout=5)
        await r.ping()
        return r
    except Exception:
        _log.warning("redis unavailable — running without the once-per-cart guard")
        return None


async def _latest_message(db, conv_id) -> Message | None:
    # Internal notes are not turns: a note after the customer's message would hide
    # that we OWE them a reply and wrongly turn a due-reply into a nudge.
    return (await db.execute(
        select(Message).where(Message.conversation_id == conv_id)
        .where(Message.media_type.is_(None) | (Message.media_type != "note"))
        .order_by(Message.created_at.desc()).limit(1))).scalar_one_or_none()


async def find_abandoned(db) -> list[dict]:
    """Open, AI-mode conversations with items still in the cart, gone quiet for a
    while but still inside the 24h window, where the ball is in THEIR court."""
    from app.agent import cart as cartmod

    now = datetime.now(timezone.utc)
    fresh = now - timedelta(hours=WINDOW_HOURS)
    idle = now - timedelta(minutes=MIN_IDLE_MINUTES)
    convs = (await db.execute(
        select(Conversation).where(
            Conversation.channel.in_(CHANNELS),
            Conversation.intercept_mode == InterceptMode.ai,
            Conversation.status == ConvStatus.open,
            Conversation.last_message_at >= fresh,
            Conversation.last_message_at <= idle,
        ).order_by(Conversation.last_message_at.desc()))).scalars().all()

    from app.core.phone import is_plausible_phone

    out: list[dict] = []
    seen_owners: set = set()
    for conv in convs:
        key = conv.wa_id if conv.channel == "whatsapp" else (conv.external_id or conv.wa_id)
        if not key:
            continue
        # Web-chat sessions masquerade as WhatsApp but "web_<hash>" is not a
        # number — a WABA send is a guaranteed Graph error (and burns the guard).
        if conv.channel == "whatsapp" and not is_plausible_phone(key):
            continue
        # The cart is PERSON-scoped: one human with WhatsApp + Messenger threads
        # shares ONE cart — dedupe by the cart's OWNER so one basket gets ONE
        # nudge, preferring the earlier (most recent conversation) row.
        store = await cartmod._load_store(db, key, conv.channel or "whatsapp")
        if store is None:
            continue
        owner = f"{type(store).__name__}:{store.id}"
        if owner in seen_owners:
            continue
        cart = cartmod.read_cart(getattr(store, "state", None))
        items = (cart or {}).get("items") or []
        if not items:
            continue
        last = await _latest_message(db, conv.id)
        # If their message is the newest, we owe them a real reply — not a nudge.
        if last is not None and last.direction == MsgDirection.inbound:
            continue
        seen_owners.add(owner)
        out.append({"conv": conv, "to": key, "items": items, "owner": owner,
                    "total": cartmod.cart_total(cart)})
    return out


async def _draft(redis, conv: Conversation, to: str, items: list) -> str:
    """Let Neema write the nudge in her own voice, naming what they actually
    picked — the agent loop, so pricing and tone stay consistent with the thread."""
    from app.agent import runtime
    from app.agent.runtime import build_llm
    summary = _summarise(items)
    prompt = (
        "(Internal: this customer built a cart and went quiet before confirming. "
        f"Their cart: {summary}. Write ONE short, warm follow-up — greet them by "
        "name if you know it, remind them what they picked, and ask if they'd like "
        "to go ahead. No pressure, no discount, no links. Two sentences at most.)"
    )
    async with AsyncSessionLocal() as db:
        if conv.channel == "whatsapp":
            return await runtime.run_turn(db, redis, to, prompt, build_llm(),
                                          read_only=True)
        return await runtime.run_turn(db, redis, wa_id=to, user_text=prompt,
                                      llm=build_llm(), channel=conv.channel,
                                      external_id=to, read_only=True)


async def _handle(redis, row: dict, *, send: bool) -> dict:
    from app.services import n8n_bridge as svc
    from app.services.meta_send import send_to_channel

    conv, to, items = row["conv"], row["to"], row["items"]
    is_wa = conv.channel == "whatsapp"
    res = {"channel": conv.channel, "to": to, "cart": _summarise(items),
           "total": row["total"], "draft": "", "sent": False,
           "skipped": None, "error": None}

    fp = cart_fingerprint(items)
    if send and redis is not None:
        try:
            owner = row.get("owner") or str(conv.id)
            ok = await redis.set(f"cartnudge:{owner}:{fp}", "1", nx=True, ex=_GUARD_TTL)
            if not ok:
                res["skipped"] = "already nudged for this cart"
                return res
        except Exception:
            pass

    try:
        reply = await _draft(redis, conv, to, items)
    except Exception as e:
        res["error"] = f"draft failed: {str(e)[:160]}"
        return res
    res["draft"] = (reply or "")[:200]

    if not send or not reply:
        return res

    try:
        if is_wa:
            await svc._send_waba(to, reply)
            async with AsyncSessionLocal() as db2:
                await svc.save_outbound_message(db2, redis, to, reply)
        else:
            await send_to_channel(conv.channel, to, reply)
            async with AsyncSessionLocal() as db2:
                await svc.save_outbound_channel_message(db2, redis, conv.channel, to, reply)
        res["sent"] = True
    except Exception as e:
        res["error"] = f"send failed: {str(e)[:160]}"
    return res


async def run(send: bool, ignore_quiet_hours: bool = False) -> dict:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    redis = await _make_redis()
    async with AsyncSessionLocal() as db:
        rows = await find_abandoned(db)

    mode = "LIVE SEND" if send else "DRY RUN (no messages sent)"
    _log.info("── abandoned-cart sweep · %s ────────────────────────", mode)
    _log.info("%d cart(s) left hanging (idle >%dm, inside the %dh window, AI mode)",
              len(rows), MIN_IDLE_MINUTES, WINDOW_HOURS)

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
        _log.info("[%s] %-9s %s\n    cart : %s (total %s)\n    nudge: %s",
                  tag, r["channel"], r["to"], r["cart"], r["total"], r["draft"])

    _log.info("── done: %d cart(s) · %d sent · %d skipped · %d failed ──",
              len(rows), sent, skipped, failed)
    if redis is not None:
        try:
            await redis.aclose()
        except Exception:
            pass
    return {"candidates": len(rows), "sent": sent, "skipped": skipped, "failed": failed}


if __name__ == "__main__":
    ap = argparse.ArgumentParser(
        description="Nudge customers who built a cart and went quiet (<=24h window).")
    ap.add_argument("--send", action="store_true",
                    help="actually send. Without this flag it only previews (dry run).")
    ap.add_argument("--ignore-quiet-hours", action="store_true",
                    help="send even outside 08:00-20:00 Nairobi time.")
    args = ap.parse_args()
    asyncio.run(run(send=args.send, ignore_quiet_hours=args.ignore_quiet_hours))
