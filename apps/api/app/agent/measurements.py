"""Measurements on file — so a repeat made-to-order takes one tap, not ten questions.

Bethany House makes vestments to size. Today a returning customer is asked for
their measurements all over again, every time, on every channel — the single
biggest friction point in the whole order flow, and the thing a tailor who knows
you would never do.

Stored on the same durable store as the cart (`persons.state["measurements"]`,
falling back to the WhatsApp `users.state`) via cart._load_store, so ONE definition
decides where a customer's durable state lives: measurements taken on the website
form are the measurements Neema recalls on WhatsApp.

Shape — free-form label → value, because garments differ (a cassock needs length
and chest; a mitre needs a head circumference) and we must never lose a figure a
customer gave us just because it wasn't in a fixed schema:

    {"chest": "42in", "length": "58in", "sleeve": "24in",
     "_updated_at": "2026-07-27T09:00:00+00:00", "_source": "website form"}
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

# ONE definition of where a customer's durable state lives (person-first, with the
# WhatsApp user row as the fallback + one-time adoption). Reused, never re-derived.
from app.agent.cart import _load_store

_KEY = "measurements"
_META = ("_updated_at", "_source")
_MAX_FIELDS = 24


def read_measurements(state: dict | None) -> dict:
    m = (state or {}).get(_KEY)
    return dict(m) if isinstance(m, dict) else {}


def visible(m: dict | None) -> dict:
    """Just the figures — without our bookkeeping keys."""
    return {k: v for k, v in (m or {}).items() if k not in _META and v not in (None, "")}


def describe(m: dict | None) -> str:
    """One human line: 'chest 42in · length 58in · sleeve 24in'."""
    fields = visible(m)
    return " · ".join(f"{k.replace('_', ' ')} {v}" for k, v in fields.items())


async def get_measurements(db: AsyncSession, key: str, channel: str = "whatsapp") -> dict:
    store = await _load_store(db, key, channel)
    return read_measurements(getattr(store, "state", None) if store else None)


async def save_measurements(db: AsyncSession, key: str, fields: dict,
                            channel: str = "whatsapp", source: str = "chat") -> dict:
    """Merge new figures over what we already hold (a customer correcting one
    measurement must never wipe the rest) and stamp when/where they came from.
    No-ops when the contact doesn't resolve, rather than losing the figures."""
    clean = {str(k).strip().lower().replace(" ", "_"): str(v).strip()
             for k, v in (fields or {}).items()
             if str(k).strip() and str(v).strip() and str(k).strip().lower() not in _META}
    if not clean:
        return await get_measurements(db, key, channel)

    store = await _load_store(db, key, channel)
    if store is None:
        return {}
    current = read_measurements(getattr(store, "state", None))
    merged = {**current, **clean}
    # Keep it bounded — newest wins if a conversation goes wild.
    if len(merged) > _MAX_FIELDS:
        merged = dict(list(merged.items())[-_MAX_FIELDS:])
    merged["_updated_at"] = datetime.now(timezone.utc).isoformat()
    merged["_source"] = source

    from sqlalchemy.orm.attributes import flag_modified
    state = dict(store.state or {})
    state[_KEY] = merged
    store.state = state
    flag_modified(store, "state")           # JSONB needs an explicit dirty flag
    await db.commit()
    return merged
