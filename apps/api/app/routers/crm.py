"""
app/routers/crm.py

Customer CRM endpoints:
  GET  /admin/customers/{wa_id}          — full profile
  PATCH /admin/customers/{wa_id}         — update profile fields
  POST  /admin/customers/{wa_id}/merge   — merge two profiles
  GET  /admin/leads                      — all leads (customers with stage info)
  PATCH /admin/leads/{wa_id}             — update lead stage / tags / notes
"""

import re

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, or_
from app.database import get_db
from app.models.agent import Agent
from app.models.user import User
from app.core.phone import is_plausible_phone
from app.models.order_event import OrderEvent
from app.models.conversation import Conversation
from app.models.customer_history import CustomerHistory
from app.models.person import Person, Identity, Identifier, PersonMerge
from app.routers.admin import get_current_agent
from app.core import hub_client
from datetime import datetime, timezone
import json
import uuid as _uuid

router = APIRouter()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _phone_verified(user: User, identities=None) -> bool:
    """Do we have a phone we can ACTUALLY reach and sell to them on — proven, not
    typed into a form?

    WhatsApp is the proof: a wa_id is the number Meta verified when they messaged
    us, so it can never be a typo or a fake. A phone captured deterministically
    elsewhere (they told us on Messenger, or an M-Pesa payment matched it) counts
    too. A Meta PSID is 16-17 digits and is_plausible_phone rejects it, so a
    Messenger-only contact never counts as reachable by phone."""
    if is_plausible_phone(getattr(user, "wa_id", None)):
        return True
    for i in (identities or []):
        ext = getattr(i, "external_id", None)
        if not is_plausible_phone(ext):
            continue
        if getattr(i, "channel", None) == "whatsapp":
            return True
        if getattr(i, "confidence", None) == "deterministic":
            return True
    return False


def _days_since(dt) -> float | None:
    d = _parse_dt(dt)
    return (datetime.now(timezone.utc) - d).total_seconds() / 86400 if d else None


def merge_notes(base: str | None, mine: str | None, current: str | None) -> str:
    """Three-way paragraph merge for the Notes field — closes the lost-update race.

    The operator edits notes from a snapshot (`base`) while the server appends
    concurrently (call-transcription summaries, merges). A plain overwrite threw
    those appends away. Instead: keep the operator's text exactly as written
    (their deletions of paragraphs that existed in `base` are respected — they
    deleted them on purpose), then re-append any paragraph that appeared AFTER
    their snapshot and isn't already in their text. Nothing concurrent is lost;
    nothing deliberately deleted comes back."""
    def paras(s):
        return [p.strip() for p in (s or "").split("\n\n") if p.strip()]
    base_p, mine_p, cur_p = paras(base), paras(mine), paras(current)
    appended_since_base = [p for p in cur_p if p not in base_p and p not in mine_p]
    return "\n\n".join(mine_p + appended_since_base)


def _measurements_of(*states) -> dict:
    """The customer's sizes from whichever store holds them (person first)."""
    from app.agent.measurements import visible, read_measurements
    for st in states:
        m = visible(read_measurements(st))
        if m:
            return m
    return {}


def _cart_size(*states) -> int:
    """Items sitting in this customer's cart, from whichever store holds it."""
    for st in states:
        items = ((st or {}).get("agent_cart") or {}).get("items") or []
        if items:
            return len(items)
    return 0


# Leadership roles buy for whole congregations — a bishop's cassock order seeds
# the parish's vestments, communion sets and choir robes.
_LEADER_ROLE_RE = re.compile(
    r"\b(bishop|archbishop|apostle|prophet|pastor|reverend|rev|founder|priest|"
    r"father|canon|dean|moderator|chairman|overseer|evangelist|elder|deacon|ceo)\b",
    re.IGNORECASE)


def _lead_score_parts(user: User, order_count: int, total_spent: float,
                      channel_count: int, phone_verified: bool = False,
                      cart_items: int = 0, days_since_contact: float | None = None,
                      role: str | None = None) -> list[dict]:
    """The lead score, itemised — ONE definition, returned to the panel so the
    breakdown can never drift from the maths that ranks the list.

    Tuned to answer "who should I call TODAY?", not "who has already bought?".
    Past purchase is still the strongest proof of a real customer, but it no
    longer dominates: a live buying signal — items sitting in their cart, and a
    conversation that is still warm — now outweighs a dormant past buyer. Reach
    (a verified phone, more than one channel) breaks the ties."""
    spend_pts = 15 if total_spent > 10000 else 8 if total_spent > 3000 else 0
    if days_since_contact is None:
        recency = 0
    elif days_since_contact <= 7:
        recency = 15
    elif days_since_contact <= 30:
        recency = 7
    else:
        recency = 0
    return [
        {"label": "Active cart",     "pts": 25 if cart_items else 0,        "max": 25},
        {"label": "Orders",          "pts": min(order_count * 10, 25),      "max": 25},
        {"label": "Recent contact",  "pts": recency,                        "max": 15},
        {"label": "Spend level",     "pts": spend_pts,                      "max": 15},
        {"label": "Phone verified",  "pts": 10 if phone_verified else 0,    "max": 10},
        {"label": "Multi-channel",   "pts": 10 if channel_count > 1 else 0, "max": 10},
        {"label": "Name known",      "pts": 5 if user.name else 0,          "max": 5},
        {"label": "Location known",  "pts": 5 if user.location else 0,      "max": 5},
        {"label": "Clergy leader",   "pts": 10 if (role and _LEADER_ROLE_RE.search(role)) else 0, "max": 10},
    ]


def _compute_lead_score(user: User, order_count: int, total_spent: float,
                        channel_count: int, phone_verified: bool = False,
                        cart_items: int = 0, days_since_contact: float | None = None,
                        role: str | None = None) -> int:
    return min(sum(p["pts"] for p in _lead_score_parts(
        user, order_count, total_spent, channel_count, phone_verified,
        cart_items, days_since_contact, role)), 100)


def _profile_of(person_state: dict | None, user_state: dict | None) -> dict:
    """Person-scoped role/organization (person first, user fallback)."""
    return ((person_state or {}).get("profile")
            or (user_state or {}).get("profile") or {})


def _cadence_label(days: float) -> str:
    """Humanise the average gap between a customer's orders."""
    if days < 1.5:
        return "multiple times a day"
    if days <= 10:
        return f"about every {round(days)} days"
    if days <= 45:
        return f"about every {max(round(days / 7), 1)} weeks"
    return f"about every {max(round(days / 30), 1)} months"


def _parse_dt(v):
    """A datetime from an ISO string / datetime / None (assume UTC if naive)."""
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    if not v:
        return None
    try:
        dt = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _map_local_order(o) -> dict:
    """A local WhatsApp order_event → the CRM panel's order shape (hub fallback)."""
    return {
        "id":             o.id,
        "order_number":   o.hub_order_number,
        "status":         o.status,
        "payment_status": o.payment_status,
        "total":          float(o.subtotal or 0),
        "subtotal":       float(o.subtotal or 0),
        "currency_code":  o.currency,
        "created_at":     o.created_at.isoformat() if o.created_at else None,
        "items":          o.items or [],
        "source":         "whatsapp",
    }


def _buying_rhythm(dates: list) -> dict:
    """How often this customer buys + how overdue they are for the next order.

    Takes order dates (datetimes). `overdue` means it's been noticeably longer
    than their usual gap since the last order — a nudge-worthy signal.
    """
    dates = sorted(d for d in dates if d)
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
    hub: dict | None = None,
    identities: list | None = None,
    person_state: dict | None = None,
    person_name: str | None = None,
    parish: dict | None = None,
) -> dict:
    # Orders + spend: the hub is the source of truth (every channel — POS, web
    # AND WhatsApp). Fall back to Neema's local WhatsApp order_events only when
    # the hub can't resolve this customer or is unreachable.
    if hub is not None:
        order_count     = hub["total_orders"]
        total_spent     = hub["total_spent"]
        avg_order_value = hub["avg_order_value"]
        order_list      = hub["orders"]
        order_dates     = [d for d in (_parse_dt(o.get("created_at")) for o in order_list) if d]
        last_dt         = _parse_dt(hub.get("last_order_date"))
        if last_dt and (not order_dates or last_dt > max(order_dates)):
            order_dates.append(last_dt)
        last_order_at   = (max(order_dates).isoformat() if order_dates
                           else (last_dt.isoformat() if last_dt else None))
        orders_source   = "hub"
    else:
        order_count     = len(orders)
        total_spent     = sum(float(o.subtotal or 0) for o in orders)
        avg_order_value = round(total_spent / order_count, 2) if order_count else 0
        order_list      = [_map_local_order(o) for o in orders]
        order_dates     = [o.created_at for o in orders if getattr(o, "created_at", None)]
        _last           = max(orders, key=lambda o: o.created_at, default=None)
        last_order_at   = _last.created_at.isoformat() if _last else None
        orders_source   = "whatsapp"

    # Build channel list from conversations
    channel_map: dict[str, dict] = {}
    for conv in conversations:
        ch = getattr(conv, "channel", "whatsapp") or "whatsapp"
        if ch not in channel_map:
            channel_map[ch] = {
                "channel": ch,
                "identifier": conv.wa_id,
                "first_seen": conv.created_at.isoformat() if conv.created_at else None,
                # A conversation with no messages yet (opened by a call, an invite
                # or an agent pick-up) has no last_message_at — fall back to when
                # it started rather than emitting null, which the panel showed as
                # a 1970 date ("20660d ago").
                "last_seen":  (conv.last_message_at or conv.created_at).isoformat()
                              if (conv.last_message_at or conv.created_at) else None,
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
    phone_verified = _phone_verified(user, identities)
    # Live buying signals: what's sitting in their cart right now, and how warm the
    # conversation still is — the difference between "has bought" and "is buying".
    cart_items = _cart_size(person_state, user.state)
    last_contact = max((c.last_message_at for c in conversations if c.last_message_at),
                       default=None)
    days_since_contact = _days_since(last_contact)
    score_parts = _lead_score_parts(user, order_count, total_spent, len(channels),
                                    phone_verified=phone_verified, cart_items=cart_items,
                                    days_since_contact=days_since_contact,
                                    role=_profile_of(person_state, user.state).get("role"))
    lead_score = min(sum(p["pts"] for p in score_parts), 100)
    rhythm = _buying_rhythm(order_dates)
    tier = _customer_tier(order_count, total_spent, rhythm["days_since_last"])
    # Suggested stage stays on the local WhatsApp order_events — a pending
    # WhatsApp order (hub_order_id set) is what signals "negotiating".
    from app.services.lead_signals import derive_lead_stage
    suggested_stage = derive_lead_stage(user, orders)

    # Extra fields stored in user.state
    state       = user.state or {}
    from app.services.lead_signals import normalise_stage
    lead_stage  = normalise_stage(state.get("lead_stage", "new"))
    tags        = state.get("tags", [])
    notes       = state.get("crm_notes")
    merged_ids  = state.get("merged_ids", [])

    # Identity spine: the real channel identities linked to this person. Replaces
    # the phantom merged_ids with concrete (channel, external_id) rows so the
    # panel can show "this is the same human across WhatsApp / Messenger / …".
    linked_identities = [
        {
            "channel":      i.channel,
            "external_id":  i.external_id,
            "display_name": i.display_name,
            "source":       i.source,
            "confidence":   i.confidence,
        }
        for i in (identities or [])
    ]

    phone_display = user.phone or (user.wa_id if is_plausible_phone(user.wa_id) else None)

    return {
        "id":             str(user.id),
        "wa_id":          user.wa_id,
        "name":           user.name or person_name,
        "name_confirmed": user.name_confirmed,
        "email":          user.email,
        "phone":          phone_display,
        "location":       user.location or (person_state or {}).get("location"),
        "age":            user.age,
        "tags":           tags,
        "lead_stage":     lead_stage,
        "lead_stage_source": state.get("lead_stage_source"),
        "suggested_lead_stage": suggested_stage,
        "lead_source":    state.get("lead_source") or (person_state or {}).get("lead_source"),
        # Which ad/post brought them (first-touch referral off the webhooks).
        "ad_ref":         state.get("ad_ref") or (person_state or {}).get("ad_ref"),
        # Who they are in the church: role/title + ministry/organization.
        "role":           _profile_of(person_state, user.state).get("role"),
        "organization":   _profile_of(person_state, user.state).get("organization"),
        "lead_score":     lead_score,
        "phone_verified": phone_verified,
        "cart_items":     cart_items,
        # The institution behind the individual — the priest orders, the parish buys.
        "parish":         parish,
        # Sizes on file — so the team can see them without digging through the chat.
        "measurements":   _measurements_of(person_state, user.state),
        # The itemised score, straight from the scoring function — the panel renders
        # this instead of re-deriving it (which had already drifted: it omitted the
        # location points entirely).
        "lead_score_breakdown": score_parts,
        "channels":       channels,
        "merged_ids":     merged_ids,
        "person_id":         str(getattr(user, "person_id", None)) if getattr(user, "person_id", None) else None,
        "linked_identities": linked_identities,
        "total_orders":   order_count,
        "total_spent":    total_spent,
        "avg_order_value": avg_order_value,
        "orders":         order_list[:20],
        "orders_source":  orders_source,
        # Identity link: this WhatsApp contact resolved to a hub (shop) customer
        # by phone. Lets the panel show their in-shop history is the same person.
        "hub_linked":       hub is not None,
        "hub_customer_id":  hub.get("customer_id") if hub else None,
        "hub_customer_name": hub.get("customer_name") if hub else None,
        "buying_rhythm":  rhythm,
        "tier":           tier["tier"],
        "tier_label":     tier["tier_label"],
        "last_order_at":  last_order_at,
        "last_seen_at":   user.last_message_at.isoformat() if user.last_message_at else None,
        "first_seen_at":  user.created_at.isoformat() if user.created_at else None,
        "notes":          notes,
        "created_at":     user.created_at.isoformat() if user.created_at else None,
        **_country_fields(user, person_state, phone_display),
    }


def _country_fields(user, person_state: dict | None, phone: str | None) -> dict:
    """Country for the profile, layered strongest-first:
    stored User fields → person.state → the PHONE's dialing prefix → the free-text
    location. The phone fallback retroactively fills every existing contact that
    has a number but a blank country (e.g. a +234 contact captured before country
    derivation shipped), with no backfill job."""
    from app.core.countries import resolve_country, iso_from_text, name_for_iso, flag_url_for
    ps = person_state or {}
    iso = user.country_iso or ps.get("country_iso")
    country = user.country or ps.get("country")
    flag = user.flag_url or ps.get("flag_url")
    if not iso and phone and is_plausible_phone(phone):
        loc = resolve_country(phone)
        iso, country, flag = loc.get("country_iso"), loc.get("country"), loc.get("flag_url")
    if not iso:
        loc_txt = (user.location or ps.get("location") or "")
        t_iso = iso_from_text(loc_txt)
        if t_iso:
            iso, country, flag = t_iso, name_for_iso(t_iso), flag_url_for(t_iso)
    return {"country_iso": iso, "country": country, "flag_url": flag}


# ── Customer profile ──────────────────────────────────────────────────────────


async def _resolve_customer_user(
    db: AsyncSession, ident: str, channel: str | None = None, *, create: bool = False
) -> User | None:
    """Resolve the CRM `User` for a customer handle that may be a WhatsApp wa_id
    OR a channel-native id (Messenger PSID / Instagram IGSID / Facebook id).

    WhatsApp contacts are a `User` row keyed by wa_id. Non-WhatsApp contacts live
    only on the identity spine (Person + Identity) with NO User row and NO wa_id —
    so operator-edited profile fields (phone, country, tags, notes…) had nowhere
    to persist and silently vanished on reload. This bridges them:

      0. internal User id (UUID) — the Leads page keys rows on this,
      1. direct wa_id (WhatsApp, or an already-provisioned shim),
      2. else the identity's person → its existing User (shared across channels),
      3. else, when `create`, provision a shim User keyed by the channel handle
         and linked to the same person, so edits stick.
    """
    # 0. Internal User id (UUID). A wa_id/PSID is never a valid UUID, so this
    #    only matches genuine ids — the Leads page PATCHes /leads/{user.id}.
    try:
        uid = _uuid.UUID(str(ident))
        user = (await db.execute(select(User).where(User.id == uid))).scalar_one_or_none()
        if user:
            return user
    except (ValueError, AttributeError, TypeError):
        pass

    # 1. Direct wa_id.
    user = (await db.execute(select(User).where(User.wa_id == ident))).scalar_one_or_none()
    if user:
        return user

    # 2. Channel-native id → person → User.
    iq = select(Identity).where(Identity.external_id == ident)
    if channel and channel != "whatsapp":
        iq = iq.where(Identity.channel == channel)
    identity = (await db.execute(iq.order_by(Identity.created_at))).scalars().first()
    if identity is None or identity.person_id is None:
        return None
    from app.services.market import users_for_person
    _users = await users_for_person(db, identity.person_id)   # merged → 2 rows; phone first
    user = _users[0] if _users else None
    if user or not create:
        return user

    # 3. Provision a shim User for this person, enriched from the identity spine
    #    so the panel is complete no matter what was captured before it was first
    #    opened: name from the person, phone from a captured phone identifier,
    #    location from person.state. wa_id holds the channel handle (a PSID/IGSID
    #    never collides with a phone wa_id) — never shown as a phone.
    person = await db.get(Person, identity.person_id)
    phone_idf = (await db.execute(
        select(Identifier).where(Identifier.person_id == identity.person_id,
                                 Identifier.type == "phone"))).scalars().first()
    user = User(
        wa_id=ident, person_id=identity.person_id,
        name=(identity.display_name
              or (person.display_name if person else None) or None),
        phone=(phone_idf.value if phone_idf else None),
        location=((person.state or {}).get("location") if person else None),
    )
    db.add(user)
    await db.flush()
    return user


@router.get("/customers/{wa_id}")
async def get_customer(
    wa_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    agent: Agent = Depends(get_current_agent),
    channel: str | None = None,
):
    # Resolve across channels: wa_id for WhatsApp, PSID/IGSID for Messenger/IG/FB
    # (via the identity spine). Provisions a shim User for a non-WhatsApp contact
    # that has none yet, so a profile always exists to hang edits on.
    user = await _resolve_customer_user(db, wa_id, channel, create=True)
    if not user:
        # Orphan conversation with no identity spine entry (legacy WhatsApp).
        conv_exists = await db.execute(
            select(Conversation.id).where(
                or_(Conversation.wa_id == wa_id, Conversation.external_id == wa_id)
            )
        )
        if conv_exists.scalar_one_or_none() is None:
            raise HTTPException(status_code=404, detail="Customer not found")
        from app.services.n8n_bridge import provision_user
        user = await provision_user(db, wa_id)
    await db.commit()
    await db.refresh(user)

    # Identity spine: gather every WhatsApp handle for this person so a *merged*
    # customer shows unified local history (two wa_ids collapse into one profile),
    # not just the requested handle's slice.
    identities: list = []
    wa_ids = [wa_id]
    if user.person_id is not None:
        identities = (await db.execute(
            select(Identity).where(Identity.person_id == user.person_id)
            .order_by(Identity.created_at)
        )).scalars().all()
        wa_handles = [i.external_id for i in identities if i.channel == "whatsapp"]
        if wa_handles:
            wa_ids = sorted(set(wa_handles) | {wa_id})

    # Match orders by handle OR by person: a Messenger/IG order is keyed on the
    # captured PHONE (which may not be a whatsapp identity yet) but carries
    # person_id — without the person match those orders were invisible here.
    order_filter = [OrderEvent.wa_id.in_(wa_ids)]
    if user.person_id is not None:
        order_filter.append(OrderEvent.person_id == user.person_id)
    orders_result = await db.execute(
        select(OrderEvent).where(or_(*order_filter)).order_by(OrderEvent.created_at.desc())
    )
    orders = orders_result.scalars().all()

    conv_filter = [Conversation.wa_id.in_(wa_ids)]
    if user.person_id is not None:
        # Non-WhatsApp conversations have a null wa_id — match them by person so
        # the profile still lists the Messenger/IG/FB channel.
        conv_filter.append(Conversation.person_id == user.person_id)
    convs_result = await db.execute(
        select(Conversation).where(or_(*conv_filter))
    )
    conversations = convs_result.scalars().all()

    history_result = await db.execute(
        select(CustomerHistory).where(CustomerHistory.wa_id.in_(wa_ids))
        .order_by(CustomerHistory.updated_at.desc())
    )
    history = history_result.scalars().first()   # most-recent snapshot across handles

    # Pull the customer's full order history + lifetime spend from the hub (the
    # system of record across POS, web and WhatsApp). Best-effort: on any failure
    # we fall back to the local WhatsApp order_events. (Hub summary is fetched by
    # the requested handle; multi-number hub aggregation is a later slice.)
    redis = getattr(request.app.state, "redis", None)
    hub = None
    # Try EVERY phone we know for this person, not just the handle that was asked
    # for: someone who bought at the shop under another number, or who reached us
    # on Messenger and later shared their phone, still has hub purchase history —
    # it just isn't filed under this handle. First hit with real orders wins.
    hub_candidates: list[str] = []
    for cand in [wa_id, user.phone, user.wa_id]:
        if cand and is_plausible_phone(cand) and cand not in hub_candidates:
            hub_candidates.append(cand)
    if user.person_id is not None:
        try:
            for ph in (await db.execute(
                select(Identifier).where(Identifier.person_id == user.person_id,
                                         Identifier.type == "phone"))).scalars().all():
                v = (ph.value or "").lstrip("+")
                if v and is_plausible_phone(v) and v not in hub_candidates:
                    hub_candidates.append(v)
        except Exception:
            pass
    for cand in hub_candidates:
        try:
            found = await hub_client.fetch_customer_summary(cand, redis)
        except Exception:
            found = None
        if found:
            hub = found
            if (found.get("total_orders") or 0) > 0:
                break        # real purchase history — stop here

    person_state = None
    person_name = None
    parish_info = None
    if user.person_id is not None:
        _p = await db.get(Person, user.person_id)
        person_state = (_p.state or None) if _p is not None else None
        person_name = _p.display_name if _p is not None else None
        if _p is not None and getattr(_p, "parish_id", None):
            try:
                from app.models.parish import Parish
                _par = await db.get(Parish, _p.parish_id)
                if _par is not None:
                    parish_info = {"id": str(_par.id), "name": _par.name,
                                   "location": _par.location}
            except Exception:
                pass
        # A captured phone (Messenger customer shared their number) shows as a
        # clickable WhatsApp entry in Cross-Channel Identity — unless a real
        # whatsapp identity already covers it.
        has_wa = any(i.channel == "whatsapp" for i in (identities or []))
        if not has_wa:
            from types import SimpleNamespace
            phones = (await db.execute(
                select(Identifier).where(Identifier.person_id == user.person_id,
                                         Identifier.type == "phone"))).scalars().all()
            for ph in phones:
                identities = list(identities or []) + [SimpleNamespace(
                    channel="whatsapp", external_id=ph.value,
                    display_name=user.name, source=ph.source,
                    confidence=ph.confidence)]
    return _build_profile(user, orders, conversations, history, hub=hub,
                          identities=identities, person_state=person_state,
                          person_name=person_name, parish=parish_info)


# ── Identity spine health (ops trust the backfill in prod) ────────────────────

@router.get("/identities/health")
async def identity_spine_health(
    db: AsyncSession = Depends(get_db),
    agent: Agent = Depends(get_current_agent),
):
    """Read-only integrity snapshot of the identity spine. After the migration
    runs in prod, every wa_id-keyed row should have a person_id (orphans == 0)
    and there should be exactly one whatsapp identity per distinct wa_id. Lets
    ops confirm the backfill + resolver are healthy without opening the DB."""
    from app.models.message import Message   # not imported at module scope — the
    # missing import made this endpoint 500 on every call
    orphans: dict[str, int] = {}
    for model, name in (
        (User, "users"), (Conversation, "conversations"), (Message, "messages"),
        (OrderEvent, "order_events"), (CustomerHistory, "customer_history"),
    ):
        orphans[name] = (await db.execute(
            select(func.count()).select_from(model).where(model.person_id.is_(None))
        )).scalar() or 0

    persons_total   = (await db.execute(select(func.count()).select_from(Person))).scalar() or 0
    persons_merged  = (await db.execute(
        select(func.count()).select_from(Person).where(Person.merged_into_id.isnot(None))
    )).scalar() or 0
    identities_total = (await db.execute(select(func.count()).select_from(Identity))).scalar() or 0
    wa_identities    = (await db.execute(
        select(func.count()).select_from(Identity).where(Identity.channel == "whatsapp")
    )).scalar() or 0
    identifiers_total = (await db.execute(select(func.count()).select_from(Identifier))).scalar() or 0
    active_merges = (await db.execute(
        select(func.count()).select_from(PersonMerge).where(PersonMerge.undone_at.is_(None))
    )).scalar() or 0

    total_orphans = sum(orphans.values())
    return {
        "healthy":            total_orphans == 0,
        "orphan_rows":        orphans,
        "total_orphan_rows":  total_orphans,
        "persons_total":      persons_total,
        "persons_merged":     persons_merged,
        "persons_live":       persons_total - persons_merged,
        "identities_total":   identities_total,
        "whatsapp_identities": wa_identities,
        "identifiers_total":  identifiers_total,
        "active_merges":      active_merges,
    }


# ── Identity graph (spine) ────────────────────────────────────────────────────

@router.get("/customers/{wa_id}/identities")
async def get_customer_identities(
    wa_id: str,
    db: AsyncSession = Depends(get_db),
    agent: Agent = Depends(get_current_agent),
):
    """The full identity graph for the person behind `wa_id`: every linked
    channel identity + the reversible merge history. Powers the panel's
    'linked identities' section and the unmerge affordance."""
    user = (await db.execute(select(User).where(User.wa_id == wa_id))).scalar_one_or_none()
    if user is None or user.person_id is None:
        raise HTTPException(status_code=404, detail="No person for this customer")

    identities = (await db.execute(
        select(Identity).where(Identity.person_id == user.person_id).order_by(Identity.created_at)
    )).scalars().all()

    identifiers = (await db.execute(
        select(Identifier).where(Identifier.person_id == user.person_id).order_by(Identifier.created_at)
    )).scalars().all()

    merges = (await db.execute(
        select(PersonMerge)
        .where(PersonMerge.primary_person_id == user.person_id)
        .order_by(PersonMerge.created_at.desc())
    )).scalars().all()

    return {
        "person_id": str(user.person_id),
        "identities": [
            {
                "channel":      i.channel,
                "external_id":  i.external_id,
                "display_name": i.display_name,
                "source":       i.source,
                "confidence":   i.confidence,
                "created_at":   i.created_at.isoformat() if i.created_at else None,
            }
            for i in identities
        ],
        "identifiers": [
            {
                "type":       idf.type,
                "value":      idf.value,
                "source":     idf.source,
                "confidence": idf.confidence,
                "created_at": idf.created_at.isoformat() if idf.created_at else None,
            }
            for idf in identifiers
        ],
        "merges": [
            {
                "id":               str(m.id),
                "secondary_wa_id":  m.secondary_wa_id,
                "moved_external_ids": m.moved_external_ids,
                "performed_by":     str(m.performed_by) if m.performed_by else None,
                "created_at":       m.created_at.isoformat() if m.created_at else None,
                "undone_at":        m.undone_at.isoformat() if m.undone_at else None,
            }
            for m in merges
        ],
    }


@router.patch("/customers/{wa_id}")
async def update_customer(
    wa_id: str,
    body: dict,
    db: AsyncSession = Depends(get_db),
    agent: Agent = Depends(get_current_agent),
    channel: str | None = None,
):
    # Resolve across channels (see _resolve_customer_user): this is what makes an
    # operator's edits on a Messenger/Instagram/Facebook contact actually persist,
    # instead of hitting /customers/null and silently reverting.
    user = await _resolve_customer_user(db, wa_id, channel, create=True)
    if not user:
        # Upsert semantics: the operator can add data to ANY conversation,
        # including orphan conversations that never got a user row. Requires a
        # conversation to exist (guards against typo'd ids creating junk rows).
        conv_exists = await db.execute(
            select(Conversation.id).where(
                or_(Conversation.wa_id == wa_id, Conversation.external_id == wa_id)
            )
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
            if key == "crm_notes":
                # Merge, don't overwrite — a call summary appended while the
                # operator was typing must survive their save.
                state[key] = merge_notes(body.get("notes_base"), body[field],
                                         state.get("crm_notes"))
            else:
                state[key] = body[field]
    # An operator-set stage is authoritative — lock it so the AI won't re-advance it.
    if "lead_stage" in body:
        state["lead_stage_source"] = "manual"

    # Person-scoped role/organization (the sidebar's "who they are" fields).
    # `""` clears a field (a mis-captured role must be removable); when no person
    # row exists the edit lands on user.state so it still sticks.
    if "role" in body or "organization" in body:
        from app.agent.tools import _save_profile_fields
        applied = None
        if user.person_id is not None:
            applied = await _save_profile_fields(
                db, user.person_id, body.get("role"), body.get("organization"))
        if applied is None:
            prof = dict(state.get("profile") or {})
            for key, limit in (("role", 100), ("organization", 200)):
                if key in body and body[key] is not None:
                    v = str(body[key]).strip()
                    if v:
                        prof[key] = v[:limit]
                    else:
                        prof.pop(key, None)
            state["profile"] = prof

    user.state = state
    await db.commit()
    return {"ok": True}


# ── Deals — the shared board's API (docs/AGENTIC_PARTNER_PLAN.md, B1/B3) ─────

@router.get("/deals")
async def list_deals(
    db: AsyncSession = Depends(get_db),
    agent: Agent = Depends(get_current_agent),
    status: str = "open",
):
    """Open deals, newest activity first — what Neema currently owns, what's
    blocking each, and when she plans to act. The board renders this."""
    from app.models.deal import Deal
    q = select(Deal).order_by(Deal.updated_at.desc()).limit(200)
    if status != "all":
        q = q.where(Deal.status == status)
    rows = (await db.execute(q)).scalars().all()
    conv_ids = [d.conversation_id for d in rows if d.conversation_id]
    convs = {}
    if conv_ids:
        for c in (await db.execute(select(Conversation).where(
                Conversation.id.in_(conv_ids)))).scalars().all():
            convs[c.id] = c
    out = []
    for d in rows:
        c = convs.get(d.conversation_id)
        out.append({
            "id": str(d.id),
            "conversation_id": str(d.conversation_id) if d.conversation_id else None,
            "customer": (getattr(c, "contact_name", None) or getattr(c, "name", None)
                         or (c.wa_id if c else None) or "Unknown"),
            "wa_id": (c.wa_id or c.external_id) if c else None,
            "channel": c.channel if c else None,
            "title": d.title,
            "items": d.items_snapshot or [],
            "stage": d.stage,
            "blocking": d.blocking,
            "next_action": d.next_action,
            "guidance": d.guidance,
            "status": d.status,
            "updated_at": d.updated_at.isoformat() if d.updated_at else None,
        })
    return {"deals": out}


@router.patch("/deals/{deal_id}")
async def update_deal(
    deal_id: str,
    body: dict,
    db: AsyncSession = Depends(get_db),
    agent: Agent = Depends(get_current_agent),
):
    """The operator's handle on a deal: guidance, blocking, next_action, stage,
    status — every field Neema reads before acting."""
    import uuid as _uuid
    from app.models.deal import Deal
    try:
        did = _uuid.UUID(deal_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid deal id")
    deal = await db.get(Deal, did)
    if deal is None:
        raise HTTPException(status_code=404, detail="Deal not found")
    for field in ("guidance", "blocking", "stage", "status", "title"):
        if field in body:
            setattr(deal, field, body[field])
    if "next_action" in body:
        deal.next_action = body["next_action"] or None
    await db.commit()
    return {"ok": True}


# ── Planned actions — Neema's initiative queue (plan B2) ─────────────────────

@router.get("/actions")
async def list_actions(
    db: AsyncSession = Depends(get_db),
    agent: Agent = Depends(get_current_agent),
    status: str = "pending",
):
    """The initiative queue: what Neema plans to do and when, what awaits your
    approval, what she's already sent. `status=pending` = planned+needs_approval."""
    from app.models.agent_action import AgentAction
    q = select(AgentAction).order_by(AgentAction.due_at).limit(200)
    if status == "pending":
        q = q.where(AgentAction.status.in_(("planned", "needs_approval")))
    elif status != "all":
        q = q.where(AgentAction.status == status)
    rows = (await db.execute(q)).scalars().all()
    return {"actions": [{
        "id": str(a.id),
        "deal_id": str(a.deal_id) if a.deal_id else None,
        "conversation_id": str(a.conversation_id) if a.conversation_id else None,
        "due_at": a.due_at.isoformat() if a.due_at else None,
        "kind": a.kind, "reason": a.reason, "draft": a.draft,
        "status": a.status, "created_by": a.created_by,
    } for a in rows]}


@router.post("/actions/{action_id}/approve")
async def approve_action(
    action_id: str,
    request: Request,
    body: dict | None = None,
    db: AsyncSession = Depends(get_db),
    agent: Agent = Depends(get_current_agent),
):
    """One tap: send this follow-up now (optionally with an edited draft)."""
    import uuid as _uuid
    from app.models.agent_action import AgentAction
    from app.models.conversation import Conversation
    from app.services import actions as act
    try:
        aid = _uuid.UUID(action_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid action id")
    action = await db.get(AgentAction, aid)
    if action is None:
        raise HTTPException(status_code=404, detail="Action not found")
    if action.status not in ("planned", "needs_approval"):
        raise HTTPException(status_code=409, detail=f"Action is {action.status}")
    conv = (await db.get(Conversation, action.conversation_id)
            if action.conversation_id else None)
    if conv is None:
        raise HTTPException(status_code=404, detail="Conversation gone")
    redis = getattr(request.app.state, "redis", None)
    text = ((body or {}).get("draft") or action.draft or "").strip()
    if not text:
        text = await act._compose_follow_up(db, redis, conv, action.reason or "follow up")
    if not text:
        raise HTTPException(status_code=500, detail="Could not compose the message")
    await act._send(db, redis, conv, text)
    action.status = "sent"
    action.draft = text
    await db.commit()
    return {"ok": True, "sent": text}


@router.post("/actions/{action_id}/veto")
async def veto_action(
    action_id: str,
    db: AsyncSession = Depends(get_db),
    agent: Agent = Depends(get_current_agent),
):
    import uuid as _uuid
    from app.models.agent_action import AgentAction
    try:
        aid = _uuid.UUID(action_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid action id")
    action = await db.get(AgentAction, aid)
    if action is None:
        raise HTTPException(status_code=404, detail="Action not found")
    action.status = "vetoed"
    await db.commit()
    return {"ok": True}


# ── Custom pipeline stages ────────────────────────────────────────────────────
# Operator-added stage labels that render between Proposal and Won in every
# pipeline view. The canonical stages stay fixed (the AI classifier and lead
# signals reason about them); customs are manual-only waypoints.

PIPELINE_CANONICAL = {"new", "contacted", "qualified", "proposal",
                      "negotiation", "won", "lost"}
PIPELINE_CUSTOM_MAX = 4
PIPELINE_LABEL_MAX = 18


@router.get("/settings/pipeline-stages")
async def get_pipeline_stages(
    db: AsyncSession = Depends(get_db),
    agent: Agent = Depends(get_current_agent),
):
    import json as _json
    from app.services.app_settings import get_value
    raw = await get_value(db, "pipeline_custom_stages")
    try:
        stages = _json.loads(raw) if raw else []
    except Exception:
        stages = []
    return {"stages": [s for s in stages if isinstance(s, str) and s.strip()]}


@router.put("/settings/pipeline-stages")
async def put_pipeline_stages(
    body: dict,
    db: AsyncSession = Depends(get_db),
    agent: Agent = Depends(get_current_agent),
):
    """Replace the custom stage list. Admin-only — it reshapes every pipeline."""
    import json as _json
    if not (getattr(agent, "is_superuser", False) or str(agent.role) in ("admin", "AgentRole.admin")):
        raise HTTPException(status_code=403, detail="Admin only")
    from app.services.app_settings import set_value
    raw_stages = body.get("stages")
    if not isinstance(raw_stages, list):
        raise HTTPException(status_code=422, detail="stages must be a list")
    cleaned: list[str] = []
    for s in raw_stages:
        label = str(s or "").strip()[:PIPELINE_LABEL_MAX]
        slug = label.lower()
        if not label or slug in PIPELINE_CANONICAL or slug in [c.lower() for c in cleaned]:
            continue
        cleaned.append(label)
    if len(cleaned) > PIPELINE_CUSTOM_MAX:
        raise HTTPException(status_code=422,
                            detail=f"At most {PIPELINE_CUSTOM_MAX} custom stages")
    await set_value(db, "pipeline_custom_stages", _json.dumps(cleaned))
    return {"ok": True, "stages": cleaned}


# ── Standing orders (docs/AGENTIC_PARTNER_PLAN.md, Phase E) ───────────────────

@router.get("/settings/directives")
async def get_operator_directives(
    request: Request,
    db: AsyncSession = Depends(get_db),
    agent: Agent = Depends(get_current_agent),
):
    from app.services.app_settings import get_directives, DIRECTIVES_MAX_CHARS
    redis = getattr(request.app.state, "redis", None)
    return {"directives": await get_directives(db, redis),
            "max_chars": DIRECTIVES_MAX_CHARS}


@router.put("/settings/directives")
async def put_operator_directives(
    body: dict,
    request: Request,
    db: AsyncSession = Depends(get_db),
    agent: Agent = Depends(get_current_agent),
):
    """Standing orders Neema reads before every reply. Admin-only — this steers
    the whole sales floor."""
    if not (getattr(agent, "is_superuser", False) or str(agent.role) in ("admin", "AgentRole.admin")):
        raise HTTPException(status_code=403, detail="Admin only")
    from app.services.app_settings import set_directives
    redis = getattr(request.app.state, "redis", None)
    val = await set_directives(db, redis, str(body.get("directives") or ""),
                               updated_by=agent.id)
    return {"ok": True, "directives": val}


# ── Team translation switch (services/translate.py) ──────────────────────────

@router.get("/settings/translation")
async def get_translation_setting(
    request: Request,
    db: AsyncSession = Depends(get_db),
    agent: Agent = Depends(get_current_agent),
):
    """The reading glass's switch, and what it has actually cost.

    The spend is read from the same `ai_usage` rows the translator writes on
    every call (node="translate"), so the number beside the switch is the real
    bill rather than an estimate — which is the only honest way to answer
    "should I leave this on?".
    """
    from datetime import datetime, timedelta, timezone
    from app.models.ai_usage import AiUsage
    from app.services.app_settings import (get_translate_enabled,
                                           _default_translate_enabled)

    redis = getattr(request.app.state, "redis", None)
    enabled = await get_translate_enabled(db, redis)

    spend = 0.0
    calls = 0
    try:
        since = datetime.now(timezone.utc) - timedelta(days=30)
        row = (await db.execute(
            select(func.coalesce(func.sum(AiUsage.cost_usd), 0), func.count())
            .where(AiUsage.node == "translate", AiUsage.created_at >= since))).one()
        spend, calls = float(row[0] or 0), int(row[1] or 0)
    except Exception:
        pass                                # a metrics hiccup must not hide the switch
    return {"enabled": enabled,
            "default": _default_translate_enabled(),
            "spend_30d_usd": round(spend, 4),
            "calls_30d": calls}


@router.put("/settings/translation")
async def put_translation_setting(
    body: dict,
    request: Request,
    db: AsyncSession = Depends(get_db),
    agent: Agent = Depends(get_current_agent),
):
    """Turn the team's translation on or off. Admin-only: it spends money and
    it changes what every operator sees under every foreign message."""
    if not (getattr(agent, "is_superuser", False) or str(agent.role) in ("admin", "AgentRole.admin")):
        raise HTTPException(status_code=403, detail="Admin only")
    if "enabled" not in body or not isinstance(body.get("enabled"), bool):
        raise HTTPException(status_code=422, detail="enabled must be true or false")
    from app.services.app_settings import set_translate_enabled
    redis = getattr(request.app.state, "redis", None)
    enabled = await set_translate_enabled(db, redis, bool(body["enabled"]),
                                          updated_by=agent.id)
    return {"ok": True, "enabled": enabled}


# ── The offer running now (services/promotions) ──────────────────────────────

@router.get("/settings/offer")
async def get_offer(
    request: Request,
    db: AsyncSession = Depends(get_db),
    agent: Agent = Depends(get_current_agent),
):
    """The declared offer, whether it is live today, and how Neema states it."""
    from app.services import promotions as promo
    from app.services.app_settings import get_value

    redis = getattr(request.app.state, "redis", None)
    stored = promo.parse(await get_value(db, promo.CAMPAIGN_KEY))
    live = await promo.active_campaign(db, redis)
    return {"campaign": stored,
            "running": bool(live),
            "says": promo.describe(live),
            "max_percent": promo.MAX_PERCENT}


@router.put("/settings/offer")
async def put_offer(
    body: dict,
    request: Request,
    db: AsyncSession = Depends(get_db),
    agent: Agent = Depends(get_current_agent),
):
    """Declare the offer, or end it by sending `{"campaign": null}`.

    Admin-only: this gives away margin on every quote until its end date.
    """
    if not (getattr(agent, "is_superuser", False) or str(agent.role) in ("admin", "AgentRole.admin")):
        raise HTTPException(status_code=403, detail="Admin only")
    from app.services import promotions as promo
    redis = getattr(request.app.state, "redis", None)
    try:
        c = await promo.set_campaign(db, redis, body.get("campaign"), updated_by=agent.id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {"ok": True, "campaign": c, "running": promo.is_running(c),
            "says": promo.describe(c)}


# ── Rule proposals (plan D4) — the weekly distillation, owner-approved ───────

@router.get("/settings/proposals")
async def list_proposals(
    db: AsyncSession = Depends(get_db),
    agent: Agent = Depends(get_current_agent),
):
    import json as _json
    from app.services.app_settings import get_value
    raw = await get_value(db, "rule_proposals")
    try:
        proposals = _json.loads(raw) if raw else []
    except Exception:
        proposals = []
    return {"proposals": proposals,
            "learned_rules": await get_value(db, "learned_rules")}


@router.post("/settings/proposals/{idx}/{verdict}")
async def judge_proposal(
    idx: int,
    verdict: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    agent: Agent = Depends(get_current_agent),
):
    """Approve moves the rule into learned_rules (injected into Neema's prompt
    within minutes); reject just marks it. Admin-only."""
    import json as _json
    if verdict not in ("approve", "reject"):
        raise HTTPException(status_code=422, detail="verdict must be approve|reject")
    if not (getattr(agent, "is_superuser", False) or str(agent.role) in ("admin", "AgentRole.admin")):
        raise HTTPException(status_code=403, detail="Admin only")
    from app.services.app_settings import get_value, set_value, LEARNED_CACHE
    raw = await get_value(db, "rule_proposals")
    try:
        proposals = _json.loads(raw) if raw else []
    except Exception:
        proposals = []
    if not (0 <= idx < len(proposals)):
        raise HTTPException(status_code=404, detail="No such proposal")
    proposals[idx]["status"] = "approved" if verdict == "approve" else "rejected"
    await set_value(db, "rule_proposals", _json.dumps(proposals))
    if verdict == "approve":
        rules = await get_value(db, "learned_rules")
        rules = (rules + "\n- " + proposals[idx]["rule"]).strip()[:1200]
        await set_value(db, "learned_rules", rules)
        redis = getattr(request.app.state, "redis", None)
        if redis is not None:
            try:
                await redis.set(LEARNED_CACHE, rules, ex=300)
            except Exception:
                pass
    return {"ok": True}


# ── Merge profiles ────────────────────────────────────────────────────────────

@router.get("/customers/{wa_id}/merge_suggestions")
async def merge_suggestions(
    wa_id: str,
    db: AsyncSession = Depends(get_db),
    agent: Agent = Depends(get_current_agent),
    channel: str | None = None,
):
    """Duplicate-profile candidates for the Merge panel, from evidence the system
    already holds: a shared phone, a shared email, or the same full name (with
    country agreement when both are known) on another profile.

    Suggestions are operator-confirmed. Only DETERMINISTIC evidence merges
    automatically elsewhere (a Messenger customer sharing their phone →
    capture_contact; a wa.me ref click-through → reconcile_waref)."""
    user = await _resolve_customer_user(db, wa_id, channel, create=False)
    if not user:
        raise HTTPException(status_code=404, detail="Customer not found")

    def _digits(s: str | None) -> str:
        return re.sub(r"\D", "", s or "")

    my_phones = {d for d in (
        _digits(user.phone),
        _digits(user.wa_id) if is_plausible_phone(user.wa_id) else "",
    ) if len(d) >= 9}
    my_email = (user.email or "").strip().lower()
    my_name = (user.name or "").strip()

    cands: dict[str, dict] = {}

    def _consider(u: User, evidence: str, strong: bool) -> None:
        if u.id == user.id:
            return
        if user.person_id and u.person_id and u.person_id == user.person_id:
            return                       # already the same person — linked, not a duplicate
        if (u.state or {}).get("merged_into"):
            return
        e = cands.setdefault(str(u.id), {
            "merge_with": u.wa_id,
            "name": u.name,
            "phone": u.phone or (u.wa_id if is_plausible_phone(u.wa_id) else None),
            "country": u.country,
            "channel_hint": "whatsapp" if is_plausible_phone(u.wa_id) else "social",
            "evidence": [],
            "strength": "possible",
        })
        if evidence not in e["evidence"]:
            e["evidence"].append(evidence)
        if strong:
            e["strength"] = "strong"

    # a) Shared phone — exact digits or a matching 9-digit national tail.
    for d in my_phones:
        tail = d[-9:]
        rows = (await db.execute(select(User).where(or_(
            User.wa_id == d,
            User.phone.in_([d, f"+{d}"]),
            User.wa_id.like(f"%{tail}"),
            User.phone.like(f"%{tail}"),
        )).limit(10))).scalars().all()
        for u in rows:
            ud = _digits(u.phone) or _digits(u.wa_id)
            if ud and (ud == d or ud.endswith(tail)):
                _consider(u, f"Same phone ····{tail[-4:]}", True)

    # b) Shared email.
    if my_email:
        rows = (await db.execute(select(User).where(
            func.lower(User.email) == my_email).limit(5))).scalars().all()
        for u in rows:
            _consider(u, "Same email", True)

    # c) Same full name on another profile (first names alone are noise); when
    #    both countries are known they must agree.
    if len(my_name) >= 5 and " " in my_name:
        rows = (await db.execute(select(User).where(
            func.lower(User.name) == my_name.lower()).limit(8))).scalars().all()
        for u in rows:
            if u.country_iso and user.country_iso and u.country_iso != user.country_iso:
                continue
            _consider(u, "Same name" + (" + country" if u.country_iso and user.country_iso else ""), False)

    out = sorted(cands.values(),
                 key=lambda c: (c["strength"] != "strong", c["name"] or ""))[:5]
    return {"suggestions": out}


@router.post("/customers/{wa_id}/merge")
async def merge_customers(
    wa_id: str,
    body: dict,
    db: AsyncSession = Depends(get_db),
    agent: Agent = Depends(get_current_agent),
    channel: str | None = None,
):
    """
    Merge `merge_with` (secondary) into the primary `wa_id` profile — a REAL,
    reversible, person-level merge:
    - Moves the secondary's identities onto the primary's person and refreshes
      the person_id on the secondary's conversations, messages, orders and
      history (via app/services/merge.py).
    - Copies any missing scalar fields secondary → primary and unions tags.
    - Records the merge in `person_merges` so it can be undone (see /unmerge).
    - Marks the secondary via state["merged_into"] so it drops out of the leads
      list, and appends it to the primary's state["merged_ids"] (UI contract).
    Precision-first: this is an operator-confirmed action, never automatic.
    """
    from app.services.identity import resolve_person_id_for_wa_id
    from app.services.merge import merge_persons

    merge_with = body.get("merge_with", "").strip()
    if not merge_with or merge_with == wa_id:
        raise HTTPException(status_code=422, detail="Invalid merge_with value")

    # Resolve both sides across channels (id / wa_id / PSID·IGSID) so a Messenger
    # or Instagram profile can be merged, not just WhatsApp numbers.
    primary   = await _resolve_customer_user(db, wa_id, channel, create=False)
    secondary = await _resolve_customer_user(db, merge_with, None, create=False)

    if not primary:
        raise HTTPException(status_code=404, detail="Primary customer not found")
    if not secondary:
        raise HTTPException(status_code=404, detail="Secondary customer not found")
    if primary.id == secondary.id:
        raise HTTPException(status_code=422, detail="Cannot merge a profile into itself")

    # Canonical handles for the audit / state bookkeeping (the typed identifier
    # may have been a UUID or a channel handle; the stored wa_id is the key both
    # the merge audit and unmerge look up by).
    pk, sk = primary.wa_id, secondary.wa_id

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

    # Record merged id (canonical secondary handle, so the unmerge chip resolves)
    merged = p_state.get("merged_ids", [])
    if sk not in merged:
        merged.append(sk)
    p_state["merged_ids"] = merged
    primary.state = p_state

    # Mark secondary as merged
    s_state["merged_into"] = pk
    secondary.state = s_state

    # ── The real merge: move identities + re-point history onto the primary ───
    # Ensure both sides carry a person_id (backfill/resolver should guarantee it;
    # provision defensively for any pre-spine orphan).
    if primary.person_id is None:
        primary.person_id = await resolve_person_id_for_wa_id(db, pk)
    if secondary.person_id is None:
        secondary.person_id = await resolve_person_id_for_wa_id(db, sk)
    await db.flush()

    merge_id = None
    if primary.person_id != secondary.person_id:
        audit = await merge_persons(
            db, primary.person_id, secondary.person_id,
            performed_by=agent.id, primary_wa_id=pk, secondary_wa_id=sk,
        )
        merge_id = str(audit.id)

    await db.commit()
    return {"ok": True, "merged": sk, "into": pk, "merge_id": merge_id}


@router.post("/customers/{wa_id}/unmerge")
async def unmerge_customer(
    wa_id: str,
    body: dict,
    db: AsyncSession = Depends(get_db),
    agent: Agent = Depends(get_current_agent),
    channel: str | None = None,
):
    """Reverse a prior merge of `merge_with` into `wa_id`: move the secondary's
    identities + history back to their own person and restore it to the leads
    list. Reversible-by-audit — the inverse of POST /customers/{wa_id}/merge."""
    from app.services.merge import unmerge, latest_active_merge

    merge_with = (body.get("merge_with") or "").strip()
    if not merge_with or merge_with == wa_id:
        raise HTTPException(status_code=422, detail="Invalid merge_with value")

    # Resolve both sides to their canonical wa_ids (the merge audit is keyed by
    # them), so unmerge works from any channel handle the same way merge does.
    primary   = await _resolve_customer_user(db, wa_id, channel, create=False)
    secondary = await _resolve_customer_user(db, merge_with, None, create=False)
    pk = primary.wa_id if primary else wa_id
    sk = secondary.wa_id if secondary else merge_with
    if pk == sk:
        raise HTTPException(status_code=422, detail="Invalid merge_with value")

    audit = await latest_active_merge(db, pk, sk)
    if audit is None:
        raise HTTPException(status_code=404, detail="No active merge to undo for this pair")

    await unmerge(db, audit, undone_by=agent.id)

    # Restore the UI/state bookkeeping.
    if primary is not None:
        p_state = dict(primary.state or {})
        p_state["merged_ids"] = [m for m in p_state.get("merged_ids", []) if m != sk]
        primary.state = p_state
    if secondary is not None:
        s_state = dict(secondary.state or {})
        s_state.pop("merged_into", None)
        secondary.state = s_state

    await db.commit()
    return {"ok": True, "unmerged": sk, "from": pk}


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

    # Persons that were merged away (tombstoned). Covers both operator merges and
    # deterministic reconciler auto-merges — the latter don't touch user state, so
    # the spine tombstone is the authoritative "this is a duplicate" signal.
    tombstoned = set((await db.execute(
        select(Person.id).where(Person.merged_into_id.isnot(None))
    )).scalars().all())

    leads = []
    for user in users:
        state = user.state or {}

        # Skip users merged into another (state contract) or whose person was
        # tombstoned by a real/reconciler merge.
        if state.get("merged_into") or (user.person_id in tombstoned):
            continue

        from app.services.lead_signals import normalise_stage
        lead_stage = normalise_stage(state.get("lead_stage", "new"))
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

        # Score on the SAME context the profile uses — the cart now lives on the
        # PERSON, so scoring from users.state alone zeroed the strongest signal
        # for exactly the hottest leads (and the list disagreed with the panel).
        lead_person_state = None
        if user.person_id is not None:
            try:
                _lp = await db.get(Person, user.person_id)
                lead_person_state = (_lp.state or None) if _lp is not None else None
            except Exception:
                lead_person_state = None
        lead_score = _compute_lead_score(
            user, order_count, total_spent, len(channels),
            phone_verified=_phone_verified(user),
            cart_items=_cart_size(lead_person_state, state),
            days_since_contact=_days_since(
                max((c.last_message_at for c in convs if c.last_message_at), default=None)),
            role=_profile_of(lead_person_state, state).get("role"),
        )
        rhythm = _buying_rhythm([o.created_at for o in orders])
        tier = _customer_tier(order_count, total_spent, rhythm["days_since_last"])

        leads.append({
            "id":           str(user.id),
            "wa_id":        user.wa_id,
            "name":         user.name,
            "phone":        user.phone or (user.wa_id if is_plausible_phone(user.wa_id) else None),
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
    channel: str | None = None,
):
    # The Leads page keys rows on the User id (UUID), not wa_id — and a Messenger
    # lead has no wa_id anyway. Resolve across id / wa_id / channel handle so a
    # stage/tag/notes change actually persists instead of 404-ing.
    user = await _resolve_customer_user(db, wa_id, channel, create=False)
    if not user:
        raise HTTPException(status_code=404, detail="Lead not found")

    state = dict(user.state or {})
    if "lead_stage" in body:
        state["lead_stage"] = body["lead_stage"]
        state["lead_stage_source"] = "manual"  # operator override locks the AI out
    if "tags" in body:
        state["tags"] = body["tags"]
    if "notes" in body:
        state["crm_notes"] = merge_notes(body.get("notes_base"), body["notes"],
                                         state.get("crm_notes"))

    user.state = state
    await db.commit()
    return {"ok": True}

# ── Made-to-order production enquiries ────────────────────────────────────────
# A public measurement-form submission lands as a ProductionEnquiry (status=new),
# flagged in the inbox. A colleague reviews it and pushes it to the hub in one
# tap — the point where a real production order (and price/payment) is created.

from app.models.production_enquiry import ProductionEnquiry


def _enq_json(e: ProductionEnquiry) -> dict:
    return {
        "id":               str(e.id),
        "created_at":       e.created_at.isoformat() if e.created_at else None,
        "product_name":     e.product_name,
        "product_slug":     e.product_slug,
        "customer_name":    e.customer_name,
        "phone":            e.phone,
        "measurements":     e.measurements or {},
        "notes":            e.notes,
        "location":         e.location,
        "status":           e.status,
        "hub_order_id":     e.hub_order_id,
        "hub_order_number": e.hub_order_number,
        "pushable":         bool(e.status == "new" and e.hub_product_id),
    }


def _measurement_notes(e: ProductionEnquiry) -> str:
    parts = [f"{k}: {v}" for k, v in (e.measurements or {}).items() if str(v).strip()]
    body = "; ".join(parts)
    tail = []
    if e.notes:
        tail.append(f"Notes: {e.notes}")
    if e.location:
        tail.append(f"Delivery: {e.location}")
    joined = " | ".join(p for p in [body, *tail] if p)
    return joined or "Confirm measurements with the customer."


@router.get("/production/conversation/{conv_id}")
async def get_conversation_enquiry(
    conv_id: str,
    db: AsyncSession = Depends(get_db),
    agent: Agent = Depends(get_current_agent),
):
    """The most recent made-to-order enquiry for a conversation (for the inbox
    Push-to-production affordance). {enquiry: null} when there is none."""
    try:
        cid = _uuid.UUID(conv_id)
    except (ValueError, TypeError):
        return {"enquiry": None}
    e = (await db.execute(
        select(ProductionEnquiry)
        .where(ProductionEnquiry.conversation_id == cid)
        .order_by(ProductionEnquiry.created_at.desc()).limit(1)
    )).scalars().first()
    return {"enquiry": _enq_json(e) if e else None}


@router.post("/production/{enquiry_id}/push")
async def push_production(
    enquiry_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    agent: Agent = Depends(get_current_agent),
):
    """Create the hub production order from a reviewed enquiry. Idempotent — a
    second call returns the already-created order rather than duplicating it."""
    try:
        eid = _uuid.UUID(enquiry_id)
    except (ValueError, TypeError):
        raise HTTPException(status_code=404, detail="Enquiry not found")
    e = await db.get(ProductionEnquiry, eid)
    if not e:
        raise HTTPException(status_code=404, detail="Enquiry not found")
    if e.status == "pushed":
        return {"ok": True, "already": True, "hub_order_id": e.hub_order_id,
                "hub_order_number": e.hub_order_number}
    if not e.hub_product_id:
        raise HTTPException(status_code=422,
                            detail="This enquiry has no linked hub product — create the order in the hub manually.")

    # Hub price is authoritative; pass it so the order isn't zero-value.
    redis = getattr(request.app.state, "redis", None)
    unit_price = None
    try:
        catalog = await hub_client.fetch_hub_catalog(redis)
        p = next((x for x in catalog if x.get("hub_product_id") == e.hub_product_id), None)
        unit_price = (p or {}).get("price_kes")
    except Exception:
        pass

    try:
        result = await hub_client.create_production_order(
            wa_id=e.phone or "",
            first_name=(e.customer_name or "").split(" ")[0],
            country_iso=e.country_iso,
            hub_product_id=e.hub_product_id,
            product_name=e.product_name or "",
            quantity=1,
            unit_price=unit_price,
            production_notes=_measurement_notes(e),
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Hub rejected the order: {exc}")

    e.status = "pushed"
    e.hub_order_id = result.get("order_id")
    e.hub_order_number = result.get("order_number")
    await db.commit()
    return {"ok": True, "hub_order_id": e.hub_order_id, "hub_order_number": e.hub_order_number,
            "total_amount": result.get("total_amount"), "currency_code": result.get("currency_code")}


@router.post("/production/{enquiry_id}/decline")
async def decline_production(
    enquiry_id: str,
    db: AsyncSession = Depends(get_db),
    agent: Agent = Depends(get_current_agent),
):
    """Dismiss an enquiry that won't go to production."""
    try:
        eid = _uuid.UUID(enquiry_id)
    except (ValueError, TypeError):
        raise HTTPException(status_code=404, detail="Enquiry not found")
    e = await db.get(ProductionEnquiry, eid)
    if e and e.status == "new":
        e.status = "declined"
        await db.commit()
    return {"ok": True}


# ── Attribution: which source/post actually drives leads and revenue ─────────

@router.get("/attribution")
async def attribution(
    db: AsyncSession = Depends(get_db),
    agent: Agent = Depends(get_current_agent),
):
    """Revenue-by-source rollup for the data-driven Bethany House.

    Joins the three places a lead's origin lands — `users.state.lead_source`
    (the WhatsApp set_lead_source tool), `persons.state.lead_source/source_post`
    (the waref comment→WhatsApp bridge), and Meta identities'
    `raw_profile.source_post` (comment capture) — against hub orders
    (OrderEvent, via person_id or wa_id). Orders with no known origin are
    reported honestly as `unattributed`, never silently dropped. Aggregated in
    Python: these tables are small at Bethany House scale, and the JSONB paths
    differ per store, so this beats a thicket of dialect-specific SQL.
    """
    users = (await db.execute(select(User))).scalars().all()
    persons = (await db.execute(
        select(Person).where(Person.merged_into_id.is_(None)))).scalars().all()
    idents = (await db.execute(
        select(Identity).where(Identity.channel.in_(("messenger", "facebook", "instagram")))
    )).scalars().all()
    orders = (await db.execute(
        select(OrderEvent).where(OrderEvent.hub_order_id.isnot(None)))).scalars().all()

    # person_id -> (source, post) — most-specific origin wins.
    origin: dict = {}
    for p in persons:
        st = p.state or {}
        if st.get("source_post") or st.get("lead_source"):
            origin[p.id] = (st.get("lead_source") or "facebook", st.get("source_post"))
    for i in idents:
        post = (i.raw_profile or {}).get("source_post")
        if post and i.person_id not in origin:
            origin[i.person_id] = (i.channel, post)
    wa_person: dict = {}
    for u in users:
        if u.person_id is not None:
            wa_person[u.wa_id] = u.person_id
        src = (u.state or {}).get("lead_source")
        if src and u.person_id is not None and u.person_id not in origin:
            origin[u.person_id] = (src, None)

    buckets: dict = {}

    def _bucket(key):
        return buckets.setdefault(key, {
            "source": key[0], "post": key[1],
            "leads": 0, "orders": 0, "revenue": 0.0, "paid_revenue": 0.0,
        })

    for pid, key in origin.items():
        _bucket(key)["leads"] += 1

    unattributed = {"orders": 0, "revenue": 0.0, "paid_revenue": 0.0}
    for o in orders:
        pid = o.person_id or wa_person.get(o.wa_id)
        try:
            amount = float(o.hub_total if o.hub_total is not None else o.subtotal or 0)
        except (TypeError, ValueError):
            amount = 0.0
        key = origin.get(pid)
        target = _bucket(key) if key else unattributed
        target["orders"] += 1
        target["revenue"] += amount
        if (o.payment_status or "") == "paid":
            target["paid_revenue"] += amount

    rows = sorted(buckets.values(),
                  key=lambda b: (b["revenue"], b["leads"]), reverse=True)

    # Human-readable post titles: the comment capture already stored each post's
    # caption on messages.comment_context — surface "Doctoral gown reel" instead
    # of a raw graph id. Best-effort, one query for just the posts on the board.
    post_ids = {r["post"] for r in rows if r["post"]}
    if post_ids:
        try:
            from app.models.message import Message
            ctxs = (await db.execute(
                select(Message.comment_context)
                .where(Message.comment_context.isnot(None)).limit(500)
            )).scalars().all()
            titles = {}
            for c in ctxs:
                pid, title = (c or {}).get("post_id"), (c or {}).get("title")
                if pid in post_ids and title and pid not in titles:
                    titles[pid] = title
            for r in rows:
                r["post_title"] = titles.get(r["post"])
        except Exception:
            for r in rows:
                r["post_title"] = None
    else:
        for r in rows:
            r["post_title"] = None

    return {
        "sources": rows,
        "unattributed": unattributed,
        "totals": {
            "leads": sum(b["leads"] for b in rows),
            "orders": sum(b["orders"] for b in rows) + unattributed["orders"],
            "revenue": sum(b["revenue"] for b in rows) + unattributed["revenue"],
        },
    }


# ── Unmet demand ──────────────────────────────────────────
# What customers asked for that we could NOT sell them. The most valuable data the
# shop generates and, until now, the only data it threw away: real requests, in the
# customer's own words, from people who wanted to pay. Answers "what should we
# stock or make next?" with evidence rather than instinct.

@router.get("/demand")
async def demand_report(
    days: int = 30,
    limit: int = 25,
    kind: str | None = None,
    db: AsyncSession = Depends(get_db),
    agent: Agent = Depends(get_current_agent),
):
    """Most-wanted things we don't have, ranked by how many DIFFERENT people asked.

    `kind`: no_match (searched, nothing found) · out_of_catalogue (escalated to a
    human) · sourcing_gap (sold, but the hub couldn't cover it). Omit for all.
    """
    from app.services import demand as demand_svc
    rows = await demand_svc.top_demand(db, days=days, limit=limit, kind=kind)
    return {
        "days": days,
        "kind": kind,
        "items": rows,
        "totals": {
            "distinct_requests": len(rows),
            "people": sum(r["people"] for r in rows),
        },
    }


# ── Parish accounts ───────────────────────────────────────
# The institution behind the individuals: who our biggest CHURCH customers are,
# with every member's orders rolled up. The priest, the secretary and the choir
# master are three contacts — one buyer.

@router.get("/parishes")
async def parish_report(
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    agent: Agent = Depends(get_current_agent),
):
    from app.models.parish import Parish
    parishes = (await db.execute(select(Parish))).scalars().all()
    out = []
    for p in parishes:
        people = (await db.execute(
            select(Person).where(Person.parish_id == p.id,
                                 Person.merged_into_id.is_(None)))).scalars().all()
        pids = [x.id for x in people]
        members = len(pids)
        if not pids:
            out.append({"id": str(p.id), "name": p.name, "location": p.location,
                        "members": 0, "orders": 0, "spent": 0.0})
            continue
        users = (await db.execute(
            select(User).where(User.person_id.in_(pids)))).scalars().all()
        wa_ids = [u.wa_id for u in users if u.wa_id]
        orders = []
        if wa_ids:
            orders = (await db.execute(
                select(OrderEvent).where(OrderEvent.wa_id.in_(wa_ids)))).scalars().all()
        out.append({
            "id": str(p.id), "name": p.name, "location": p.location,
            "members": members,
            "orders": len(orders),
            "spent": float(sum(float(o.subtotal or 0) for o in orders)),
        })
    out.sort(key=lambda r: (r["spent"], r["orders"], r["members"]), reverse=True)
    return {"parishes": out[:max(1, min(limit, 200))]}
