"""Cross-conversation customer memory for the Tier 2 agent.

Stored as a capped list of short, durable facts (preferences, church, sizing…)
in a JSONB `state` column — on the **User** for WhatsApp (the historical home,
`users.state["agent_memory"]`) and on the identity's **Person** for Meta
channels (`persons.state["agent_memory"]`), which have no User row. Keying Meta
memory on the person means it survives a Messenger↔WhatsApp merge and a repeat
Messenger buyer is remembered instead of treated as new every time. Also
surfaces a one-line summary of past hub orders (by wa_id for WhatsApp, by
person for Meta) so the agent sells like it remembers them.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.models.order_event import OrderEvent
from app.models.person import Person, Identity
from app.models.user import User

_KEY = "agent_memory"
_MAX_FACTS = 20


async def _load_user(db: AsyncSession, wa_id: str) -> User | None:
    return (await db.execute(select(User).where(User.wa_id == wa_id))).scalar_one_or_none()


async def _load_store(db: AsyncSession, key: str, channel: str = "whatsapp"):
    """The ORM object whose JSONB `state` owns this customer's memory:
    the User for WhatsApp, the identity's Person for Meta channels.
    Returns None when the contact doesn't resolve (memory then no-ops)."""
    if channel == "whatsapp":
        return await _load_user(db, key)
    ident = (await db.execute(
        select(Identity).where(Identity.channel == channel,
                               Identity.external_id == key)
    )).scalar_one_or_none()
    if ident is None:
        return None
    return await db.get(Person, ident.person_id)


def read_memory(state: dict | None) -> list[str]:
    facts = (state or {}).get(_KEY)
    return facts if isinstance(facts, list) else []


def _merge(facts: list[str], fact: str) -> list[str]:
    """Append `fact` unless it's already present (case-insensitive), then cap
    the list to the most recent `_MAX_FACTS`, dropping the oldest first."""
    fact = fact.strip()
    if not fact:
        return facts
    if any(f.strip().lower() == fact.lower() for f in facts):
        return facts
    merged = facts + [fact]
    return merged[-_MAX_FACTS:]


async def get_memory(db: AsyncSession, wa_id: str, channel: str = "whatsapp") -> list[str]:
    store = await _load_store(db, wa_id, channel)
    return read_memory(store.state if store else None)


async def add_fact(db: AsyncSession, wa_id: str, fact: str, channel: str = "whatsapp") -> list[str]:
    store = await _load_store(db, wa_id, channel)
    if store is None:
        return []
    state = dict(store.state or {})
    facts = _merge(read_memory(state), fact)
    state[_KEY] = facts
    store.state = state
    # JSONB columns need an explicit reassignment to be flagged dirty.
    flag_modified(store, "state")
    await db.commit()
    return facts


async def _recent_orders_summary(db: AsyncSession, wa_id: str, limit: int = 3,
                                 person_id=None) -> list[str]:
    """Best-effort: swallow errors so a turn never fails just because the
    order-history lookup couldn't be served (mirrors the usage-logging
    best-effort pattern in runtime.run_turn). WhatsApp orders key on wa_id;
    a Meta contact's orders are found via their person (stamped on OrderEvent),
    so a merged Messenger↔WhatsApp customer shows one history."""
    try:
        where = (OrderEvent.person_id == person_id) if person_id is not None else (
            OrderEvent.wa_id == wa_id)
        rows = (await db.execute(
            select(OrderEvent)
            .where(where, OrderEvent.hub_order_id.isnot(None))
            .order_by(OrderEvent.created_at.desc()).limit(limit)
        )).scalars().all()
    except Exception:
        return []
    lines = []
    for row in rows:
        number = row.hub_order_number or row.id
        total = row.hub_total if row.hub_total is not None else row.subtotal
        currency = row.hub_currency or row.currency
        lines.append(f"{number} — {currency} {total}")
    return lines


async def build_memory_context(db: AsyncSession, redis, wa_id: str, user: User | None = None,
                               channel: str = "whatsapp") -> str | None:
    """Return a short block combining stored facts + a past-orders summary, or
    None if there's nothing worth telling the model about this customer yet.

    `user` may be passed in when the caller already loaded it (e.g.
    `runtime.run_turn`) to avoid a redundant query; otherwise the store (User
    for WhatsApp, the identity's Person for Meta) is fetched here.
    """
    store = user if (user is not None and channel == "whatsapp") else (
        await _load_store(db, wa_id, channel))
    facts = read_memory(getattr(store, "state", None) if store else None)
    if channel == "whatsapp" and store is not None and getattr(store, "person_id", None):
        # A customer who started on Messenger carries facts on their PERSON
        # (merged across by the waref/phone link) — surface them here so the
        # WhatsApp conversation continues where Messenger left off.
        person = await db.get(Person, store.person_id)
        pfacts = read_memory(person.state if person else None)
        facts = facts + [f for f in pfacts if f not in facts]
    person_id = store.id if (channel != "whatsapp" and isinstance(store, Person)) else None
    orders = await _recent_orders_summary(db, wa_id, person_id=person_id)
    if not facts and not orders:
        return None

    parts = []
    if facts:
        parts.append("Known facts:\n" + "\n".join(f"- {f}" for f in facts))
    if orders:
        parts.append("Past orders (most recent first):\n" + "\n".join(f"- {o}" for o in orders))
    return "\n\n".join(parts)
