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
from app.services.state_lock import lock_for_write

_log = logging.getLogger("neema.agent")

# Forward-only rank; won/lost are terminal (handled separately).
# NOTE: the stage id is "negotiation" — the dashboard Kanban's column id.
# The old "negotiating" spelling made those leads vanish from the board.
_STAGE_RANK = {"new": 0, "contacted": 1, "qualified": 2, "proposal": 3, "negotiation": 4, "won": 5}


def normalise_stage(s: str | None) -> str:
    """Map legacy spellings to the canonical stage ids."""
    s = (s or "new").strip().lower()
    return "negotiation" if s == "negotiating" else s


def _placed_by_their_own_details(user: User, person_state: dict | None) -> bool:
    """Something the CUSTOMER gave us about where they are: a stated or
    operator-confirmed location (users.location, or the geography record's
    probable / confirmed reading). A dialling prefix is not that — every
    WhatsApp contact has one, so it qualified nobody in particular."""
    if getattr(user, "location", None):
        return True
    geo = ((person_state or {}).get("geo") or {})
    return any((geo.get(k) or {}).get("value") for k in ("confirmed_residence", "probable_country"))


def derive_lead_stage(user: User, orders: list, person_state: dict | None = None) -> str:
    """A stage from concrete signals — the AI's read of where this lead is.
    "Qualified" needs the customer's OWN details: a name and an email or a
    location they (or an operator) gave — not the country their number
    implies (slice 14; audit §5)."""
    if any(getattr(o, "hub_order_id", None) for o in orders):
        return "negotiation"                       # placed an order, awaiting payment
    if user and user.name and (user.email or _placed_by_their_own_details(user, person_state)):
        return "qualified"                         # a real prospect with details
    if orders or (user and getattr(user, "last_message_at", None)):
        return "contacted"                         # has engaged
    return "new"


def apply_signals(state: dict | None, derived_stage: str, country: str | None) -> tuple[dict, bool]:
    """Return (new_state, changed): forward-only stage advance + country tag.
    Respects a manual stage and terminal won/lost."""
    state = dict(state or {})
    changed = False
    current = normalise_stage(state.get("lead_stage", "new"))
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
        person_state = None
        if getattr(user, "person_id", None) is not None:
            try:
                from app.models.person import Person
                _p = await db.get(Person, user.person_id)
                person_state = (_p.state or None) if _p is not None else None
            except Exception:
                person_state = None
        derived = derive_lead_stage(user, orders, person_state)
        # Decided on the copy we hold (most turns change nothing, and take no
        # lock), written on the row as it is now.
        if apply_signals(user.state, derived, user.country)[1]:
            user = await lock_for_write(db, user)
            if user is None:
                return
            before = normalise_stage((user.state or {}).get("lead_stage", "new"))
            new_state, changed = apply_signals(user.state, derived, user.country)
            if changed:
                user.state = new_state
                flag_modified(user, "state")
            await db.commit()
            after = normalise_stage(new_state.get("lead_stage", "new"))
            if changed and after != before:
                # A customer-level event on the timeline (services/timeline).
                from app.services import timeline as _tl
                await _tl.note(db, channel="whatsapp", contact=wa_id, kind="stage",
                               summary=f"Stage moved to {after}",
                               detail=f"from {before}, by Neema's read of the signals",
                               args={"from": before, "to": after})
    except Exception:
        _log.warning("refresh_lead_signals failed for %s", wa_id, exc_info=False)
