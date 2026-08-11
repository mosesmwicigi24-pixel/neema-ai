"""The n8n retirement (2026-08-11) — the code matches the infrastructure.

n8n's container was stopped 2026-07-30; the owner then asked for the code to be
corrected and aligned. These tests pin the retirement so the dead surface can't
quietly return, and pin the SURVIVORS so the hub's legacy pushes keep working:
the hub's plugin still posts payments/orders/history on the `/api/n8n` prefix
with the `X-N8N-SECRET` header — that bridge must outlive n8n itself.
"""
import app.main  # noqa: F401 — registers all models + routes
from app.main import app


def _paths() -> set[str]:
    return {r.path for r in app.routes if hasattr(r, "path")}


def test_hub_bridge_survives_on_both_prefixes():
    """Canonical clean paths at /api/hub/*, legacy aliases at /api/n8n/* —
    the aliases stay until the hub's plugin migrates (HUB_BRIDGE_MIGRATION.md)."""
    paths = _paths()
    for route in ("payment", "order-event", "customer-history"):
        assert f"/api/hub/{route}" in paths, f"canonical /api/hub/{route} missing"
        assert f"/api/n8n/{route}" in paths, f"legacy alias /api/n8n/{route} missing"


class _FakeRedis:
    def __init__(self):
        self.counts, self.ttls = {}, {}
    async def incr(self, k):
        self.counts[k] = self.counts.get(k, 0) + 1
        return self.counts[k]
    async def expire(self, k, ttl):
        self.ttls[k] = ttl
    async def get(self, k):
        v = self.counts.get(k)
        return None if v is None else str(v)


def _req(path: str, redis=None):
    import types
    return types.SimpleNamespace(
        url=types.SimpleNamespace(path=path),
        app=types.SimpleNamespace(state=types.SimpleNamespace(redis=redis)))


def test_hub_secret_accepts_both_headers_and_fails_closed(monkeypatch):
    import asyncio
    import pytest
    from fastapi import HTTPException
    from app.core.config import settings
    from app.routers.hub_bridge import verify_hub_secret
    monkeypatch.setattr(settings, "n8n_api_secret", "s3cret", raising=False)
    r = _req("/api/hub/payment")
    asyncio.run(verify_hub_secret(r, x_hub_secret="s3cret", x_n8n_secret=None))
    asyncio.run(verify_hub_secret(r, x_hub_secret=None, x_n8n_secret="s3cret"))
    for bad in (dict(x_hub_secret=None, x_n8n_secret=None),
                dict(x_hub_secret="wrong", x_n8n_secret=None),
                dict(x_hub_secret="", x_n8n_secret="")):
        with pytest.raises(HTTPException):
            asyncio.run(verify_hub_secret(r, **bad))
    # Unconfigured secret must reject EVERYTHING — the old check compared
    # equal empty strings and would have waved an empty header through.
    monkeypatch.setattr(settings, "n8n_api_secret", "", raising=False)
    with pytest.raises(HTTPException):
        asyncio.run(verify_hub_secret(r, x_hub_secret="", x_n8n_secret=None))
    with pytest.raises(HTTPException):
        asyncio.run(verify_hub_secret(r, x_hub_secret=None, x_n8n_secret=None))


def test_legacy_surface_hits_are_counted_clean_ones_are_not(monkeypatch):
    """The migration's evidence: legacy prefix OR legacy header bumps the daily
    counter; a fully-clean push (new path + new header) does not."""
    import asyncio
    from app.core.config import settings
    from app.routers.hub_bridge import verify_hub_secret
    monkeypatch.setattr(settings, "n8n_api_secret", "s3cret", raising=False)
    r = _FakeRedis()
    # legacy PATH (even with the clean header) counts
    asyncio.run(verify_hub_secret(_req("/api/n8n/payment", r),
                                  x_hub_secret="s3cret", x_n8n_secret=None))
    # legacy HEADER on the clean path counts
    asyncio.run(verify_hub_secret(_req("/api/hub/payment", r),
                                  x_hub_secret=None, x_n8n_secret="s3cret"))
    assert sum(r.counts.values()) == 2
    assert all(k.startswith("bridge:legacy:") for k in r.counts)
    assert all(ttl == 14 * 24 * 3600 for ttl in r.ttls.values())
    # fully clean push → no count
    asyncio.run(verify_hub_secret(_req("/api/hub/payment", r),
                                  x_hub_secret="s3cret", x_n8n_secret=None))
    assert sum(r.counts.values()) == 2
    # an unauthenticated hit never counts (403 first)
    import pytest
    from fastapi import HTTPException
    with pytest.raises(HTTPException):
        asyncio.run(verify_hub_secret(_req("/api/n8n/payment", r),
                                      x_hub_secret=None, x_n8n_secret="wrong"))
    assert sum(r.counts.values()) == 2


def test_standup_reports_legacy_bridge_pushes(monkeypatch):
    """The owner learns from the 08:00 standup — not from box archaeology —
    whether the hub plugin has fully migrated."""
    import asyncio
    from datetime import datetime, timedelta, timezone
    from app.jobs.self_qa import compose_standup
    from app.main import app as _app
    r = _FakeRedis()
    y = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y%m%d")
    r.counts[f"bridge:legacy:{y}"] = 7
    monkeypatch.setattr(_app.state, "redis", r, raising=False)

    class _Res:
        def scalar_one(self): return 0
        def scalars(self): return self
        def all(self): return []
        def one(self): return (0, 0)
    class _DB:
        async def execute(self, *a, **k): return _Res()
    out = asyncio.run(compose_standup(_DB()))
    assert "🌉 Hub bridge: 7 push(es) yesterday still used the legacy /api/n8n path" in out
    # and silence when the counter is empty
    r.counts.clear()
    out = asyncio.run(compose_standup(_DB()))
    assert "Hub bridge" not in out


def test_n8n_workflow_only_routes_are_gone():
    paths = _paths()
    for gone in ("/api/n8n/context/{wa_id}", "/api/n8n/session",
                 "/api/n8n/profile/{wa_id}", "/api/n8n/messages/{wa_id}",
                 "/api/n8n/message", "/api/n8n/user", "/api/n8n/usage",
                 "/api/n8n/route", "/api/n8n/outbound", "/api/n8n/catalog",
                 "/api/n8n/notify", "/api/n8n/escalate",
                 "/api/n8n/media/save-tts", "/api/n8n/media/download"):
        assert gone not in paths, f"n8n-only route {gone} should be retired"


def test_tier_routing_seam_is_gone():
    """/agent/turn was n8n's hop into the agent; native calls the runtime
    directly, so the whole Tier-1/Tier-2 seam retires with it."""
    assert "/api/agent/turn" not in _paths()
    from app.agent import runtime
    assert not hasattr(runtime, "is_tier2")


def test_the_hub_secret_and_service_module_stay():
    """N8N_API_SECRET authenticates the hub's pushes (setting keeps its env
    name), and services/n8n_bridge.py is the messaging service — historical
    name, real code."""
    from app.core.config import Settings
    assert "n8n_api_secret" in Settings.model_fields
    from app.services import n8n_bridge as svc
    assert hasattr(svc, "upsert_message") and hasattr(svc, "save_outbound_message")
    # and the retired ROUTER module name is gone — the router is hub_bridge now
    import importlib.util
    assert importlib.util.find_spec("app.routers.n8n_bridge") is None
