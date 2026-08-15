"""TikTok Business Messaging webhook + owner OAuth — the ManyChat replacement.

Once the owner's TikTok Business Account authorizes our developer app
(GET /oauth/connect → TikTok consent → /oauth/callback), TikTok webhooks every
DM here in real time and Neema replies through services/tiktok_native.py —
asynchronous like WhatsApp/Messenger, not squeezed into ManyChat's 10s window.

Events (envelope: {event, user_openid: OUR business open_id, content: json-str}):
  im_receive_msg  — customer → us: persist on the (tiktok, customer_open_id)
                    spine, stamp their conversation id (the only address TikTok
                    lets us send to), and schedule the shared async agent turn.
  im_send_msg     — echo of OUR sends AND the owner typing in the TikTok app:
                    ours dedupe away on message_id; the owner's get persisted
                    as human replies so history stays whole and Neema knows a
                    human spoke.
  im_mark_read_msg — acknowledged, unused.

Auth: Tiktok-Signature header "t=<unix>,s=<hex>", HMAC-SHA256 of "{t}.{body}"
with the app secret, and a freshness bound. Inert (503) until the app secret
is configured — the standing convention for every channel here.
"""
import hashlib
import hmac
import json
import logging
import time
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.database import get_db
from app.models.conversation import InterceptMode
from app.models.message import Message, MsgDirection, MsgSender

router = APIRouter()
_log = logging.getLogger("neema.tiktok")

CHANNEL = "tiktok"
_SIG_TOLERANCE_S = 300


def _valid_signature(raw: bytes, header: str | None) -> bool:
    secret = settings.tiktok_app_secret
    if not header:
        return False
    parts = dict(p.split("=", 1) for p in header.split(",") if "=" in p)
    ts, sig = parts.get("t"), parts.get("s")
    if not ts or not sig:
        return False
    try:
        if abs(time.time() - int(ts)) > _SIG_TOLERANCE_S:
            return False
    except ValueError:
        return False
    expected = hmac.new(secret.encode(), f"{ts}.".encode() + raw, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, sig)


def _content_text(content: dict) -> str:
    """The words the agent should hear, whatever the message type. A shared
    video is a buying signal about THAT video's product — say so; media the
    API can't give us as text becomes an honest placeholder."""
    mtype = content.get("type")
    if mtype == "text":
        return ((content.get("text") or {}).get("body") or "").strip()
    if mtype == "share_post":
        url = (content.get("share_post") or {}).get("embed_url") or ""
        return f"[Customer shared one of our TikTok videos{': ' + url if url else ''} — they're asking about what's in it]"
    if mtype == "image":
        return "[Customer sent a photo]"
    return ""                                  # stickers etc. — nothing to answer


@router.post("/webhook/events")
async def events(request: Request, db: AsyncSession = Depends(get_db)):
    if not settings.tiktok_app_secret:
        return Response(status_code=503)
    raw = await request.body()
    if not _valid_signature(raw, request.headers.get("Tiktok-Signature")):
        _log.warning("tiktok webhook rejected: bad signature")
        return Response(status_code=403)
    try:
        event = json.loads(raw)
        content = json.loads(event.get("content") or "{}")
    except Exception:
        return Response(status_code=400)

    name = event.get("event")
    if name == "im_receive_msg":
        await _receive(db, request, event, content)
    elif name == "im_send_msg":
        await _echo(db, event, content)
    # im_mark_read_msg and anything newer: acknowledge and move on.
    return {"ok": True}


async def _receive(db: AsyncSession, request: Request, event: dict, content: dict) -> None:
    business_id = str(event.get("user_openid") or "")
    from_user = str(((content.get("from_user") or {}).get("id")) or "")
    conv_tt = str(content.get("conversation_id") or "")
    mid = str(content.get("message_id") or "")
    if not from_user or not conv_tt or from_user == business_id:
        return
    text = _content_text(content)

    # Idempotency: a redelivered webhook must not create a duplicate.
    if mid:
        dup = (await db.execute(
            select(Message.id).where(Message.channel == CHANNEL,
                                     Message.waba_msg_id == mid).limit(1)
        )).scalar_one_or_none()
        if dup is not None:
            return

    from app.services.identity import resolve_or_create_person
    from app.services.channel import get_or_create_conversation
    ident = await resolve_or_create_person(
        db, CHANNEL, from_user,
        display_name=(content.get("from") or "").strip() or None,
        raw_profile={"username": content.get("from"), "source": "tiktok_native",
                     "tt_conversation_id": conv_tt},
        source="tiktok_native")
    # The conversation id is our ONLY send address — keep it current even for
    # a returning identity (TikTok can re-thread).
    if (ident.raw_profile or {}).get("tt_conversation_id") != conv_tt:
        ident.raw_profile = {**(ident.raw_profile or {}), "tt_conversation_id": conv_tt}
    conv = await get_or_create_conversation(db, CHANNEL, from_user,
                                            person_id=ident.person_id)
    db.add(Message(channel=CHANNEL, external_id=from_user, wa_id=None,
                   conversation_id=conv.id, person_id=conv.person_id,
                   direction=MsgDirection.inbound, sender=MsgSender.user,
                   text=text or "[unsupported message]", waba_msg_id=mid or None))
    conv.last_message_at = datetime.now(timezone.utc)
    conv.last_message_preview = (text or "[media]")[:100]
    intercepted = conv.intercept_mode in (InterceptMode.human, InterceptMode.paused)
    await db.commit()

    redis = getattr(request.app.state, "redis", None)
    try:
        from app.services.redis import broadcast
        await broadcast(redis, str(conv.id), {
            "type": "message", "conversationId": str(conv.id),
            "channel": CHANNEL, "sender": "user", "direction": "inbound", "text": text,
        })
    except Exception:
        pass

    # A human owns the thread (and, native now: can actually answer from the
    # dashboard) — Neema stays out. Stickers and other empty turns get silence.
    if intercepted or not text:
        return
    from app.agent.runtime import schedule_meta_reply
    await schedule_meta_reply(redis, CHANNEL, from_user, text, dedup_id=mid or None)


async def _echo(db: AsyncSession, event: dict, content: dict) -> None:
    """Our own sends echo back (skip: already saved by the send path) — but a
    message the OWNER typed in the TikTok app is a human reply Neema must see."""
    mid = str(content.get("message_id") or "")
    to_user = str(((content.get("to_user") or {}).get("id")) or "")
    if not mid or not to_user:
        return
    dup = (await db.execute(
        select(Message.id).where(Message.channel == CHANNEL,
                                 Message.waba_msg_id == mid).limit(1)
    )).scalar_one_or_none()
    if dup is not None:
        return
    text = _content_text(content)
    if not text:
        return
    from app.services.channel import get_or_create_conversation
    conv = await get_or_create_conversation(db, CHANNEL, to_user)
    db.add(Message(channel=CHANNEL, external_id=to_user, wa_id=None,
                   conversation_id=conv.id, person_id=conv.person_id,
                   direction=MsgDirection.outbound, sender=MsgSender.human_agent,
                   text=text, waba_msg_id=mid))
    conv.last_message_at = datetime.now(timezone.utc)
    conv.last_message_preview = text[:100]
    await db.commit()


# ── owner OAuth (one-time connect; repeat only if the 30d refresh lapses) ────

def _verify_connect_key(key: str = ""):
    expected = settings.tiktok_connect_key
    if not expected:
        raise HTTPException(status_code=503,
                            detail="TikTok connect is not configured (TIKTOK_CONNECT_KEY unset).")
    if not hmac.compare_digest(key or "", expected):
        raise HTTPException(status_code=401, detail="Invalid connect key.")


@router.get("/oauth/connect", dependencies=[Depends(_verify_connect_key)])
async def oauth_connect(request: Request):
    """Owner-only door: mints a CSRF state and forwards to TikTok's consent
    screen. Open in a browser while logged into the business TikTok account."""
    from app.services import tiktok_native
    if not tiktok_native.configured():
        raise HTTPException(status_code=503,
                            detail="TikTok app not configured (TIKTOK_APP_ID/SECRET unset).")
    state = tiktok_native.mint_state()
    redis = getattr(request.app.state, "redis", None)
    if redis is not None:
        try:
            await redis.setex(f"tiktok:oauth:state:{state}", 600, "1")
        except Exception:
            pass
    return RedirectResponse(tiktok_native.authorize_url(state))


@router.get("/oauth/callback")
async def oauth_callback(request: Request, code: str = "", state: str = "",
                         db: AsyncSession = Depends(get_db)):
    from app.services import tiktok_native
    if not tiktok_native.configured():
        raise HTTPException(status_code=503, detail="TikTok app not configured.")
    redis = getattr(request.app.state, "redis", None)
    ok = False
    if redis is not None and state:
        try:
            ok = bool(await redis.getdel(f"tiktok:oauth:state:{state}"))
        except Exception:
            ok = False
    if not ok:
        raise HTTPException(status_code=403, detail="State mismatch — restart the connect flow.")
    if not code:
        raise HTTPException(status_code=400, detail="TikTok sent no code.")
    blob = await tiktok_native.exchange_code(db, code)
    username = ""
    try:
        username = (await tiktok_native.business_profile(db)).get("username") or ""
    except Exception:
        pass
    try:
        await tiktok_native.register_webhook()
    except Exception:
        _log.warning("tiktok webhook self-registration failed — set the callback "
                     "URL in the app portal instead", exc_info=True)
    return HTMLResponse(
        f"<h3>✅ TikTok connected{' as @' + username if username else ''}</h3>"
        f"<p>Business open_id: <code>{blob.get('business_id')}</code>. "
        "Neema now answers TikTok DMs natively — you can close this tab.</p>")
