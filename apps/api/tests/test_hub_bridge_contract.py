"""The hub bridge contract — the Bethany House hub's pushes keep working.

Canonical surface: `/api/hub/*` with `X-Hub-Secret`. The hub's plugin is still
configured with the older `/api/n8n/*` prefix and `X-N8N-Secret` header, so the
same router is mounted there too; both read ONE secret (HUB_BRIDGE_SECRET, or
the older env name N8N_API_SECRET an existing box .env still carries). These
tests pin that nothing in the API depends on anything outside it, and that the
plugin's current address does not break.
"""
import app.main  # noqa: F401 — registers all models + routes
from app.main import app


def _paths() -> set[str]:
    return {r.path for r in app.routes if hasattr(r, "path")}


def test_hub_bridge_answers_on_both_prefixes():
    """Canonical paths at /api/hub/*, the plugin's current address at /api/n8n/*
    — the alias stays until the hub is repointed (HUB_BRIDGE_MIGRATION.md)."""
    paths = _paths()
    for route in ("payment", "order-event", "customer-history"):
        assert f"/api/hub/{route}" in paths, f"canonical /api/hub/{route} missing"
        assert f"/api/n8n/{route}" in paths, f"alias /api/n8n/{route} missing"


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
    monkeypatch.setattr(settings, "hub_bridge_secret", "s3cret", raising=False)
    r = _req("/api/hub/payment")
    asyncio.run(verify_hub_secret(r, x_hub_secret="s3cret", x_n8n_secret=None))
    asyncio.run(verify_hub_secret(r, x_hub_secret=None, x_n8n_secret="s3cret"))
    for bad in (dict(x_hub_secret=None, x_n8n_secret=None),
                dict(x_hub_secret="wrong", x_n8n_secret=None),
                dict(x_hub_secret="", x_n8n_secret="")):
        with pytest.raises(HTTPException):
            asyncio.run(verify_hub_secret(r, **bad))
    # Unconfigured secret must reject EVERYTHING — a check that compared equal
    # empty strings would wave an empty header through.
    monkeypatch.setattr(settings, "hub_bridge_secret", "", raising=False)
    with pytest.raises(HTTPException):
        asyncio.run(verify_hub_secret(r, x_hub_secret="", x_n8n_secret=None))
    with pytest.raises(HTTPException):
        asyncio.run(verify_hub_secret(r, x_hub_secret=None, x_n8n_secret=None))


def test_the_secret_is_read_from_either_env_name(monkeypatch):
    """A box .env that still says N8N_API_SECRET keeps authenticating the hub;
    a fresh box uses HUB_BRIDGE_SECRET. Same setting either way."""
    from app.core.config import Settings
    monkeypatch.delenv("HUB_BRIDGE_SECRET", raising=False)
    monkeypatch.setenv("N8N_API_SECRET", "old-name")
    assert Settings(_env_file=None).hub_bridge_secret == "old-name"
    monkeypatch.setenv("HUB_BRIDGE_SECRET", "new-name")
    assert Settings(_env_file=None).hub_bridge_secret == "new-name"
    monkeypatch.delenv("N8N_API_SECRET")
    assert Settings(_env_file=None).hub_bridge_secret == "new-name"
    assert "n8n_api_secret" not in Settings.model_fields


def test_alias_surface_hits_are_counted_clean_ones_are_not(monkeypatch):
    """The evidence for dropping the alias: the older prefix OR the older
    header bumps the daily counter; a fully-clean push does not."""
    import asyncio
    from app.core.config import settings
    from app.routers.hub_bridge import verify_hub_secret
    monkeypatch.setattr(settings, "hub_bridge_secret", "s3cret", raising=False)
    r = _FakeRedis()
    # older PATH (even with the clean header) counts
    asyncio.run(verify_hub_secret(_req("/api/n8n/payment", r),
                                  x_hub_secret="s3cret", x_n8n_secret=None))
    # older HEADER on the clean path counts
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


def test_standup_reports_alias_bridge_pushes(monkeypatch):
    """The owner learns from the 08:00 standup — not from box archaeology —
    whether the hub plugin has been repointed."""
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
    assert "🌉 Hub bridge: 7 push(es) yesterday still used the older /api/n8n alias" in out
    # and silence when the counter is empty
    r.counts.clear()
    out = asyncio.run(compose_standup(_DB()))
    assert "Hub bridge" not in out


def test_only_the_three_hub_pushes_exist_on_the_alias():
    """Nothing but the hub's three pushes answers under the older prefix: no
    message, session, usage, route, outbound, catalog, notify, escalate or
    media endpoints — the API never calls out to an orchestrator."""
    alias = sorted(p for p in _paths() if p.startswith("/api/n8n/"))
    assert alias == ["/api/n8n/customer-history", "/api/n8n/order-event", "/api/n8n/payment"]
    assert "/api/agent/turn" not in _paths()
    from app.agent import runtime
    assert not hasattr(runtime, "is_tier2")


def test_no_module_file_or_setting_carries_the_old_name():
    """The rename is complete: the messaging service and the bridge DTOs live
    under their own names, and nothing imports the old module paths."""
    import importlib.util
    import pathlib
    from app.services import messaging as svc
    assert hasattr(svc, "upsert_message") and hasattr(svc, "save_outbound_message")
    for gone in ("app.services.n8n_bridge", "app.schemas.n8n", "app.routers.n8n_bridge"):
        assert importlib.util.find_spec(gone) is None, gone
    app_dir = pathlib.Path(__file__).resolve().parents[1] / "app"
    offenders = [str(p.relative_to(app_dir)) for p in app_dir.rglob("*.py")
                 if "n8n" in p.name.lower()]
    assert offenders == []
    # Only the hub plugin's current address (prefix + header) and the env alias
    # may still spell the old name — nowhere else in the app's own code.
    allowed = {"routers/hub_bridge.py", "main.py", "jobs/self_qa.py", "core/config.py"}
    spelt = {str(p.relative_to(app_dir)) for p in app_dir.rglob("*.py")
             if "n8n" in p.read_text(errors="ignore").lower()}
    assert spelt <= allowed, spelt - allowed
