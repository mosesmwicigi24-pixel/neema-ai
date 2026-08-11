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


def test_hub_secret_accepts_both_headers_and_fails_closed(monkeypatch):
    import pytest
    from fastapi import HTTPException
    from app.core.config import settings
    from app.routers.hub_bridge import verify_hub_secret
    monkeypatch.setattr(settings, "n8n_api_secret", "s3cret", raising=False)
    verify_hub_secret(x_hub_secret="s3cret", x_n8n_secret=None)     # clean header
    verify_hub_secret(x_hub_secret=None, x_n8n_secret="s3cret")     # legacy header
    for bad in (dict(x_hub_secret=None, x_n8n_secret=None),
                dict(x_hub_secret="wrong", x_n8n_secret=None),
                dict(x_hub_secret="", x_n8n_secret="")):
        with pytest.raises(HTTPException):
            verify_hub_secret(**bad)
    # Unconfigured secret must reject EVERYTHING — the old check compared
    # equal empty strings and would have waved an empty header through.
    monkeypatch.setattr(settings, "n8n_api_secret", "", raising=False)
    with pytest.raises(HTTPException):
        verify_hub_secret(x_hub_secret="", x_n8n_secret=None)
    with pytest.raises(HTTPException):
        verify_hub_secret(x_hub_secret=None, x_n8n_secret=None)


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
