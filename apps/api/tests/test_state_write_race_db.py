"""users.state and persons.state are one JSONB document with many owners —
crm_notes, call_note_ids, agent_memory. A writer that reads the document, edits
a copy and writes the whole thing back loses whatever landed in between. Our
sessions run expire_on_commit=False, so a later SELECT of a row the session
already holds does NOT refresh it: "reads" can mean the copy from a while ago,
and with_for_update alone would lock the row and still write that old copy.

Every test forces its interleaving with a hook, on a real Postgres, instead of
hoping for it: the sweep's asyncio.gather lost a call id on main only when the
timing lined up (run 41017833238, tests/test_transcript_recovery_db.py).
"""
import asyncio
import uuid

import pytest
import sqlalchemy as sa

from tests import test_voice_notes_db as vn
from tests.test_security_db import fresh_db  # noqa: F401 — the throwaway-database fixture

pytestmark = vn.pytestmark
rig = vn.rig
run = vn.run

WA = "254744000009"
PSID = "25583188000000009"
BOTH = pytest.mark.parametrize("handle, channel", [(WA, "whatsapp"), (PSID, "messenger")])


def _customer(rig):
    """A customer reachable on both shapes: a WhatsApp User, and a Messenger
    contact whose facts live on their Person and notes on a shim User."""
    from app.models.person import Identity, Person
    from app.models.user import User
    pid = uuid.uuid4()

    async def go():
        async with rig.maker() as db:
            db.add(Person(id=pid, state={}))
            await db.flush()
            db.add(Identity(person_id=pid, channel="messenger", external_id=PSID))
            db.add(User(wa_id=PSID, person_id=pid))
            db.add(User(wa_id=WA, phone=WA))
            await db.commit()
    run(go())
    return pid


def _user_state(rig, handle):
    from app.models.user import User

    async def go():
        async with rig.maker() as db:
            return (await db.execute(sa.select(User.state).where(User.wa_id == handle))).scalar_one()
    return run(go()) or {}


def _person_state(rig, pid):
    from app.models.person import Person

    async def go():
        async with rig.maker() as db:
            return (await db.execute(sa.select(Person.state).where(Person.id == pid))).scalar_one()
    return run(go()) or {}


def _facts(rig, handle, channel, pid):
    state = _user_state(rig, handle) if channel == "whatsapp" else _person_state(rig, pid)
    return state.get("agent_memory") or []


async def _note(rig, summary, call_id, handle=WA, channel="whatsapp"):
    """One finished call, on its own session — how _finish saves each brief."""
    from app.services import call_transcribe as ct
    async with rig.maker() as db:
        await ct._save_call_note(db, handle, summary, channel=channel, call_id=call_id)


async def _fact(rig, handle, channel, fact):
    from app.agent import memory
    async with rig.maker() as db:
        await memory.add_fact(db, handle, fact, channel=channel)


async def _blocked_or_finished(rig, task) -> bool:
    """True once `task` is parked on a row lock, False if it simply finished —
    no sleeping-and-hoping: Postgres says which."""
    async with rig.maker() as db:
        for _ in range(1000):
            if task.done():
                return False
            waiting = (await db.execute(sa.text(
                "SELECT count(*) FROM pg_stat_activity "
                "WHERE datname = current_database() AND wait_event_type = 'Lock'"))).scalar_one()
            await db.rollback()     # pg_stat_activity is a per-transaction snapshot
            if waiting:
                return True
            await asyncio.sleep(0.01)
    raise AssertionError("the other writer neither finished nor blocked")


def _before_next_commit(db, hook):
    """Run `hook` inside `db`'s next commit: past the read, before the write."""
    real = db.commit

    async def commit():
        db.commit = real
        await hook()
        await real()
    db.commit = commit


# ═════════════════════════════════════════════════════════════════════════════
# The reported race: _save_call_note commits, then add_fact rewrites the state
# ═════════════════════════════════════════════════════════════════════════════

def test_a_second_call_noted_before_our_memory_write_survives_it(rig, monkeypatch):
    """The exact shape of the flake: call A commits its note and lets go of the
    row, call B — already waiting on that lock — notes in full, then A's
    add_fact writes back the document A's session is still holding."""
    from app.agent import memory
    _customer(rig)
    real, fired = memory.add_fact, []

    async def after_a_commits(db, wa_id, fact, channel="whatsapp"):
        if not fired:
            fired.append(True)
            await _note(rig, "Second call: wants a chalice.", "wacid.b")
        return await real(db, wa_id, fact, channel=channel)
    monkeypatch.setattr(memory, "add_fact", after_a_commits)

    run(_note(rig, "First call: wants a red cope.", "wacid.a"))

    st = _user_state(rig, WA)
    assert sorted(st["call_note_ids"]) == ["wacid.a", "wacid.b"]
    assert "red cope" in st["crm_notes"] and "chalice" in st["crm_notes"]
    assert len(st["agent_memory"]) == 2


def test_a_note_arriving_mid_write_waits_for_the_fact_and_both_land(rig):
    """Past add_fact's read, before its write: the other writer must queue on
    the row, not slip in and get overwritten."""
    from app.agent import memory
    _customer(rig)

    async def go():
        seen, others = [], []

        async def second_call_arrives():
            other = asyncio.create_task(_note(rig, "Second call: wants a chalice.", "wacid.b"))
            others.append(other)
            seen.append(await _blocked_or_finished(rig, other))

        async with rig.maker() as db:
            _before_next_commit(db, second_call_arrives)
            await memory.add_fact(db, WA, "Phone call: red cope")
        await others[0]
        return seen[0]
    blocked = run(go())

    st = _user_state(rig, WA)
    assert st["call_note_ids"] == ["wacid.b"]
    assert "chalice" in st["crm_notes"]
    assert any("red cope" in f for f in st["agent_memory"])
    assert any("chalice" in f for f in st["agent_memory"])
    assert blocked is True


def test_many_calls_finishing_together_all_land(rig):
    """The sweep's own shape, unforced: asyncio.gather over one customer."""
    _customer(rig)

    async def go():
        await asyncio.gather(*[_note(rig, f"Call {i}: wants item {i}.", f"wacid.{i}") for i in range(8)])
    run(go())

    st = _user_state(rig, WA)
    assert sorted(st["call_note_ids"]) == sorted(f"wacid.{i}" for i in range(8))
    assert st["crm_notes"].count("\U0001F4DE Call (") == 8
    assert len(st["agent_memory"]) == 8


# ═════════════════════════════════════════════════════════════════════════════
# add_fact on both stores
# ═════════════════════════════════════════════════════════════════════════════

@BOTH
def test_add_fact_rereads_a_row_its_session_already_holds(rig, handle, channel):
    """An agent turn keeps one session for the whole model loop, so the row it
    loaded at the start is old by the time `remember` runs."""
    from app.agent import memory
    pid = _customer(rig)

    async def go():
        async with rig.maker() as db:
            # The turn keeps `user` alive: the identity map is weak, so only a
            # row something still references comes back stale.
            held = await memory._load_store(db, handle, channel)
            await _fact(rig, handle, channel, "landed during the turn")
            await memory.add_fact(db, handle, "remembered by the turn", channel=channel)
            assert "landed during the turn" in held.state["agent_memory"]
    run(go())

    assert sorted(_facts(rig, handle, channel, pid)) == ["landed during the turn", "remembered by the turn"]


@BOTH
def test_two_facts_racing_on_one_store_both_land(rig, handle, channel):
    from app.agent import memory
    pid = _customer(rig)

    async def go():
        others = []

        async def other_fact_arrives():
            other = asyncio.create_task(_fact(rig, handle, channel, "second"))
            others.append(other)
            await _blocked_or_finished(rig, other)

        async with rig.maker() as db:
            _before_next_commit(db, other_fact_arrives)
            await memory.add_fact(db, handle, "first", channel=channel)
        await others[0]
    run(go())

    assert sorted(_facts(rig, handle, channel, pid)) == ["first", "second"]


@BOTH
def test_rereading_keeps_a_callers_unflushed_edits(rig, handle, channel):
    """populate_existing overwrites the object from the row, so a caller's
    pending edits must reach the row first (the session's autoflush) — a tool
    that set a field and then called add_fact must not lose it."""
    from app.agent import memory
    from app.models.person import Person
    from app.models.user import User
    pid = _customer(rig)

    async def go():
        async with rig.maker() as db:
            if channel == "whatsapp":
                store = (await db.execute(sa.select(User).where(User.wa_id == handle))).scalar_one()
                store.name = "Pending Name"
            else:
                store = await db.get(Person, pid)
                store.display_name = "Pending Name"
            store.state = {**(store.state or {}), "profile": {"role": "pending"}}
            await memory.add_fact(db, handle, "a fact", channel=channel)

        async with rig.maker() as db:
            name = (await db.execute(sa.select(User.name).where(User.wa_id == handle))).scalar_one() \
                if channel == "whatsapp" else \
                (await db.execute(sa.select(Person.display_name).where(Person.id == pid))).scalar_one()
        return name
    assert run(go()) == "Pending Name"

    state = _user_state(rig, handle) if channel == "whatsapp" else _person_state(rig, pid)
    assert state["profile"] == {"role": "pending"} and state["agent_memory"] == ["a fact"]


# ═════════════════════════════════════════════════════════════════════════════
# _save_call_note's own Messenger path
# ═════════════════════════════════════════════════════════════════════════════

def test_a_messenger_note_rereads_the_row_it_resolved_before_locking(rig, monkeypatch):
    """The Messenger branch resolves the customer (loading the row), THEN locks
    it: without a re-read the lock protects a copy taken before the wait."""
    import app.routers.crm as crm
    _customer(rig)
    real, fired = crm._resolve_customer_user, []

    async def resolved_then_beaten(db, ident, channel=None, *, create=False):
        found = await real(db, ident, channel, create=create)
        if not fired:
            fired.append(True)
            await _note(rig, "Second call: wants a chalice.", "wacid.b", handle=PSID, channel="messenger")
        return found
    monkeypatch.setattr(crm, "_resolve_customer_user", resolved_then_beaten)

    run(_note(rig, "First call: wants a red cope.", "wacid.a", handle=PSID, channel="messenger"))

    st = _user_state(rig, PSID)
    assert sorted(st["call_note_ids"]) == ["wacid.a", "wacid.b"]
    assert "red cope" in st["crm_notes"] and "chalice" in st["crm_notes"]
