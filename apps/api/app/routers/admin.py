from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File, Form
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, func, delete
from app.database import get_db
from app.models.conversation import Conversation, InterceptMode
from app.models.message import Message
from app.models.agent import Agent
from app.models.user import User
from app.models.person import Person, Identity
from app.models.intercept import Intercept, InterceptAction
from app.schemas.conversation import ConversationListItem, InterceptRequest
from app.services.conversation import (
    intercept_conversation, release_conversation,
    transfer_conversation, send_agent_reply, approve_draft, send_agent_media,
)
import jwt
from app.core.security import decode_token
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

router = APIRouter()
bearer = HTTPBearer()


async def get_current_agent(
    credentials: HTTPAuthorizationCredentials = Depends(bearer),
    db: AsyncSession = Depends(get_db),
):
    try:
        payload = decode_token(credentials.credentials)
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid token")

    result = await db.execute(select(Agent).where(Agent.id == payload["sub"]))
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent


# ── Conversations ─────────────────────────────────────────

@router.get("/conversations")
async def list_conversations(
    mode: str | None = None,
    db: AsyncSession = Depends(get_db),
    agent: Agent = Depends(get_current_agent),
):
    from sqlalchemy import and_, case, literal

    q = select(Conversation)
    if mode:
        q = q.where(Conversation.intercept_mode == mode)
    result = await db.execute(q)
    conversations = result.scalars().all()

    if not conversations:
        return []

    conv_ids = [c.id for c in conversations]
    wa_ids   = [c.wa_id for c in conversations]

    # ── Batch-load User names / metadata ─────────────────────────────────────
    user_map: dict[str, User] = {}
    u_res = await db.execute(select(User).where(User.wa_id.in_(wa_ids)))
    for u in u_res.scalars().all():
        user_map[u.wa_id] = u

    # ── Batch-load person display_names (names for phone-less Meta contacts) ──
    # WhatsApp names come from User (keyed on wa_id); Messenger/IG/Facebook have
    # no wa_id, so their name lives on the resolved person (enriched from the FB
    # comment name or the Messenger profile API). Without this they read "Unknown".
    person_ids = [c.person_id for c in conversations if getattr(c, "person_id", None)]
    person_map: dict = {}
    if person_ids:
        p_res = await db.execute(select(Person).where(Person.id.in_(person_ids)))
        for p in p_res.scalars().all():
            person_map[p.id] = p

    # ── Profile photos (Messenger/IG avatars) keyed by person ────────────────
    # Stored on the identity's raw_profile by the DM enrichment. Meta pic URLs can
    # expire, so the frontend falls back to the initial if the image 404s.
    avatar_map: dict = {}
    if person_ids:
        id_res = await db.execute(select(Identity).where(Identity.person_id.in_(person_ids)))
        for idn in id_res.scalars().all():
            pic = (idn.raw_profile or {}).get("profile_pic")
            if pic and idn.person_id not in avatar_map:
                avatar_map[idn.person_id] = pic

    def _pstate(c: Conversation) -> dict:
        p = person_map.get(getattr(c, "person_id", None))
        return (getattr(p, "state", None) or {}) if p else {}

    def _list_country(c: Conversation) -> tuple:
        """(country_iso, flag_url) for the row: stored User → person.state → the
        contact's own phone prefix (external_id/wa_id). The phone fallback fills
        the flag for a Meta contact whose number is their key, with no backfill."""
        from app.core.countries import resolve_country
        from app.core.phone import is_plausible_phone
        u = user_map.get(c.wa_id)
        ps = _pstate(c)
        iso = (u.country_iso if u else None) or ps.get("country_iso")
        flag = (u.flag_url if u else None) or ps.get("flag_url")
        if not iso:
            handle = (u.phone if u and u.phone else None) or c.wa_id or getattr(c, "external_id", None)
            if handle and is_plausible_phone(handle):
                loc = resolve_country(handle)
                iso, flag = loc.get("country_iso"), loc.get("flag_url")
        return iso, flag

    def _name_for(c: Conversation):
        u = user_map.get(c.wa_id)
        if u and u.name:
            return u.name
        p = person_map.get(getattr(c, "person_id", None))
        return p.display_name if p else None

    # ── Batch-load assigned agent names ──────────────────────────────────────
    agent_ids = [c.assigned_agent_id for c in conversations if c.assigned_agent_id]
    agent_map: dict[str, str] = {}
    if agent_ids:
        a_res = await db.execute(select(Agent).where(Agent.id.in_(agent_ids)))
        for a in a_res.scalars().all():
            agent_map[str(a.id)] = a.name or ""

    # ── Batch-load latest message per conversation for preview + true sort ───
    latest_sub = (
        select(
            Message.conversation_id,
            func.max(Message.created_at).label("max_at"),
        )
        .where(Message.conversation_id.in_(conv_ids))
        .where(Message.media_type.is_(None) | (Message.media_type != "note"))
        .group_by(Message.conversation_id)
        .subquery()
    )
    latest_q = select(Message).join(
        latest_sub,
        (Message.conversation_id == latest_sub.c.conversation_id)
        & (Message.created_at == latest_sub.c.max_at),
    )
    preview_map: dict[str, tuple[str, str]] = {}
    for m in (await db.execute(latest_q)).scalars().all():
        cid = str(m.conversation_id)
        ts  = m.created_at.isoformat() if m.created_at else None
        preview_map[cid] = (m.text or "", ts)

    # ── Compute unread per conversation ───────────────────────────────────────
    last_outbound_sub = (
        select(
            Message.conversation_id,
            func.max(Message.created_at).label("last_out_at"),
        )
        .where(Message.conversation_id.in_(conv_ids))
        .where(Message.direction == "outbound")
        .where(Message.media_type.is_(None) | (Message.media_type != "note"))
        .group_by(Message.conversation_id)
        .subquery()
    )

    unread_q = (
        select(
            Message.conversation_id,
            func.count().label("unread"),
        )
        .outerjoin(
            last_outbound_sub,
            Message.conversation_id == last_outbound_sub.c.conversation_id,
        )
        .where(Message.conversation_id.in_(conv_ids))
        .where(Message.direction == "inbound")
        .where(
            last_outbound_sub.c.last_out_at.is_(None)
            | (Message.created_at > last_outbound_sub.c.last_out_at)
        )
        .group_by(Message.conversation_id)
    )
    unread_map: dict[str, int] = {}
    for row in (await db.execute(unread_q)).all():
        unread_map[str(row.conversation_id)] = row.unread

    # ── Build response, sorted by true latest-message timestamp desc ──────────
    def sort_key(c: Conversation):
        entry = preview_map.get(str(c.id))
        if entry and entry[1]:
            return entry[1]
        if c.last_message_at:
            return c.last_message_at.isoformat()
        return c.created_at.isoformat() if c.created_at else ""

    conversations.sort(key=sort_key, reverse=True)

    return [
        {
            "id":                   str(c.id),
            "wa_id":                c.wa_id,
            # Channel-native handle (wa_id | PSID | IGSID). == wa_id for WhatsApp,
            # but the ONLY customer key for Messenger/IG/FB (whose wa_id is null),
            # so the panel can load + save their profile.
            "external_id":          getattr(c, "external_id", None),
            "intercept_mode":       c.intercept_mode,
            "assigned_agent_id":    str(c.assigned_agent_id) if c.assigned_agent_id else None,
            "assigned_agent_name":  agent_map.get(str(c.assigned_agent_id), "") if c.assigned_agent_id else None,
            "intercept_since":      c.intercept_since.isoformat() if c.intercept_since else None,
            "last_message_at":      preview_map[str(c.id)][1] if str(c.id) in preview_map else (
                                        c.last_message_at.isoformat() if c.last_message_at else None
                                    ),
            "last_message":         preview_map.get(str(c.id), (c.last_message_preview or "", None))[0],
            "last_message_preview": preview_map.get(str(c.id), (c.last_message_preview or "", None))[0],
            "status":               c.status,
            "created_at":           c.created_at.isoformat() if c.created_at else None,
            "updated_at":           c.updated_at.isoformat() if c.updated_at else None,
            "name":                 _name_for(c),
            "avatar_url":           avatar_map.get(getattr(c, "person_id", None)),
            "country_iso":          _list_country(c)[0],
            "flag_url":             _list_country(c)[1],
            "channel":              getattr(c, "channel", "whatsapp") or "whatsapp",
            "unread":               unread_map.get(str(c.id), 0),
            "tags":                 (user_map[c.wa_id].state or {}).get("tags", []) if c.wa_id in user_map else [],
        }
        for c in conversations
    ]


@router.get("/conversations/{conv_id}/messages")
async def get_thread(
    conv_id: str,
    db: AsyncSession = Depends(get_db),
    agent: Agent = Depends(get_current_agent),
):
    """
    Return the full conversation timeline: regular chat messages interleaved
    with system-event items (escalations, intercepts, releases, transfers).

    Every item in the returned list has a `type` field:
      - "message"      → normal chat bubble
      - "system_event" → inline timeline divider with event_kind + event_reason
    """
    # ── 1. Fetch messages ─────────────────────────────────────────────────────
    msg_result = await db.execute(
        select(Message)
        .where(Message.conversation_id == conv_id)
        .order_by(Message.created_at.asc())
    )
    msgs = msg_result.scalars().all()

    # Batch-load agent names referenced by messages to avoid N+1
    msg_agent_ids = [m.agent_id for m in msgs if m.agent_id]
    agent_name_map: dict[str, str] = {}
    if msg_agent_ids:
        a_res = await db.execute(select(Agent).where(Agent.id.in_(msg_agent_ids)))
        for a in a_res.scalars().all():
            agent_name_map[str(a.id)] = a.name

    # ── 2. Fetch intercept events (activity log rows) ─────────────────────────
    # We surface escalated, flag, intercept, release, and transfer actions.
    # approve_draft is skipped — it's implicit from the AI message that follows.
    SURFACED_ACTIONS = {
        InterceptAction.escalated,
        InterceptAction.flag,
        InterceptAction.intercept,
        InterceptAction.release,
        InterceptAction.transfer,
    }

    evt_result = await db.execute(
        select(Intercept)
        .where(Intercept.conversation_id == conv_id)
        .where(Intercept.action.in_(SURFACED_ACTIONS))
        .order_by(Intercept.created_at.asc())
    )
    events = evt_result.scalars().all()

    # Batch-load agent names referenced by events
    evt_agent_ids = [e.agent_id for e in events if e.agent_id]
    all_agent_ids = list(set(msg_agent_ids + evt_agent_ids))
    if evt_agent_ids:
        extra_agents = [aid for aid in evt_agent_ids if str(aid) not in agent_name_map]
        if extra_agents:
            ea_res = await db.execute(select(Agent).where(Agent.id.in_(extra_agents)))
            for a in ea_res.scalars().all():
                agent_name_map[str(a.id)] = a.name

    # ── 3. Shape messages into thread items ───────────────────────────────────
    thread: list[dict] = []

    for m in msgs:
        thread.append({
            "id":            str(m.id),
            "type":          "message",
            "direction":     m.direction,
            "sender":        m.sender,
            "text":          m.text,
            "isNote":        m.media_type == "note",
            "agent_name":    agent_name_map.get(str(m.agent_id)) if m.agent_id else None,
            "created_at":    m.created_at.isoformat() if m.created_at else None,
            # ── Media ────────────────────────────────────────────────────────
            "media_type":    m.media_type if m.media_type != "note" else None,
            "media_id":      m.media_id,
            "media_url":     m.media_url,
            "media_caption": m.media_caption,
            "mime_type":     m.mime_type,
            "filename":      m.filename,
            # Source-post context for FB/IG comment messages (what it replies to)
            "comment_context": m.comment_context,
        })

    # ── 4. Shape intercept events into system_event thread items ──────────────
    # Human-readable labels for each action shown in the timeline pill
    ACTION_LABEL: dict[InterceptAction, str] = {
        InterceptAction.escalated: "Escalated — needs human",
        InterceptAction.flag:      "Flagged: Needs Attention",
        InterceptAction.intercept: "Picked up by agent",
        InterceptAction.release:   "Released to AI",
        InterceptAction.transfer:  "Transferred",
    }

    # Build a quick lookup: messages that arrived before each event timestamp
    # so we can auto-detect the escalation cause for agentless intercepts.
    msg_list = sorted(msgs, key=lambda m: m.created_at or "")

    for e in events:
        agent_name = agent_name_map.get(str(e.agent_id)) if e.agent_id else None

        label = ACTION_LABEL.get(e.action, e.action)
        if e.action == InterceptAction.intercept and agent_name:
            label = f"Picked up by {agent_name}"
        elif e.action == InterceptAction.release and agent_name:
            label = f"Released to AI by {agent_name}"
        elif e.action == InterceptAction.transfer and e.note:
            label = f"Transferred — {e.note}"

        # ── Auto-derive reason for agentless intercepts (media escalations) ──
        # When no agent triggered the intercept it was auto-escalated by the
        # system because of inbound media or a media request.  Look at messages
        # that arrived just before this event to identify which case it is.
        auto_reason: str | None = None
        if e.action == InterceptAction.intercept and not e.agent_id:
            evt_ts = e.created_at
            preceding = [
                m for m in msg_list
                if m.created_at and evt_ts and m.created_at <= evt_ts
            ]
            has_inbound_media = any(
                m.direction == "inbound" and m.media_type and m.media_type != "note"
                for m in preceding[-10:]  # check last 10 messages before event
            )
            if has_inbound_media:
                auto_reason = (
                    "Customer sent a media file (image, document, or audio) "
                    "that the AI cannot process. An agent needs to review and respond."
                )
            else:
                auto_reason = (
                    "Customer requested media or files that the AI cannot send. "
                    "An agent needs to take over to fulfil this request."
                )

        thread.append({
            "id":           f"evt-{e.id}",
            "type":         "system_event",
            "direction":    "outbound",
            "sender":       "ai",
            "text":         label,
            "created_at":   e.created_at.isoformat() if e.created_at else None,
            # ── Timeline-specific fields ──────────────────────────────────
            "event_kind":   e.action.value,
            # For escalated rows: use note. For agentless intercepts: use auto_reason.
            "event_reason": (
                e.note if e.action == InterceptAction.escalated
                else auto_reason
            ),
            "agent_name":   agent_name,
        })

    # ── 5. Sort merged timeline by created_at ascending ───────────────────────
    thread.sort(key=lambda x: x["created_at"] or "")

    return thread


@router.get("/conversations/{conv_id}/latest-draft")
async def get_latest_draft(
    conv_id: str,
    db: AsyncSession = Depends(get_db),
    agent: Agent = Depends(get_current_agent),
):
    """Return the most recent held AI draft for this conversation, if any."""
    result = await db.execute(
        select(Intercept)
        .where(Intercept.conversation_id == conv_id)
        .where(Intercept.ai_reply_held.isnot(None))
        .order_by(Intercept.created_at.desc())
        .limit(1)
    )
    intercept = result.scalar_one_or_none()
    return {"draft": intercept.ai_reply_held if intercept else None}


@router.post("/conversations/{conv_id}/generate-draft")
async def generate_draft(
    conv_id: str,
    db: AsyncSession = Depends(get_db),
    agent: Agent = Depends(get_current_agent),
):
    """
    Generate a fresh AI draft reply based on the last 10 messages
    in the conversation. Uses the OpenAI API directly.
    """
    from openai import OpenAI
    from app.core.config import settings

    conv_result = await db.execute(
        select(Conversation).where(Conversation.id == conv_id)
    )
    conv = conv_result.scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    msg_result = await db.execute(
        select(Message)
        .where(Message.conversation_id == conv_id)
        .order_by(Message.created_at.desc())
        .limit(10)
    )
    recent = list(reversed(msg_result.scalars().all()))

    if not recent:
        raise HTTPException(status_code=422, detail="No messages to draft from")

    history_lines = []
    for m in recent:
        role = "Customer" if m.direction == "inbound" else "Agent/AI"
        history_lines.append(f"{role}: {m.text}")
    history = "\n".join(history_lines)

    try:
        client = OpenAI(api_key=settings.openai_api_key)
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            max_tokens=500,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are assisting a human support agent at Bethany House, "
                        "a Catholic goods supplier in Nairobi. "
                        "Based on the conversation history below, draft a helpful, "
                        "warm, and concise WhatsApp reply the agent can send to the customer. "
                        "Write only the reply text — no preamble, no labels, no explanation. "
                        "UK spelling. Max 300 characters."
                    ),
                },
                {
                    "role": "user",
                    "content": f"Conversation so far:\n\n{history}\n\nDraft a reply for the agent to send next.",
                },
            ],
        )
        draft = response.choices[0].message.content.strip()
    except Exception as e:
        raise HTTPException(
            status_code=502,
            detail=f"Draft generation failed: {str(e)}"
        )

    return {"draft": draft}


@router.post("/conversations/{conv_id}/note")
async def add_note(
    conv_id: str,
    body: dict,
    db: AsyncSession = Depends(get_db),
    agent: Agent = Depends(get_current_agent),
):
    """Save an internal agent note against the conversation thread."""
    text = body.get("text", "").strip()
    if not text:
        raise HTTPException(status_code=422, detail="text is required")

    result = await db.execute(select(Conversation).where(Conversation.id == conv_id))
    conv = result.scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    msg = Message(
        wa_id=conv.wa_id,
        conversation_id=conv.id,
        direction="outbound",
        sender="human_agent",
        text=text,
        media_type="note",
        agent_id=agent.id,
    )
    db.add(msg)
    await db.commit()
    await db.refresh(msg)

    return {
        "id": str(msg.id),
        "type": "message",
        "direction": "outbound",
        "sender": "human_agent",
        "text": text,
        "isNote": True,
        "created_at": msg.created_at.isoformat() if msg.created_at else None,
    }


@router.post("/conversations/{conv_id}/intercept")
async def intercept(conv_id: str, request: Request, db: AsyncSession = Depends(get_db),
                    agent: Agent = Depends(get_current_agent)):
    return await intercept_conversation(db, conv_id, agent, request.app.state.redis)


@router.post("/conversations/{conv_id}/reply")
async def reply(conv_id: str, request: Request, body: dict, db: AsyncSession = Depends(get_db),
                agent: Agent = Depends(get_current_agent)):
    text = body.get("text", "")
    if not text:
        raise HTTPException(status_code=422, detail="text is required")
    return await send_agent_reply(db, conv_id, agent, text, request.app.state.redis)


@router.post("/conversations/{conv_id}/approve-draft")
async def approve(conv_id: str, request: Request, db: AsyncSession = Depends(get_db),
                  agent: Agent = Depends(get_current_agent)):
    try:
        body = await request.json()
    except Exception:
        body = {}
    return await approve_draft(db, conv_id, agent, body.get("text") if isinstance(body, dict) else None, request.app.state.redis)


@router.post("/conversations/{conv_id}/release")
async def release(conv_id: str, request: Request, db: AsyncSession = Depends(get_db),
                  agent: Agent = Depends(get_current_agent)):
    return await release_conversation(db, conv_id, agent, request.app.state.redis)


@router.post("/conversations/{conv_id}/close")
async def close_conv(conv_id: str, db: AsyncSession = Depends(get_db),
                     agent: Agent = Depends(get_current_agent)):
    from app.models.conversation import ConvStatus
    result = await db.execute(select(Conversation).where(Conversation.id == conv_id))
    conv = result.scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    conv.status = ConvStatus.closed
    await db.commit()
    return {"ok": True, "status": "closed"}


@router.post("/conversations/{conv_id}/transfer")
async def transfer(conv_id: str, request: Request, body: dict, db: AsyncSession = Depends(get_db),
                   agent: Agent = Depends(get_current_agent)):
    agent_id = body.get("agentId") or body.get("agent_id")
    if not agent_id:
        raise HTTPException(status_code=422, detail="agentId or agent_id required")
    return await transfer_conversation(db, conv_id, agent, agent_id, request.app.state.redis)


# ── Media upload + send ───────────────────────────────────────────────────────

@router.post("/conversations/{conv_id}/upload-media")
async def upload_media(
    conv_id: str,
    request: Request,
    file: UploadFile = File(...),
    caption: str | None = Form(None),
    db: AsyncSession = Depends(get_db),
    agent: Agent = Depends(get_current_agent),
):
    import aiofiles, os, uuid, mimetypes
    from app.core.config import settings

    ALLOWED_MIME = {
        "image/jpeg", "image/png", "image/webp", "image/gif",
        "application/pdf", "application/msword",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.ms-excel",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "video/mp4", "video/3gpp",
        "audio/ogg", "audio/aac", "audio/mpeg",
    }

    ct = file.content_type or mimetypes.guess_type(file.filename or "")[0] or ""
    if ct not in ALLOWED_MIME:
        raise HTTPException(status_code=415, detail=f"Unsupported media type: {ct}")

    if ct.startswith("image/"):
        waba_type = "image"
    elif ct.startswith("video/"):
        waba_type = "video"
    elif ct.startswith("audio/"):
        waba_type = "audio"
    else:
        waba_type = "document"

    from app.routers.media import MEDIA_DIR
    media_dir = MEDIA_DIR
    os.makedirs(media_dir, exist_ok=True)
    ext = os.path.splitext(file.filename or "file")[1] or (mimetypes.guess_extension(ct) or "")
    saved_name = f"{uuid.uuid4().hex}{ext}"
    file_path  = os.path.join(media_dir, saved_name)

    async with aiofiles.open(file_path, "wb") as f:
        content = await file.read()
        await f.write(content)

    public_base = getattr(settings, "media_public_url", "").rstrip("/")
    if not public_base:
        raise HTTPException(
            status_code=500,
            detail="MEDIA_PUBLIC_URL is not configured. Set it in your .env file.",
        )
    public_url = f"{public_base}/api/admin/media/{saved_name}"

    return await send_agent_media(
        db=db,
        conv_id=conv_id,
        agent=agent,
        media_url=public_url,
        media_type=waba_type,
        caption=caption,
        filename=file.filename,
        redis=request.app.state.redis,
    )


@router.post("/conversations/{conv_id}/reply-media")
async def reply_media(
    conv_id: str,
    body: dict,
    request: Request,
    db: AsyncSession = Depends(get_db),
    agent: Agent = Depends(get_current_agent),
):
    media_url  = body.get("media_url")
    media_type = body.get("media_type", "image")
    if not media_url:
        raise HTTPException(status_code=422, detail="media_url is required")

    return await send_agent_media(
        db=db,
        conv_id=conv_id,
        agent=agent,
        media_url=media_url,
        media_type=media_type,
        caption=body.get("caption"),
        filename=body.get("filename"),
        redis=request.app.state.redis,
    )


@router.delete("/conversations/{conv_id}/messages")
async def clear_chat_history(
    conv_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    agent: Agent = Depends(get_current_agent),
):
    if agent.role != "admin" and not agent.is_superuser:
        raise HTTPException(status_code=403, detail="Only admins can clear chat history")

    result = await db.execute(select(Conversation).where(Conversation.id == conv_id))
    conv = result.scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    # Delete all messages AND all activity-log rows so both the thread
    # and the activity log are completely clean after a clear.
    await db.execute(delete(Message).where(Message.conversation_id == conv_id))
    await db.execute(delete(Intercept).where(Intercept.conversation_id == conv_id))

    conv.last_message_preview = None
    conv.last_message_at      = None
    # Return conversation to AI mode so it is ready for a fresh start.
    conv.intercept_mode    = InterceptMode.ai
    conv.assigned_agent_id = None
    conv.intercept_since   = None

    await db.commit()

    redis = request.app.state.redis
    import json, logging as _logging
    _redis_log = _logging.getLogger("neema.redis")

    # Cache invalidation — non-fatal: if Redis is a read replica or temporarily
    # unavailable the cache will expire on its own (TTL=1h).
    try:
        await redis.delete(f"context:{conv.wa_id}")
    except Exception as exc:
        _redis_log.warning("Redis delete failed (context:%s): %s", conv.wa_id, exc)

    # Broadcast — non-fatal: agents will see the cleared state on next refresh.
    try:
        await redis.publish(
            f"ws:channel:{conv_id}",
            json.dumps({
                "type":           "history_cleared",
                "conversationId": conv_id,
                "clearedBy":      agent.name,
            })
        )
    except Exception as exc:
        _redis_log.warning("Redis publish failed (channel:%s): %s", conv_id, exc)

    return {"ok": True, "cleared": True, "conversation_id": conv_id}


# ── Agents ────────────────────────────────────────────────

@router.get("/agents")
async def list_agents(
    db: AsyncSession = Depends(get_db),
    agent: Agent = Depends(get_current_agent),
):
    from sqlalchemy import text
    rows = await db.execute(text("""
        SELECT
            a.id,
            a.name,
            a.email,
            a.role,
            a.is_available,
            a.is_superuser,
            a.avatar_url,
            a.created_at,
            a.last_seen_at,
            COALESCE(a.active_convs, 0)  AS active_convs,
            a.custom_role_id,
            a.custom_permissions,
            r.name        AS role_name,
            r.color       AS role_color,
            r.permissions AS role_permissions
        FROM agents a
        LEFT JOIN custom_roles r ON r.id = a.custom_role_id
        ORDER BY a.name
    """))
    keys = rows.keys()
    return [dict(zip(keys, row)) for row in rows.fetchall()]


@router.patch("/agents/{agent_id}/role")
async def assign_agent_role(
    agent_id: str,
    body: dict,
    db: AsyncSession = Depends(get_db),
    current: Agent = Depends(get_current_agent),
):
    from sqlalchemy import text
    import json

    custom_role_id = body.get("custom_role_id")
    if not custom_role_id:
        raise HTTPException(status_code=422, detail="custom_role_id is required")

    role_row = await db.execute(
        text("SELECT id FROM custom_roles WHERE id = :id"),
        {"id": custom_role_id},
    )
    if not role_row.fetchone():
        raise HTTPException(status_code=404, detail="Role not found")

    result = await db.execute(select(Agent).where(Agent.id == agent_id))
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    custom_permissions = body.get("custom_permissions")
    perms_json = json.dumps(custom_permissions) if custom_permissions is not None else None

    await db.execute(
        text("""
            UPDATE agents
            SET custom_role_id     = :role_id,
                custom_permissions = CAST(:perms AS jsonb)
            WHERE id = :agent_id
        """),
        {"role_id": custom_role_id, "perms": perms_json, "agent_id": agent_id},
    )
    await db.commit()

    row = await db.execute(
        text("""
            SELECT a.id, a.name, a.email, a.role, a.is_available,
                   a.custom_role_id, a.custom_permissions,
                   r.name  AS role_name,
                   r.color AS role_color
            FROM agents a
            LEFT JOIN custom_roles r ON r.id = a.custom_role_id
            WHERE a.id = :id
        """),
        {"id": agent_id},
    )
    keys = row.keys()
    data = row.fetchone()
    return dict(zip(keys, data))


@router.patch("/agents/{agent_id}")
async def update_agent(agent_id: str, body: dict,
                       db: AsyncSession = Depends(get_db),
                       current: Agent = Depends(get_current_agent)):
    from app.core.security import hash_password
    result = await db.execute(select(Agent).where(Agent.id == agent_id))
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    if "name" in body and body["name"]:
        agent.name = body["name"]
    if "email" in body and body["email"]:
        agent.email = body["email"]
    if "role" in body and body["role"]:
        agent.role = body["role"]
    if "is_available" in body:
        agent.is_available = bool(body["is_available"])
    if "password" in body and body["password"]:
        if len(body["password"]) < 8:
            raise HTTPException(status_code=422, detail="Password must be at least 8 characters")
        agent.password_hash = hash_password(body["password"])
    await db.commit()
    return {"ok": True}


# ── Orders ────────────────────────────────────────────────────────────────────

@router.get("/orders")
async def list_orders(
    status: str | None = None,
    wa_id: str | None = None,
    db: AsyncSession = Depends(get_db),
    agent: Agent = Depends(get_current_agent),
):
    from app.models.order_event import OrderEvent
    q = select(OrderEvent).order_by(OrderEvent.created_at.desc())
    if status:
        q = q.where(OrderEvent.status == status)
    if wa_id:
        q = q.where(OrderEvent.wa_id == wa_id)
    result = await db.execute(q)
    return result.scalars().all()


@router.get("/orders/{order_id}")
async def get_order(
    order_id: str,
    db: AsyncSession = Depends(get_db),
    agent: Agent = Depends(get_current_agent),
):
    from app.models.order_event import OrderEvent
    result = await db.execute(
        select(OrderEvent).where(OrderEvent.id == order_id)
    )
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    return order


@router.patch("/orders/{order_id}")
async def update_order(
    order_id: str,
    body: dict,
    db: AsyncSession = Depends(get_db),
    agent: Agent = Depends(get_current_agent),
):
    from app.models.order_event import OrderEvent
    result = await db.execute(
        select(OrderEvent).where(OrderEvent.id == order_id)
    )
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    allowed = {"status", "payment_status", "fulfillment_status", "reply_text"}
    for k, v in body.items():
        if k in allowed:
            setattr(order, k, v)
    await db.commit()
    return order


# ── Catalog ───────────────────────────────────────────────────────────────────

@router.get("/catalog")
async def list_catalog(
    request: Request,
    category: str | None = None,
    search: str | None = None,
    db: AsyncSession = Depends(get_db),
    agent: Agent = Depends(get_current_agent),
):
    """Operator catalogue view.

    Reads the SAME source the AI sells from — the Bethany House hub when
    `catalog_source=hub` (live prices + stock), falling back to Neema's local
    table if the hub is unreachable. Read-only here: products are maintained in
    the hub, so operators see exactly what the agent quotes.
    """
    from app.services import n8n_bridge as svc
    items = await svc.catalog_items(db, request.app.state.redis)
    if category:
        items = [i for i in items if (i.get("category") or "") == category]
    if search:
        needle = search.lower()
        items = [
            i for i in items
            if needle in (i.get("name") or "").lower()
            or needle in (i.get("sku") or "").lower()
            or any(needle in str(a).lower() for a in (i.get("aliases") or []))
        ]
    return items


@router.post("/catalog")
async def create_catalog_item(
    body: dict,
    db: AsyncSession = Depends(get_db),
    agent: Agent = Depends(get_current_agent),
):
    from app.models.catalog import Catalog
    from decimal import Decimal, InvalidOperation
    if not body.get("name"):
        raise HTTPException(status_code=422, detail="name is required")
    try:
        price = Decimal(str(body["price"])) if "price" in body else Decimal("0")
    except (InvalidOperation, KeyError):
        raise HTTPException(status_code=422, detail="price must be a valid number")
    item = Catalog(
        sku=body.get("sku", ""),
        name=body["name"],
        price=price,
        unit=body.get("unit"),
        category=body.get("category"),
        description=body.get("description"),
        aliases=body.get("aliases", []),
        in_stock=body.get("in_stock", True),
    )
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return item


@router.patch("/catalog/{item_id}")
async def update_catalog_item(
    item_id: str,
    body: dict,
    db: AsyncSession = Depends(get_db),
    agent: Agent = Depends(get_current_agent),
):
    from app.models.catalog import Catalog
    from decimal import Decimal, InvalidOperation
    result = await db.execute(
        select(Catalog).where(Catalog.id == item_id)
    )
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    allowed = {"name", "price", "unit", "category", "description", "aliases", "in_stock", "sku"}
    for k, v in body.items():
        if k in allowed:
            if k == "price":
                try:
                    setattr(item, k, Decimal(str(v)))
                except (InvalidOperation, ValueError):
                    raise HTTPException(status_code=422, detail="price must be a valid number")
            else:
                setattr(item, k, v)
    await db.commit()
    await db.refresh(item)
    return item


@router.delete("/catalog/{item_id}")
async def delete_catalog_item(
    item_id: str,
    db: AsyncSession = Depends(get_db),
    agent: Agent = Depends(get_current_agent),
):
    from app.models.catalog import Catalog
    result = await db.execute(
        select(Catalog).where(Catalog.id == item_id)
    )
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    await db.delete(item)
    await db.commit()
    return {"ok": True}


# ── Stats ─────────────────────────────────────────────────────────────────────

@router.get("/stats")
async def overview_stats(
    db: AsyncSession = Depends(get_db),
    agent: Agent = Depends(get_current_agent),
):
    from app.models.order_event import OrderEvent
    from app.models.catalog import Catalog
    from sqlalchemy import func

    convs   = (await db.execute(select(Conversation))).scalars().all()
    agents  = (await db.execute(select(Agent))).scalars().all()
    orders  = (await db.execute(select(OrderEvent))).scalars().all()
    catalog = (await db.execute(select(Catalog))).scalars().all()

    return {
        "open_conversations":   sum(1 for c in convs if c.status == "open"),
        "human_conversations":  sum(1 for c in convs if c.intercept_mode == "human"),
        "ai_conversations":     sum(1 for c in convs if c.intercept_mode == "ai"),
        "active_agents":        sum(1 for a in agents if a.is_available),
        "total_agents":         len(agents),
        "total_revenue":        float(sum(o.subtotal or 0 for o in orders if o.status not in ("cancelled",))),
        "total_orders":         len(orders),
        "pending_orders":       sum(1 for o in orders if o.status in ("open", "pending")),
        "delivered_orders":     sum(1 for o in orders if o.status == "delivered"),
        "confirmed_orders":     sum(1 for o in orders if o.status == "confirmed"),
        "cancelled_orders":     sum(1 for o in orders if o.status == "cancelled"),
        "in_stock_items":       sum(1 for c in catalog if c.in_stock),
        "total_items":          len(catalog),
        "channel_breakdown":    [
            {"channel": ch, "count": cnt, "open": opn}
            for ch, cnt, opn in (
                (ch,
                 sum(1 for c in convs if getattr(c, "channel", None) == ch),
                 sum(1 for c in convs if getattr(c, "channel", None) == ch and c.status == "open"))
                for ch in ("whatsapp", "messenger", "instagram", "email", "sms")
            )
            if cnt > 0
        ],
    }


# ── Me (current agent profile) ────────────────────────────────────────────────

@router.get("/me")
async def get_me(agent: Agent = Depends(get_current_agent)):
    return agent


@router.patch("/me")
async def update_me(
    body: dict,
    db: AsyncSession = Depends(get_db),
    agent: Agent = Depends(get_current_agent),
):
    from app.core.security import hash_password
    if "name" in body:
        agent.name = body["name"]
    if "email" in body:
        agent.email = body["email"]
    if "password" in body:
        agent.password_hash = hash_password(body["password"])
    await db.commit()
    return agent


# ── Agents CRUD ───────────────────────────────────────────────────────────────

@router.post("/agents")
async def create_agent(
    body: dict,
    db: AsyncSession = Depends(get_db),
    current: Agent = Depends(get_current_agent),
):
    from app.core.security import hash_password
    missing = [f for f in ("name", "email", "password") if not body.get(f)]
    if missing:
        raise HTTPException(status_code=422, detail=f"Missing required fields: {', '.join(missing)}")
    agent = Agent(
        name=body["name"],
        email=body["email"],
        password_hash=hash_password(body["password"]),
        role=body.get("role", "agent"),
        is_available=True,
    )
    db.add(agent)
    await db.commit()
    await db.refresh(agent)
    return agent


@router.delete("/agents/{agent_id}")
async def delete_agent(
    agent_id: str,
    db: AsyncSession = Depends(get_db),
    current: Agent = Depends(get_current_agent),
):
    result = await db.execute(select(Agent).where(Agent.id == agent_id))
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    await db.delete(agent)
    await db.commit()
    return {"ok": True}

# ── Meta profile backfill ─────────────────────────────────────────────────────
# Retro-enrich "Unknown" Messenger/Instagram/Facebook contacts now that the Meta
# app is approved for the Profile API. Operator-triggered (safe, bounded); a
# gated pass also runs on startup (see main.py) so the backlog drains on its own.
@router.post("/meta/backfill-profiles")
async def backfill_meta_profiles(
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    agent: Agent = Depends(get_current_agent),
):
    from app.services.meta_enrich import backfill_unknown_profiles
    return await backfill_unknown_profiles(db, limit=min(max(limit, 1), 200))
