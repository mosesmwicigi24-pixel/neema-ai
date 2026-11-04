"""The pacing review list (owner, 2026-11-04, record-only first): a decision
is recorded against the customer's conversation, listed newest first with
its reasons and counts, and marked right / wrong by the owner. Real Postgres
through the real admin routes; skips without one."""
import asyncio

from tests import test_calls_db as _calls, test_security_db as _sec
from tests.test_security_db import _as

fresh_db, world, env = _sec.fresh_db, _calls.world, _calls.env
pytestmark = _calls.pytestmark


def test_decisions_are_listed_and_marked(env, world):
    from app.agent import conversation_budget as cb
    from app.services.channel import get_or_create_conversation
    from app.services.identity import resolve_or_create_person

    async def mk():
        async with env.maker() as db:
            ident = await resolve_or_create_person(db, "whatsapp", "254700000401", display_name="Chatty 401")
            conv = await get_or_create_conversation(db, "whatsapp", "254700000401",
                                                    person_id=ident.person_id, wa_id="254700000401")
            await db.commit()
            return str(conv.id)
    conv = asyncio.run(mk())
    asyncio.run(cb.record(channel="whatsapp", contact="254700000401", decision="shorten",
                          reasons=["16 replies today, budget 15 (0 steps of progress)"],
                          counts={"turns": 16, "progress": 0, "budget": 15}))
    asyncio.run(cb.record(channel="whatsapp", contact="254700000401", decision="bot",
                          reasons=["auto-reply text"], counts={"bot_score": 4}))

    got = env.client.get("/api/admin/reports/pacing", headers=_as(world["boss"])).json()
    assert got["mode"] == "shadow" and got["counts"]["shorten"] == 1 and got["counts"]["bot"] == 1
    item = next(i for i in got["items"] if i["decision"] == "shorten")
    assert item["conversation_id"] == conv and item["name"] == "Chatty 401"
    assert item["turns"] == 16 and item["budget"] == 15 and "budget 15" in item["reasons"][0]
    assert item["label"] == cb.DECISIONS["shorten"]
    only = env.client.get("/api/admin/reports/pacing?decision=bot", headers=_as(world["boss"])).json()
    assert [i["decision"] for i in only["items"]] == ["bot"]

    r = env.client.post(f"/api/admin/reports/pacing/{item['id']}/mark", json={"mark": "wrong"},
                        headers=_as(world["boss"]))
    assert r.status_code == 200 and r.json()["owner_mark"] == "wrong"
    got = env.client.get("/api/admin/reports/pacing", headers=_as(world["boss"])).json()
    assert got["marked"] == {"right": 0, "wrong": 1}
    assert env.client.post(f"/api/admin/reports/pacing/{item['id']}/mark", json={"mark": "x"},
                           headers=_as(world["boss"])).status_code == 422


def test_the_list_needs_reports_access(env, world):
    assert env.client.get("/api/admin/reports/pacing", headers=_as(world["ann"])).status_code == 403
