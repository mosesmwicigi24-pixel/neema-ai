from fastapi import APIRouter, Depends, HTTPException, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.core.config import settings
from app.services import n8n_bridge as svc
from app.schemas.n8n import (
    OutboundDto, SessionDto, MessageDto, UpsertMessagePatchDto,
    UserDto, OrderEventDto, CustomerHistoryDto, UserFactsDto
)

router = APIRouter()


def verify_n8n_secret(x_n8n_secret: str = Header(...)):
    """All n8n → API calls must include this header."""
    if x_n8n_secret != settings.n8n_api_secret:
        raise HTTPException(status_code=403, detail="Forbidden")


# ── Context ───────────────────────────────────────────────
@router.get("/context/{wa_id}", dependencies=[Depends(verify_n8n_secret)])
async def get_context(wa_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    return await svc.get_context(db, request.app.state.redis, wa_id)


# ── Session ───────────────────────────────────────────────
@router.post("/session", dependencies=[Depends(verify_n8n_secret)])
async def touch_session(body: SessionDto, db: AsyncSession = Depends(get_db)):
    return await svc.touch_session(db, body)


# ── Messages ──────────────────────────────────────────────
@router.get("/messages/{wa_id}", dependencies=[Depends(verify_n8n_secret)])
async def get_messages(wa_id: str, db: AsyncSession = Depends(get_db)):
    return await svc.get_messages(db, wa_id)


@router.post("/message", dependencies=[Depends(verify_n8n_secret)])
async def upsert_message(
    body: MessageDto,
    request: Request,                    
    db: AsyncSession = Depends(get_db)
):
    return await svc.upsert_message(db, request.app.state.redis, body)  


@router.patch("/message/{docid}", dependencies=[Depends(verify_n8n_secret)])
async def patch_message(docid: str, body: UpsertMessagePatchDto, db: AsyncSession = Depends(get_db)):
    return await svc.patch_message(db, docid, body)


# ── Users ─────────────────────────────────────────────────
@router.post("/user", dependencies=[Depends(verify_n8n_secret)])
async def upsert_user(body: UserDto, db: AsyncSession = Depends(get_db)):
    return await svc.upsert_user(db, body)


@router.post("/user/facts", dependencies=[Depends(verify_n8n_secret)])
async def save_user_facts(body: UserFactsDto, db: AsyncSession = Depends(get_db)):
    return await svc.save_user_facts(db, body)

@router.get("/user/{wa_id}", dependencies=[Depends(verify_n8n_secret)])
async def get_user(wa_id: str, db: AsyncSession = Depends(get_db)):
    return await svc.get_user(db, wa_id)


# ── Orders ────────────────────────────────────────────────
@router.post("/order-event", dependencies=[Depends(verify_n8n_secret)])
async def upsert_order_event(body: OrderEventDto, db: AsyncSession = Depends(get_db)):
    return await svc.upsert_order_event(db, body)


# ── Customer History ──────────────────────────────────────
@router.post("/customer-history", dependencies=[Depends(verify_n8n_secret)])
async def upsert_customer_history(body: CustomerHistoryDto, db: AsyncSession = Depends(get_db)):
    return await svc.upsert_customer_history(db, body)


# ── INTERCEPT GATE ────────────────────────────────────────
@router.post("/outbound", dependencies=[Depends(verify_n8n_secret)])
async def outbound_gate(body: OutboundDto, request: Request, db: AsyncSession = Depends(get_db)):
    """
    Called by n8n after AI generates a reply.
    Returns {"action": "send"} or {"action": "hold"}.
    """
    return await svc.outbound_gate(db, request.app.state.redis, body)


# ── Catalog (for n8n price lookups) ───────────────────────────────────────────
@router.get("/catalog", dependencies=[Depends(verify_n8n_secret)])
async def get_catalog(db: AsyncSession = Depends(get_db)):
    """
    Returns all in-stock catalog items so n8n can build a live price map
    instead of relying on the hardcoded fallback map.
    """
    from sqlalchemy import select
    from app.models.catalog import Catalog
    result = await db.execute(
        select(Catalog).where(Catalog.in_stock == True).order_by(Catalog.category, Catalog.name)
    )
    items = result.scalars().all()
    return [
        {
            "sku": str(i.sku),
            "name": str(i.name),
            "category": str(i.category or ""),
            "price": float(i.price),
            "unit": str(i.unit or ""),
            "description": str(i.description or ""),
            "aliases": i.aliases or [],
            "in_stock": i.in_stock,
        }
        for i in items
    ]

@router.post("/notify", dependencies=[Depends(verify_n8n_secret)])
async def post_notify(body: dict, request: Request):
    redis = request.app.state.redis
    agent_id = body.get("agent_id")
    # Broadcast to specific agent or all agents
    channel = f"agents:{agent_id}" if agent_id else "agents:all"
    await redis.publish(f"ws:channel:{channel}", json.dumps({
        "event":  "notification",
        "type":   body.get("type"),
        "title":  body.get("title"),
        "body":   body.get("body"),
        "wa_id":  body.get("wa_id"),
        "ts":     body.get("ts"),
        "data":   body,
    }))
    return {"ok": True}