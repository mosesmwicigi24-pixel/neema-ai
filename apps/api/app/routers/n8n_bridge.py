from fastapi import APIRouter, Depends, HTTPException, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.core.config import settings
from app.services import n8n_bridge as svc
from app.schemas.n8n import (
    OutboundDto, SessionDto, MessageDto, UpsertMessagePatchDto,
    UserDto, OrderEventDto, CustomerHistoryDto, UserFactsDto
)
import json

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

# Add to app/routers/n8n_bridge.py router
@router.post("/media/download", dependencies=[Depends(verify_n8n_secret)])
async def n8n_download_media(body: dict, request: Request):
    media_id  = body.get("media_id")
    mime_type = body.get("mime_type", "application/octet-stream")

    if not media_id:
        return {"ok": False, "error": "media_id required"}

    from app.routers.media import MEDIA_DIR, _mime_to_ext
    import os, httpx

    ext      = _mime_to_ext(mime_type)
    filename = f"{media_id}{ext}"
    filepath = os.path.join(MEDIA_DIR, filename)

    if not os.path.exists(filepath):
        async with httpx.AsyncClient(timeout=30) as client:

            # Step 1 — get the current download URL from Graph API using media_id
            meta_resp = await client.get(
                f"https://graph.facebook.com/v19.0/{media_id}",
                headers={"Authorization": f"Bearer {settings.waba_token}"},
            )
            if not meta_resp.is_success:
                return {"ok": False, "error": f"Graph API metadata failed: {meta_resp.status_code}"}

            download_url = meta_resp.json().get("url")
            if not download_url:
                return {"ok": False, "error": "No URL in Graph API response"}

            # Step 2 — download the actual file using the fresh URL + token
            file_resp = await client.get(
                download_url,
                headers={"Authorization": f"Bearer {settings.waba_token}"},
                follow_redirects=True,
            )
            if not file_resp.is_success:
                return {"ok": False, "error": f"File download failed: {file_resp.status_code}"}

            with open(filepath, "wb") as f:
                f.write(file_resp.content)

    base = str(request.base_url).rstrip("/")
    return {
        "ok":         True,
        "filename":   filename,
        "media_id":   media_id,
        "stable_url": f"{base}/api/media/serve/{filename}",
        "mime_type":  mime_type,
    }