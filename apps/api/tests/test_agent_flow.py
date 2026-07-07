"""End-to-end Tier 2 agent loop with fakes (no DB, no network).

Drives runtime.run_turn through a full sell→confirm→order turn using FakeLLM for
the model and a stubbed tool runner, asserting the loop threads tool results back
to the model and closes on the order. Requires Python 3.11 (SQLAlchemy models).
"""
import asyncio
import types

import app.agent.runtime as runtime
from app.agent.llm import FakeLLM


class _Res:
    def __init__(self, one=None, many=None):
        self._one, self._many = one, many or []

    def scalar_one_or_none(self):
        return self._one

    def scalars(self):
        return types.SimpleNamespace(all=lambda: self._many)


class _FakeDB:
    """Returns queued results for each execute() in call order."""
    def __init__(self, results):
        self._results, self._i = list(results), 0

    async def execute(self, *a, **k):
        r = self._results[self._i]
        self._i += 1
        return r


def test_full_order_turn(monkeypatch):
    calls = []

    async def fake_run_tool(name, args, ctx):
        calls.append((name, args))
        return {
            "search_catalog": {"count": 1, "results": [{"name": "Cassock", "price_kes": 12000, "made_to_order": True}]},
            "update_cart": {"ok": True, "items": [{"name": "Cassock", "qty": 3}], "total_kes": 36000},
            "create_order": {"ok": True, "order_number": "ORD-250707-ABCD", "total": 36000,
                              "currency": "KES", "payment_url": "https://hub.example/pay/tok123",
                              "made_to_order_items": ["Cassock"]},
        }[name]

    monkeypatch.setattr(runtime, "run_tool", fake_run_tool)

    llm = FakeLLM([
        {"tools": [{"name": "search_catalog", "input": {"query": "cassock"}}]},
        {"tools": [{"name": "update_cart", "input": {"action": "add", "product": "Cassock", "quantity": 3}}]},
        {"text": "Added 3 cassocks (KES 36,000). Shall I place the order?"},
        {"tools": [{"name": "create_order", "input": {}}]},
        {"text": "Done! Order ORD-250707-ABCD, KES 36,000. Pay here: https://hub.example/pay/tok123"},
    ])

    user = types.SimpleNamespace(name="Moses")
    # run_turn queries: User (scalar), then Message history (scalars) — per turn.
    db1 = _FakeDB([_Res(one=user), _Res(many=[])])

    async def go():
        r1 = await runtime.run_turn(db1, None, "254700000001", "I want 3 white cassocks", llm)
        assert "place the order" in r1        # first turn ends by asking to confirm
        db2 = _FakeDB([_Res(one=user), _Res(many=[])])
        r2 = await runtime.run_turn(db2, None, "254700000001", "yes, confirm", llm)
        return r1, r2

    r1, r2 = asyncio.run(go())

    names = [c[0] for c in calls]
    assert names == ["search_catalog", "update_cart", "create_order"]
    assert "ORD-250707-ABCD" in r2 and "hub.example/pay/tok123" in r2
