"""
app/routers/crm.py

Customer CRM endpoints:
  GET  /admin/customers/{wa_id}          — full profile
  PATCH /admin/customers/{wa_id}         — update profile fields
  POST  /admin/customers/{wa_id}/merge   — merge two profiles
  GET  /admin/leads                      — all leads (customers with stage info)
  PATCH /admin/leads/{wa_id}             — update lead stage / tags / notes
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from app.database import get_db
from app.models.agent import Agent
from app.models.user import User
from app.models.order_event import OrderEvent
from app.models.conversation import Conversation
from app.models.customer_history import CustomerHistory
from app.routers.admin import get_current_agent
from datetime import datetime, timezone
import json

router = APIRouter()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _compute_lead_score(user: User, order_count: int, total_spent: float, channel_count: int) -> int:
    score = 0
    score += min(order_count * 15, 45)
    if total_spent > 10000:
        score += 30
    elif total_spent > 3000:
        score += 15
    if user.email:
        score += 10
    if user.name:
        score += 10
    if user.location:
        score += 5
    if channel_count > 1:
        score += 15
    return min(score, 100)


def _cadence_label(days: float) -> str:
    """Humanise the average gap between a customer's orders."""
    if days < 1.5:
        return "multiple times a day"
    if days <= 10:
        return f"about every {round(days)} days"
    if days <= 45:
        return f"about every {max(round(days / 7), 1)} weeks"
    return f"about every {max(round(days / 30), 1)} months"


def _buying_rhythm(orders: list) -> dict:
    """How often this customer buys + how overdue they are for the next order.

    Uses order dates (created_at). `overdue` means it's been noticeably longer
    than their usual gap since the last order — a nudge-worthy signal.
    """
    dates = sorted(o.created_at for o in orders if getattr(o, "created_at", None))
    n = len(dates)
    now = datetime.now(timezone.utc)
    days_since_last = (now - dates[-1]).days if dates else None
    if n < 2:
        return {"days_since_last": days_since_last, "avg_interval_days": None,
                "cadence_label": None, "overdue": False}
    gaps = [(dates[i] - dates[i - 1]).days for i in range(1, n)]
    avg = sum(gaps) / len(gaps)
    overdue = bool(days_since_last is not None and avg > 0 and days_since_last > avg * 1.5)
    return {"days_since_last": days_since_last, "avg_interval_days": round(avg, 1),
            "cadence_label": _cadence_label(avg), "overdue": overdue}


_TIER_LABELS = {"prospect": "Prospect", "new": "New", "regular": "Regular",
                "loyal": "Loyal", "vip": "VIP", "at_risk": "At risk"}


def _customer_tier(order_count: int, total_spent: float, days_since_last) -> dict:
    """A quick-read segment so an operator knows who they're talking to:
    a big/loyal spender, a newcomer, or a good customer who's gone quiet."""
    dsl = days_since_last if days_since_last is not None else 0
    if order_count == 0:
        t = "prospect"
    elif order_count >= 3 and dsl > 120:
        t = "at_risk"
    elif total_spent >= 500_000 or order_count >= 20:
        t = "vip"
    elif order_count >= 5:
        t = "loyal"
    elif order_count <= 1:
        t = "new"
    else:
        t = "regular"
    return {"tier": t, "tier_label": _TIER_LABELS[t]}


def _build_profile(
    user: User,
    orders: list,
    conversations: list,
    history: CustomerHistory | None,
) -> dict:
    total_spent    = sum(float(o.subtotal or 0) for o in orders)
    order_count    = len(orders)
    last_order     = max(orders, key=lambda o: o.created_at, default=None)

    # Build channel list from conversations
    channel_map: dict[str, dict] = {}
    for conv in conversations:
        ch = getattr(conv, "channel", "whatsapp") or "whatsapp"
        if ch not in channel_map:
            channel_map[ch] = {
                "channel": ch,
                "identifier": conv.wa_id,
                "first_seen": conv.created_at.isoformat() if conv.created_at else None,
                "last_seen":  conv.last_message_at.isoformat() if conv.last_message_at else None,
                "conversation_count": 1,
            }
        else:
            channel_map[ch]["conversation_count"] += 1
            if conv.last_message_at and (
                not channel_map[ch]["last_seen"] or
                conv.last_message_at.isoformat() > channel_map[ch]["last_seen"]
            ):
                channel_map[ch]["last_seen"] = conv.last_message_at.isoformat()

    channels = list(channel_map.values())
    lead_score = _compute_lead_score(user, order_count, total_spent, len(channels))
    rhythm = _buying_rhythm(orders)
    tier = _customer_tier(order_count, total_spent, rhythm["days_since_last"])
    from app.services.lead_signals import derive_lead_stage
    suggested_stage = derive_lead_stage(user, orders)

    # Extra fields stored in user.state
    state       = user.state or {}
    lead_stage  = state.get("lead_stage", "new")
    tags        = state.get("tags", [])
    notes       = state.get("crm_notes")
    merged_ids  = state.get("merged_ids", [])

    return {
        "id":             str(user.id),
        "wa_id":          user.wa_id,
        "name":           user.name,
        "name_confirmed": user.name_confirmed,
        "email":          user.email,
        "phone":          user.phone or user.wa_id,
        "location":       user.location,
        "age":            user.age,
        "tags":           tags,
        "lead_stage":     lead_stage,
        "lead_stage_source": state.get("lead_stage_source"),
        "suggested_lead_stage": suggested_stage,
        "lead_source":    state.get("lead_source"),
        "lead_score":     lead_score,
        "channels":       channels,
        "merged_ids":     merged_ids,
        "total_orders":   order_count,
        "total_spent":    total_spent,
        "avg_order_value": round(total_spent / order_count, 2) if order_count else 0,
        "buying_rhythm":  rhythm,
        "tier":           tier["tier"],
        "tier_label":     tier["tier_label"],
        "last_order_at":  last_order.created_at.isoformat() if last_order else None,
        "last_seen_at":   user.last_message_at.isoformat() if user.last_message_at else None,
        "first_seen_at":  user.created_at.isoformat() if user.created_at else None,
        "notes":          notes,
        "created_at":     user.created_at.isoformat() if user.created_at else None,
        "country_iso":    user.country_iso,
        "country":        user.country,
        "flag_url":       user.flag_url,
    }


# ── Customer profile ──────────────────────────────────────────────────────────

@router.get("/customers/{wa_id}")
async def get_customer(
    wa_id: str,
    db: AsyncSession = Depends(get_db),
    agent: Agent = Depends(get_current_agent),
):
    result = await db.execute(select(User).where(User.wa_id == wa_id))
    user = result.scalar_one_or_none()
    if not user:
        # Auto-provision from the conversation so a profile always exists (this
        # is the 'orphan conversation' case) and resolve the country
        # server-side. 404 only when there is no conversation either.
        conv_exists = await db.execute(
            select(Conversation.wa_id).where(Conversation.wa_id == wa_id)
        )
        if conv_exists.scalar_one_or_none() is None:
            raise HTTPException(status_code=404, detail="Customer not found")
        from app.services.n8n_bridge import provision_user
        user = await provision_user(db, wa_id)
        await db.commit()
        await db.refresh(user)

    orders_result = await db.execute(
        select(OrderEvent).where(OrderEvent.wa_id == wa_id).order_by(OrderEvent.created_at.desc())
    )
    orders = orders_result.scalars().all()

    convs_result = await db.execute(
        select(Conversation).where(Conversation.wa_id == wa_id)
    )
    conversations = convs_result.scalars().all()

    history_result = await db.execute(
        select(CustomerHistory).where(CustomerHistory.wa_id == wa_id)
    )
    history = history_result.scalar_one_or_none()

    return _build_profile(user, orders, conversations, history)


@router.patch("/customers/{wa_id}")
async def update_customer(
    wa_id: str,
    body: dict,
    db: AsyncSession = Depends(get_db),
    agent: Agent = Depends(get_current_agent),
):
    result = await db.execute(select(User).where(User.wa_id == wa_id))
    user = result.scalar_one_or_none()
    if not user:
        # Upsert semantics: the operator can add data to ANY conversation,
        # including orphan conversations that never got a user row. Requires a
        # conversation to exist (guards against typo'd ids creating junk rows).
        conv_exists = await db.execute(
            select(Conversation.wa_id).where(Conversation.wa_id == wa_id)
        )
        if conv_exists.scalar_one_or_none() is None:
            raise HTTPException(status_code=404, detail="Customer not found")
        from app.services.n8n_bridge import provision_user
        user = await provision_user(db, wa_id)

    # Direct model fields the operator can edit.
    for field in ("name", "email", "phone", "location", "age", "country", "country_iso", "flag_url"):
        if field in body and body[field] is not None:
            setattr(user, field, body[field])

    # An operator-set name is authoritative — lock it so the WhatsApp profile
    # name / AI never overwrites it. Also keep the flag consistent when the
    # operator changes the country ISO.
    if "name" in body and (body["name"] or "").strip():
        user.name_confirmed = True
    if "country_iso" in body and body["country_iso"] and "flag_url" not in body:
        from app.core.countries import flag_url_for
        user.flag_url = flag_url_for(body["country_iso"])

    # State-stored fields (lead_stage, tags, notes, merged_ids)
    state = dict(user.state or {})
    for field in ("lead_stage", "tags", "crm_notes", "notes", "lead_source"):
        if field in body:
            key = "crm_notes" if field == "notes" else field
            state[key] = body[field]
    # An operator-set stage is authoritative — lock it so the AI won't re-advance it.
    if "lead_stage" in body:
        state["lead_stage_source"] = "manual"

    user.state = state
    await db.commit()
    return {"ok": True}


# ── Merge profiles ────────────────────────────────────────────────────────────

@router.post("/customers/{wa_id}/merge")
async def merge_customers(
    wa_id: str,
    body: dict,
    db: AsyncSession = Depends(get_db),
    agent: Agent = Depends(get_current_agent),
):
    """
    Merge `merge_with` profile into the primary `wa_id` profile.
    - Copies any missing fields from secondary to primary
    - Re-points secondary's orders and conversations to primary
    - Records secondary wa_id in primary's merged_ids list
    - Marks secondary as merged (does not delete)
    """
    merge_with = body.get("merge_with", "").strip()
    if not merge_with or merge_with == wa_id:
        raise HTTPException(status_code=422, detail="Invalid merge_with value")

    primary_res   = await db.execute(select(User).where(User.wa_id == wa_id))
    secondary_res = await db.execute(select(User).where(User.wa_id == merge_with))

    primary   = primary_res.scalar_one_or_none()
    secondary = secondary_res.scalar_one_or_none()

    if not primary:
        raise HTTPException(status_code=404, detail="Primary customer not found")
    if not secondary:
        raise HTTPException(status_code=404, detail="Secondary customer not found")

    # Merge missing fields from secondary → primary
    for field in ("name", "email", "phone", "location", "age"):
        if not getattr(primary, field) and getattr(secondary, field):
            setattr(primary, field, getattr(secondary, field))

    # Merge tags
    p_state = dict(primary.state or {})
    s_state = dict(secondary.state or {})
    p_tags = set(p_state.get("tags", []))
    s_tags = set(s_state.get("tags", []))
    p_state["tags"] = list(p_tags | s_tags)

    # Record merged id
    merged = p_state.get("merged_ids", [])
    if merge_with not in merged:
        merged.append(merge_with)
    p_state["merged_ids"] = merged
    primary.state = p_state

    # Mark secondary as merged
    s_state["merged_into"] = wa_id
    secondary.state = s_state

    await db.commit()
    return {"ok": True, "merged": merge_with, "into": wa_id}


# ── AI cost dashboard ─────────────────────────────────────────────────────────

@router.get("/ai-cost")
async def ai_cost(
    days: int = 30,
    db: AsyncSession = Depends(get_db),
    agent: Agent = Depends(get_current_agent),
):
    """Token spend by model over the last `days` — so cost optimizations can
    be measured. Populated once n8n logs calls via POST /api/n8n/usage."""
    from app.services.n8n_bridge import ai_cost_summary
    return await ai_cost_summary(db, days=max(1, min(days, 365)))


# ── Leads pipeline ────────────────────────────────────────────────────────────

@router.get("/leads")
async def list_leads(
    stage: str | None = None,
    db: AsyncSession = Depends(get_db),
    agent: Agent = Depends(get_current_agent),
):
    """Returns all users formatted as CRM leads, optionally filtered by stage."""
    users_result = await db.execute(select(User).order_by(User.updated_at.desc()))
    users = users_result.scalars().all()

    leads = []
    for user in users:
        state = user.state or {}

        # Skip users merged into another
        if state.get("merged_into"):
            continue

        lead_stage = state.get("lead_stage", "new")
        if stage and lead_stage != stage:
            continue

        # Get order stats (lightweight — just count and sum)
        orders_result = await db.execute(
            select(OrderEvent).where(OrderEvent.wa_id == user.wa_id)
        )
        orders = orders_result.scalars().all()
        total_spent = sum(float(o.subtotal or 0) for o in orders)
        order_count = len(orders)

        # Channel list from conversations
        convs_result = await db.execute(
            select(Conversation).where(Conversation.wa_id == user.wa_id)
        )
        convs = convs_result.scalars().all()
        channels = list({getattr(c, "channel", "whatsapp") or "whatsapp" for c in convs})

        lead_score = _compute_lead_score(user, order_count, total_spent, len(channels))
        rhythm = _buying_rhythm(orders)
        tier = _customer_tier(order_count, total_spent, rhythm["days_since_last"])

        leads.append({
            "id":           str(user.id),
            "wa_id":        user.wa_id,
            "name":         user.name,
            "phone":        user.phone or user.wa_id,
            "email":        user.email,
            "location":     user.location,
            "lead_stage":   lead_stage,
            "lead_score":   lead_score,
            "tier":         tier["tier"],
            "tier_label":   tier["tier_label"],
            "tags":         state.get("tags", []),
            "channels":     channels,
            "total_orders": order_count,
            "total_spent":  total_spent,
            "buying_rhythm": rhythm,
            "last_seen_at": user.last_message_at.isoformat() if user.last_message_at else None,
            "notes":        state.get("crm_notes"),
        })

    # Sort by lead_score desc
    leads.sort(key=lambda l: l["lead_score"], reverse=True)
    return leads


@router.patch("/leads/{wa_id}")
async def update_lead(
    wa_id: str,
    body: dict,
    db: AsyncSession = Depends(get_db),
    agent: Agent = Depends(get_current_agent),
):
    result = await db.execute(select(User).where(User.wa_id == wa_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="Lead not found")

    state = dict(user.state or {})
    if "lead_stage" in body:
        state["lead_stage"] = body["lead_stage"]
        state["lead_stage_source"] = "manual"  # operator override locks the AI out
    if "tags" in body:
        state["tags"] = body["tags"]
    if "notes" in body:
        state["crm_notes"] = body["notes"]

    user.state = state
    await db.commit()
    return {"ok": True}