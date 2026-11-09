"""CUSTOMER NAMES on a real Postgres (owner, 2026-11-09: "John 14:14"): a
verse profile name is kept as the channel's name but never greeted; the
customer's own "My name is…" wins over every profile; a WhatsApp profile
never replaces what they said or what staff confirmed; staff can correct;
the person, the user row and the inbox agree; the audit recovers a legacy
record from real evidence only. Skips without a reachable Postgres."""
import asyncio

import app.main  # noqa: F401
from sqlalchemy import select
from tests import test_calls_db as _calls, test_security_db as _sec

fresh_db, world, env = _sec.fresh_db, _calls.world, _calls.env
pytestmark = _calls.pytestmark

KE = "254728528853"
PSID = "7712345678901234"


def _run(coro):
    return asyncio.run(coro)


def test_a_verse_profile_name_then_their_own_name(env, world):
    from app.models.person import Identity, Person
    from app.services import names
    from app.services.identity import resolve_or_create_person
    from app.services.messaging import _record_self_introduction

    async def go():
        async with env.maker() as db:
            ident = await resolve_or_create_person(db, "messenger", PSID, display_name="John 14:14",
                                                   source="messenger_inbound")
            await db.commit()
            pid = ident.person_id
        async with env.maker() as db:
            p = await db.get(Person, pid)
            assert p.display_name == "John 14:14"                       # shown: nothing better known
            cur = p.state["name"]["current"]
            assert cur["kind"] == "scripture" and cur["by"] == "messenger"
            assert names.for_agent(p.display_name)[0] == ""             # …but never greeted by it
            await _record_self_introduction(db, pid, "Habari, my name is Peter Otieno")
            await db.commit()
        async with env.maker() as db:
            p = await db.get(Person, pid)
            ident = (await db.execute(select(Identity).where(Identity.external_id == PSID))).scalar_one()
            assert p.display_name == "Peter Otieno"
            assert p.state["name"]["current"]["by"] == "stated"
            assert ident.display_name == "John 14:14"                   # the channel's own name is kept
            assert p.state["name"]["readings"]["messenger"]["value"] == "John 14:14"
            assert p.state["name"]["history"][-1]["previous"]["value"] == "John 14:14"
            # a verse quoted later is not an introduction
            await _record_self_introduction(db, pid, '"I am the way, the truth and the life" John 14:6')
            await db.commit()
            assert (await db.get(Person, pid)).display_name == "Peter Otieno"
    _run(go())


def test_whatsapp_profile_said_name_and_staff_correction(env, world):
    from app.agent.tools import ToolContext, _capture_customer
    from app.models.person import Person
    from app.models.user import User
    from app.routers import crm
    from app.services.messaging import provision_user

    async def go():
        async with env.maker() as db:
            user = await provision_user(db, KE, name="Psalm 23")
            await db.commit()
            assert user.name == "Psalm 23" and user.name_confirmed is False
            ctx = ToolContext(db=db, redis=None, wa_id=KE, currency="KES", channel="whatsapp")
            # the writer is handed a verse as a name: refused
            out = await _capture_customer({"name": "John 14:14"}, ctx)
            assert "name_note" in out and user.name == "Psalm 23"
            out = await _capture_customer({"name": "Bishop Daniel Mwangi"}, ctx)
        async with env.maker() as db:
            user = (await db.execute(select(User).where(User.wa_id == KE))).scalar_one()
            p = await db.get(Person, user.person_id)
            assert user.name == p.display_name == "Bishop Daniel Mwangi" and user.name_confirmed
            # the next inbound with a different profile name changes nothing shown
            await provision_user(db, KE, name="Danny M")
            await db.commit()
        async with env.maker() as db:
            user = (await db.execute(select(User).where(User.wa_id == KE))).scalar_one()
            p = await db.get(Person, user.person_id)
            assert user.name == p.display_name == "Bishop Daniel Mwangi"
            assert p.state["name"]["readings"]["whatsapp"]["value"] == "Danny M"   # kept as the profile name
            # staff correct it; it stands against the customer's later words
            await crm.update_customer(KE, {"name": "Daniel Mwangi"}, db=db, agent=None)
        async with env.maker() as db:
            user = (await db.execute(select(User).where(User.wa_id == KE))).scalar_one()
            ctx = ToolContext(db=db, redis=None, wa_id=KE, currency="KES", channel="whatsapp")
            out = await _capture_customer({"name": "Dan"}, ctx)
            assert "Staff confirmed" in out.get("name_note", "")
        async with env.maker() as db:
            user = (await db.execute(select(User).where(User.wa_id == KE))).scalar_one()
            p = await db.get(Person, user.person_id)
            assert user.name == p.display_name == "Daniel Mwangi"
            assert p.state["name"]["current"]["by"] == "operator"
            prof = crm._build_profile(user, [], [], None, person_state=p.state,
                                      person_name=p.display_name)
            assert prof["name"] == "Daniel Mwangi"
            assert prof["name_info"]["label"] == "Confirmed by staff" and prof["name_info"]["addressable"]
    _run(go())


def test_the_audit_recovers_from_evidence_and_never_invents(env, world):
    from app.models.message import Message, MsgDirection, MsgSender
    from app.models.person import Identity, Person
    from app.models.user import User
    from app.scripts import audit_names

    async def go():
        async with env.maker() as db:
            # Legacy records, written before services/names: no name record.
            a, b = Person(display_name="John 14:14"), Person(display_name="Grace Ministries")
            db.add_all([a, b])
            await db.flush()
            db.add_all([
                Identity(person_id=a.id, channel="facebook", external_id="fb-a", display_name="John 14:14"),
                Identity(person_id=b.id, channel="facebook", external_id="fb-b", display_name="Grace Ministries"),
                User(wa_id="254700000001", name="John 14:14", person_id=a.id),
                Message(channel="facebook", external_id="fb-a", person_id=a.id,
                        direction=MsgDirection.inbound, sender=MsgSender.user,
                        text="Praise God. I'm Pastor James Kariuki, from Nyeri"),
            ])
            await db.commit()
            aid, bid = a.id, b.id
        # dry run writes nothing
        await audit_names.run(apply=False, actor=None, limit=100)
        async with env.maker() as db:
            assert (await db.get(Person, aid)).display_name == "John 14:14"
            assert "name" not in ((await db.get(Person, aid)).state or {})
        await audit_names.run(apply=True, actor="test", limit=100)
        async with env.maker() as db:
            a = await db.get(Person, aid)
            u = (await db.execute(select(User).where(User.person_id == aid))).scalar_one()
            assert a.display_name == u.name == "Pastor James Kariuki"
            assert a.state["name"]["readings"]["facebook"]["value"] == "John 14:14"
            assert a.state["name"]["audited"]["by"] == "test"
            b = await db.get(Person, bid)
            assert b.display_name == "Grace Ministries"                  # nothing to recover from: kept
            snapshot = dict(a.state)
        await audit_names.run(apply=True, actor="test", limit=100)        # idempotent
        async with env.maker() as db:
            assert (await db.get(Person, aid)).state["name"]["current"] == snapshot["name"]["current"]
    _run(go())
