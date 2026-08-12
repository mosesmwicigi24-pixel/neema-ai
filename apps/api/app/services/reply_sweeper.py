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
from app.models.message import Message, MsgDirection, MsgSender

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
        # A polite closer ("thanks", "I'll get back to you", "God bless") is not
        # a hanging question — rescuing it restarts the politeness ping-pong
        # the closer gate exists to end.
        from app.agent.runtime import is_closer
        if is_closer(t):
            return None, None
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


async def _unanswered_dms(since, until, limit: int):
    """Meta DM conversations (never comment threads) still in AI mode whose LATEST
    message is an inbound the customer is waiting on, created in (since, until)."""
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
                Message.comment_context.is_(None),
                Message.created_at < since,
                Message.created_at > until,
                Conversation.intercept_mode == InterceptMode.ai,
            )
            .order_by(Message.created_at.desc()).limit(limit)
        )
        return (await db.execute(q)).all()


# ── Cross-channel continuation ───────────────────────────────────────────────
# The window shut on THIS channel, but the person may have another door open —
# same identity spine, different conversation. Continuing there beats flagging
# a human: the customer hears back in minutes, on a channel they used within
# the last day, instead of waiting for someone to notice a flag.


async def _compose_bridge(db, redis, dest_conv, src_channel: str,
                          question: str) -> str:
    """Neema's own voice on the DESTINATION thread, bridging the stranded
    question across — read-only turn, so composing can never double-send."""
    from app.agent import runtime
    key = dest_conv.wa_id if dest_conv.channel == "whatsapp" else dest_conv.external_id
    src_label = {"messenger": "Messenger", "instagram": "Instagram",
                 "facebook": "Facebook"}.get(src_channel, src_channel)
    text = (
        f"[CROSS-CHANNEL CONTINUATION — not a customer message. On {src_label} "
        f'they asked: "{(question or "").strip()[:300]}" — and that channel can '
        "no longer be replied to. Compose the ONE warm message to send them "
        f"HERE instead: briefly bridge (you're picking their {src_label} "
        "question up here), then answer it or move it one step forward. Never "
        "mention windows, policies or systems — just continue the conversation.]"
    )
    reply = await runtime.run_turn(
        db, redis, wa_id=key, user_text=text, llm=runtime.build_llm(),
        channel=dest_conv.channel,
        external_id=(None if dest_conv.channel == "whatsapp" else dest_conv.external_id),
        read_only=True)
    return (reply or "").strip()


async def _try_continue_elsewhere(redis, conv, msg):
    """Continue a window-closed question on the same person's open channel.

    Returns True (continued — don't escalate), False (no door open — escalate),
    or "deferred" (a door exists but it's quiet hours in Nairobi; a Neema-
    initiated send waits for morning, and the row stays queued until then)."""
    if getattr(conv, "person_id", None) is None:
        return False
    async with AsyncSessionLocal() as db:
        sibs = (await db.execute(select(Conversation).where(
            Conversation.person_id == conv.person_id,
            Conversation.id != conv.id,
            # Never barge into a thread a human is working.
            Conversation.intercept_mode == InterceptMode.ai,
        ))).scalars().all()
        if not sibs:
            return False

        from app.services.hub_events import is_quiet_hours
        if is_quiet_hours(datetime.now(timezone.utc)):
            return "deferred"

        from app.services.conversation import messaging_window
        # WhatsApp first (the most-answered channel here), then most recent.
        sibs.sort(key=lambda s: (s.channel != "whatsapp",
                                 -(s.last_message_at.timestamp()
                                   if s.last_message_at else 0)))
        for sib in sibs:
            try:
                win = await messaging_window(db, sib)
            except Exception:
                continue
            if win.get("mode") != "open":
                continue
            text = await _compose_bridge(db, redis, sib, conv.channel, msg.text)
            if not text:
                return False
            from app.services.actions import _send
            await _send(db, redis, sib, text)
            # Explain the source thread to any human reading it — and this note
            # becomes its latest (outbound) message, so the sweep de-queues it.
            db.add(Message(
                channel=conv.channel, wa_id=conv.wa_id,
                external_id=getattr(conv, "external_id", None),
                person_id=conv.person_id, conversation_id=conv.id,
                direction=MsgDirection.outbound, sender=MsgSender.human_agent,
                text=(f"↪ The reply window closed here — Neema continued this "
                      f"conversation on {sib.channel} "
                      f"({sib.wa_id or sib.external_id})."),
                media_type="note",
            ))
            await db.commit()
            _log.info("cross-channel: %s question continued on %s (%s)",
                      conv.channel, sib.channel, sib.wa_id or sib.external_id)
            return True
    return False


async def _already_escalated_since(conv_id, inbound_at) -> bool:
    """True when this conversation was already handed to a human AFTER the
    customer's message — so the alert has been raised and judged once."""
    if inbound_at is None:
        return False
    from app.database import AsyncSessionLocal
    from app.models.intercept import Intercept, InterceptAction
    from sqlalchemy import func as _f
    try:
        async with AsyncSessionLocal() as db:
            n = (await db.execute(
                select(_f.count()).select_from(Intercept).where(
                    Intercept.conversation_id == conv_id,
                    Intercept.action.in_((InterceptAction.flag,
                                          InterceptAction.escalated)),
                    Intercept.created_at >= inbound_at,
                )
            )).scalar_one()
        return bool(n)
    except Exception:
        return False          # never let the guard itself block an escalation


async def escalate_window_closed(redis=None, *, window_h: int = 23,
                                 reachable_d: int = 7, limit: int = 20) -> int:
    """A DM whose Meta 24-hour window shut with the customer still unanswered:
    FIRST try to continue on another channel the same person has open (the
    identity spine knows their WhatsApp) — the customer hears back in minutes.
    Only when every door is shut, hand a human the thread (Meta gives human
    agents a 7-day window). Past 7 days even a human is locked out, so we
    stop there rather than flag something nobody can action.

    Escalation routes the thread out of AI mode, so the sweep skips it next
    tick. But a human who reads it and hands it BACK to Neema would be flagged
    all over again on the next pass — the same alert re-firing every few hours
    on a thread they have already judged. So it also refuses to flag anything
    already flagged since that customer message: one escalation per unanswered
    message, not one per release."""
    from app.agent.runtime import escalate_to_human
    now = datetime.now(timezone.utc)
    rows = await _unanswered_dms(now - timedelta(hours=window_h),
                                 now - timedelta(days=reachable_d), limit)
    n = 0
    for msg, conv in rows:
        text, media = _answerable_turn(msg.text, msg.media_type, msg.media_url)
        if text is None and media is None:
            continue                       # a bare sticker/file — nothing to answer
        if await _already_escalated_since(conv.id, msg.created_at):
            continue                       # a human has already seen this one
        # The limb: same person, different door. Best-effort — any failure
        # falls straight through to the human escalation it replaces.
        try:
            moved = await _try_continue_elsewhere(redis, conv, msg)
        except Exception as exc:
            _log.warning("cross-channel continuation failed for %s: %s",
                         conv.id, exc)
            moved = False
        if moved == "deferred":
            continue                       # quiet hours — stays queued for morning
        if moved:
            n += 1
            continue
        if await escalate_to_human(
            conv.channel, msg.external_id,
            "Customer is waiting and Meta's 24-hour window has closed — Neema can't "
            "reply. Please respond from here (human agents get a 7-day window).",
        ):
            n += 1
    if n:
        _log.info("window-closed sweep: handed %d unanswered DM(s) to a human", n)
    return n


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
