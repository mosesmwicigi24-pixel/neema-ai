"""GEOGRAPHY WITH PROVENANCE on a real Postgres (owner's directive,
2026-11-09): the Bahrain / Kenya case end to end — the number places the
customer in Bahrain with its provenance, their words place them in Kenya and
switch the market, the profile shows both with the discrepancy, an operator's
edit confirms a residence, a merge carries the record, and an older profile
gets its telephone country on the next message. Skips without a reachable
Postgres."""
import asyncio

import app.main  # noqa: F401
from sqlalchemy import select
from tests import test_calls_db as _calls, test_security_db as _sec

fresh_db, world, env = _sec.fresh_db, _calls.world, _calls.env
pytestmark = _calls.pytestmark

BH = "97333123456"


def _run(coro):
    return asyncio.run(coro)


async def _person_state(db, user):
    from app.models.person import Person
    p = await db.get(Person, user.person_id)
    return dict(p.state or {}), p


def test_the_bahrain_number_in_kenya_end_to_end(env, world):
    from app.agent.tools import ToolContext, _capture_customer
    from app.models.agent_activity import AgentActivity
    from app.models.user import User
    from app.routers import crm
    from app.services.channel import get_or_create_conversation
    from app.services.market import customer_market
    from app.services.messaging import provision_user

    async def go():
        async with env.maker() as db:
            # 1. the first message: the number is the only evidence
            user = await provision_user(db, BH, name="Amina")
            await get_or_create_conversation(db, "whatsapp", BH, wa_id=BH)
            await db.commit()
            st, _ = await _person_state(db, user)
            tel = st["geo"]["telephone_country"]
            assert tel["value"] == "BH" and tel["by"] == "phone" and tel["confidence"] == "confirmed"
            assert tel["detail"] == "+973"
            assert (user.country, user.country_iso) == ("Bahrain", "BH")
            assert await customer_market(db, "whatsapp", BH) == ("USD", {"country_iso": "BH", "country": "Bahrain"})
            assert crm._country_fields(user, st, BH)["country_iso"] == "BH"
            view = crm._geo_view(st, BH)
            assert view["decision"]["country_iso"] == "BH" and view["discrepancy"] is False

            # 2. they say where they are
            ctx = ToolContext(db=db, redis=None, wa_id=BH, currency="USD", channel="whatsapp",
                              market_locked=True)
            out = await _capture_customer({"location": "Nairobi"}, ctx)
            assert out["placed"] == "Kenya" and out["currency_now"] == "KES" and ctx.currency == "KES"

        async with env.maker() as db:
            user = (await db.execute(select(User).where(User.wa_id == BH))).scalar_one()
            st, _ = await _person_state(db, user)
            g = st["geo"]
            assert g["telephone_country"]["value"] == "BH"                      # kept
            assert g["probable_country"]["value"] == "KE" and g["probable_country"]["by"] == "stated"
            assert g["probable_country"]["confidence"] == "high" and g["probable_country"]["detail"] == "Nairobi"
            assert g["city"]["value"] == "Nairobi"
            assert (user.country, user.country_iso, user.location) == ("Kenya", "KE", "Nairobi")
            # the market, the profile and the view agree
            assert await customer_market(db, "whatsapp", BH) == ("KES", {"country_iso": "KE", "country": "Kenya"})
            assert crm._country_fields(user, st, BH) == {"country_iso": "KE", "country": "Kenya",
                                                         "flag_url": "https://flagcdn.com/ke.svg"}
            view = crm._geo_view(st, BH)
            assert view["telephone_country"]["label"] == "Bahrain"
            assert view["decision"]["country_iso"] == "KE" and view["decision"]["source"] == "what the customer said"
            assert view["discrepancy"] is True
            # a customer-level event was written, on the conversation
            rows = (await db.execute(select(AgentActivity).where(
                AgentActivity.contact == BH, AgentActivity.tool == "geography"))).scalars().all()
            assert len(rows) == 1 and rows[0].summary == "Placed the customer"
            assert rows[0].detail == "Placed in Kenya (what the customer said); was Bahrain"
            assert rows[0].conversation_id is not None

            # 3. the same words again: no new event, nothing moves
            ctx = ToolContext(db=db, redis=None, wa_id=BH, currency="KES", channel="whatsapp")
            out = await _capture_customer({"location": "Nairobi"}, ctx)
            assert "currency_now" not in out
        async with env.maker() as db:
            rows = (await db.execute(select(AgentActivity).where(
                AgentActivity.contact == BH, AgentActivity.tool == "geography"))).scalars().all()
            assert len(rows) == 1

            # 4. an operator confirms a different residence: it outranks the words
            await crm.update_customer(BH, {"country": "United Arab Emirates"}, db=db, agent=None)
        async with env.maker() as db:
            user = (await db.execute(select(User).where(User.wa_id == BH))).scalar_one()
            st, _ = await _person_state(db, user)
            res = st["geo"]["confirmed_residence"]
            assert res["value"] == "AE" and res["by"] == "operator" and res["confidence"] == "confirmed"
            assert (user.country_iso, user.country) == ("AE", "United Arab Emirates")   # the name alone used to leave the ISO unset
            assert st["geo"]["probable_country"]["value"] == "KE"                       # the words are kept
            assert (await customer_market(db, "whatsapp", BH))[0] == "USD"
            assert crm._country_fields(user, st, BH)["country_iso"] == "AE"
            rows = (await db.execute(select(AgentActivity).where(
                AgentActivity.contact == BH, AgentActivity.tool == "geography"))).scalars().all()
            assert len(rows) == 2 and rows[-1].detail == "Placed in United Arab Emirates (an operator); was Kenya"

            # 5. a weaker reading afterwards (an IP guess) does not move the decision
            from app.services import geography as geo
            _, p = await _person_state(db, user)
            change = await geo.place(db, p, [("probable_country", "US", {"by": "ip", "confidence": "probable"})], user=user)
            await db.commit()
            assert change is not None and change["moved"] is False
        async with env.maker() as db:
            user = (await db.execute(select(User).where(User.wa_id == BH))).scalar_one()
            st, _ = await _person_state(db, user)
            assert st["geo"]["probable_country"]["value"] == "KE"
            assert any(h["value"] == "US" and h.get("kept") == "previous" for h in st["geo"]["history"])
            assert user.country_iso == "AE"
    _run(go())


def test_an_older_profile_gets_its_telephone_country_on_the_next_message(env, world):
    from app.models.user import User
    from app.services.messaging import provision_user

    async def go():
        async with env.maker() as db:
            user = await provision_user(db, "254712345678")
            await db.commit()
            # simulate a profile from before this slice: no geo on the person
            from sqlalchemy.orm.attributes import flag_modified
            st, p = await _person_state(db, user)
            st.pop("geo", None)
            p.state = st
            flag_modified(p, "state")
            await db.commit()
        async with env.maker() as db:
            user = await provision_user(db, "254712345678", last_text="hi")
            await db.commit()
            st, _ = await _person_state(db, user)
            assert st["geo"]["telephone_country"]["value"] == "KE"
            assert (user.country, user.country_iso) == ("Kenya", "KE")
            u2 = (await db.execute(select(User).where(User.wa_id == "254712345678"))).scalar_one()
            assert u2.person_id == user.person_id
    _run(go())


def test_a_shared_dialling_code_names_the_right_country(env, world):
    from app.services.messaging import provision_user

    async def go():
        async with env.maker() as db:
            user = await provision_user(db, "12125550123")        # New York
            await db.commit()
            st, _ = await _person_state(db, user)
            assert st["geo"]["telephone_country"]["value"] == "US"
            assert (user.country, user.country_iso) == ("United States", "US")
    _run(go())


def test_a_merge_carries_geography_and_the_opt_out(env, world):
    from app.models.person import Person
    from app.services import geography as geo
    from app.services.identity import resolve_or_create_person
    from app.services.merge import merge_persons
    from app.services.messaging import provision_user
    from sqlalchemy.orm.attributes import flag_modified

    async def go():
        async with env.maker() as db:
            wa = await provision_user(db, "254722000111")
            ident = await resolve_or_create_person(db, "messenger", "psid-geo-1", source="test")
            sec = await db.get(Person, ident.person_id)
            st, _ = geo.observe_many(sec.state, geo.stated_readings("Mombasa"))
            st["contact_preferences"] = {"opt_out": {"at": "2026-11-01T00:00:00+00:00",
                                                     "channel": "messenger", "said": "stop"},
                                         "language": "sw"}
            st["customer_state"] = {"state": "needs_time"}
            sec.state = st
            flag_modified(sec, "state")
            await db.commit()
            await merge_persons(db, wa.person_id, ident.person_id, primary_wa_id="254722000111")
            await db.commit()
            pst, _ = await _person_state(db, wa)
            g = pst["geo"]
            assert g["telephone_country"]["value"] == "KE"
            assert g["probable_country"]["value"] == "KE" and g["probable_country"]["by"] == "stated"
            assert g["city"]["value"] == "Mombasa"
            assert pst["contact_preferences"]["opt_out"]["said"] == "stop"
            assert pst["contact_preferences"]["language"] == "sw"
            assert pst["customer_state"] == {"state": "needs_time"}
    _run(go())


def test_confirming_the_placement_by_iso_alone_records_the_residence(env, world):
    """The panel's Confirm button sends only the ISO of the current decision
    (slice 17): the residence is recorded as the operator's confirmation, the
    user row's country NAME follows the decision (not left at the old one),
    and the timeline gets its line."""
    from app.models.agent_activity import AgentActivity
    from app.models.user import User
    from app.routers import crm
    from app.services.channel import get_or_create_conversation
    from app.services.messaging import provision_user

    async def go():
        wa = "97333123457"
        async with env.maker() as db:
            user = await provision_user(db, wa, name="Yusuf")
            await get_or_create_conversation(db, "whatsapp", wa, wa_id=wa)
            await db.commit()
            assert user.country == "Bahrain"
            await crm.update_customer(wa, {"country_iso": "KE"}, db=db, agent=None)
        async with env.maker() as db:
            user = (await db.execute(select(User).where(User.wa_id == wa))).scalar_one()
            st, _ = await _person_state(db, user)
            res = st["geo"]["confirmed_residence"]
            assert res["value"] == "KE" and res["by"] == "operator" and res["confidence"] == "confirmed"
            assert (user.country_iso, user.country) == ("KE", "Kenya")
            assert st["geo"]["telephone_country"]["value"] == "BH"
            view = crm._geo_view(st, wa)
            assert view["decision"]["confidence"] == "confirmed" and view["discrepancy"] is True
            rows = (await db.execute(select(AgentActivity).where(
                AgentActivity.contact == wa, AgentActivity.tool == "geography"))).scalars().all()
            assert [r.detail for r in rows] == ["Placed in Kenya (an operator); was Bahrain"]
    _run(go())
