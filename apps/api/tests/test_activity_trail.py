"""The Activity Log's per-turn trail (owner, 2026-08-19): "ensure the activity
log captures every activity in the interaction of a customer in every turn."

Before this, each tool call — the search, the cards, the cart change, the
order, the captured measurements — existed only as an `agent tool …` server
log line no one could reach from the dashboard. The Activity Log narrated the
system's milestones around the agent, never the agent's own steps.

These tests pin the trail: every tool call becomes a readable row (with a
fallback line so nothing is ever unrecorded), failures are marked, payload
echoes stay bounded and storable, read-only turns never write, and the trail
can never cost a reply.
"""
import asyncio
import types

import app.main  # noqa: F401 — registers models
import app.agent.runtime as runtime
from app.services import activity_trail as trail


class _Res:
    def __init__(self, one=None, many=None):
        self._one, self._many = one, many or []

    def scalar_one_or_none(self):
        return self._one

    def scalars(self):
        return types.SimpleNamespace(all=lambda: self._many,
                                     first=lambda: (self._many[0] if self._many else self._one))


class _FakeDB:
    """Queued results; once exhausted, every further query answers EMPTY —
    matching what the many best-effort context queries expect on a bare
    thread (orders, calls, memory), so run_turn's shape stays realistic."""

    def __init__(self, results):
        self._results, self._i = list(results), 0
        self.added, self.commits = [], 0

    async def execute(self, *a, **k):
        r = (self._results[self._i] if self._i < len(self._results)
             else _Res(one=None, many=[]))
        self._i += 1
        return r

    def add(self, row):
        self.added.append(row)

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        pass


# ── describe(): the plain-English lines ──────────────────────────────────────

def test_the_shopkeeper_diary_lines():
    label, d = trail.describe("search_catalog", {"query": "communion tray"},
                              {"count": 3, "results": [1, 2, 3]})
    assert label == "Searched the catalogue" and "communion tray" in d and "3" in d

    label, d = trail.describe("send_product_cards",
                              {"products": ["Aluminium 4 Stacked Communion Set"]},
                              {"sent_cards": 1, "album_photos": 3})
    assert label == "Showed product card(s)"
    assert "Aluminium 4 Stacked Communion Set" in d and "+3 gallery photos" in d

    label, d = trail.describe("update_cart",
                              {"action": "add", "product": "Cassock", "quantity": 3},
                              {"ok": True, "total": 36000, "currency": "KES"})
    assert label == "Updated the cart" and "add Cassock ×3" in d and "36,000" in d

    label, d = trail.describe("create_order", {},
                              {"order_number": "ORD-1", "total": 36000, "currency": "KES"})
    assert label == "Created an order" and "ORD-1" in d and "36,000" in d

    label, d = trail.describe("save_measurements",
                              {"measurements": {"chest": "42in", "length": "58in"}}, {})
    assert label == "Saved measurements" and "chest 42in" in d

    label, d = trail.describe("schedule_check_in",
                              {"days_from_now": 14, "reason": "divai runs out"}, {})
    assert label == "Booked a check-in" and "14" in d and "divai" in d


def test_nothing_the_agent_does_goes_unrecorded():
    """An unknown tool still earns a row — the fallback keeps the promise."""
    label, d = trail.describe("some_future_tool", {"x": 1}, {"ok": True})
    assert label == "Agent step: some_future_tool"
    assert d and "1" in d
    # and a describe() crash inside a handler still falls through, not raises
    label, _ = trail.describe("update_cart", None, None)
    assert label


# ── record(): one bounded, honest row per call ───────────────────────────────

def _conv():
    return types.SimpleNamespace(id="conv-1", person_id="person-1")


def test_record_writes_a_row_bound_to_the_conversation():
    db = _FakeDB([_Res(many=[_conv()])])
    asyncio.run(trail.record(db, channel="whatsapp", contact="254700000001",
                             tool="search_catalog", args={"query": "tray"},
                             out={"count": 2}))
    assert db.commits == 1 and len(db.added) == 1
    row = db.added[0]
    assert row.conversation_id == "conv-1" and row.person_id == "person-1"
    assert row.tool == "search_catalog"
    assert row.summary == "Searched the catalogue"
    assert row.payload == {"args": {"query": '"tray"'}}


def test_record_marks_failures_and_bounds_huge_args():
    db = _FakeDB([_Res(many=[_conv()])])
    asyncio.run(trail.record(db, channel="whatsapp", contact="254700000001",
                             tool="create_order", args={"note": "x" * 5000},
                             out={"error": "hub rejected the push"}))
    row = db.added[0]
    assert "failed: " in (row.detail or "") and "hub rejected" in row.detail
    assert len(row.payload["args"]["note"]) <= 150


def test_record_survives_a_missing_conversation_and_a_broken_db():
    db = _FakeDB([_Res(many=[])])              # no conversation resolved
    asyncio.run(trail.record(db, channel="web", contact="web_abc",
                             tool="search_catalog", args={}, out={}))
    assert db.added and db.added[0].conversation_id is None

    class _Boom:
        def __getattr__(self, name):
            async def _b(*a, **kw):
                raise RuntimeError("db down")
            return _b
    # must not raise into the turn
    asyncio.run(trail.record(_Boom(), channel="whatsapp", contact="k",
                             tool="search_catalog", args={}, out={}))


# ── the runtime loop writes the trail on real turns only ─────────────────────

def _turn_db():
    user = types.SimpleNamespace(name="Moses")
    # User, standing-orders, learned-rules, history; every later best-effort
    # query (memory, the trail's conversation lookup) answers empty — so the
    # trail row binds to no conversation here, which the dedicated record()
    # test covers with a real lookup.
    return _FakeDB([_Res(one=user), _Res(one=None), _Res(one=None), _Res(many=[])])


def _tool_llm():
    from app.agent.llm import FakeLLM
    return FakeLLM([
        {"tools": [{"name": "search_catalog", "input": {"query": "tray"}}]},
        {"text": "The Aluminium Tray is KES 9,000 — how many would you like?"},
    ])


def test_every_tool_call_of_a_real_turn_lands_in_the_trail(monkeypatch):
    async def fake_run_tool(name, args, ctx):
        return {"count": 1, "results": [{"name": "Aluminium Tray", "price": 9000}]}
    monkeypatch.setattr(runtime, "run_tool", fake_run_tool)
    db = _turn_db()
    asyncio.run(runtime.run_turn(db, None, "254700000001", "how much is the tray?",
                                 _tool_llm()))
    from app.models.agent_activity import AgentActivity
    rows = [r for r in db.added if isinstance(r, AgentActivity)]
    assert len(rows) == 1
    assert rows[0].summary == "Searched the catalogue"
    assert rows[0].channel == "whatsapp" and rows[0].contact == "254700000001"


def test_a_read_only_draft_leaves_no_trail(monkeypatch):
    async def fake_run_tool(name, args, ctx):
        return {"count": 0, "results": []}
    monkeypatch.setattr(runtime, "run_tool", fake_run_tool)
    db = _turn_db()
    asyncio.run(runtime.run_turn(db, None, "254700000001", "draft this",
                                 _tool_llm(), read_only=True))
    from app.models.agent_activity import AgentActivity
    assert not [r for r in db.added if isinstance(r, AgentActivity)]


def test_the_activity_ledger_serves_the_trail():
    """The Activity Log endpoint must merge the agent's own steps — and keep
    working on a box whose migration hasn't landed yet (guarded)."""
    import inspect
    from app.routers import admin
    src = inspect.getsource(admin.get_conversation_activity)
    assert "AgentActivity" in src
    assert '"kind": "tool"' in src
    assert "except Exception" in src.split("AgentActivity", 1)[1][:900]
