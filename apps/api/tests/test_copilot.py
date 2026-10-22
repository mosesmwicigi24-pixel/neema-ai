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
        async def complete(self, *, system, messages, tools, **kw):
            seen["tools"] = [t["name"] for t in tools]
            seen["system"] = system
            seen["messages"] = list(messages)
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
    # The scribe is SHOWN the copilot's one shared list (the draft's look-only
    # tools + these) so the two passes read one cache entry; it may RUN only
    # the record-keeping ones (tools.run_tool, ctx.allowed_tools).
    assert set(seen["tools"]) <= _SCRIBE_TOOL_NAMES | runtime._READONLY_TOOL_NAMES
    assert _SCRIBE_TOOL_NAMES & set(seen["tools"])
    # The scribe instruction rides on the message — the rules block (cached
    # fleet-wide) never changes for it.
    sys_text = seen["system"] if isinstance(seen["system"], str) else "\n".join(seen["system"])
    assert "SCRIBE MODE" not in sys_text
    last = seen["messages"][-1]["content"]
    assert any("SCRIBE MODE" in (b.get("text") or "") for b in last if isinstance(b, dict))


def test_the_draft_and_the_scribe_share_one_cached_prefix(monkeypatch):
    """Tools render first, then the system blocks, then the conversation: the
    draft and the scribe pass for the same customer message must match on all
    of it up to the customer's own words, or each writes the whole thread."""
    import app.agent.runtime as runtime
    from app.agent.llm import _cache_last_message, _cached_system
    calls = []

    class _RecLLM:
        async def complete(self, *, system, messages, tools, **kw):
            calls.append((_cached_system(system), _cache_last_message(messages), tools))
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
            self._i += 1
            return self._r[self._i - 1]

    user = types.SimpleNamespace(name="Moses")
    for mode in ({"read_only": True}, {"scribe_only": True}):
        db = _FakeDB([_Res(one=user), _Res(one=None), _Res(one=None), _Res(one=None), _Res(many=[])])
        asyncio.run(runtime.run_turn(db, None, "254700000001", "chest 42, St Mary's",
                                     _RecLLM(), **mode))
    (s1, m1, t1), (s2, m2, t2) = calls[0], calls[-1]
    assert t1 == t2 and s1 == s2
    words1 = m1[-1]["content"][0]
    words2 = m2[-1]["content"][0]
    assert words1 == words2 and words1.get("cache_control")   # cached up to their words
    assert m1[:-1] == m2[:-1]


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
