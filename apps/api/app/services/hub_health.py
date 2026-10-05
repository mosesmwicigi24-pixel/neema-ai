"""Is the hub still taking Neema's orders?

From 2026-08-24 to 2026-10-05 every order Neema tried to place was refused by
the hub (403 on POST /api/v1/admin/pos/pending-order — a staff gate that did
not know her service account). 151 attempts across 76+ conversations, and
nobody noticed for six weeks: the failure was only a tool result the model
read, and nothing watched the order path itself.

This watches it two ways:
- a cheap READ-ONLY probe of the same authenticated route group with the same
  token (GET /api/v1/admin/pos/pending-order/open?outlet_id=…), run by the
  hourly self-check;
- every real create_order outcome (a refusal, a hub error or an accepted order)
  is recorded here too, so the state moves the moment an order fails.

A failing state logs ERROR, rings the team (at most once an hour) and shows in
/api/health as `hub_orders: failing` — coarse kinds only, never the token, the
URL or the hub's raw reply. Best-effort everywhere: monitoring must never cost
a reply or an order.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

import httpx

from app.core.config import settings

_log = logging.getLogger("neema.hub")

STATE_KEY = "hub:orders:health"
ALARM_KEY = "hub:orders:alarm"
_STATE_TTL = 3 * 3600            # outlives two hourly probes; absent = unknown
_ALARM_EVERY = 3600              # one ring an hour while it stays broken

_KIND_TEXT = {
    "unauthorized": "the hub rejects Neema's token (401) — re-issue HUB_API_TOKEN",
    "forbidden": ("the hub refuses Neema's account (403) — check the neema-bot service "
                  "account's access to /admin/pos"),
    "server_error": "the hub is erroring (5xx)",
    "timeout": "the hub is not answering (timeout)",
    "network": "the hub cannot be reached",
    "unconfigured": "HUB_API_TOKEN is not set on the box",
    "http_error": "the hub answered with an unexpected error",
}


def kind_of(http_status: int | None, exc: Exception | None = None) -> str:
    """A coarse, secret-free name for a hub failure."""
    if http_status == 401:
        return "unauthorized"
    if http_status == 403:
        return "forbidden"
    if http_status is not None and http_status >= 500:
        return "server_error"
    if http_status is not None:
        return "http_error"
    if isinstance(exc, httpx.TimeoutException):
        return "timeout"
    return "network"


def path_broken(http_status: int | None, kind: str) -> bool:
    """Does this order failure say the ORDER PATH is down (every order will
    fail), rather than this one order being refused on its merits (a 422 on
    stock, say)?"""
    if http_status in (401, 403) or (http_status is not None and http_status >= 500):
        return True
    return kind in ("timeout", "network", "unconfigured")


async def record(redis, *, ok: bool, http_status: int | None = None,
                 kind: str = "ok", source: str = "probe") -> dict:
    """Store the order path's state; on failure log ERROR and ring the team
    (rate-limited). Never raises."""
    state = {"status": "ok" if ok else "failing", "http_status": http_status,
             "kind": "ok" if ok else kind, "source": source,
             "at": datetime.now(timezone.utc).isoformat()}
    if not ok:
        _log.error("HUB ORDER PATH FAILING (%s, %s, http %s): %s", source, kind,
                   http_status, _KIND_TEXT.get(kind, kind))
    if redis is None:
        return state
    try:
        await redis.set(STATE_KEY, json.dumps(state), ex=_STATE_TTL)
    except Exception:
        _log.warning("hub order health not stored", exc_info=True)
    if not ok:
        await _alarm(redis, state)
    return state


async def _alarm(redis, state: dict) -> bool:
    """One team notification an hour while the order path is broken — the
    same `hub_event` frame the hub relay rings with (high priority on
    Android, opens Orders)."""
    try:
        if not await redis.set(ALARM_KEY, "1", nx=True, ex=_ALARM_EVERY):
            return False
        await redis.publish("ws:channel:agents:all", json.dumps({
            "event": "notification", "type": "hub_event",
            "title": "🚨 The hub is refusing Neema's orders",
            "body": (f"Orders cannot be placed: {_KIND_TEXT.get(state.get('kind'), state.get('kind'))}. "
                     "Customers' orders are being handed to you — fix the hub link.")[:200],
        }))
        return True
    except Exception:
        _log.warning("hub order alarm not sent", exc_info=True)
        return False


async def probe(redis) -> dict:
    """The cheap read-only check of the order path, with Neema's own token."""
    if not settings.hub_api_token:
        return await record(redis, ok=False, kind="unconfigured")
    from app.core.hub_client import _api_headers
    base = settings.hub_api_url.rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{base}/api/v1/admin/pos/pending-order/open",
                                    headers=_api_headers(),
                                    params={"outlet_id": settings.hub_outlet_id})
    except Exception as exc:
        return await record(redis, ok=False, kind=kind_of(None, exc))
    status = resp.status_code
    if 200 <= status < 300:
        return await record(redis, ok=True, http_status=status)
    return await record(redis, ok=False, http_status=status, kind=kind_of(status))


async def read(redis) -> dict:
    """The last recorded state, {} when nothing is known."""
    if redis is None:
        return {}
    try:
        raw = await redis.get(STATE_KEY)
        return json.loads(raw) if raw else {}
    except Exception:
        return {}


def health_view(state: dict) -> dict:
    """What /api/health shows — coarse and secret-free."""
    if not state:
        return {"status": "unknown"}
    out = {"status": state.get("status") or "unknown", "checked_at": state.get("at")}
    if state.get("status") == "failing":
        out["kind"] = state.get("kind")
        if state.get("http_status") is not None:
            out["http_status"] = state.get("http_status")
    return out


def finding(state: dict) -> list[str]:
    """The self-check / standup line for a failing order path."""
    if (state or {}).get("status") != "failing":
        return []
    return ["HUB ORDERS FAILING — Neema cannot place orders: "
            + _KIND_TEXT.get(state.get("kind"), str(state.get("kind")))]
