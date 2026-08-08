"""The initiative engine — planned actions with a veto window (plan B2).

Neema's follow-ups are visible rows FIRST (agent_actions), executed by a
leader-locked 60s loop. Routine ones fire on their own; sensitive ones flip to
needs_approval and wait for the operator's one tap.

The sensitivity gate (conservative on purpose):
  · deal total > KES 50,000
  · the conversation is human-held
  · ≥2 follow-ups already sent on this deal
  · outside the 24h messaging window (a free-form send would breach policy)

Sending only happens when AGENT_INITIATIVE=1; with the flag off the queue
still fills — the operator sees what Neema WOULD do, before trusting her to.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, func as sa_func

from app.core.config import settings

_log = logging.getLogger("neema.actions")

LEADER_KEY = "agentactions:leader"
SENSITIVE_TOTAL_KES = 50_000
MAX_AUTO_NUDGES = 2


async def upsert_follow_up(db, deal, *, due_at: datetime, kind: str,
                           reason: str) -> None:
    """One open planned action per deal — a newer promise reschedules it
    instead of stacking nags."""
    from app.models.agent_action import AgentAction
    row = (await db.execute(select(AgentAction).where(
        AgentAction.deal_id == deal.id,
        AgentAction.status.in_(("planned", "needs_approval"))
    ).limit(1))).scalar_one_or_none()
    if row is None:
        db.add(AgentAction(deal_id=deal.id, conversation_id=deal.conversation_id,
                           due_at=due_at, kind=kind, reason=reason[:500]))
    else:
        row.due_at = due_at
        row.kind = kind
        row.reason = reason[:500]
        row.status = "planned"


def deal_total(deal) -> float:
    total = 0.0
    for i in (deal.items_snapshot or []):
        try:
            total += float(i.get("price") or 0) * float(i.get("qty") or 1)
        except (TypeError, ValueError):
            pass
    return total


async def needs_approval(db, deal, conv, in_window: bool) -> str | None:
    """The reason this action must wait for a human — None when safe to auto-send."""
    from app.models.agent_action import AgentAction
    from app.models.conversation import InterceptMode
    if not in_window:
        return "outside the 24h messaging window"
    if conv is not None and conv.intercept_mode == InterceptMode.human:
        return "conversation is human-held"
    if deal is not None and deal_total(deal) > SENSITIVE_TOTAL_KES:
        return f"deal total above KES {SENSITIVE_TOTAL_KES:,}"
    if deal is not None:
        sent = (await db.execute(select(sa_func.count()).select_from(AgentAction).where(
            AgentAction.deal_id == deal.id,
            AgentAction.status == "sent"))).scalar_one()
        if (sent or 0) >= MAX_AUTO_NUDGES:
            return f"already nudged {sent} times"
    return None


async def _send_followup_template(db, redis, conv, action) -> bool:
    """Send a due follow-up (fit check / replenishment check-in) as the
    approved utility template (name / order / status placeholders). True when
    it went out."""
    import re
    from app.services import n8n_bridge as svc
    try:
        m = re.search(r"[Oo]rder\s+([A-Za-z0-9-]+)", action.reason or "")
        number = m.group(1) if m else "your recent order"
        first = ((getattr(conv, "contact_name", None) or "").split(" ") or ["there"])[0] or "there"
        if action.kind == "replenishment":
            number = m.group(1) if m else "your supplies"
            phrase = ("the check-in you asked for — about time for the next "
                      "round? Reply here and we'll plan your delivery")
        else:
            phrase = ("delivered a few days ago — how is it fitting? If anything "
                      "needs adjusting, we're glad to help")
        tpl = await svc.send_wa_template(conv.wa_id, settings.wa_event_template,
                                         settings.wa_event_lang,
                                         [first, number, phrase])
        await svc.save_outbound_message(
            db, redis, conv.wa_id,
            f"[template {settings.wa_event_template}] {action.kind} on {number}",
            waba_msg_id=(((tpl or {}).get("messages") or [{}])[0].get("id") or None))
        action.status = "sent"
        action.draft = f"[template] {action.kind} on {number}"
        await db.commit()
        _log.info("%s sent via template for %s", action.kind, conv.wa_id)
        return True
    except Exception as exc:
        _log.warning("%s template send failed for %s: %s", action.kind, conv.wa_id, exc)
        return False


async def _compose_follow_up(db, redis, conv, reason: str) -> str:
    from app.agent import runtime
    key = conv.wa_id if conv.channel == "whatsapp" else conv.external_id
    text = ("[SCHEDULED FOLLOW-UP — not a customer message. Time to keep the "
            f"commitment: {reason}. Compose the ONE short, warm message to send "
            "them now. If the commitment was to confirm something you still "
            "can't confirm, be honest and say you're still on it. Never repeat "
            "a message already sent; never pressure.]")
    return (await runtime.run_turn(
        db, redis, wa_id=key, user_text=text, llm=runtime.build_llm(),
        channel=conv.channel,
        external_id=(None if conv.channel == "whatsapp" else conv.external_id),
        read_only=True)).strip()


def _norm(s: str) -> str:
    return " ".join((s or "").lower().split())


async def _repeats_earlier(db, conv, text: str, *, look_back: int = 6) -> bool:
    """True when this follow-up is essentially something we already said.

    A promise like "let me check on that for you" is exactly the phrasing the
    composer is most likely to echo — and re-sending the stall hours later is
    worse than silence: it tells the customer we still haven't moved. The
    persona forbids it, but a prompt is not a guarantee, so this enforces it.
    """
    from app.models.message import Message, MsgDirection
    rows = (await db.execute(
        select(Message.text)
        .where(Message.conversation_id == conv.id,
               Message.direction == MsgDirection.outbound)
        .order_by(Message.created_at.desc())
        .limit(look_back)
    )).scalars().all()

    t = _norm(text)
    if not t:
        return True
    tw = set(t.split())
    for prev in rows:
        p = _norm(prev)
        if not p:
            continue
        if p == t:
            return True
        pw = set(p.split())
        if not pw or not tw:
            continue
        # Containment, not Jaccard: a short stall repeated inside a slightly
        # longer one is still the same non-answer.
        if len(tw & pw) / min(len(tw), len(pw)) >= 0.8:
            return True
    return False


async def _send(db, redis, conv, text: str) -> None:
    from app.services import n8n_bridge as svc
    recipient = conv.wa_id if conv.channel == "whatsapp" else conv.external_id
    if conv.channel == "whatsapp":
        wamid = await svc._send_waba(recipient, text)
        await svc.save_outbound_message(db, redis, recipient, text, waba_msg_id=wamid)
    else:
        from app.services.meta_send import send_to_channel
        await send_to_channel(conv.channel, recipient, text)
        await svc.save_outbound_channel_message(db, redis, conv.channel, recipient, text)


async def _notify(redis, title: str, body: str, conv=None) -> None:
    if redis is None:
        return
    payload = {"event": "notification", "type": "planned_action",
               "title": title, "body": body[:200]}
    if conv is not None:
        payload["conv_id"] = str(conv.id)
        payload["wa_id"] = conv.wa_id or conv.external_id
    try:
        await redis.publish("ws:channel:agents:all", json.dumps(payload))
    except Exception:
        pass


async def process_due(db, redis, *, now: datetime | None = None, limit: int = 10) -> int:
    """Execute every due planned action: gate → auto-send or needs_approval."""
    from app.models.agent_action import AgentAction
    from app.models.conversation import Conversation
    from app.models.deal import Deal
    from app.services.hub_events import _within_window, is_quiet_hours

    now = now or datetime.now(timezone.utc)
    if is_quiet_hours(now):
        return 0
    rows = (await db.execute(select(AgentAction).where(
        AgentAction.status == "planned",
        AgentAction.due_at <= now,
    ).order_by(AgentAction.due_at).limit(limit))).scalars().all()

    done = 0
    for action in rows:
        try:
            conv = (await db.get(Conversation, action.conversation_id)
                    if action.conversation_id else None)
            deal = (await db.get(Deal, action.deal_id)
                    if action.deal_id else None)
            if conv is None:
                action.status = "failed"
                action.reason = (action.reason or "") + " [no conversation]"
                await db.commit()
                continue
            # The deal may have closed since (paid, lost) — a follow-up on a
            # settled deal is noise, not initiative.
            if deal is not None and deal.status != "open":
                action.status = "vetoed"
                action.reason = (action.reason or "") + " [deal closed]"
                await db.commit()
                continue

            in_window = await _within_window(db, conv)
            gate = await needs_approval(db, deal, conv, in_window)
            # Fit-checks (~6 days after delivery) and customer-agreed
            # replenishment check-ins ("check with me in two weeks") come due
            # long after the WhatsApp window closed. Both are service
            # follow-ups on the customer's own transaction/request, so they
            # ride the approved UTILITY template instead of dying in the
            # approvals queue.
            if (gate == "outside the 24h messaging window"
                    and action.kind in ("fit_check", "replenishment")
                    and conv.channel == "whatsapp" and settings.wa_event_template
                    and settings.agent_initiative):
                if await _send_followup_template(db, redis, conv, action):
                    done += 1
                    continue
            if gate is not None:
                draft = ""
                try:
                    draft = await _compose_follow_up(db, redis, conv, action.reason or "follow up")
                except Exception:
                    pass
                action.status = "needs_approval"
                action.draft = draft or action.draft
                await db.commit()
                await _notify(redis, "⏳ Follow-up needs your approval",
                              f"{gate} — draft ready: {(draft or '')[:80]}", conv)
                continue

            if not settings.agent_initiative:
                # Flag off: leave it planned, visible — the trust-building mode.
                continue

            text = await _compose_follow_up(db, redis, conv, action.reason or "follow up")
            if not text:
                action.status = "failed"
                await db.commit()
                continue
            # Never nudge someone with a message they've already had. If the
            # composer only managed to echo an earlier line, a human rewords it.
            if await _repeats_earlier(db, conv, text):
                action.status = "needs_approval"
                action.draft = text
                await db.commit()
                _log.info("planned action %s held — draft repeats an earlier message",
                          action.id)
                await _notify(redis, "⏳ Follow-up needs a reword",
                              "Neema's draft repeats what she already said: "
                              f"{text[:80]}", conv)
                continue
            await _send(db, redis, conv, text)
            action.status = "sent"
            action.draft = text
            await db.commit()
            done += 1
            _log.info("planned action %s sent to %s", action.id,
                      conv.wa_id or conv.external_id)
        except Exception as exc:
            _log.warning("planned action %s failed: %s", action.id, exc)
            try:
                await db.rollback()
            except Exception:
                pass
    return done


async def actions_loop(redis) -> None:
    """60s tick, leader-locked — the heartbeat of Neema's initiative."""
    from app.database import AsyncSessionLocal
    while True:
        try:
            await asyncio.sleep(60)
            if redis is None:
                continue
            got = await redis.set(LEADER_KEY, "1", nx=True, ex=55)
            if not got:
                continue
            async with AsyncSessionLocal() as db:
                await process_due(db, redis)
            # Copilot C4 rides the same heartbeat: quiet human-held threads
            # get their once-a-day "take it back?" ping.
            try:
                from app.services.copilot import take_back_scan
                async with AsyncSessionLocal() as db:
                    await take_back_scan(db, redis)
            except Exception:
                pass
            # Inbound Meta photos/videos arrive as signed CDN links that expire
            # within days. Re-host anything still on one, so the inbox never
            # loses sight of what a customer actually sent.
            try:
                from app.services.meta_media import repair_pending
                async with AsyncSessionLocal() as db:
                    await repair_pending(db)
            except Exception as exc:
                _log.info("meta media repair skipped: %s", exc)
            # Outcome self-check (services/selfcheck.py): most subsystems here
            # are best-effort, so a broken one looks identical to a quiet one.
            # Hourly, leader-only; a failed tick is itself logged loudly.
            try:
                hour_key = "selfcheck:" + datetime.now(timezone.utc).strftime("%Y%m%d%H")
                if await redis.set(hour_key, "1", nx=True, ex=3600):
                    from app.services.selfcheck import run_checks
                    async with AsyncSessionLocal() as db:
                        await run_checks(db, redis)
            except Exception as exc:
                _log.warning("selfcheck tick failed: %s", exc)
            # Learning loops (plan D): 03:00 self-QA, 08:00 standup,
            # Sunday 07:00 weekly distillation — daily-guarded, leader-only.
            try:
                from datetime import datetime as _dt, timedelta as _td, timezone as _tz
                from app.jobs import self_qa as _qa
                nbo = _dt.now(_tz.utc) + _td(hours=3)
                today = nbo.strftime("%Y%m%d")
                if nbo.hour == 3 and await redis.set(f"selfqa:{today}", "1", nx=True, ex=86400):
                    async with AsyncSessionLocal() as db:
                        await _qa.run_qa(db)
                # 06:00: identify the page's recent posts BEFORE anyone
                # comments — comments look up, they never guess.
                if nbo.hour == 6 and await redis.set(f"postsweep:{today}", "1", nx=True, ex=86400):
                    from app.services.post_catalog import sweep_page_posts
                    async with AsyncSessionLocal() as db:
                        await sweep_page_posts(db, redis)
                if nbo.hour == 8 and await redis.set(f"standup:{today}", "1", nx=True, ex=86400):
                    async with AsyncSessionLocal() as db:
                        standup = await _qa.compose_standup(db)
                    await redis.publish("ws:channel:agents:all", json.dumps({
                        "event": "notification", "type": "standup",
                        "title": "☀️ Neema's morning standup",
                        "body": standup[:400]}))
                if (nbo.weekday() == 6 and nbo.hour == 7 and
                        await redis.set(f"distill:{nbo.strftime('%G%V')}", "1",
                                        nx=True, ex=8 * 86400)):
                    async with AsyncSessionLocal() as db:
                        await _qa.distill_weekly(db)
            except Exception as exc:
                _log.info("learning-loop tick skipped: %s", exc)
        except asyncio.CancelledError:
            return
        except Exception as exc:
            _log.warning("actions loop tick failed: %s", exc)
