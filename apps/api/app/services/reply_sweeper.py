"""Self-healing sweep for Meta DMs that never got their auto-reply.

Neema's auto-replies are fire-and-forget background tasks (schedule_meta_reply).
If the container is replaced mid-flight — which happens on EVERY deploy — or the
LLM/Graph call errors transiently, that reply is lost silently and the
customer's message just sits there unanswered (the "Munakaa wapi" case). No
customer should ever be left hanging on a sales channel.

This periodic sweep finds Meta DM conversations whose LATEST message is an
unanswered inbound — AI mode, not paused, old enough that the normal path had
its chance, young enough to still be worth answering — and generates + sends the
reply through the same pipeline. Idempotent: a per-conversation redis lock plus a
fresh "is the last message still inbound?" recheck prevent double-replies, and
the reply it sends becomes the new latest message so the next tick skips it.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, func, and_

from app.database import AsyncSessionLocal
from app.models.conversation import Conversation, InterceptMode
from app.models.message import Message, MsgDirection

_log = logging.getLogger("neema.agent")

_META_DM = ("messenger", "instagram")


def _answerable_turn(text: str | None, media_type: str | None, media_url: str | None):
    """What the sweep should send for a last-inbound message: (text, media).
    Returns (None, None) when there's nothing to answer — a bare attachment
    placeholder like "[video]"/"[file]" with no words and no image."""
    t = (text or "").strip()
    if media_type == "image" and media_url:
        caption = "" if t.startswith("[") else t
        return caption, {"type": "image", "url": media_url, "caption": caption}
    if t and not t.startswith("["):
        return t, None
    return None, None


async def _page_id_for(db, channel: str, ext: str) -> str | None:
    """The Page a contact belongs to (PSIDs are page-scoped) — stashed on the
    identity's raw_profile by the webhook — so a multi-page reply uses the right
    token. None → the default meta_page_token."""
    from app.models.person import Identity
    ident = (await db.execute(select(Identity).where(
        Identity.channel == channel, Identity.external_id == ext))).scalar_one_or_none()
    return (getattr(ident, "raw_profile", None) or {}).get("page_id") if ident else None


async def sweep_missed_replies(redis, *, min_age_s: int = 90, max_age_h: int = 23,
                               limit: int = 20) -> int:
    """Answer Meta DMs whose latest message is an unanswered inbound. Returns the
    number of replies actually delivered this pass. Best-effort per conversation.

    max_age_h defaults to 23h ON PURPOSE: Meta's Messenger Platform only allows a
    message within 24h of the customer's last message ('standard messaging'
    window). Beyond that, a send is rejected with error (#10) — so there's no
    point generating a reply we can't deliver. 23h leaves a margin under the
    boundary. Older backlog can only be reached by a human within the 7-day
    HUMAN_AGENT-tag window, or once the customer messages again."""
    from app.agent.runtime import _run_and_send_meta, _is_paused

    now = datetime.now(timezone.utc)
    young = now - timedelta(seconds=min_age_s)      # give the normal path its chance
    old = now - timedelta(hours=max_age_h)          # don't resurrect ancient threads

    async with AsyncSessionLocal() as db:
        latest = (
            select(Message.conversation_id, func.max(Message.created_at).label("m"))
            .where(Message.channel.in_(_META_DM))
            .group_by(Message.conversation_id).subquery()
        )
        q = (
            select(Message, Conversation)
            .join(latest, and_(Message.conversation_id == latest.c.conversation_id,
                               Message.created_at == latest.c.m))
            .join(Conversation, Conversation.id == Message.conversation_id)
            .where(
                Message.direction == MsgDirection.inbound,
                Message.comment_context.is_(None),     # DMs only, never comment threads
                Message.created_at < young,
                Message.created_at > old,
                Conversation.intercept_mode == InterceptMode.ai,
            )
            .order_by(Message.created_at.desc()).limit(limit)
        )
        rows = (await db.execute(q)).all()

    sent = 0
    for msg, conv in rows:
        channel, ext = conv.channel, msg.external_id
        text, media = _answerable_turn(msg.text, msg.media_type, msg.media_url)
        if text is None and media is None:
            continue
        # One worker, one attempt per conversation per window — no double-sends.
        try:
            if redis is not None and not await redis.set(
                    f"agent:missed:lock:{channel}:{ext}", "1", nx=True, ex=300):
                continue
        except Exception:
            pass
        if await _is_paused(redis, channel, ext):
            continue
        # Fresh recheck: has an outbound landed since we queried? (normal path or
        # a human just replied) — if so, leave it alone.
        async with AsyncSessionLocal() as db2:
            still = (await db2.execute(
                select(Message.direction)
                .where(Message.channel == channel, Message.external_id == ext)
                .order_by(Message.created_at.desc()).limit(1))).scalar_one_or_none()
            if still != MsgDirection.inbound:
                continue
            page_id = await _page_id_for(db2, channel, ext)
        try:
            if await _run_and_send_meta(redis, channel, ext, text or "",
                                        page_id=page_id, media=media):
                sent += 1                       # count only messages that truly went out
        except Exception as exc:
            _log.warning("missed-reply send failed for %s/%s: %s", channel, ext, exc)
    if sent:
        _log.info("missed-reply sweep answered %d unattended DM(s)", sent)
    return sent
