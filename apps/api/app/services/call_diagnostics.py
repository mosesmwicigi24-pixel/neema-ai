"""WHY A CALL'S AUDIO DID NOT CONNECT (owner, 2026-11-15: "it's not
connecting, we're not able to get through calls").

"The call audio couldn't connect" was shown on the device and recorded
nowhere: no reason, no network detail, and an answered call whose audio never
formed was logged as completed. Each device now reports what it saw when a
call's audio fails — the connection states, what kinds of network path it
found (direct, via STUN, via a relay), whether our relay was offered — and the
last few hundred reports are kept for the owner's reports page.

No new table: the reports live in a capped redis list (`calls:diag`) and one
log line each. They hold no customer number and no audio.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

_log = logging.getLogger("neema.call_diagnostics")

KEY = "calls:diag"
KEEP = 500
_STATES = {"new", "checking", "connecting", "connected", "completed", "disconnected", "failed",
           "closed", "gathering", "complete", "unknown", ""}
_KINDS = ("host", "srflx", "prflx", "relay")


def _word(v, allowed=_STATES, limit: int = 24) -> str:
    s = str(v or "").strip().lower()[:limit]
    return s if s in allowed else "unknown"


def _counts(v) -> dict:
    out = {}
    if isinstance(v, dict):
        for k in _KINDS:
            try:
                out[k] = max(0, min(int(v.get(k) or 0), 99))
            except (TypeError, ValueError):
                out[k] = 0
    return out


def clean(body: dict | None) -> dict:
    """The report as stored: a fixed set of short fields — nothing a client
    sends is kept verbatim except bounded plain words."""
    b = body if isinstance(body, dict) else {}
    return {
        "stage": _word(b.get("stage"), {"connect_guard", "ice_failed", "ice_lost", "no_answer_sdp",
                                        "mic", "signalling", "other"}),
        "direction": _word(b.get("direction"), {"inbound", "outbound"}),
        "connection": _word(b.get("connection")),
        "ice": _word(b.get("ice")),
        "gathering": _word(b.get("gathering")),
        "local": _counts(b.get("local")),
        "remote": _counts(b.get("remote")),
        "pair": _word(b.get("pair"), {"none", "host", "srflx", "prflx", "relay", "unknown"}),
        "relay_offered": bool(b.get("relay_offered")),
        "relay_errors": max(0, min(int(b.get("relay_errors") or 0), 99))
        if str(b.get("relay_errors") or "0").isdigit() else 0,
        "seconds": max(0, min(int(b.get("seconds") or 0), 600))
        if str(b.get("seconds") or "0").isdigit() else 0,
        "client": _word(b.get("client"), {"web", "android", "ios"}),
        "platform": " ".join(str(b.get("platform") or "").split())[:60],
        "network": _word(b.get("network"), {"wifi", "cellular", "ethernet", "none", "unknown",
                                            "4g", "3g", "2g", "slow-2g", "5g"}),
    }


def reading(r: dict) -> str:
    """One plain sentence on what a report most likely means."""
    local = r.get("local") or {}
    if r.get("stage") == "mic":
        return "The microphone could not be opened on that device."
    if not any(local.values()):
        return "The device found no network path at all (blocked network, or it gave up early)."
    if not local.get("relay"):
        if not r.get("relay_offered"):
            return "No relay of our own was offered, and the device could not get one from the fallback."
        return "Our relay was offered but the device could not reach it (port blocked, or the relay is down)."
    if r.get("pair") in ("none", "unknown", ""):
        return "A relay path existed but audio still did not flow — look at the far side or the relay's ports."
    return "A path was chosen and then lost."


async def record(redis, call_id: str, agent, body: dict | None) -> dict:
    row = clean(body)
    row.update(at=datetime.now(timezone.utc).isoformat(), call=str(call_id)[-8:],
               agent=str(getattr(agent, "name", "") or "")[:60])
    row["reading"] = reading(row)
    _log.warning("call audio failed: %s", json.dumps(row, ensure_ascii=False))
    if redis is not None:
        try:
            await redis.lpush(KEY, json.dumps(row, ensure_ascii=False))
            await redis.ltrim(KEY, 0, KEEP - 1)
        except Exception as exc:
            _log.info("call diagnostics not stored: %s", exc)
    return row


async def recent(redis, limit: int = 50) -> dict:
    rows: list[dict] = []
    if redis is not None:
        try:
            for raw in await redis.lrange(KEY, 0, max(1, min(int(limit), KEEP)) - 1):
                try:
                    rows.append(json.loads(raw if isinstance(raw, str) else raw.decode()))
                except Exception:
                    continue
        except Exception as exc:
            _log.info("call diagnostics unreadable: %s", exc)
    by: dict[str, int] = {}
    for r in rows:
        by[r.get("reading") or "?"] = by.get(r.get("reading") or "?", 0) + 1
    return {"count": len(rows), "by_reading": by, "items": rows}
