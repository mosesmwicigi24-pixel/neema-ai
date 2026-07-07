"""Let the AI keep a lead's stage + tags current as it converses.

The Tier 2 agent calls refresh_lead_signals() after each turn: it derives the
lead stage from concrete signals (order placed, details captured, engaged) and
advances it FORWARD-ONLY — never downgrading, never overriding a stage an
operator set by hand, never moving off a terminal won/lost. It also ensures the
customer's country is a tag (we qualify partly by country). crm.py reuses the
pure helpers to show a `suggested_lead_stage` in the panel.
"""
from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.models.order_event import OrderEvent
from app.models.user import User

_log = logging.getLogger("neema.agent")

# Forward-only rank; won/lost are terminal (handled separately).
_STAGE_RANK = {"new": 0, "contacted": 1, "qualified": 2, "proposal": 3, "negotiating": 4, "won": 5}


def derive_lead_stage(user: User, orders: list) -> str:
    """A stage from concrete signals — the AI's read of where this lead is."""
    if any(getattr(o, "hub_order_id", None) for o in orders):
        return "negotiating"                       # placed an order, awaiting payment
    if user and user.name and (user.email or user.country):
        return "qualified"                         # a real prospect with details
    if orders or (user and getattr(user, "last_message_at", None)):
        return "contacted"                         # has engaged
    return "new"


def apply_signals(state: dict | None, derived_stage: str, country: str | None) -> tuple[dict, bool]:
    """Return (new_state, changed): forward-only stage advance + country tag.
    Respects a manual stage and terminal won/lost."""
    state = dict(state or {})
    changed = False
    current = state.get("lead_stage", "new")
    if state.get("lead_stage_source") != "manual" and current not in ("won", "lost"):
        if _STAGE_RANK.get(derived_stage, 0) > _STAGE_RANK.get(current, 0):
            state["lead_stage"] = derived_stage
            state["lead_stage_source"] = "auto"
            changed = True
    if country:
        tags = list(state.get("tags") or [])
        if not any((t or "").strip().lower() == country.strip().lower() for t in tags):
            tags.append(country)
            state["tags"] = tags
            changed = True
    return state, changed


async def refresh_lead_signals(db: AsyncSession, wa_id: str) -> None:
    """Best-effort: derive + forward-advance the lead stage and ensure the
    country tag. Never raises into the caller (called from the agent turn)."""
    try:
        user = (await db.execute(select(User).where(User.wa_id == wa_id))).scalar_one_or_none()
        if user is None:
            return
        orders = (await db.execute(
            select(OrderEvent).where(OrderEvent.wa_id == wa_id)
        )).scalars().all()
        derived = derive_lead_stage(user, orders)
        new_state, changed = apply_signals(user.state, derived, user.country)
        if changed:
            user.state = new_state
            flag_modified(user, "state")
            await db.commit()
    except Exception:
        _log.warning("refresh_lead_signals failed for %s", wa_id, exc_info=False)
