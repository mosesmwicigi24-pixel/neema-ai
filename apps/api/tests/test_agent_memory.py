"""Tests for cross-conversation agent memory (facts + past-order summary).

Covers the pure dedup/cap logic directly, `get_memory`/`add_fact` against a
lightweight fake db+user (mirroring the fake style in test_agent_flow.py, since
this repo has no DB-fixture tests), and the `remember` tool's dispatch wiring.
Requires Python 3.11 (SQLAlchemy models).
"""
import asyncio
import types

import app.main  # noqa: F401  — registers all SQLAlchemy models (User() needs the full mapper)
import app.agent.memory as memory
from app.agent.tools import run_tool, ToolContext
from app.models.user import User


# ── Pure dedup/cap logic ──────────────────────────────────────────────────────

def test_merge_dedupes_case_insensitively():
    facts = ["prefers black cassocks"]
    merged = memory._merge(facts, "Prefers Black Cassocks")
    assert merged == facts  # no duplicate added


def test_merge_appends_new_fact():
    facts = ["prefers black cassocks"]
    merged = memory._merge(facts, "church: Deliverance Nairobi")
    assert merged == ["prefers black cassocks", "church: Deliverance Nairobi"]


def test_merge_caps_at_max_and_drops_oldest():
    facts = [f"fact {i}" for i in range(memory._MAX_FACTS)]
    merged = memory._merge(facts, "brand new fact")
    assert len(merged) == memory._MAX_FACTS
    assert "fact 0" not in merged          # oldest dropped
    assert merged[-1] == "brand new fact"  # newest kept


def test_merge_ignores_blank_fact():
    facts = ["prefers black cassocks"]
    assert memory._merge(facts, "   ") == facts


def test_read_memory_defensive_on_bad_shape():
    assert memory.read_memory(None) == []
    assert memory.read_memory({"agent_memory": "not-a-list"}) == []
    assert memory.read_memory({"agent_memory": ["a", "b"]}) == ["a", "b"]


# ── get_memory / add_fact against a fake db+user ─────────────────────────────

class _Res:
    def __init__(self, one=None):
        self._one = one

    def scalar_one_or_none(self):
        return self._one


class _FakeDB:
    """Returns queued results for each execute() in call order; records commits."""
    def __init__(self, results):
        self._results, self._i = list(results), 0
        self.commits = 0

    async def execute(self, *a, **k):
        r = self._results[self._i]
        self._i += 1
        return r

    async def commit(self):
        self.commits += 1


def test_get_memory_returns_stored_facts():
    user = types.SimpleNamespace(state={"agent_memory": ["prefers black cassocks"]})
    db = _FakeDB([_Res(one=user)])

    facts = asyncio.run(memory.get_memory(db, "254700000001"))
    assert facts == ["prefers black cassocks"]


def test_get_memory_no_user_returns_empty():
    db = _FakeDB([_Res(one=None)])
    facts = asyncio.run(memory.get_memory(db, "254700000001"))
    assert facts == []


def test_add_fact_persists_and_dedupes():
    # Real (transient) User instance — add_fact calls flag_modified, which needs
    # a mapped instance, not a bare namespace.
    user = User(state={"agent_memory": ["prefers black cassocks"]})
    db = _FakeDB([_Res(one=user)])

    facts = asyncio.run(memory.add_fact(db, "254700000001", "church: Deliverance Nairobi"))
    assert facts == ["prefers black cassocks", "church: Deliverance Nairobi"]
    assert user.state["agent_memory"] == facts
    assert db.commits == 1

    # Adding the same fact again (different case) is a no-op.
    db2 = _FakeDB([_Res(one=user)])
    facts2 = asyncio.run(memory.add_fact(db2, "254700000001", "PREFERS BLACK CASSOCKS"))
    assert facts2 == facts
    assert db2.commits == 1  # still commits, but content unchanged


def test_add_fact_no_user_is_noop():
    db = _FakeDB([_Res(one=None)])
    facts = asyncio.run(memory.add_fact(db, "254700000001", "prefers black cassocks"))
    assert facts == []
    assert db.commits == 0


# ── build_memory_context ──────────────────────────────────────────────────────

def test_build_memory_context_none_when_empty():
    user = types.SimpleNamespace(state={})
    db = _FakeDB([])  # orders lookup fails (no queued result) and is swallowed

    ctx = asyncio.run(memory.build_memory_context(db, None, "254700000001", user=user))
    assert ctx is None


def test_build_memory_context_includes_facts():
    user = types.SimpleNamespace(state={"agent_memory": ["prefers black cassocks"]})
    db = _FakeDB([])  # orders lookup fails and is swallowed -> facts-only context

    ctx = asyncio.run(memory.build_memory_context(db, None, "254700000001", user=user))
    assert ctx is not None
    assert "prefers black cassocks" in ctx
    assert "Known facts" in ctx


# ── remember tool wiring ──────────────────────────────────────────────────────

def test_remember_tool_dispatches_to_add_fact(monkeypatch):
    calls = []

    async def fake_add_fact(db, wa_id, fact):
        calls.append((wa_id, fact))
        return ["prefers black cassocks", fact]

    monkeypatch.setattr("app.agent.tools.memorymod.add_fact", fake_add_fact)

    ctx = ToolContext(db=None, redis=None, wa_id="254700000001")
    out = asyncio.run(run_tool("remember", {"fact": "church: Deliverance Nairobi"}, ctx))

    assert calls == [("254700000001", "church: Deliverance Nairobi")]
    assert out == {"ok": True, "memory": ["prefers black cassocks", "church: Deliverance Nairobi"]}


def test_remember_tool_requires_fact():
    ctx = ToolContext(db=None, redis=None, wa_id="254700000001")
    out = asyncio.run(run_tool("remember", {}, ctx))
    assert out == {"error": "fact is required"}
