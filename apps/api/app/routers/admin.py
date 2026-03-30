from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from app.database import get_db
from app.models.conversation import Conversation, InterceptMode
from app.models.message import Message
from app.models.agent import Agent
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
    return result.scalars().all()


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
    return result.scalars().all()


@router.post("/conversations/{conv_id}/intercept")
async def intercept(conv_id: str, db: AsyncSession = Depends(get_db),
                    agent: Agent = Depends(get_current_agent)):
    return await intercept_conversation(db, conv_id, agent)


@router.post("/conversations/{conv_id}/reply")
async def reply(conv_id: str, body: dict, db: AsyncSession = Depends(get_db),
                agent: Agent = Depends(get_current_agent)):
    return await send_agent_reply(db, conv_id, agent, body["text"])


@router.post("/conversations/{conv_id}/approve-draft")
async def approve(conv_id: str, body: dict = {}, db: AsyncSession = Depends(get_db),
                  agent: Agent = Depends(get_current_agent)):
    return await approve_draft(db, conv_id, agent, body.get("text"))


@router.post("/conversations/{conv_id}/release")
async def release(conv_id: str, db: AsyncSession = Depends(get_db),
                  agent: Agent = Depends(get_current_agent)):
    return await release_conversation(db, conv_id, agent)


@router.post("/conversations/{conv_id}/transfer")
async def transfer(conv_id: str, body: dict, db: AsyncSession = Depends(get_db),
                   agent: Agent = Depends(get_current_agent)):
    return await transfer_conversation(db, conv_id, agent, body["agentId"])


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
    from decimal import Decimal
    item = Catalog(
        sku=body.get("sku", ""),
        name=body["name"],
        price=Decimal(str(body["price"])),
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
    from decimal import Decimal
    result = await db.execute(
        select(Catalog).where(Catalog.id == item_id)
    )
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    allowed = {"name", "price", "unit", "category", "description", "aliases", "in_stock", "sku"}
    for k, v in body.items():
        if k in allowed:
            setattr(item, k, Decimal(str(v)) if k == "price" else v)
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
        "total_revenue":        float(sum(o.subtotal or 0 for o in orders if o.status != "cancelled")),
        "total_orders":         len(orders),
        "pending_orders":       sum(1 for o in orders if o.status == "pending"),
        "delivered_orders":     sum(1 for o in orders if o.status == "delivered"),
        "confirmed_orders":     sum(1 for o in orders if o.status == "confirmed"),
        "cancelled_orders":     sum(1 for o in orders if o.status == "cancelled"),
        "in_stock_items":       sum(1 for c in catalog if c.in_stock),
        "total_items":          len(catalog),
        "channel_breakdown":    [],
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