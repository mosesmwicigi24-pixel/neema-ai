from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
import json
import httpx
from datetime import datetime, timezone, timedelta

from app.models.conversation import Conversation, InterceptMode
from app.models.message import Message, MsgDirection, MsgSender
from app.models.user import User
from app.models.order_event import OrderEvent
from app.models.customer_history import CustomerHistory
from app.models.session import Session
from app.models.intercept import Intercept, InterceptAction
from app.core.config import settings
from app.schemas.n8n import OutboundDto


# ── Shared timestamp helpers ──────────────────────────────

def _fmt_ts(dt: datetime | None) -> str:
    """UTC datetime → Firestore timestampValue string (no microseconds)."""
    if dt is None:
        dt = datetime.now(timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def _fmt_ts_ms(dt: datetime | None) -> str:
    """UTC datetime → timestampValue/tsIso with millisecond precision (.000Z)."""
    if dt is None:
        dt = datetime.now(timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"

def _fmt_precise(dt: datetime | None) -> str:
    """UTC datetime → createTime/updateTime string with microseconds."""
    if dt is None:
        dt = datetime.now(timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")

# Normalize wa_id by stripping leading + and whitespace to ensure consistent storage and lookup.
def _normalize_wa_id(wa_id: str) -> str:
    """Always store wa_id without a leading + to ensure consistent lookup."""
    return wa_id.lstrip("+").strip() if wa_id else wa_id


async def provision_user(
    db: AsyncSession,
    wa_id: str,
    *,
    name: str | None = None,
    last_text: str | None = None,
    last_direction: str | None = None,
) -> User:
    """Find-or-create the User row behind a wa_id and enrich it server-side.

    This is the single place that guarantees every conversation has a backing
    profile. It is server-AUTHORITATIVE for country (resolved from the dialing
    prefix, so it never depends on the n8n enrichment call landing) and it
    captures the WhatsApp profile name without ever clobbering a name an
    operator has confirmed.

    - name: only fills an empty, non-operator-confirmed name (the WhatsApp
      profile name). Operator edits set name_confirmed=True and win.
    - country/country_iso/flag_url: filled from the phone prefix whenever the
      row has no country yet.

    Caller owns the commit (this only flushes so the row is usable within the
    same transaction).
    """
    from app.core.countries import resolve_country

    wa_id = _normalize_wa_id(wa_id)
    result = await db.execute(select(User).where(User.wa_id == wa_id))
    user = result.scalar_one_or_none()
    created = False
    if user is None:
        user = User(wa_id=wa_id, phone=wa_id)
        db.add(user)
        created = True

    clean_name = (name or "").strip()
    if clean_name and not user.name_confirmed and not (user.name or "").strip():
        user.name = clean_name[:100]

    if not user.country:
        loc = resolve_country(wa_id)
        if loc["country"]:
            user.country = loc["country"]
            user.country_iso = loc["country_iso"]
            user.flag_url = loc["flag_url"]

    if last_text is not None:
        user.last_text = last_text
    if last_direction is not None:
        user.last_direction = last_direction
    if created or last_text is not None:
        user.last_message_at = datetime.now(timezone.utc)

    await db.flush()
    return user


# ── Intercept Gate ────────────────────────────────────────

async def outbound_gate(db: AsyncSession, redis, body: OutboundDto) -> dict:
    """
    Core logic: AI mode sends immediately; human mode holds the reply.

    Idempotency guard: the n8n workflow has both the audio gate
    (Outbound Gate API1 send Audio) and the text gate (Outbound Gate API)
    connecting to the same downstream If node. When a customer sends audio,
    n8n calls this endpoint twice — once with is_audio_reply=True (audio gate)
    and once with is_audio_reply=False (text gate, which fires even though the
    audio branch was taken, because If fires once per incoming connection).

    The guard matches on ai_reply text within a 30-second window regardless of
    media_type, so the audio row saved by the first call is found by the second
    call even though the second has is_audio=False and would otherwise miss the
    audio row (which has media_type='audio', not NULL).
    """
    from sqlalchemy import and_
    body.wa_id = _normalize_wa_id(body.wa_id)

    result = await db.execute(
        select(Conversation).where(Conversation.wa_id == body.wa_id)
    )
    conv = result.scalar_one_or_none()
    if not conv:
        conv = Conversation(wa_id=body.wa_id)
        db.add(conv)
        await db.flush()

    # ── Human intercept: hold the reply ──────────────────────────────────────
    if conv.intercept_mode == InterceptMode.human:
        intercept = Intercept(
            conversation_id=conv.id,
            agent_id=conv.assigned_agent_id,
            action=InterceptAction.intercept,
            ai_reply_held=body.ai_reply,
        )
        db.add(intercept)
        await _broadcast(redis, str(conv.id), {
            "type": "ai_draft_ready",
            "conversationId": str(conv.id),
            "waId": body.wa_id,
            "draft": body.ai_reply,
        })
        return {"action": "hold"}

    # ── Idempotency guard ─────────────────────────────────────────────────────
    # Match on (wa_id + outbound direction + same text + within 30s).
    # Intentionally does NOT filter on media_type so that a prior audio row
    # (media_type='audio') is found by the follow-up text-gate call
    # (is_audio=False), preventing a duplicate plain-text bubble.
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=30)
    existing = await db.execute(
        select(Message).where(
            and_(
                Message.wa_id == body.wa_id,
                Message.direction == MsgDirection.outbound,
                Message.text == body.ai_reply,
                Message.created_at >= cutoff,
            )
        )
    )
    if existing.scalar_one_or_none():
        return {"action": "send"}

    # ── Send to WhatsApp ──────────────────────────────────────────────────────
    is_audio = body.is_audio_reply and bool(body.audio_url)
    if is_audio:
        await _send_waba_audio(body.wa_id, body.audio_url)
        # Send the full text reply alongside audio only when cart content is present.
        # cart_text being non-empty is the signal (set by the n8n workflow only when
        # full_cart / items_added is non-empty). We send ai_reply — the complete
        # formatted message with the bullet-point order summary — rather than
        # cart_text alone, so the customer receives the full readable context.
        # Audio-only replies (greetings, questions, clarifications) have cart_text=""
        # and get no accompanying text message.
        if body.cart_text:
            # WhatsApp does not guarantee delivery order based solely on API call order.
            # The audio message is queued on WhatsApp's infrastructure and can be
            # overtaken by the text if it is sent immediately. A short delay gives
            # WhatsApp enough time to process and deliver the audio first so the
            # customer always hears the voice note before reading the order summary.
            import asyncio
            await asyncio.sleep(2)
            await _send_waba(body.wa_id, body.ai_reply)
    else:
        await _send_waba(body.wa_id, body.ai_reply)

    # ── Save exactly ONE outbound Message row ─────────────────────────────────
    msg = Message(
        wa_id=body.wa_id,
        conversation_id=conv.id,
        direction=MsgDirection.outbound,
        sender=MsgSender.ai,
        text=body.ai_reply,
        media_type="audio" if is_audio else None,
        media_url=body.audio_url if is_audio else None,
        media_caption=body.cart_text if (is_audio and body.cart_text) else None,
    )
    db.add(msg)

    conv.last_message_at      = datetime.now(timezone.utc)
    conv.last_message_preview = (body.ai_reply or "")[:100]

    await db.commit()
    await db.refresh(msg)

    ws_payload: dict = {
        "type":           "new_message",
        "id":             str(msg.id),
        "conversationId": str(conv.id),
        "sender":         "ai",
        "text":           body.ai_reply,
    }
    if is_audio:
        ws_payload["mediaType"]    = "audio"
        ws_payload["mediaUrl"]     = body.audio_url
        ws_payload["mediaCaption"] = body.cart_text or None

    await _broadcast(redis, str(conv.id), ws_payload)
    return {"action": "send"}


async def _send_waba_audio(wa_id: str, audio_url: str) -> None:
    """Send a pre-generated TTS audio file to WhatsApp via a public link."""
    url = (f"https://graph.facebook.com/{settings.waba_api_version}"
           f"/{settings.waba_phone_number_id}/messages")
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            url,
            headers={"Authorization": f"Bearer {settings.waba_token}"},
            json={
                "messaging_product": "whatsapp",
                "to": wa_id,
                "type": "audio",
                "audio": {"link": audio_url},
            },
            timeout=30.0,
        )
        if not resp.is_success:
            import logging
            logging.error(f"WABA audio error {resp.status_code}: {resp.text}")
            resp.raise_for_status()

# ── WABA Sender ───────────────────────────────────────────

async def _send_waba(wa_id: str, text: str) -> None:
    url = (f"https://graph.facebook.com/{settings.waba_api_version}"
           f"/{settings.waba_phone_number_id}/messages")
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            url,
            headers={"Authorization": f"Bearer {settings.waba_token}"},
            json={
                "messaging_product": "whatsapp",
                "to": wa_id,
                "type": "text",
                "text": {"body": text},
            },
        )
        if not resp.is_success:
            import logging
            logging.error(f"WABA error {resp.status_code}: {resp.text}")
            resp.raise_for_status()


# ── Redis Broadcast ───────────────────────────────────────

async def _broadcast(redis, channel: str, payload: dict) -> None:
    await redis.publish(f"ws:channel:{channel}", json.dumps(payload))


# ── Context ───────────────────────────────────────────────

import re as _re

# Trivial inbound messages that don't need the expensive reasoning model — a
# cheap templated reply (or a mini model) is enough. Kept deliberately small
# and high-precision so real sales questions never get short-circuited.
_GREETING_RE = _re.compile(
    r"^(hi+|hey+|hello+|helo+|habari|niaje|mambo|sasa|yo+|good\s*(morning|afternoon|evening)|"
    r"vipi|shalom)[\s!.,]*$",
    _re.IGNORECASE,
)
_ACK_RE = _re.compile(
    r"^(ok+(ay)?|k|kk|sawa|poa|noted|alright|got\s*it|sure|fine|yes+|no+|"
    r"thanks?|thank\s*you|asante(\s*sana)?|thx|ty|👍+|🙏+|❤️*|😊+|amen)[\s!.,🙏👍❤😊]*$",
    _re.IGNORECASE,
)


async def log_usage(db: AsyncSession, body) -> dict:
    """Persist one LLM call's token usage + estimated cost."""
    from app.models.ai_usage import AiUsage
    from app.core.ai_pricing import estimate_cost_usd

    cost = estimate_cost_usd(
        body.model, body.prompt_tokens, body.completion_tokens, body.cached_tokens
    )
    db.add(AiUsage(
        wa_id=_normalize_wa_id(body.wa_id) if body.wa_id else None,
        workflow=body.workflow,
        node=body.node,
        model=body.model,
        prompt_tokens=body.prompt_tokens,
        completion_tokens=body.completion_tokens,
        cached_tokens=body.cached_tokens,
        cost_usd=cost,
    ))
    await db.commit()
    return {"ok": True, "cost_usd": cost}


async def route_message(db: AsyncSession, redis, body) -> dict:
    """Decide how much intelligence THIS message deserves — server-side, no
    LLM tokens spent. Returns a decision n8n branches on:

      path: "skip" | "cheap" | "full"
      duplicate: WhatsApp re-delivered the same message id → don't answer twice
      intent_hint: greeting | ack | media | question
      canned_reply: a ready reply for greetings/acks (n8n may send as-is)
      cooldown_active / cooldown_seconds: the AI has answered a lot very
        recently — hold or hand to a human so a runaway loop can't rack up calls
    """
    wa_id = _normalize_wa_id(body.wa_id)
    text = (body.text or "").strip()
    decision = {
        "wa_id": wa_id, "path": "full", "duplicate": False,
        "intent_hint": "question", "canned_reply": None,
        "cooldown_active": False, "cooldown_seconds": 0,
    }

    # 1. Idempotency — a WhatsApp retry with the same id must not re-invoke GPT.
    if body.msg_id:
        seen_key = f"seen_msg:{body.msg_id}"
        try:
            if await redis.get(seen_key):
                decision["duplicate"] = True
                decision["path"] = "skip"
                return decision
            await redis.setex(seen_key, 6 * 3600, "1")
        except Exception:
            pass  # dedupe is best-effort; never block a real message

    # 2. Media always needs its own (vision/transcription) path.
    if body.media_type and body.media_type not in ("text", ""):
        decision["intent_hint"] = "media"
        return decision  # path stays "full"; media sub-workflows handle it

    # 3. Cool-off: count AI replies sent to this conversation in the last 60s.
    #    Beyond the threshold, tell n8n to hold — the "no time to cool off" fix.
    try:
        conv_res = await db.execute(select(Conversation).where(Conversation.wa_id == wa_id))
        conv = conv_res.scalar_one_or_none()
        if conv:
            since = datetime.now(timezone.utc) - timedelta(seconds=60)
            recent_ai = await db.execute(
                select(Message).where(
                    Message.conversation_id == conv.id,
                    Message.direction == MsgDirection.outbound,
                    Message.created_at >= since,
                )
            )
            n_recent = len(recent_ai.scalars().all())
            if n_recent >= 6:  # >6 AI replies in a minute = runaway loop
                decision["cooldown_active"] = True
                decision["cooldown_seconds"] = 60
    except Exception:
        pass

    # 4. Cheap-path classification (rule-based, high precision).
    if _GREETING_RE.match(text):
        decision.update(
            path="cheap", intent_hint="greeting",
            canned_reply="Hello and welcome to Bethany House! 🙏 How may I help you today?",
        )
    elif _ACK_RE.match(text):
        decision.update(path="cheap", intent_hint="ack", canned_reply="")

    return decision


async def ai_cost_summary(db: AsyncSession, days: int = 30) -> dict:
    """Aggregate token spend for the admin cost view."""
    from app.models.ai_usage import AiUsage
    from sqlalchemy import func

    since = datetime.now(timezone.utc) - timedelta(days=days)
    rows = (await db.execute(
        select(
            AiUsage.model,
            func.count().label("calls"),
            func.sum(AiUsage.prompt_tokens),
            func.sum(AiUsage.completion_tokens),
            func.sum(AiUsage.cached_tokens),
            func.sum(AiUsage.cost_usd),
        ).where(AiUsage.created_at >= since).group_by(AiUsage.model)
    )).all()

    by_model = [{
        "model": r[0], "calls": r[1],
        "prompt_tokens": int(r[2] or 0), "completion_tokens": int(r[3] or 0),
        "cached_tokens": int(r[4] or 0), "cost_usd": float(r[5] or 0),
    } for r in rows]

    total_cost = round(sum(m["cost_usd"] for m in by_model), 4)
    total_calls = sum(m["calls"] for m in by_model)
    return {
        "days": days,
        "total_cost_usd": total_cost,
        "total_calls": total_calls,
        "avg_cost_per_call": round(total_cost / total_calls, 6) if total_calls else 0,
        "by_model": sorted(by_model, key=lambda m: -m["cost_usd"]),
    }


async def get_profile(db: AsyncSession, redis, wa_id: str) -> dict:
    """One-call context bundle for the AI pipeline.

    Replaces the fragile n8n 'Customer Profile & Session Setup' assembly
    (RunQuery -> Bundle -> a chain of 'combine' merges that collapsed to 0
    items whenever a branch was empty, silently halting the agent before it
    ever replied). This is server-authoritative and ALWAYS returns a usable
    object: identity + resolved country, the recent message window in the
    shape n8n's 'Compose context' expects, session state/cart, and the live
    catalogue — everything the AI needs, in one robust payload.
    """
    from app.core.countries import resolve_country
    from app.models.catalog import Catalog

    wa_id = _normalize_wa_id(wa_id)
    user = await provision_user(db, wa_id)   # find-or-create + country enrichment
    await db.commit()
    await db.refresh(user)

    ctx = await get_context(db, redis, wa_id)

    # Recent messages, oldest->newest, in the bundled shape the pipeline reads.
    res = await db.execute(
        select(Message)
        .where(Message.wa_id == wa_id)
        .order_by(Message.created_at.desc())
        .limit(20)
    )
    rows = list(reversed(res.scalars().all()))
    messages = [{
        "id":        str(m.id),
        "wa_id":     wa_id,
        "name":      user.name or "",
        "direction": m.direction.value if hasattr(m.direction, "value") else str(m.direction or "inbound"),
        "sender":    m.sender.value if hasattr(m.sender, "value") else str(m.sender or "user"),
        "text":      m.text or "",
        "media_type": m.media_type or "",
        "mediaType": m.media_type or "",
        "media_url": m.media_url or "",
        "mediaUrl":  m.media_url or "",
        "ts_ms":     m.ts_ms or (int(m.created_at.timestamp() * 1000) if m.created_at else 0),
        "tsMs":      m.ts_ms or (int(m.created_at.timestamp() * 1000) if m.created_at else 0),
        "tsIso":     m.created_at.isoformat() if m.created_at else "",
        "created_at": m.created_at.isoformat() if m.created_at else "",
        "createdAt": m.created_at.isoformat() if m.created_at else "",
    } for m in rows]

    loc = resolve_country(wa_id)
    facts = {
        "name": user.name or "", "email": user.email, "phone": user.phone or wa_id,
        "location": user.location, "country": user.country, "country_iso": user.country_iso,
    }
    state = ctx.get("state") or {"active": "active", "cart": {"items": [], "subtotal": 0}}
    cart = state.get("cart") if isinstance(state.get("cart"), dict) else {"items": [], "subtotal": 0}

    cat_res = await db.execute(
        select(Catalog).where(Catalog.in_stock == True).order_by(Catalog.category, Catalog.name)
    )
    catalog = [{
        "sku": str(i.sku), "name": str(i.name), "category": str(i.category or ""),
        "price": float(i.price), "unit": str(i.unit or ""),
        "description": str(i.description or ""), "aliases": i.aliases or [], "in_stock": i.in_stock,
    } for i in cat_res.scalars().all()]

    last_in  = next((m["text"] for m in reversed(messages) if m["direction"] == "inbound"), "")
    last_out = next((m["text"] for m in reversed(messages) if m["direction"] == "outbound"), "")

    # ── Cost governor: should this turn spend the expensive model? ────────────
    # n8n gates the Conversation-Intelligence sub-workflow on `should_run_ai`.
    # This is the "give the AI time to cool off" fix + skip replies nobody needs.
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    recent_ai_replies = sum(
        1 for m in messages
        if m["direction"] == "outbound" and (now_ms - (m["tsMs"] or 0)) <= 60_000
    )
    li = (last_in or "").strip()
    is_ack = bool(_ACK_RE.match(li)) and not _GREETING_RE.match(li)
    should_run_ai, route_reason = True, "full"
    if recent_ai_replies >= 6:
        should_run_ai, route_reason = False, "cooldown"   # runaway loop → hold
    elif is_ack:
        should_run_ai, route_reason = False, "ack"         # "ok"/"thanks" → no reply needed

    return {
        "wa_id": wa_id,
        "should_run_ai": should_run_ai,
        "route_reason": route_reason,
        "name": user.name or "",
        "phone": user.phone or wa_id,
        "email": user.email,
        "location": user.location,
        "country": user.country,
        "countryName": user.country,
        "countryIso": user.country_iso,
        "countryCode": loc.get("code"),
        "flag_url": user.flag_url,
        "user": facts,
        "userFacts": facts,
        "messages": messages,
        "history": {
            "last10Messages": messages[-10:],
            "lastInbound": last_in,
            "lastOutbound": last_out,
        },
        "state": state,
        "cart": cart,
        "last_text": ctx.get("last_text"),
        "last_direction": ctx.get("last_direction"),
        "last_message_ts": ctx.get("last_message_ts"),
        "last_message_at": ctx.get("last_message_at"),
        "intercept_mode": ctx.get("intercept_mode"),
        "catalog": catalog,
        "mergeKey": 1,
    }


async def get_context(db: AsyncSession, redis, wa_id: str) -> dict:
    wa_id = _normalize_wa_id(wa_id)
    cache_key = f"context:{wa_id}"
    cached = await redis.get(cache_key)
    if cached:
        return json.loads(cached)

    result = await db.execute(select(User).where(User.wa_id == wa_id))
    user = result.scalar_one_or_none()

    last_message_at: datetime | None = user.last_message_at if user else None
    last_message_ts: int | None = (
        int(last_message_at.astimezone(timezone.utc).timestamp() * 1000)
        if last_message_at else None
    )
    last_message_at_iso: str | None = (
        last_message_at.astimezone(timezone.utc).isoformat()
        if last_message_at else None
    )

    # ── Intercept / handover context ──────────────────────────────────────────
    conv_result = await db.execute(
        select(Conversation).where(Conversation.wa_id == wa_id)
    )
    conv = conv_result.scalar_one_or_none()

    recent_intercept = None
    intercept_mode   = "ai"

    if conv:
        intercept_mode = conv.intercept_mode.value if conv.intercept_mode else "ai"

        intercept_result = await db.execute(
            select(Intercept)
            .where(Intercept.conversation_id == conv.id)
            .order_by(Intercept.created_at.desc())
            .limit(1)
        )
        last_intercept = intercept_result.scalar_one_or_none()
        if last_intercept:
            recent_intercept = {
                "action":   last_intercept.action.value,
                "agent_id": str(last_intercept.agent_id) if last_intercept.agent_id else None,
                "at":       last_intercept.created_at.isoformat() if last_intercept.created_at else None,
            }

    default_state = {"active": "active", "cart": {"items": [], "subtotal": 0}}

    ctx = {
        "wa_id":           wa_id,
        "state":           (user.state if (user and user.state) else default_state),
        "last_text":       user.last_text      if user else "",
        "last_direction":  user.last_direction if user else "inbound",
        "last_message_ts": last_message_ts,
        "last_message_at": last_message_at_iso,
        "intercept_mode":   intercept_mode,
        "recent_intercept": recent_intercept,
    }

    try:
        await redis.setex(cache_key, 3600, json.dumps(ctx))
    except Exception:
        pass  # Cache failure is non-fatal; always return the dict

    return ctx

# ── Get User ──────────────────────────────────────────────

async def get_user(db: AsyncSession, wa_id: str) -> dict:
    wa_id = _normalize_wa_id(wa_id)
    result = await db.execute(select(User).where(User.wa_id == wa_id))
    user = result.scalar_one_or_none()
    if not user:
        return {"found": False, "wa_id": wa_id}
    return {
        "found": True,
        "id": str(user.id),
        "wa_id": user.wa_id,
        "phone": user.phone,
        "name": user.name,
        "last_text": user.last_text,
        "last_direction": user.last_direction,
        "state": user.state,
    }


# ── Upsert User ───────────────────────────────────────────

async def upsert_user(db: AsyncSession, body) -> dict:
    # Find-or-create + server-side enrichment (name capture + country). This
    # fixes the long-standing bug where the old ON CONFLICT clause dropped the
    # WhatsApp profile name for returning customers and never set the country.
    user = await provision_user(
        db,
        body.wa_id,
        name=body.name,
        last_text=body.last_text,
        last_direction=body.last_direction,
    )
    if body.state:
        user.state = body.state
    await db.commit()
    return {"id": str(user.id), "wa_id": user.wa_id}


# ── Upsert Message ────────────────────────────────────────
# Stores media_type / media_url when present.
# Inbound media messages are automatically escalated to human mode so an
# agent can view the attachment and respond appropriately.
# Returns a Firestore-style document array so n8n can consume the output directly.

async def upsert_message(db: AsyncSession, redis, body) -> list:
    # Normalise wa_id so inbound and outbound messages always resolve to the
    # same Conversation row regardless of whether the '+' prefix is present.
    body.wa_id = _normalize_wa_id(body.wa_id)

    result = await db.execute(
        select(Conversation).where(Conversation.wa_id == body.wa_id)
    )
    conv = result.scalar_one_or_none()
    if not conv:
        conv = Conversation(wa_id=body.wa_id)
        db.add(conv)
        await db.flush()

    # Guarantee a backing profile for every conversation, capturing the
    # WhatsApp profile name (body.name) and resolving the country server-side.
    # Only inbound messages carry a trustworthy profile name.
    await provision_user(
        db,
        body.wa_id,
        name=body.name if body.direction == "inbound" else None,
        last_text=(body.text or None),
        last_direction=body.direction,
    )

    sender    = MsgSender.user       if body.direction == "inbound" else MsgSender.ai
    direction = MsgDirection.inbound if body.direction == "inbound" else MsgDirection.outbound

    media_type  = getattr(body, "media_type", None)
    media_url   = getattr(body, "media_url",  None)
    media_id    = getattr(body, "media_id",   None)
    mime_type   = getattr(body, "mime_type",  None)
    filename    = getattr(body, "filename",   None)
    # image_analysis is populated by the Product Image Recognition sub-workflow
    # (GPT-4o description of the image). It is stored in media_caption so the
    # UI ImageBubble can render it as a collapsible "Image analysis" toggle,
    # mirroring how audio transcriptions are stored and displayed.
    # If image_analysis is absent, fall back to any explicit media_caption sent.
    image_analysis = getattr(body, "image_analysis", None)
    media_caption  = image_analysis or getattr(body, "media_caption", None)

    ts_ms: int | None = getattr(body, "ts_ms", None)
    ts_iso_raw: str | None = getattr(body, "ts_iso", None)
    if not ts_ms and ts_iso_raw:
        try:
            ts_ms = int(
                datetime.fromisoformat(ts_iso_raw.replace("Z", "+00:00"))
                .timestamp() * 1000
            )
        except (ValueError, AttributeError):
            pass
    if not ts_ms:
        ts_ms = int(datetime.now(timezone.utc).timestamp() * 1000)

    msg = Message(
        conversation_id=conv.id,
        wa_id=body.wa_id,
        direction=direction,
        sender=sender,
        text=body.text or (media_caption or f"[{media_type} received]" if media_type else ""),
        media_type=media_type,
        media_url=media_url,
        media_id=media_id,
        media_caption=media_caption,
        mime_type=mime_type,
        filename=filename,
        ts_ms=ts_ms,
    )
    db.add(msg)

    # ── Selective auto-escalation for inbound media ───────────────────────────
    # Audio voice notes are handled end-to-end by the AI (transcribed by Whisper,
    # replied to with TTS audio). They must NOT escalate to human mode.
    #
    # Images are now also handled end-to-end by the AI via GPT-4o analysis
    # (Product Image Recognition sub-workflow). The analysis is stored in
    # media_caption and fed back into Neema as the "user message". Escalation
    # for images is driven explicitly by n8n via POST /api/n8n/escalate only
    # when the AI flags that the item cannot be identified from the catalog.
    #
    # Only video and document messages still require a human agent to review,
    # so those continue to auto-escalate.
    escalated = False
    is_ai_handled_media = (
        media_type == "audio"
        or bool(mime_type and mime_type.startswith("audio/"))
        or media_type == "image"
        or bool(mime_type and mime_type.startswith("image/"))
    )
    intercept_log = None
    if direction == MsgDirection.inbound and media_type and not is_ai_handled_media:
        if conv.intercept_mode != InterceptMode.human:
            conv.intercept_mode  = InterceptMode.human
            conv.intercept_since = datetime.now(timezone.utc)
            escalated = True
            # Write the Intercept row with created_at = message time + 1s so it
            # always sorts AFTER the inbound message that triggered the escalation.
            from app.models.intercept import Intercept, InterceptAction
            reason = (
                f"Customer sent a {media_type}"
                + (f" — agent review required")
            )
            intercept_log = Intercept(
                conversation_id=conv.id,
                agent_id=None,
                action=InterceptAction.intercept,
                note=reason,
                created_at=datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc) + timedelta(seconds=1),
            )
            db.add(intercept_log)

    await db.commit()
    await db.refresh(msg)

    # ── Broadcast WebSocket events ────────────────────────────────────────────
    await _broadcast(redis, str(conv.id), {
        "type":           "new_message",
        "conversationId": str(conv.id),
        "waId":           body.wa_id,
        "sender":         sender.value,
        "text":           msg.text,
        "mediaType":      media_type,
        "mediaId":        media_id,
        "mediaUrl":       media_url,
        "mediaCaption":   media_caption,
        "mimeType":       mime_type,
        "filename":       filename,
    })

    if escalated:
        reason = (
            f"Customer sent a {media_type}"
            + " — agent review required"
        )
        # Broadcast to all agents — anyone can pick it up
        await _broadcast(redis, "agents:all", {
            "event":          "notification",
            "type":           "human_transfer",
            "title":          f"Media received — {media_type}",
            "body":           f"{body.wa_id} sent a {media_type} — agent review required",
            "waId":           body.wa_id,
            "conversationId": str(conv.id),
            "mediaType":      media_type,
        })
        # Broadcast intercept_changed with reason so the frontend pill shows it
        await _broadcast(redis, str(conv.id), {
            "type":           "intercept_changed",
            "conversationId": str(conv.id),
            "mode":           "human",
            "eventKind":      "intercept",
            "eventReason":    reason,
        })

    # ── Build response ────────────────────────────────────────────────────────
    doc_id        = f"{msg.wa_id}_{ts_ms}"
    created_at    = msg.created_at or datetime.now(timezone.utc)
    ttl_expire_at = created_at + timedelta(days=120)
    ts_dt    = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
    ts_iso   = _fmt_ts_ms(ts_dt)
    ttl_iso  = _fmt_ts_ms(ttl_expire_at)
    now_str  = _fmt_precise(created_at)

    fields = {
        "tsMs":        {"integerValue": str(ts_ms)},
        "direction":   {"stringValue": str(direction.value)},
        "ttlExpireAt": {"timestampValue": ttl_iso},
        "text":        {"stringValue": msg.text or ""},
        "tsIso":       {"stringValue": ts_iso},
        "wa_id":       {"stringValue": body.wa_id},
    }

    if media_type:
        fields["mediaType"]    = {"stringValue": media_type}
    if media_id:
        fields["mediaId"]      = {"stringValue": media_id}
    if media_url:
        fields["mediaUrl"]     = {"stringValue": media_url}
    if media_caption:
        fields["mediaCaption"] = {"stringValue": media_caption}
    if mime_type:
        fields["mimeType"]     = {"stringValue": mime_type}
    if filename:
        fields["filename"]     = {"stringValue": filename}
    if escalated:
        fields["escalated"]    = {"booleanValue": True}

    # Expose the identity/message fields at the TOP LEVEL too — not just inside
    # the Firestore-style `fields` envelope. n8n's HTTP node makes this response
    # the new `$json`, and every downstream node (the debounce, and via it the
    # session setup, the AI, and reply dispatch) reads `$json.wa_id` etc.
    # directly. Without these top-level keys wa_id was empty all the way down,
    # so /context/{wa_id} 404'd and no reply was ever sent. Additive — the
    # nested `fields` and doc `name` are unchanged, so existing readers still work.
    result = {
        "name": f"projects/neema-6037c/databases/(default)/documents/messages/{doc_id}",
        "fields": fields,
        "createTime": now_str,
        "updateTime": now_str,
        # top-level identity/message fields for n8n expressions
        "wa_id": body.wa_id,
        "docid": doc_id,
        "tsMs": ts_ms,
        "tsIso": ts_iso,
        "text": msg.text or "",
        "direction": direction.value,
        "msgText": msg.text or "",
    }
    if media_type:
        result["media_type"] = media_type
    if media_url:
        result["media_url"] = media_url
    if media_caption:
        result["media_caption"] = media_caption
    return [result]

# ── Patch Message ─────────────────────────────────────────

async def patch_message(db: AsyncSession, docid: str, body) -> dict:
    """
    Patches an inbound message doc with its transcription/corrected text.

    The n8n 'patch inbound and outbound' node calls this with:
      - inbound_text  → corrected transcription for the inbound message
      - outbound_text → the AI reply text (NOT applied here — the outbound
                        Message row is already created by outbound_gate(), so
                        applying outbound_text here would overwrite the inbound
                        message's text field, causing a duplicate to appear in
                        the agent UI)
      - direction     → NOT applied; direction is set at insert time and must
                        never be changed by a patch, otherwise an inbound message
                        silently becomes outbound and renders on the wrong side.

    Only inbound_text updates are accepted. Everything else is a no-op.
    """
    from sqlalchemy import and_

    # ── Locate the message by UUID or by wa_id_tsMs composite key ────────────
    try:
        import uuid
        uuid.UUID(docid)
        result = await db.execute(
            select(Message).where(Message.id == docid)
        )
    except ValueError:
        # docid format: "{wa_id}_{ts_ms}" — strip '+' from wa_id so the lookup
        # matches the normalised form used when the message was inserted.
        parts = docid.rsplit("_", 1)
        if len(parts) == 2:
            wa_id = _normalize_wa_id(parts[0])
            ts_ms = parts[1]
            result = await db.execute(
                select(Message).where(
                    and_(
                        Message.wa_id == wa_id,
                        Message.ts_ms == int(ts_ms),
                    )
                )
            )
        else:
            return {"ok": False, "error": f"Invalid docid format: {docid}"}

    msg = result.scalar_one_or_none()
    if not msg:
        # Silently skip — the inbound message may not have been upserted yet
        # (e.g. audio path where Upsert inbound audio message runs in parallel).
        return {"ok": True, "skipped": True, "docid": docid}

    # ── Only update inbound_text ──────────────────────────────────────────────
    # outbound_text is intentionally ignored: the outbound reply is already
    # stored as its own Message row by outbound_gate(). Applying it here would
    # overwrite the inbound message's text field, making it render on the
    # wrong side of the thread and appear as a duplicate of the outbound reply.
    #
    # direction is intentionally ignored: it is set at insert time and must
    # never be mutated post-hoc or inbound messages flip to the outbound side.
    if body.inbound_text is not None:
        msg.text = body.inbound_text

    await db.commit()
    return {"ok": True, "message_id": str(msg.id)}

# ── Touch Session ─────────────────────────────────────────

async def touch_session(db: AsyncSession, body) -> list:
    from app.models.session import Session as SessionModel

    def parse_dt(val):
        if not val:
            return None
        if isinstance(val, datetime):
            return val
        return datetime.fromisoformat(val.replace("Z", "+00:00"))

    session_id = body.session_id or f"{body.wa_id}_{int(datetime.now(timezone.utc).timestamp())}"

    stmt = pg_insert(SessionModel).values(
        id=session_id,
        wa_id=body.wa_id,
        turns=body.turns,
        start_ts=parse_dt(body.start_ts),
        last_ts=parse_dt(body.last_ts),
    ).on_conflict_do_update(
        index_elements=["id"],
        set_={
            "turns": body.turns,
            "last_ts": parse_dt(body.last_ts),
        },
    )
    await db.execute(stmt)
    await db.commit()

    # Re-fetch the persisted row so timestamps reflect actual DB values
    result = await db.execute(select(SessionModel).where(SessionModel.id == session_id))
    row = result.scalar_one()

    now_precise = _fmt_precise(datetime.now(timezone.utc))

    return [
        {
            "name": f"projects/neema-6037c/databases/(default)/documents/sessions/{session_id}",
            "fields": {
                "turns":   {"integerValue": str(row.turns)},
                "lastTs":  {"timestampValue": _fmt_ts(row.last_ts)},
                "wa_id":   {"stringValue": row.wa_id},
                "startTs": {"timestampValue": _fmt_ts(row.start_ts)},
            },
            "createTime": _fmt_precise(row.start_ts),
            "updateTime": now_precise,
        }
    ]


# ── Get Messages ──────────────────────────────────────────

async def get_messages(db: AsyncSession, wa_id: str) -> list:
    wa_id = _normalize_wa_id(wa_id)
    result = await db.execute(
        select(Message)
        .where(Message.wa_id == wa_id)
        .order_by(Message.created_at.desc())
        .limit(50)
    )
    msgs = result.scalars().all()

    rows = []
    for m in msgs:
        created_at = m.created_at

        # ts_ms: prefer the stored ts_ms column; fall back to created_at
        if m.ts_ms is not None:
            ts_ms = m.ts_ms
        elif created_at:
            ts_ms = int(created_at.astimezone(timezone.utc).timestamp() * 1000)
        else:
            ts_ms = None

        # ts_iso: millisecond-precision ISO string for sorting consistency
        if ts_ms is not None:
            ts_iso = _fmt_ts_ms(datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc))
        elif created_at:
            ts_iso = _fmt_ts_ms(created_at.astimezone(timezone.utc))
        else:
            ts_iso = None

        rows.append({
            "id":         str(m.id),
            "wa_id":      m.wa_id,
            "direction":  m.direction,
            "sender":     m.sender,
            "text":       m.text,
            "media_type": m.media_type,
            "media_url":  m.media_url,
            "ts_ms":      ts_ms,       # integer ms — used by Bundle messages for sort
            "ts_iso":     ts_iso,      # ISO string with ms precision
            "created_at": created_at.isoformat() if created_at else None,
        })

    return rows


# ── Save User Facts ───────────────────────────────────────

async def save_user_facts(db: AsyncSession, body) -> dict:
    # Normalize wa_id — strip leading + to match how it's stored
    wa_id = (body.wa_id or "").lstrip("+").strip()
    
    result = await db.execute(select(User).where(User.wa_id == wa_id))
    user = result.scalar_one_or_none()
    if not user:
        return {"ok": False, "error": "User not found"}

    only_if_empty = getattr(body, 'only_if_empty', [])
    for field in ("name", "email", "phone", "location", "age", "country", "country_iso", "flag_url"):
        val = getattr(body, field, None)
        if val is None:
            continue
        if field in only_if_empty and getattr(user, field, None):
            continue
        setattr(user, field, val)

    await db.commit()
    return {"ok": True}


# ── Upsert Order Event ────────────────────────────────────

async def upsert_order_event(db: AsyncSession, body) -> dict:
    from app.models.order_event import OrderEvent

    event_id = f"{body.wa_id}_{int(datetime.now(timezone.utc).timestamp() * 1000)}"

    stmt = pg_insert(OrderEvent).values(
        id=event_id,
        wa_id=body.wa_id,
        session_id=body.session_id,
        event_type=body.event_type,
        items=body.items,
        subtotal=body.subtotal,
        currency=body.currency,
        status=body.status,
        payment_status=body.payment_status,
        fulfillment_status=body.fulfillment_status,
        reply_text=body.reply_text,
        channel=body.channel,
        state=body.state,
    ).on_conflict_do_update(
        index_elements=["id"],
        set_={
            "status": body.status,
            "payment_status": body.payment_status,
            "fulfillment_status": body.fulfillment_status,
            "reply_text": body.reply_text,
            "state": body.state,
            "items": body.items,
            "subtotal": body.subtotal,
        },
    )
    await db.execute(stmt)
    await db.commit()
    return {"ok": True, "event_id": event_id}


# ── Upsert Customer History ───────────────────────────────

async def upsert_customer_history(db: AsyncSession, body) -> dict:
    from app.models.customer_history import CustomerHistory

    stmt = pg_insert(CustomerHistory).values(
        wa_id=body.wa_id,
        last_status=body.last_status,
        has_open_order=body.has_open_order,
        last_event=body.last_event or {},
        last_chat={},
        last_order={},
        counts=body.counts or {},
    ).on_conflict_do_update(
        index_elements=["wa_id"],
        set_={
            "last_status": body.last_status,
            "has_open_order": body.has_open_order,
            "last_event": body.last_event or {},
            "counts": body.counts or {},
        },
    )
    await db.execute(stmt)
    await db.commit()
    return {"ok": True}