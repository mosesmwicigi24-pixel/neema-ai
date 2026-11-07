"""Are customer messages still ARRIVING? — the question the health endpoint
could not answer.

The owner twice reported "no new inbound chats" (after the Stage 8 deploy, and
on 2026-11-07 after four quiet hours across WhatsApp, Messenger, Instagram
and Facebook). Both times the webhooks were alive and nothing could say,
from outside the box, when the last customer message had actually landed:
the inbox lists only threads a person holds, the review tallies count
replies (shadow drafts included), and the box logs need SSH.

Every inbound door stamps here when it ACCEPTS a customer message — after
the signature check, after dedup, when a Message row is written — and
`/api/health` reports, per channel, when the last one arrived and how many
came in the rolling hour. Coarse by construction: a channel name, a time
and a count; never a number, a handle or a text. Best-effort by
construction: a redis blip never costs the message.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

_log = logging.getLogger("neema.health")

CHANNELS = ("whatsapp", "messenger", "instagram", "comment", "tiktok")
_LAST_TTL = 30 * 24 * 3600          # "last seen" survives a quiet month
_HOUR = 3600                        # the count is a rolling hour, like agent_health


def _last_key(channel: str) -> str:
    return f"inbound:last:{channel}"


def _count_key(channel: str) -> str:
    return f"inbound:count:{channel}"


async def stamp(redis, channel: str) -> None:
    """A customer message was accepted on `channel` just now."""
    if redis is None or channel not in CHANNELS:
        return
    try:
        await redis.set(_last_key(channel), datetime.now(timezone.utc).isoformat(timespec="seconds"),
                        ex=_LAST_TTL)
        n = await redis.incr(_count_key(channel))
        if n == 1:
            await redis.expire(_count_key(channel), _HOUR)
    except Exception as exc:                     # monitoring never costs a message
        _log.debug("inbound stamp skipped for %s: %s", channel, exc)


async def read(redis, *, now: datetime | None = None) -> dict:
    """{channel: {last_at, last_hour, silent_for_min}} for every channel,
    plus `quiet_for_min`: how long since ANY channel last delivered (None
    when nothing has ever been stamped — a fresh box, or redis gone)."""
    now = now or datetime.now(timezone.utc)
    out: dict = {}
    newest: datetime | None = None
    for ch in CHANNELS:
        last_at = None
        count = 0
        if redis is not None:
            try:
                raw = await redis.get(_last_key(ch))
                last_at = str(raw) if raw else None
                rc = await redis.get(_count_key(ch))
                count = int(rc) if rc else 0
            except Exception:
                last_at, count = None, 0
        silent = None
        if last_at:
            try:
                then = datetime.fromisoformat(last_at)
                if then.tzinfo is None:
                    then = then.replace(tzinfo=timezone.utc)
                silent = max(0, int((now - then).total_seconds() // 60))
                if newest is None or then > newest:
                    newest = then
            except Exception:
                silent = None
        out[ch] = {"last_at": last_at, "last_hour": count, "silent_for_min": silent}
    out["quiet_for_min"] = (max(0, int((now - newest).total_seconds() // 60))
                            if newest is not None else None)
    return out
