"""Non-buying drift pause: the agent's pause_conversation tool sets a redis
cooldown, and BOTH reply schedulers skip the contact while it lives — drift
costs zero tokens for two hours.
"""
import asyncio
from types import SimpleNamespace

from app.agent import runtime
from app.agent.tools import run_tool, ToolContext


class _FakeRedis:
    def __init__(self):
        self.store = {}
    async def set(self, k, v, ex=None, nx=False):
        if nx and k in self.store:
            return False
        self.store[k] = v
        return True
    async def get(self, k):
        return self.store.get(k)


def test_pause_tool_sets_cooldown_and_schedulers_skip(monkeypatch):
    r = _FakeRedis()
    ctx = ToolContext(db=None, redis=r, wa_id="254700000001", channel="whatsapp")
    out = asyncio.run(run_tool("pause_conversation", {}, ctx))
    assert out == {"ok": True, "paused_hours": 2}
    assert "agent:pause:whatsapp:254700000001" in r.store

    fired = []

    async def fake_run(*a, **k):
        fired.append(a)

    monkeypatch.setattr(runtime, "_run_and_send", fake_run, raising=False)
    ok = asyncio.run(runtime.schedule_reply(r, "254700000001", "hello", "mid1"))
    assert ok is False and fired == []          # paused → no agent run scheduled

    # A different contact is unaffected.
    ok2 = asyncio.run(runtime.schedule_reply(r, "254700000002", "hello", "mid2"))
    assert ok2 is True


def test_meta_scheduler_respects_pause(monkeypatch):
    r = _FakeRedis()
    asyncio.run(run_tool("pause_conversation", {},
                         ToolContext(db=None, redis=r, wa_id="PSID_1", channel="messenger")))
    fired = []

    async def fake_run(*a, **k):
        fired.append(a)

    monkeypatch.setattr(runtime, "_run_and_send_meta", fake_run, raising=False)
    ok = asyncio.run(runtime.schedule_meta_reply(r, "messenger", "PSID_1", "hi", "m1"))
    assert ok is False and fired == []


def test_no_redis_never_blocks():
    ctx = ToolContext(db=None, redis=None, wa_id="254700", channel="whatsapp")
    assert asyncio.run(run_tool("pause_conversation", {}, ctx)) == {"ok": False}
    assert asyncio.run(runtime._is_paused(None, "whatsapp", "254700")) is False
