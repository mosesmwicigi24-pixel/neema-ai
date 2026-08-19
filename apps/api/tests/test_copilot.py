"""Phase C — copilot mode: both workers keep working in human-held threads."""
import asyncio
import json
import types

import pytest

from app.core.config import settings
from app.services import copilot as cp


def test_flag_off_schedules_nothing(monkeypatch):
    monkeypatch.setattr(settings, "copilot_mode", False, raising=False)
    spawned = []
    monkeypatch.setattr(cp, "_spawn", lambda c: (spawned.append(c), c.close()))
    cp.schedule_human_held(None, "254700000001", "whatsapp", "hello")
    cp.schedule_briefing(None, "conv1")
    assert spawned == []


def test_flag_on_schedules_draft_and_scribe(monkeypatch):
    monkeypatch.setattr(settings, "copilot_mode", True, raising=False)
    spawned = []
    monkeypatch.setattr(cp, "_spawn", lambda c: (spawned.append(c), c.close()))
    cp.schedule_human_held(None, "254700000001", "whatsapp", "my chest is 42")
    assert len(spawned) == 1
    # empty text never schedules (stickers/receipts don't deserve a turn)
    cp.schedule_human_held(None, "254700000001", "whatsapp", "   ")
    assert len(spawned) == 1


def test_scribe_mode_locks_tools_to_crm_writers():
    """Scribe turns can save facts but never sell, order, or send."""
    from app.agent.runtime import _SCRIBE_TOOL_NAMES
    for banned in ("create_order", "update_cart", "send_product_cards",
                   "whatsapp_checkout_link", "share_catalog", "handoff_to_human",
                   "pause_conversation", "search_catalog"):
        assert banned not in _SCRIBE_TOOL_NAMES
    for allowed in ("capture_customer", "save_measurements", "save_parish", "remember"):
        assert allowed in _SCRIBE_TOOL_NAMES


def test_run_turn_scribe_only_offers_scribe_tools(monkeypatch):
    import app.agent.runtime as runtime
    from app.agent.runtime import _SCRIBE_TOOL_NAMES
    seen = {}

    class _RecLLM:
        async def complete(self, *, system, messages, tools):
            seen["tools"] = [t["name"] for t in tools]
            seen["system"] = system
            return types.SimpleNamespace(text="noted", tool_calls=[],
                                         assistant_content=[], usage={})

    class _Res:
        def __init__(self, one=None, many=None):
            self._one, self._many = one, many or []
        def scalar_one_or_none(self): return self._one
        def scalars(self): return types.SimpleNamespace(all=lambda: self._many)

    class _FakeDB:
        def __init__(self, results): self._r, self._i = list(results), 0
        async def execute(self, *a, **k):
            r = self._r[self._i]; self._i += 1; return r

    user = types.SimpleNamespace(name="Moses")
    db = _FakeDB([_Res(one=user), _Res(one=None), _Res(one=None), _Res(one=None), _Res(many=[])])
    out = asyncio.run(runtime.run_turn(db, None, "254700000001",
                                       "I'm Bishop Moses from St Mary's, chest 42",
                                       _RecLLM(), scribe_only=True))
    assert out == "noted"
    assert set(seen["tools"]) <= _SCRIBE_TOOL_NAMES
    # system arrives as [shared rules block, per-customer block] since the
    # prompt-cache split; the scribe marker rides on the rules block.
    sys_text = seen["system"] if isinstance(seen["system"], str) else "\n".join(seen["system"])
    assert "SCRIBE MODE" in sys_text


def test_take_back_scan_pings_once_per_day(monkeypatch):
    monkeypatch.setattr(settings, "copilot_mode", True, raising=False)
    from datetime import datetime, timedelta, timezone
    conv = types.SimpleNamespace(id="c1", wa_id="254700000001", external_id=None,
                                 contact_name="Bishop Elias")

    class _Rows:
        def scalars(self): return types.SimpleNamespace(all=lambda: [conv])

    class _DB:
        async def execute(self, *a, **k): return _Rows()

    class _Redis:
        def __init__(self): self.store, self.published = {}, []
        async def set(self, k, v, nx=False, ex=None):
            if nx and k in self.store: return False
            self.store[k] = v; return True
        async def publish(self, ch, msg): self.published.append(json.loads(msg))

    r = _Redis()
    n = asyncio.run(cp.take_back_scan(_DB(), r))
    assert n == 1
    assert r.published[0]["type"] == "take_back"
    # second scan same day → guarded silent
    assert asyncio.run(cp.take_back_scan(_DB(), r)) == 0


def test_ask_route_registered():
    from app.routers.admin import router
    paths = {r.path for r in router.routes}
    assert "/conversations/{conv_id}/ask" in paths
