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


async def get_value(db, key: str) -> str:
    try:
        from app.models.app_setting import AppSetting
        row = (await db.execute(select(AppSetting).where(
            AppSetting.id == key))).scalar_one_or_none()
        return (row.value if row else "") or ""
    except Exception:
        return ""


async def set_value(db, key: str, value: str) -> None:
    from app.models.app_setting import AppSetting
    row = (await db.execute(select(AppSetting).where(
        AppSetting.id == key))).scalar_one_or_none()
    if row is None:
        db.add(AppSetting(id=key, value=value))
    else:
        row.value = value
    await db.commit()


LEARNED_CACHE = "app:learned_rules"


async def get_learned_rules(db, redis) -> str:
    """Rules the owner approved from the weekly distillation — cached like the
    directives, injected into the prompt alongside them."""
    if redis is not None:
        try:
            v = await redis.get(LEARNED_CACHE)
            if v is not None:
                return v.decode() if isinstance(v, bytes) else str(v)
        except Exception:
            pass
    val = await get_value(db, "learned_rules")
    if redis is not None:
        try:
            await redis.set(LEARNED_CACHE, val, ex=300)
        except Exception:
            pass
    return val


HOUSE_VOICE_CACHE = "app:house_voice"


async def get_house_voice(db, redis) -> str:
    """The distilled voice of the team's own replies (app.tools.stylebook) —
    cached like the directives, injected beside the brevity contract."""
    if redis is not None:
        try:
            v = await redis.get(HOUSE_VOICE_CACHE)
            if v is not None:
                return v.decode() if isinstance(v, bytes) else str(v)
        except Exception:
            pass
    val = await get_value(db, "house_voice")
    if redis is not None:
        try:
            await redis.set(HOUSE_VOICE_CACHE, val, ex=300)
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


# ── Team translation (services/translate.py) ─────────────────────────────────
# The reading glass costs money on every foreign message, so a person must be
# able to stop it — and start it again — without an env edit and a restart.
# `TRANSLATE_FOR_TEAM` in the environment is the DEFAULT; this row overrides it
# for good once anyone touches the switch.

TRANSLATE_KEY = "translate_for_team"
TRANSLATE_CACHE = "app:translate_enabled"


def _default_translate_enabled() -> bool:
    from app.core.config import settings
    return bool(getattr(settings, "translate_for_team", True))


async def translate_enabled_cached(redis) -> bool | None:
    """The switch from redis alone — None when the cache can't answer.

    Split out because both callers sit on hot paths (every reply, every thread
    open) and neither should reach for a database on the normal case."""
    if redis is None:
        return None
    try:
        v = await redis.get(TRANSLATE_CACHE)
    except Exception:
        return None
    if v is None:
        return None
    s = v.decode() if isinstance(v, bytes) else str(v)
    return s == "on" if s in ("on", "off") else None


async def get_translate_enabled(db, redis) -> bool:
    """Is the team's reading glass on right now?

    Cache-first, DB fallback, and on ANY failure the environment default —
    a settings hiccup must never silently disable a feature the owner paid to
    have on, nor silently enable one they turned off.
    """
    cached = await translate_enabled_cached(redis)
    if cached is not None:
        return cached
    try:
        val = (await get_value(db, TRANSLATE_KEY) or "").strip().lower()
    except Exception:
        return _default_translate_enabled()
    enabled = _default_translate_enabled() if val not in ("on", "off") else val == "on"
    if redis is not None:
        try:
            await redis.set(TRANSLATE_CACHE, "on" if enabled else "off", ex=300)
        except Exception:
            pass
    return enabled


async def set_translate_enabled(db, redis, enabled: bool, updated_by=None) -> bool:
    """Flip the switch. The cache is written in the same breath as the row, so
    the next thread-open honours it immediately rather than up to 5 minutes
    later — an operator who turns this off during a spend scare means NOW."""
    from app.models.app_setting import AppSetting
    val = "on" if enabled else "off"
    row = (await db.execute(select(AppSetting).where(
        AppSetting.id == TRANSLATE_KEY))).scalar_one_or_none()
    if row is None:
        db.add(AppSetting(id=TRANSLATE_KEY, value=val, updated_by=updated_by))
    else:
        row.value = val
        row.updated_by = updated_by
    await db.commit()
    if redis is not None:
        try:
            await redis.set(TRANSLATE_CACHE, val, ex=300)
        except Exception:
            pass
    _log.info("team translation turned %s", "ON" if enabled else "OFF")
    return enabled
