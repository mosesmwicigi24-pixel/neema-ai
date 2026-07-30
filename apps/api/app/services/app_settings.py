"""Standing orders — the owner's steering wheel between deploys.

`operator_directives` is read before EVERY agent turn (redis-cached, 5 min) and
injected into the system prompt, hard-capped so a long note can't crowd out the
selling rules. Directives steer emphasis; they can never override pricing,
payment or stock safety rules (the prompt says so explicitly).
"""
from __future__ import annotations

import logging

from sqlalchemy import select

DIRECTIVES_KEY = "operator_directives"
DIRECTIVES_CACHE = "app:directives"
DIRECTIVES_MAX_CHARS = 600

_log = logging.getLogger("neema.settings")


async def get_directives(db, redis) -> str:
    """Current standing orders — cache-first, DB fallback, '' on any failure
    (a settings hiccup must never break a customer reply)."""
    if redis is not None:
        try:
            v = await redis.get(DIRECTIVES_CACHE)
            if v is not None:
                return (v.decode() if isinstance(v, bytes) else str(v))[:DIRECTIVES_MAX_CHARS]
        except Exception:
            pass
    try:
        from app.models.app_setting import AppSetting
        row = (await db.execute(select(AppSetting).where(
            AppSetting.id == DIRECTIVES_KEY))).scalar_one_or_none()
        val = ((row.value if row else "") or "")[:DIRECTIVES_MAX_CHARS]
    except Exception:
        return ""
    if redis is not None:
        try:
            await redis.set(DIRECTIVES_CACHE, val, ex=300)
        except Exception:
            pass
    return val


async def set_directives(db, redis, value: str, updated_by=None) -> str:
    from app.models.app_setting import AppSetting
    val = (value or "").strip()[:DIRECTIVES_MAX_CHARS]
    row = (await db.execute(select(AppSetting).where(
        AppSetting.id == DIRECTIVES_KEY))).scalar_one_or_none()
    if row is None:
        row = AppSetting(id=DIRECTIVES_KEY, value=val, updated_by=updated_by)
        db.add(row)
    else:
        row.value = val
        row.updated_by = updated_by
    await db.commit()
    if redis is not None:
        try:
            await redis.set(DIRECTIVES_CACHE, val, ex=300)
        except Exception:
            pass
    return val
