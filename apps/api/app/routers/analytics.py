"""Cross-channel analytics rollup for the Bethany House hub.

The hub owns customers, orders and web visits; Neema owns the messaging spine
(persons ← identities(channel) ← messages) with cross-channel identity already
reconciled and anchored on the phone number. This exposes a per-person ×
per-channel message rollup, keyed by phone, so the hub can join it to its own
customers and show each customer's engagement frequency across WhatsApp,
Messenger and Instagram alongside web + orders.

Server-to-server only: gated by a shared X-Analytics-Key (INERT until the key is
configured — 503 otherwise). We load + aggregate in Python to match the existing
/stats endpoint's idiom; the `since_days` window bounds how many rows we scan.
"""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.database import get_db
from app.models.message import Message
from app.models.person import Identifier

router = APIRouter()


def verify_analytics_key(x_analytics_key: str = Header(None)):
    """Shared-secret gate. Disabled (503) until the key is configured."""
    if not settings.analytics_api_key:
        raise HTTPException(status_code=503, detail="analytics rollup disabled")
    if x_analytics_key != settings.analytics_api_key:
        raise HTTPException(status_code=401, detail="invalid analytics key")


@router.get("/analytics/message-rollup")
async def message_rollup(
    since_days: int = Query(365, ge=1, le=1095),
    db: AsyncSession = Depends(get_db),
    _: None = Depends(verify_analytics_key),
):
    since = datetime.now(timezone.utc) - timedelta(days=since_days)

    # person_id → phone (first phone identifier). Phone is stored E.164 without
    # the leading '+'; the hub normalises both sides before matching.
    idents = (
        await db.execute(select(Identifier).where(Identifier.type == "phone"))
    ).scalars().all()
    phone_of: dict = {}
    for i in idents:
        phone_of.setdefault(i.person_id, i.value)

    msgs = (
        await db.execute(
            select(Message).where(
                Message.created_at >= since,
                Message.person_id.isnot(None),
            )
        )
    ).scalars().all()

    agg: dict = {}
    for m in msgs:
        phone = phone_of.get(m.person_id)
        if not phone:
            continue  # no phone claim yet → can't join to a hub customer
        key = (phone, m.channel or "whatsapp")
        a = agg.setdefault(key, {"messages": 0, "inbound": 0, "first_at": None, "last_at": None})
        a["messages"] += 1
        if m.direction == "inbound":
            a["inbound"] += 1
        ts = m.created_at
        if ts is not None:
            if a["first_at"] is None or ts < a["first_at"]:
                a["first_at"] = ts
            if a["last_at"] is None or ts > a["last_at"]:
                a["last_at"] = ts

    rows = [
        {
            "phone": phone,
            "channel": channel,
            "messages": v["messages"],
            "inbound": v["inbound"],
            "first_at": v["first_at"].isoformat() if v["first_at"] else None,
            "last_at": v["last_at"].isoformat() if v["last_at"] else None,
        }
        for (phone, channel), v in agg.items()
    ]
    rows.sort(key=lambda r: r["messages"], reverse=True)

    return {
        "since_days": since_days,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "rows": rows,
    }
