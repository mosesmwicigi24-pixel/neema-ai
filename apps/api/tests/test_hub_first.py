"""THE HUB IS THE ONE SOURCE OF TRUTH (owner, 2026-11-16) — Stage A.
What the AI knows of a customer's past orders comes from the hub's record
(shop, website and chat), not from Neema's own mirror of chat orders."""
import asyncio
import inspect
import json

import app.main  # noqa: F401
from app.agent import memory
from app.core import hub_client
from app.core.config import settings

ORDERS = [
    {"order_number": "BH-1001", "created_at": "2026-09-02T10:00:00Z", "total": 13000.0,
     "currency_code": "KES", "status": "completed",
     "items": [{"name": "Cassock", "qty": 1}, {"name": "Clergy Stole", "qty": 2}]},
    {"order_number": "BH-1040", "created_at": "2026-11-01T09:30:00Z", "total": 22000.0,
     "currency_code": "KES", "status": "processing", "items": [{"name": "Golden Communion Tray", "qty": 1}]},
    {"order_number": "BH-0990", "created_at": "2026-08-01T09:30:00Z", "total": 500.0,
     "currency_code": "KES", "status": "cancelled", "items": []},
]


def test_hub_orders_read_newest_first_without_the_cancelled():
    lines = memory._hub_order_lines(ORDERS)
    assert lines[0].startswith("BH-1040 (01 Nov 2026) — KES 22000.0 — Golden Communion Tray")
    assert lines[1] == "BH-1001 (02 Sep 2026) — KES 13000.0 — Cassock; Clergy Stole ×2"
    assert len(lines) == 2 and memory._hub_order_lines([]) == [] and memory._hub_order_lines(None) == []


class _R:
    def __init__(self):
        self.kv = {}

    async def get(self, k):
        return self.kv.get(k)

    async def set(self, k, v, ex=None):
        self.kv[k] = v


def test_the_ai_asks_the_hub_once_then_reuses_the_answer(monkeypatch):
    calls = []

    async def summary(wa_id, redis=None, **kw):
        calls.append(wa_id)
        return {"orders": ORDERS}
    monkeypatch.setattr(settings, "hub_api_token", "t", raising=False)
    monkeypatch.setattr(hub_client, "fetch_customer_summary", summary)
    r = _R()
    first = asyncio.run(memory._hub_orders_summary(r, "254700111222"))
    again = asyncio.run(memory._hub_orders_summary(r, "254700111222"))
    assert first == again and len(first) == 2 and calls == ["254700111222"]
    assert json.loads(r.kv["hub:customer_orders_lines:254700111222"]) == first


def test_when_the_hub_cannot_say_the_local_mirror_is_used(monkeypatch):
    async def down(wa_id, redis=None, **kw):
        raise RuntimeError("hub down")

    async def unknown(wa_id, redis=None, **kw):
        return None
    monkeypatch.setattr(settings, "hub_api_token", "t", raising=False)
    monkeypatch.setattr(hub_client, "fetch_customer_summary", down)
    assert asyncio.run(memory._hub_orders_summary(_R(), "254700111222")) is None
    monkeypatch.setattr(hub_client, "fetch_customer_summary", unknown)
    assert asyncio.run(memory._hub_orders_summary(_R(), "254700111222")) is None
    # no token, or a handle that is not a phone: the hub is not asked
    monkeypatch.setattr(settings, "hub_api_token", "", raising=False)
    assert asyncio.run(memory._hub_orders_summary(_R(), "254700111222")) is None
    src = inspect.getsource(memory.build_memory_context)
    assert "_hub_orders_summary(redis, wa_id)" in src and "_recent_orders_summary(" in src
    assert memory.HUB_ORDERS_WAIT <= 3.0
