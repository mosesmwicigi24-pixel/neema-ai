"""CAN NEEMA STILL PLACE AN ORDER? (2026-10-05)

Nothing watched the hub order path, so six weeks of 403s went unseen. The
self-check now probes it read-only with Neema's own token; a refusal logs
ERROR, rings the team at most once an hour, and /api/health shows
`hub_orders: failing` — never the token, the URL or the hub's reply.
"""
import asyncio
import json
import logging
from types import SimpleNamespace

import httpx

import app.main  # noqa: F401
from app.core.config import settings
from app.routers.health import health
from app.services import hub_health, selfcheck

TOKEN = "sekret-hub-token-DO-NOT-LEAK"


class _Redis:
    def __init__(self):
        self.kv: dict = {}
        self.published: list = []

    async def get(self, k):
        return self.kv.get(k)

    async def set(self, k, v, nx=False, ex=None):
        if nx and k in self.kv:
            return None
        self.kv[k] = v
        return True

    async def publish(self, channel, payload):
        self.published.append((channel, json.loads(payload)))


def _hub(monkeypatch, status):
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(status, json={"message": "This action is unauthorized."}
                              if status == 403 else None)
    real = httpx.AsyncClient
    monkeypatch.setattr(hub_health.httpx, "AsyncClient",
                        lambda *a, **k: real(*a, transport=httpx.MockTransport(handler), **k))
    monkeypatch.setattr(settings, "hub_api_token", TOKEN, raising=False)
    monkeypatch.setattr(settings, "hub_outlet_id", 2, raising=False)
    return seen


def _health(r):
    req = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(redis=r)))
    return asyncio.run(health(req))


def _alarms(r):
    return [p for ch, p in r.published if ch == "ws:channel:agents:all" and p.get("type") == "hub_event"]


def test_a_refused_probe_raises_the_alarm_once_and_health_says_failing(monkeypatch, caplog):
    seen = _hub(monkeypatch, 403)
    r = _Redis()
    with caplog.at_level(logging.ERROR, logger="neema.hub"):
        findings = asyncio.run(selfcheck._probe_hub_orders(None, r))
    # read-only, on the order route group, for Neema's own outlet, with her token
    req = seen[0]
    assert req.method == "GET" and req.url.path == "/api/v1/admin/pos/pending-order/open"
    assert req.url.params["outlet_id"] == "2" and req.headers["authorization"] == f"Bearer {TOKEN}"
    assert findings and "HUB ORDERS FAILING" in findings[0] and "403" in findings[0]
    assert any("HUB ORDER PATH FAILING" in rec.getMessage() for rec in caplog.records
               if rec.levelno == logging.ERROR)
    assert len(_alarms(r)) == 1
    # the next hourly probe while still broken: no second ring within the hour
    asyncio.run(selfcheck._probe_hub_orders(None, r))
    assert len(_alarms(r)) == 1
    out = _health(r)
    assert out["hub_orders"]["status"] == "failing"
    assert out["hub_orders"]["http_status"] == 403 and out["hub_orders"]["kind"] == "forbidden"
    # nothing secret leaves the box
    blob = json.dumps(out) + json.dumps(r.published)
    assert TOKEN not in blob and settings.hub_api_url not in blob


def test_an_answering_hub_is_ok(monkeypatch):
    _hub(monkeypatch, 200)
    r = _Redis()
    assert asyncio.run(selfcheck._probe_hub_orders(None, r)) == []
    assert _alarms(r) == []
    assert _health(r)["hub_orders"]["status"] == "ok"


def test_unknown_until_checked_and_a_missing_token_is_a_finding(monkeypatch):
    assert _health(_Redis())["hub_orders"] == {"status": "unknown"}
    monkeypatch.setattr(settings, "hub_api_token", "", raising=False)
    r = _Redis()
    findings = asyncio.run(selfcheck._probe_hub_orders(None, r))
    assert findings and "HUB_API_TOKEN is not set" in findings[0]
    assert _health(r)["hub_orders"]["kind"] == "unconfigured"


def test_the_probe_is_registered_in_the_self_check():
    assert "hub_orders" in [n for n, _ in selfcheck.PROBES]
