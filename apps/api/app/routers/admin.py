from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from app.database import get_db
from app.models.conversation import Conversation, InterceptMode
from app.models.message import Message
from app.models.agent import Agent
from app.models.user import User
from app.models.intercept import Intercept, InterceptAction
from app.schemas.conversation import ConversationListItem, InterceptRequest
from app.services.conversation import (
    intercept_conversation, release_conversation,
    transfer_conversation, send_agent_reply, approve_draft
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
    q = select(Conversation).order_by(Conversation.last_message_at.desc().nullslast())
    if mode:
        q = q.where(Conversation.intercept_mode == mode)
    result = await db.execute(q)
    conversations = result.scalars().all()

    # Batch-load User names and Agent names to avoid N+1
    wa_ids     = [c.wa_id for c in conversations]
    agent_ids  = [c.assigned_agent_id for c in conversations if c.assigned_agent_id]

    user_map: dict[str, str] = {}
    if wa_ids:
        u_res = await db.execute(select(User).where(User.wa_id.in_(wa_ids)))
        for u in u_res.scalars().all():
            user_map[u.wa_id] = u.name or ""

    agent_map: dict[str, str] = {}
    if agent_ids:
        a_res = await db.execute(select(Agent).where(Agent.id.in_(agent_ids)))
        for a in a_res.scalars().all():
            agent_map[str(a.id)] = a.name or ""

    return [
        {
            "id":                   str(c.id),
            "wa_id":                c.wa_id,
            "intercept_mode":       c.intercept_mode,
            "assigned_agent_id":    str(c.assigned_agent_id) if c.assigned_agent_id else None,
            "assigned_agent_name":  agent_map.get(str(c.assigned_agent_id), "") if c.assigned_agent_id else None,
            "intercept_since":      c.intercept_since.isoformat() if c.intercept_since else None,
            "last_message_at":      c.last_message_at.isoformat() if c.last_message_at else None,
            "last_message_preview": c.last_message_preview,
            "status":               c.status,
            "created_at":           c.created_at.isoformat() if c.created_at else None,
            "updated_at":           c.updated_at.isoformat() if c.updated_at else None,
            "name":                 user_map.get(c.wa_id) or None,
            "channel":              getattr(c, "channel", "whatsapp") or "whatsapp",
            "unread":               0,
        }
        for c in conversations
    ]


@router.get("/conversations/{conv_id}/messages")
async def get_thread(
    conv_id: str,
    db: AsyncSession = Depends(get_db),
    agent: Agent = Depends(get_current_agent),
):
    result = await db.execute(
        select(Message)
        .where(Message.conversation_id == conv_id)
        .order_by(Message.created_at.asc())
    )
    msgs = result.scalars().all()
    return [
        {
            "id": str(m.id),
            "direction": m.direction,
            "sender": m.sender,
            "text": m.text,
            "isNote": m.media_type == "note",
            "created_at": m.created_at.isoformat() if m.created_at else None,
        }
        for m in msgs
    ]


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

    # Fetch conversation and recent messages
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

    # Build conversation history for the prompt
    history_lines = []
    for m in recent:
        role = "Customer" if m.direction == "inbound" else "Agent/AI"
        history_lines.append(f"{role}: {m.text}")
    history = "\n".join(history_lines)

    # Call OpenAI to generate a suggested reply
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

    # Store as an outbound message with media_type="note" so it stays
    # in the message stream but is never sent to the customer
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


# ── Agents ────────────────────────────────────────────────

@router.get("/agents")
async def list_agents(db: AsyncSession = Depends(get_db),
                      agent: Agent = Depends(get_current_agent)):
    result = await db.execute(select(Agent).order_by(Agent.name))
    return result.scalars().all()


@router.patch("/agents/{agent_id}")
async def update_agent(agent_id: str, body: dict,
                       db: AsyncSession = Depends(get_db),
                       current: Agent = Depends(get_current_agent)):
    allowed = {"name", "is_available", "role", "avatar_url"}
    updates = {k: v for k, v in body.items() if k in allowed}
    await db.execute(update(Agent).where(Agent.id == agent_id).values(**updates))
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
    category: str | None = None,
    search: str | None = None,
    db: AsyncSession = Depends(get_db),
    agent: Agent = Depends(get_current_agent),
):
    from app.models.catalog import Catalog
    q = select(Catalog).order_by(Catalog.name)
    if category:
        q = q.where(Catalog.category == category)
    if search:
        q = q.where(Catalog.name.ilike(f"%{search}%"))
    result = await db.execute(q)
    return result.scalars().all()


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