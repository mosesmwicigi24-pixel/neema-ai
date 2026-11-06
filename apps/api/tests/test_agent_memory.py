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

    async def fake_add_fact(db, wa_id, fact, channel="whatsapp"):
        calls.append((wa_id, fact))
        assert channel == "whatsapp"      # default ToolContext channel
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


def test_a_messenger_turn_reads_the_linked_whatsapp_users_facts(monkeypatch):
    """W7-5 (investigation): facts live on the User for WhatsApp and on the
    Person for Meta. The WhatsApp side already read the person's; the Meta
    side never read the linked user's. Now both directions continue."""
    import uuid
    from app.models.person import Person

    person = Person(id=uuid.uuid4(), state={"agent_memory": ["parish: St Peter's, Nakuru"]})

    async def fake_store(db, key, channel="whatsapp", *, lock=False):
        return person
    monkeypatch.setattr(memory, "_load_store", fake_store)
    wa_user = types.SimpleNamespace(state={"agent_memory": ["prefers black cassocks", "Parish: St Peter's, Nakuru"]})

    class _RowDB:
        """Answers the User lookup from the statement itself (verification
        pass 2b): only a query on users.person_id = <this person> finds the row."""
        def __init__(self, raise_on_execute=False):
            self.sql, self.raise_on_execute = [], raise_on_execute
        async def execute(self, stmt):
            if self.raise_on_execute:
                raise RuntimeError("db down")
            from sqlalchemy.dialects import postgresql
            sql = str(stmt.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
            self.sql.append(sql)
            hit = f"users.person_id = '{person.id}'" in sql and "FROM users" in sql
            return types.SimpleNamespace(scalar_one_or_none=lambda: wa_user if hit else None)

    db = _RowDB()
    ctx = asyncio.run(memory.build_memory_context(db, None, "PSID_1", channel="messenger"))
    assert ctx is not None
    assert "prefers black cassocks" in ctx and ctx.lower().count("st peter's") == 1   # case-insensitive union
    assert "ORDER BY users.updated_at DESC" in db.sql[0]                                 # the newest linked row wins
    # a DB error on the lookup leaves the person's own facts, no exception
    ctx2 = asyncio.run(memory.build_memory_context(_RowDB(raise_on_execute=True), None, "PSID_1", channel="messenger"))
    assert "St Peter's" in ctx2 and "black cassocks" not in ctx2


def test_a_fact_carries_the_day_it_was_noted_and_a_restatement_refreshes_it(monkeypatch):
    """W5-3: sizes and parishes age. add_fact stamps the day; the context shows
    it; saying the same fact again refreshes the day; a fact that falls off
    the cap takes its day with it."""
    from datetime import datetime, timezone
    user = types.SimpleNamespace(state={"agent_memory": ["prefers black cassocks"]})

    class _DB:
        async def commit(self): pass

    async def fake_store(db, key, channel="whatsapp", *, lock=False):
        return user
    monkeypatch.setattr(memory, "_load_store", fake_store)
    monkeypatch.setattr(memory, "flag_modified", lambda *a, **k: None)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    asyncio.run(memory.add_fact(_DB(), "254700000001", "cassock size 42"))
    assert user.state["agent_memory_at"] == {"cassock size 42": today}
    assert "prefers black cassocks" not in user.state["agent_memory_at"]      # older row: no date, no crash
    user.state["agent_memory_at"]["cassock size 42"] = "2025-01-15"
    asyncio.run(memory.add_fact(_DB(), "254700000001", "Cassock Size 42"))    # restated → refreshed, not duplicated
    assert user.state["agent_memory"].count("cassock size 42") == 1
    assert user.state["agent_memory_at"]["cassock size 42"] == today

    ctx = asyncio.run(memory.build_memory_context(_FakeDB([]), None, "254700000001", user=user))
    assert f"- cassock size 42 (noted {today})" in ctx
    assert "- prefers black cassocks\n" in ctx or ctx.endswith("- prefers black cassocks")   # dateless row: no "(noted"
    assert "prefers black cassocks (noted" not in ctx
    assert "confirm an old one" in ctx
    # the renderer finds a date whatever the case of the stored fact (pass 3)
    user.state["agent_memory"][-1] = "Cassock Size 42"
    ctx_mixed = asyncio.run(memory.build_memory_context(_FakeDB([]), None, "254700000001", user=user))
    assert f"- Cassock Size 42 (noted {today})" in ctx_mixed
    # two homes with a date for the same fact: the user's own date wins over the person's
    person = types.SimpleNamespace(state={"agent_memory": ["cassock size 42"], "agent_memory_at": {"cassock size 42": "2020-01-01"}})
    linked = types.SimpleNamespace(state=user.state, person_id="p1")
    class _PDB(_FakeDB):
        async def get(self, model, pk): return person
    ctx_two = asyncio.run(memory.build_memory_context(_PDB([]), None, "254700000001", user=linked))
    assert f"(noted {today})" in ctx_two and "(noted 2020-01-01)" not in ctx_two

    for i in range(memory._MAX_FACTS + 2):                                     # over the cap: the oldest and its day go
        asyncio.run(memory.add_fact(_DB(), "254700000001", f"fact {i}"))
    assert "cassock size 42" not in user.state["agent_memory"]
    assert "cassock size 42" not in user.state["agent_memory_at"]
    assert set(user.state["agent_memory_at"]) <= {f.lower() for f in user.state["agent_memory"]}
