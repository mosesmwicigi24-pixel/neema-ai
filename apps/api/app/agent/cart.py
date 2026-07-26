"""Durable per-customer cart for the Tier 2 agent.

Stored in a JSONB `state` column so it survives across turns without a new table
— on the **User** for WhatsApp (`users.state["agent_cart"]`, the historical
home) and on the identity's **Person** for Meta channels
(`persons.state["agent_cart"]`), which have no User row. Same split as
`agent_memory`: keying Meta carts on the person means a cart built in Messenger
survives a Messenger↔WhatsApp merge instead of silently vanishing.

Kept separate from Tier 1's `state.cart` to avoid cross-talk while both tiers
run. Each line carries the resolved hub product (id, variant SKU, hub price) so
`create_order` pushes straight through without re-guessing.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.person import Person, Identity
from app.models.user import User

_KEY = "agent_cart"


def _empty() -> dict:
    return {"items": []}


async def _load_user(db: AsyncSession, wa_id: str) -> User | None:
    return (await db.execute(select(User).where(User.wa_id == wa_id))).scalar_one_or_none()


async def _load_store(db: AsyncSession, key: str, channel: str = "whatsapp"):
    """The ORM object whose JSONB `state` owns this customer's cart.

    ONE CART PER PERSON, wherever they are. Whenever the contact resolves to a
    Person the cart lives on `persons.state` — so a cart started on Facebook or
    Instagram is the SAME cart on WhatsApp (and vice versa) the moment identity
    links them. A WhatsApp contact with no person yet falls back to its historical
    home (`users.state`), and any cart already sitting there is carried onto the
    person the first time one exists, so nothing in flight is ever lost.
    None when the contact doesn't resolve (the cart no-ops rather than losing items)."""
    if channel == "whatsapp":
        user = await _load_user(db, key)
        if user is None:
            return None
        person = await _live_person(db, user.person_id) if user.person_id else None
        if person is None:
            return user
        # Adopt a pre-existing WhatsApp-only cart onto the person — as a MOVE, not
        # a copy. Leaving the user-row copy behind re-armed the adoption after
        # every clear: a bought basket resurrected on the next read (duplicate
        # orders, post-purchase recovery nudges). Popping the old key makes the
        # adoption genuinely once.
        if not read_cart(person.state).get("items") and read_cart(user.state).get("items"):
            from sqlalchemy.orm.attributes import flag_modified
            state = dict(person.state or {})
            state[_KEY] = read_cart(user.state)
            person.state = state
            flag_modified(person, "state")
            u_state = dict(user.state or {})
            u_state.pop(_KEY, None)
            user.state = u_state
            flag_modified(user, "state")
            await db.commit()
        return person
    ident = (await db.execute(
        select(Identity).where(Identity.channel == channel,
                               Identity.external_id == key)
    )).scalar_one_or_none()
    if ident is None:
        return None
    return await _live_person(db, ident.person_id)


async def _live_person(db: AsyncSession, person_id) -> Person | None:
    """The SURVIVING person — follows the merge tombstone chain, so a contact
    whose person was merged (e.g. a ref-linked web visitor pinned to the old row)
    still reads and writes the one live cart/measurements store."""
    person = await db.get(Person, person_id) if person_id else None
    hops = 0
    while person is not None and person.merged_into_id and hops < 5:
        person = await db.get(Person, person.merged_into_id)
        hops += 1
    return person


def read_cart(state: dict | None) -> dict:
    cart = (state or {}).get(_KEY)
    if not isinstance(cart, dict) or not isinstance(cart.get("items"), list):
        return _empty()
    return cart


def cart_total(cart: dict) -> float:
    return round(sum(float(i.get("unit_price") or 0) * int(i.get("qty") or 0)
                     for i in cart.get("items", [])), 2)


async def get_cart(db: AsyncSession, wa_id: str, channel: str = "whatsapp") -> dict:
    store = await _load_store(db, wa_id, channel)
    return read_cart(getattr(store, "state", None) if store else None)


async def save_cart(db: AsyncSession, wa_id: str, cart: dict,
                    channel: str = "whatsapp") -> dict:
    store = await _load_store(db, wa_id, channel)
    if store is None:
        return cart
    state = dict(store.state or {})
    state[_KEY] = cart
    store.state = state
    # JSONB columns need an explicit reassignment to be flagged dirty.
    from sqlalchemy.orm.attributes import flag_modified
    flag_modified(store, "state")
    await db.commit()
    return cart


async def clear_cart(db: AsyncSession, wa_id: str, channel: str = "whatsapp") -> dict:
    return await save_cart(db, wa_id, _empty(), channel)
