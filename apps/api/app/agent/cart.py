"""Durable per-customer cart for the Tier 2 agent.

Stored on `users.state["agent_cart"]` (JSONB) so it survives across turns without
a new table. Kept separate from Tier 1's `state.cart` to avoid cross-talk while
both tiers run. Each line carries the resolved hub product so `create_order` can
push straight through without re-guessing.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User

_KEY = "agent_cart"


def _empty() -> dict:
    return {"items": []}


async def _load_user(db: AsyncSession, wa_id: str) -> User | None:
    return (await db.execute(select(User).where(User.wa_id == wa_id))).scalar_one_or_none()


def read_cart(state: dict | None) -> dict:
    cart = (state or {}).get(_KEY)
    if not isinstance(cart, dict) or not isinstance(cart.get("items"), list):
        return _empty()
    return cart


def cart_total(cart: dict) -> float:
    return round(sum(float(i.get("unit_price") or 0) * int(i.get("qty") or 0)
                     for i in cart.get("items", [])), 2)


async def get_cart(db: AsyncSession, wa_id: str) -> dict:
    user = await _load_user(db, wa_id)
    return read_cart(user.state if user else None)


async def save_cart(db: AsyncSession, wa_id: str, cart: dict) -> dict:
    user = await _load_user(db, wa_id)
    if user is None:
        return cart
    state = dict(user.state or {})
    state[_KEY] = cart
    user.state = state
    # JSONB columns need an explicit reassignment to be flagged dirty.
    from sqlalchemy.orm.attributes import flag_modified
    flag_modified(user, "state")
    await db.commit()
    return cart


async def clear_cart(db: AsyncSession, wa_id: str) -> dict:
    return await save_cart(db, wa_id, _empty())
