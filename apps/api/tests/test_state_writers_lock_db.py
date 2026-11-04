"""The writers an agent turn runs: tags, lead source, lead signals, the cart,
measurements, profile and contact capture. Each rewrites the whole of
users.state or persons.state, so each must lock the row and re-read it at the
moment of writing (tests/test_state_write_race_db.py has the why) — and must
let go again, because a turn goes straight back to the model.

Two windows, forced on a real Postgres:
  held       the session loaded the row earlier, as a turn does, and someone
             else wrote since;
  mid_write  someone else arrives past the writer's read, before its commit.
"""
import asyncio
import uuid

import pytest
import sqlalchemy as sa

from tests import test_voice_notes_db as vn
from tests.test_security_db import fresh_db  # noqa: F401 — the throwaway-database fixture
from tests.test_state_write_race_db import (
    PSID, WA, _before_next_commit, _blocked_or_finished, _customer, _fact, _note, _person_state, _user_state,
)

pytestmark = vn.pytestmark
rig = vn.rig
run = vn.run

ITEM = {"name": "Red cope", "qty": 1}


def _ctx(db, key=WA, channel="whatsapp"):
    from app.agent.tools import ToolContext
    return ToolContext(db=db, redis=None, wa_id=key, channel=channel)


async def _add_tags(db, pid):
    from app.agent import tools
    await tools._add_tags({"tags": ["vip"]}, _ctx(db))


async def _lead_source(db, pid):
    from app.agent import tools
    await tools._set_lead_source({"source": "facebook"}, _ctx(db))


async def _lead_signals(db, pid):
    from app.services.lead_signals import refresh_lead_signals
    await refresh_lead_signals(db, WA)


async def _user_cart(db, pid):
    from app.agent import cart
    await cart.save_cart(db, WA, {"items": [ITEM]})


async def _user_sizes(db, pid):
    from app.agent import measurements
    await measurements.save_measurements(db, WA, {"chest": "40"})


async def _person_cart(db, pid):
    from app.agent import cart
    await cart.save_cart(db, PSID, {"items": [ITEM]}, "messenger")


async def _person_sizes(db, pid):
    from app.agent import measurements
    await measurements.save_measurements(db, PSID, {"chest": "40"}, "messenger")


async def _profile(db, pid):
    from app.agent import tools
    await tools._save_profile_fields(db, pid, "Priest", None)
    await db.commit()


async def _contact_location(db, pid):
    from app.agent import tools
    await tools._capture_contact({"location": "Nairobi, Kenya"}, _ctx(db, PSID, "messenger"))


async def _contact_phone(db, pid):
    from app.agent import tools
    await tools._capture_contact({"phone": "+254712000009"}, _ctx(db, PSID, "messenger"))


USER_WRITERS = {
    "add_tags": (_add_tags, lambda st: "vip" in st["tags"]),
    "set_lead_source": (_lead_source, lambda st: st["lead_source"] == "facebook"),
    "lead_signals": (_lead_signals, lambda st: "Kenya" in st["tags"]),
    "save_cart": (_user_cart, lambda st: st["agent_cart"]["items"] == [ITEM]),
    "save_measurements": (_user_sizes, lambda st: st["measurements"]["chest"] == "40"),
}
PERSON_WRITERS = {
    "save_cart": (_person_cart, lambda st: st["agent_cart"]["items"] == [ITEM]),
    "save_measurements": (_person_sizes, lambda st: st["measurements"]["chest"] == "40"),
    "save_profile_fields": (_profile, lambda st: st["profile"]["role"] == "Priest"),
    "capture_contact_location": (_contact_location, lambda st: st["location"] == "Nairobi, Kenya"),
    "capture_contact_phone": (_contact_phone, lambda st: st["country_iso"] == "KE"),
}


def _prep(rig):
    from app.models.user import User
    pid = _customer(rig)

    async def go():
        async with rig.maker() as db:
            await db.execute(sa.update(User).where(User.wa_id == WA).values(country="Kenya"))
            await db.commit()
    run(go())
    return pid


async def _write_racing(rig, writer, pid, window, load, arrive):
    """Run `writer` with `arrive` (another session's write) in the given window."""
    tasks = []
    async with rig.maker() as db:
        held = await load(db)       # a strong reference: the identity map is weak
        if window == "held":
            await arrive()
        else:
            async def someone_else_arrives():
                task = asyncio.create_task(arrive())
                tasks.append(task)
                await _blocked_or_finished(rig, task)
            _before_next_commit(db, someone_else_arrives)
        await writer(db, pid)
        del held
    await asyncio.gather(*tasks)


@pytest.mark.parametrize("window", ["held", "mid_write"])
@pytest.mark.parametrize("name", list(USER_WRITERS))
def test_a_call_note_survives_every_user_state_writer(rig, name, window):
    from app.models.user import User
    writer, wrote = USER_WRITERS[name]
    pid = _prep(rig)

    async def load(db):
        return (await db.execute(sa.select(User).where(User.wa_id == WA))).scalar_one()
    run(_write_racing(rig, writer, pid, window, load, lambda: _note(rig, "Wants a chalice.", "wacid.x")))

    st = _user_state(rig, WA)
    assert "chalice" in st.get("crm_notes", "") and st.get("call_note_ids") == ["wacid.x"]
    assert wrote(st)


@pytest.mark.parametrize("window", ["held", "mid_write"])
@pytest.mark.parametrize("name", list(PERSON_WRITERS))
def test_a_fact_survives_every_person_state_writer(rig, name, window):
    from app.models.person import Person
    writer, wrote = PERSON_WRITERS[name]
    pid = _prep(rig)

    async def load(db):
        return await db.get(Person, pid)
    run(_write_racing(rig, writer, pid, window, load, lambda: _fact(rig, PSID, "messenger", "landed")))

    st = _person_state(rig, pid)
    assert st.get("agent_memory") == ["landed"]
    assert wrote(st)


# ═════════════════════════════════════════════════════════════════════════════
# A lock must never outlive the write: the turn goes back to the model next
# ═════════════════════════════════════════════════════════════════════════════

async def _row_is_free(rig, model, *where) -> bool:
    async with rig.maker() as db:
        try:
            await db.execute(sa.select(model).where(*where).with_for_update(nowait=True))
        except sa.exc.DBAPIError:
            return False
        return True


@pytest.mark.parametrize("name", list(USER_WRITERS))
def test_no_user_state_writer_leaves_the_row_locked(rig, name):
    from app.models.user import User
    pid = _prep(rig)

    async def go():
        async with rig.maker() as db:
            await USER_WRITERS[name][0](db, pid)
            return await _row_is_free(rig, User, User.wa_id == WA)
    assert run(go()) is True


@pytest.mark.parametrize("name", list(PERSON_WRITERS))
def test_no_person_state_writer_leaves_the_row_locked(rig, name):
    from app.models.person import Person
    pid = _prep(rig)

    async def go():
        async with rig.maker() as db:
            await PERSON_WRITERS[name][0](db, pid)
            return await _row_is_free(rig, Person, Person.id == pid)
    assert run(go()) is True


def test_the_no_op_paths_let_go_of_the_row_too(rig):
    """The two paths that take the lock, find nothing to do, and could return
    without the commit that releases it."""
    from app.agent import tools
    from app.models.user import User
    from app.services.lead_signals import refresh_lead_signals
    pid = _prep(rig)

    async def go():
        async with rig.maker() as db:
            await tools._set_lead_source({"source": "facebook"}, _ctx(db))
            await tools._set_lead_source({"source": "tiktok"}, _ctx(db))     # first touch stands
            first = await _row_is_free(rig, User, User.wa_id == WA)
            await _lead_signals(db, pid)
            await refresh_lead_signals(db, WA)                               # already tagged
            return first, await _row_is_free(rig, User, User.wa_id == WA)
    assert run(go()) == (True, True)
    assert _user_state(rig, WA)["lead_source"] == "facebook"


def test_lead_signals_lets_go_when_the_fresh_row_needs_nothing(rig):
    """The copy this session holds says "tag it"; by the time the row is locked
    someone else has. Nothing to write, and the lock still has to go."""
    from app.models.user import User
    from app.services.lead_signals import refresh_lead_signals
    pid = _prep(rig)

    async def go():
        async with rig.maker() as db:
            held = (await db.execute(sa.select(User).where(User.wa_id == WA))).scalar_one()
            async with rig.maker() as other:
                await _lead_signals(other, pid)
            assert "Kenya" not in (held.state or {}).get("tags", [])
            await refresh_lead_signals(db, WA)
            del held
            return await _row_is_free(rig, User, User.wa_id == WA)
    assert run(go()) is True


def test_the_lock_never_blocks_rows_being_inserted_against_it(rig):
    """Messages, identities and identifiers keep arriving while a state write
    is in flight. FOR UPDATE would stall their foreign-key checks; two sessions
    holding such a check and both wanting the lock would deadlock."""
    from app.models.person import Identity, Person
    from app.services.state_lock import lock_for_write
    pid = _prep(rig)

    async def go():
        async with rig.maker() as db:
            await lock_for_write(db, await db.get(Person, pid))
            async with rig.maker() as other:
                await other.execute(sa.text("SET LOCAL lock_timeout = '2s'"))
                other.add(Identity(person_id=pid, channel="instagram", external_id="ig-1"))
                await other.commit()
            await db.rollback()
    run(go())


def test_lock_for_write_passes_through_what_has_no_row_to_lock(rig):
    from app.models.user import User
    from app.services.state_lock import lock_for_write

    async def go():
        async with rig.maker() as db:
            assert await lock_for_write(db, None) is None
            new = User(wa_id="254744000011")
            assert await lock_for_write(db, new) is new          # transient
            db.add(new)
            assert await lock_for_write(db, new) is new          # pending
            await db.rollback()
    run(go())


# ═════════════════════════════════════════════════════════════════════════════
# The cart's move from the user row to the person
# ═════════════════════════════════════════════════════════════════════════════

def test_adopting_a_cart_keeps_a_note_and_moves_the_cart_once(rig):
    from app.agent import cart
    from app.models.person import Person
    from app.models.user import User
    wa, pid = "254744000010", uuid.uuid4()

    async def go():
        async with rig.maker() as db:
            db.add(Person(id=pid, state={}))
            await db.flush()
            db.add(User(wa_id=wa, phone=wa, person_id=pid, state={"agent_cart": {"items": [ITEM]}}))
            await db.commit()
        async with rig.maker() as db:
            held = (await db.execute(sa.select(User).where(User.wa_id == wa))).scalar_one()
            await _note(rig, "Wants a chalice.", "wacid.x", handle=wa)
            found = await cart.get_cart(db, wa)
            del held
            return found
    assert run(go())["items"] == [ITEM]

    st = _user_state(rig, wa)
    assert "chalice" in st["crm_notes"] and "agent_cart" not in st
    assert _person_state(rig, pid)["agent_cart"]["items"] == [ITEM]


def test_a_turn_and_calls_finishing_together_lose_nothing(rig):
    """Unforced: every user-row writer and four call notes on one customer."""
    pid = _prep(rig)

    async def writer(fn):
        async with rig.maker() as db:
            await fn(db, pid)

    async def go():
        await asyncio.gather(*[writer(w) for w, _ in USER_WRITERS.values()],
                             *[_note(rig, f"Call {i}.", f"wacid.{i}") for i in range(4)])
    run(go())

    st = _user_state(rig, WA)
    assert sorted(st["call_note_ids"]) == [f"wacid.{i}" for i in range(4)]
    assert st["crm_notes"].count("\U0001F4DE Call (") == 4
    assert all(wrote(st) for _, wrote in USER_WRITERS.values())
