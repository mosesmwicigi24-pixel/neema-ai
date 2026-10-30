"""The photo check's review list (owner, 2026-10-29: "start in shadow mode"):
every check is recorded against the customer's own message, listed newest
first with the photo, and marked right / wrong by the owner. Real Postgres
through the real admin routes; skips without one."""
import asyncio
from datetime import datetime, timezone

from tests import test_calls_db as _calls, test_security_db as _sec
from tests.test_security_db import _as

fresh_db, world, env = _sec.fresh_db, _calls.world, _calls.env
pytestmark = _calls.pytestmark


def _photo_thread(env, wa):
    from app.models.message import Message, MsgDirection, MsgSender
    from app.services.channel import get_or_create_conversation
    from app.services.identity import resolve_or_create_person

    async def go():
        async with env.maker() as db:
            ident = await resolve_or_create_person(db, "whatsapp", wa, display_name=f"Pastor {wa[-3:]}")
            conv = await get_or_create_conversation(db, "whatsapp", wa,
                                                    person_id=ident.person_id, wa_id=wa)
            db.add(Message(channel="whatsapp", wa_id=wa, external_id=wa, person_id=ident.person_id,
                           conversation_id=conv.id, direction=MsgDirection.inbound,
                           sender=MsgSender.user, media_type="image",
                           media_url=f"/api/admin/media/{wa}.jpg",
                           created_at=datetime.now(timezone.utc)))
            await db.commit()
            return str(conv.id)
    return asyncio.run(go())


def test_checks_are_listed_with_the_photo_and_marked_by_the_owner(env, world):
    from app.services import photo_check as pc
    conv = _photo_thread(env, "254700000301")
    refer = {"verdict": "refer", "reasons": ["extra embroidery beyond our Ornate Chasuble: gold IHS"],
             "product": "Ornate Chasuble", "product_slug": "ornate-chasuble", "match": "same",
             "ai_made": "likely", "extra_embroidery": True, "source": "vision", "image_sha": "a" * 40}
    asyncio.run(pc.record(refer, channel="whatsapp", contact="254700000301",
                          media_url="/api/admin/media/254700000301.jpg", mode="shadow", acted=False))
    # The same photo again (a re-run of the turn) is one row, not two.
    asyncio.run(pc.record(refer, channel="whatsapp", contact="254700000301",
                          media_url="/api/admin/media/254700000301.jpg", mode="shadow", acted=False))
    asyncio.run(pc.record({"verdict": "ours", "reasons": ["our own photo of Clergy Stole"],
                           "product": "Clergy Stole", "image_sha": "b" * 40},
                          channel="whatsapp", contact="254700000301", media_url=None,
                          mode="shadow", acted=False))

    got = env.client.get("/api/admin/reports/photo-checks", headers=_as(world["boss"])).json()
    assert got["mode"] == "shadow" and got["counts"]["refer"] == 1 and got["counts"]["ours"] == 1
    assert len(got["items"]) == 2
    item = next(i for i in got["items"] if i["verdict"] == "refer")
    assert item["conversation_id"] == conv and item["name"] == "Pastor 301"
    assert item["photo_url"].startswith("/api/admin/media/254700000301.jpg")
    assert item["extra_embroidery"] is True and "gold IHS" in item["reasons"][0]
    only = env.client.get("/api/admin/reports/photo-checks?verdict=refer", headers=_as(world["boss"])).json()
    assert [i["id"] for i in only["items"]] == [item["id"]]

    r = env.client.post(f"/api/admin/reports/photo-checks/{item['id']}/mark",
                        json={"mark": "wrong", "note": "this is our Ornate Chasuble with IHS — we do it daily"},
                        headers=_as(world["boss"]))
    assert r.status_code == 200 and r.json()["owner_mark"] == "wrong"
    got = env.client.get("/api/admin/reports/photo-checks", headers=_as(world["boss"])).json()
    assert got["marked"] == {"right": 0, "wrong": 1}
    assert next(i for i in got["items"] if i["id"] == item["id"])["owner_note"].startswith("this is our")
    assert env.client.post(f"/api/admin/reports/photo-checks/{item['id']}/mark", json={"mark": "maybe"},
                           headers=_as(world["boss"])).status_code == 422
    # Cleared again.
    env.client.post(f"/api/admin/reports/photo-checks/{item['id']}/mark", json={"mark": None},
                    headers=_as(world["boss"]))
    got = env.client.get("/api/admin/reports/photo-checks", headers=_as(world["boss"])).json()
    assert got["marked"] == {"right": 0, "wrong": 0}


def test_the_list_needs_reports_access(env, world):
    assert env.client.get("/api/admin/reports/photo-checks",
                          headers=_as(world["ann"])).status_code == 403
