"""Cross-conversation customer memory for the Tier 2 agent.

Stored on `users.state["agent_memory"]` (JSONB) as a capped list of short,
durable facts (preferences, church, sizing, etc.) — separate from `agent_cart`
so the two don't collide. Follows the exact load/mutate/flag_modified/commit
pattern used by `cart.py`. Also surfaces a one-line summary of the customer's
past hub orders so the agent can sell like it remembers them.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.models.order_event import OrderEvent
from app.models.user import User

_KEY = "agent_memory"
_MAX_FACTS = 20


async def _load_user(db: AsyncSession, wa_id: str) -> User | None:
    return (await db.execute(select(User).where(User.wa_id == wa_id))).scalar_one_or_none()


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


async def get_memory(db: AsyncSession, wa_id: str) -> list[str]:
    user = await _load_user(db, wa_id)
    return read_memory(user.state if user else None)


async def add_fact(db: AsyncSession, wa_id: str, fact: str) -> list[str]:
    user = await _load_user(db, wa_id)
    if user is None:
        return []
    state = dict(user.state or {})
    facts = _merge(read_memory(state), fact)
    state[_KEY] = facts
    user.state = state
    # JSONB columns need an explicit reassignment to be flagged dirty.
    flag_modified(user, "state")
    await db.commit()
    return facts


async def _recent_orders_summary(db: AsyncSession, wa_id: str, limit: int = 3) -> list[str]:
    """Best-effort: swallow errors so a turn never fails just because the
    order-history lookup couldn't be served (mirrors the usage-logging
    best-effort pattern in runtime.run_turn)."""
    try:
        rows = (await db.execute(
            select(OrderEvent)
            .where(OrderEvent.wa_id == wa_id, OrderEvent.hub_order_id.isnot(None))
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


async def build_memory_context(db: AsyncSession, redis, wa_id: str, user: User | None = None) -> str | None:
    """Return a short block combining stored facts + a past-orders summary, or
    None if there's nothing worth telling the model about this customer yet.

    `user` may be passed in when the caller already loaded it (e.g.
    `runtime.run_turn`) to avoid a redundant query; otherwise it's fetched here.
    """
    if user is None:
        user = await _load_user(db, wa_id)
    facts = read_memory(getattr(user, "state", None) if user else None)
    orders = await _recent_orders_summary(db, wa_id)
    if not facts and not orders:
        return None

    parts = []
    if facts:
        parts.append("Known facts:\n" + "\n".join(f"- {f}" for f in facts))
    if orders:
        parts.append("Past orders (most recent first):\n" + "\n".join(f"- {o}" for o in orders))
    return "\n\n".join(parts)
