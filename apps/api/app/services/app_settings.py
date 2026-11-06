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


# ── Outbound communication control (services/actions.py, Stage 5) ────────────
# The shadow week ends with a decision per RULE, not one big switch: the two
# "someone already answered" rules are near-certain and go first, the daily cap
# trades recoveries for restraint and deserves its own week. `OUTREACH_MODE`
# and `OUTREACH_ENFORCE_RULES` in the environment are the DEFAULTS; these rows
# override them from the dashboard, between deploys, in seconds.

OUTREACH_MODE_KEY = "outreach_mode"
OUTREACH_RULES_KEY = "outreach_enforce_rules"
OUTREACH_CACHE = "app:outreach_control"
OUTREACH_MODES = ("shadow", "enforce")
OUTREACH_RULES = ("customer_replied", "colleague_replied", "daily_cap")
OUTREACH_RULE_LABELS = {
    "customer_replied": "the customer wrote after the message was planned",
    "colleague_replied": "a colleague replied after the message was planned",
    "daily_cap": "one unprompted sales message per customer per day",
}


def parse_outreach_rules(text: str | None) -> list[str]:
    """'customer_replied, daily_cap' → the known rules, in canonical order."""
    wanted = {w.strip().lower() for w in (text or "").replace(";", ",").split(",") if w.strip()}
    return [r for r in OUTREACH_RULES if r in wanted]


def _default_outreach_control() -> dict:
    from app.core.config import settings
    mode = str(getattr(settings, "outreach_mode", "shadow") or "shadow").strip().lower()
    return {"mode": mode if mode in OUTREACH_MODES else "shadow",
            "rules": parse_outreach_rules(getattr(settings, "outreach_enforce_rules", ""))}


def _decode_control(raw) -> dict | None:
    import json
    try:
        data = json.loads(raw.decode() if isinstance(raw, bytes) else str(raw))
    except (TypeError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("mode") not in OUTREACH_MODES:
        return None
    return {"mode": data["mode"], "rules": parse_outreach_rules(",".join(data.get("rules") or []))}


async def outreach_control_cached(redis) -> dict | None:
    """The control from redis alone — None when the cache can't answer."""
    if redis is None:
        return None
    try:
        v = await redis.get(OUTREACH_CACHE)
    except Exception:
        return None
    return _decode_control(v) if v is not None else None


async def get_outreach_control(db, redis) -> dict:
    """{'mode': shadow|enforce, 'rules': [enforced while in shadow]}.
    Cache-first, DB fallback, the environment default on any failure."""
    cached = await outreach_control_cached(redis)
    if cached is not None:
        return cached
    default = _default_outreach_control()
    try:
        mode_v = (await get_value(db, OUTREACH_MODE_KEY) or "").strip().lower()
        rules_v = await get_value(db, OUTREACH_RULES_KEY)
    except Exception:
        return default
    ctrl = {"mode": mode_v if mode_v in OUTREACH_MODES else default["mode"],
            "rules": parse_outreach_rules(rules_v) if (rules_v or "").strip() else default["rules"]}
    if redis is not None:
        try:
            import json
            await redis.set(OUTREACH_CACHE, json.dumps(ctrl), ex=300)
        except Exception:
            pass
    return ctrl


async def set_outreach_control(db, redis, *, mode: str | None = None, rules: list[str] | None = None,
                               updated_by=None) -> dict:
    """Change the mode and/or the enforced rules; the cache is written in the
    same breath so the next dispatcher tick honours it."""
    from app.models.app_setting import AppSetting
    if mode is not None and mode not in OUTREACH_MODES:
        raise ValueError(f"mode must be one of {', '.join(OUTREACH_MODES)}")
    if rules is not None:
        bad = [r for r in rules if r not in OUTREACH_RULES]
        if bad:
            raise ValueError(f"unknown rule(s): {', '.join(bad)}")
    writes = {}
    if mode is not None:
        writes[OUTREACH_MODE_KEY] = mode
    if rules is not None:
        # an explicit empty list is stored as "-" so it overrides the environment default
        writes[OUTREACH_RULES_KEY] = ",".join(parse_outreach_rules(",".join(rules))) or "-"
    for key, val in writes.items():
        row = (await db.execute(select(AppSetting).where(AppSetting.id == key))).scalar_one_or_none()
        if row is None:
            db.add(AppSetting(id=key, value=val, updated_by=updated_by))
        else:
            row.value = val
            row.updated_by = updated_by
    await db.commit()
    if redis is not None:
        try:
            await redis.delete(OUTREACH_CACHE)
        except Exception:
            pass
    ctrl = await get_outreach_control(db, redis)
    _log.info("outreach control: mode=%s enforced=%s", ctrl["mode"], ",".join(ctrl["rules"]) or "-")
    return ctrl
