"""ManyChat relay → Neema. TikTok DMs, one brain everywhere.

TikTok has no public inbound-DM API for a business our size — ManyChat (an
official TikTok partner) owns that transport. Inside a ManyChat automation an
External Request action POSTs the subscriber's message here and maps the JSON
response onto a custom field, which the very next block sends back to the
customer. So, like web chat, this endpoint is synchronous request→reply — but
identity-keyed like Messenger/IG: the ManyChat subscriber id is the customer's
handle, there is no phone.

TikTok's physics (why this file is shaped the way it is):
  - ManyChat's External Request gives up at ~10s → we answer within a hard
    budget (settings.manychat_reply_budget_s, default 9s) or return a short
    resend line instead of letting the flow fall into its error branch.
  - Only ~10 automated replies per 48h window → every reply must count: the
    closer gate turns politeness ping-pong into silence (empty reply = the
    ManyChat flow's condition skips the send), and hold notes are redis-gated.
  - NO push API — a reply travels ONLY in this response. meta_send refuses the
    channel loudly; a human takes over in ManyChat Live Chat, not the inbox.
"""
import asyncio
import hmac
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.database import get_db
from app.models.conversation import InterceptMode
from app.models.message import Message, MsgDirection, MsgSender

router = APIRouter()
_log = logging.getLogger("neema.manychat")

CHANNEL = "tiktok"

# Delivered by ManyChat when the agent can't finish inside the budget: warm,
# short (it spends one of the 10-per-48h replies), and it tells the customer
# exactly how to get the real answer — resend, so the next turn starts clean.
_BUDGET_LINE = ("Samahani, nakuja! ⏳ Please send that once more in a few "
                "seconds — I'll have your answer ready.")

# First message after a human takes the thread. Sent once per 12h (redis-gated)
# so an intercepted customer isn't answered with silence — but the budget isn't
# burned again on every further message while the human types in ManyChat.
_HUMAN_LINE = "Asante — one of our team will reply to you right here shortly."


def verify_manychat_key(x_manychat_key: str = Header(...)):
    """Every ManyChat → API call must carry the shared secret. Constant-time
    compare; 503 if the key isn't configured (endpoint disabled until it is)."""
    expected = settings.manychat_webhook_key
    if not expected:
        raise HTTPException(status_code=503,
                            detail="ManyChat relay is not configured (MANYCHAT_WEBHOOK_KEY unset).")
    if not hmac.compare_digest(x_manychat_key or "", expected):
        raise HTTPException(status_code=401, detail="Invalid ManyChat key.")


class ManyChatIn(BaseModel):
    subscriber_id: str          # ManyChat contact id ({{user_id}}) — the identity key
    message: str                # {{last_text_input}} — what the customer just said
    name: str | None = None     # {{full_name}} — TikTok display name, may be a handle
    username: str | None = None  # TikTok username, if the flow can supply it
    # Guard rail, not a router: Meta channels have native webhooks, so a flow
    # misconfigured to relay anything but TikTok here must fail loudly instead
    # of minting phantom customers in the wrong namespace.
    channel: str | None = None


@router.post("/webhook", dependencies=[Depends(verify_manychat_key)])
async def manychat_webhook(body: ManyChatIn, request: Request,
                           db: AsyncSession = Depends(get_db)):
    if body.channel and body.channel.strip().lower() != CHANNEL:
        raise HTTPException(status_code=400,
                            detail=f"This relay serves TikTok only, got channel={body.channel!r}.")
    text = (body.message or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="message is required")
    if len(text) > 4000:
        text = text[:4000]
    sub_id = (body.subscriber_id or "").strip()
    if not sub_id:
        raise HTTPException(status_code=400, detail="subscriber_id is required")

    # Cutover guard: once the native Business Messaging channel is authorized
    # (routers/tiktok_webhook.py), IT owns TikTok — same DM would otherwise
    # arrive twice under two different identity namespaces. The relay answers
    # empty (the flow's condition sends nothing) until ManyChat is disconnected.
    from app.services import tiktok_native
    if await tiktok_native.native_live(db):
        return {"reply": "", "handled_by": "native"}

    redis = getattr(request.app.state, "redis", None)

    # Identity + conversation on the (tiktok, subscriber_id) spine — the same
    # find-or-create seam Messenger/IG use, so the person shows up in the CRM
    # and later merges with their WhatsApp self when a phone lands.
    from app.services.identity import resolve_or_create_person
    from app.services.channel import get_or_create_conversation
    raw: dict = {"source": "manychat"}
    if body.username:
        raw["username"] = body.username.strip()
    ident = await resolve_or_create_person(
        db, CHANNEL, sub_id,
        display_name=(body.name or "").strip() or None,
        raw_profile=raw, source="manychat")
    conv = await get_or_create_conversation(db, CHANNEL, sub_id,
                                            person_id=ident.person_id)

    db.add(Message(channel=CHANNEL, external_id=sub_id, wa_id=None,
                   conversation_id=conv.id, person_id=conv.person_id,
                   direction=MsgDirection.inbound, sender=MsgSender.user, text=text))
    conv.last_message_at = datetime.now(timezone.utc)
    conv.last_message_preview = text[:100]
    intercepted = conv.intercept_mode in (InterceptMode.human, InterceptMode.paused)
    await db.commit()

    try:
        from app.services.redis import broadcast
        await broadcast(redis, str(conv.id), {
            "type": "message", "conversationId": str(conv.id),
            "channel": CHANNEL, "sender": "user", "direction": "inbound", "text": text,
        })
    except Exception:
        pass

    # A human owns this thread (they reply from ManyChat Live Chat — the inbox
    # can't push to TikTok). Tell the customer once, then hold silence so the
    # 48h reply budget is saved for the human-side conversation.
    if intercepted:
        reply = _HUMAN_LINE
        if redis is not None:
            try:
                if not await redis.set(f"manychat:holdnote:{sub_id}", "1",
                                       nx=True, ex=12 * 3600):
                    reply = ""
            except Exception:
                pass
        if reply:
            await _save_reply(db, redis, sub_id, reply)
        return {"reply": reply, "handled_by": "human"}

    from app.agent.runtime import (run_turn, build_llm, route_model, _hold_line,
                                   closer_gate, mark_closer_answered)
    # Politeness ping-pong ends in silence, not another blessing — on TikTok
    # that silence is also a saved reply from the 10-per-48h budget.
    if await closer_gate(redis, CHANNEL, sub_id, text):
        return {"reply": "", "handled_by": "ai"}

    try:
        reply = await asyncio.wait_for(
            run_turn(db, redis, sub_id, text, build_llm(model=route_model(text)),
                     channel=CHANNEL, external_id=sub_id),
            timeout=settings.manychat_reply_budget_s)
        await mark_closer_answered(redis, CHANNEL, sub_id, text)
    except asyncio.TimeoutError:
        # ManyChat is about to give up — hand back the resend line while the
        # cancelled turn's tool work (cart, captured facts) stays committed, so
        # the retried turn picks up exactly where this one got slow.
        _log.warning("manychat turn overran %.1fs budget for %s",
                     settings.manychat_reply_budget_s, sub_id)
        try:
            await db.rollback()
        except Exception:
            pass
        reply = _BUDGET_LINE
    except Exception:
        _log.exception("manychat turn failed for %s", sub_id)
        # Same posture as web chat: a warm hold line as the reply AND a
        # dashboard flag so a human actually follows up (from ManyChat Live
        # Chat). The flag files at most once per 2h per subscriber.
        try:
            await db.rollback()
        except Exception:
            pass
        reply = _hold_line(CHANNEL)
        try:
            flag = True
            if redis is not None:
                flag = bool(await redis.set(f"agent:holdline:tiktok:{sub_id}", "1",
                                            nx=True, ex=7200))
            if flag:
                from app.models.intercept import Intercept, InterceptAction
                db.add(Intercept(conversation_id=conv.id, action=InterceptAction.flag,
                                 note="Neema's reply FAILED here (TikTok via ManyChat) — "
                                      "she sent a short hold message; please follow up "
                                      "from ManyChat Live Chat."))
                await db.commit()
        except Exception:
            _log.warning("manychat: hold flag failed for %s", sub_id)

    if reply:
        await _save_reply(db, redis, sub_id, reply)
    return {"reply": reply or "", "handled_by": "ai"}


async def _save_reply(db, redis, sub_id: str, reply: str) -> None:
    """Persist + broadcast what ManyChat will deliver — history must show only
    what the customer actually received. Best-effort: a bookkeeping failure
    must never cost the customer their answer."""
    try:
        from app.services.n8n_bridge import save_outbound_channel_message
        await save_outbound_channel_message(db, redis, CHANNEL, sub_id, reply)
    except Exception:
        _log.warning("manychat: saving outbound failed for %s", sub_id)
