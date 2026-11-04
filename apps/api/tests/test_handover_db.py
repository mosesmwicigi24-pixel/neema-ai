"""Ask the colleague holding a chat to hand it over (owner, 2026-11-04): "a
button that can request the other person who is holding that chat to release
it to this person. If that is granted on the other end, then that will be
transferred to this new person." Real Postgres through the real admin routes;
skips without one."""
import asyncio

import pytest

from tests import test_calls_db as _calls, test_security_db as _sec
from tests.test_security_db import _as

fresh_db, world, env = _sec.fresh_db, _calls.world, _calls.env
pytestmark = _calls.pytestmark


@pytest.fixture
def held(env, world, monkeypatch):
    """A WhatsApp chat Ann has picked up. Customer-facing sends are faked."""
    from app.services import conversation as cs
    from app.services.channel import get_or_create_conversation
    sent = []

    async def _send(channel, to, text, **kw):
        sent.append(text)
        return "wamid.x"
    monkeypatch.setattr(cs, "send_to_channel", _send)

    async def mk():
        async with env.maker() as db:
            conv = await get_or_create_conversation(db, "whatsapp", "254700000501", wa_id="254700000501")
            await db.commit()
            return str(conv.id)
    cid = asyncio.run(mk())
    assert env.client.post(f"/api/admin/conversations/{cid}/intercept",
                           headers=_as(world["ann"])).status_code == 200
    return cid, sent


def _row(env, world, cid, who="ben"):
    return env.client.get(f"/api/admin/conversations/{cid}", headers=_as(world[who])).json()


def test_ben_asks_ann_and_ann_hands_it_over(env, world, held):
    cid, sent = held
    # Ben is locked out of Ann's chat…
    assert env.client.post(f"/api/admin/conversations/{cid}/intercept",
                           headers=_as(world["ben"])).status_code == 409
    # …so he asks her.
    r = env.client.post(f"/api/admin/conversations/{cid}/handover-request", headers=_as(world["ben"]))
    assert r.status_code == 200, r.text
    req = r.json()["request"]
    assert req["from_agent_name"] == "Ben Otieno" and req["holder_agent_id"] == world["ann"]
    # Asking twice is one request.
    again = env.client.post(f"/api/admin/conversations/{cid}/handover-request", headers=_as(world["ben"]))
    assert again.json().get("already") is True and again.json()["request"]["id"] == req["id"]

    # The chat row carries it, for Ann's Hand over / Keep and Ben's "waiting".
    row = _row(env, world, cid, "ann")
    assert row["assigned_agent_id"] == world["ann"] and row["handover_request"]["id"] == req["id"]

    # Someone else can't answer for Ann — not even an admin.
    for who in ("ben", "boss"):
        assert env.client.post(f"/api/admin/conversations/{cid}/handover-request/accept",
                               headers=_as(world[who])).status_code == 403

    # The boss can't queue a second ask while Ben's is open.
    other = env.client.post(f"/api/admin/conversations/{cid}/handover-request", headers=_as(world["boss"]))
    assert other.status_code == 409 and "Ben Otieno has already asked" in other.json()["detail"]

    ok = env.client.post(f"/api/admin/conversations/{cid}/handover-request/accept",
                         json={"request_id": req["id"]}, headers=_as(world["ann"]))
    assert ok.status_code == 200, ok.text
    row = _row(env, world, cid)
    assert row["assigned_agent_id"] == world["ben"] and row["intercept_mode"] == "human"
    assert row["handover_request"] is None

    thread = env.client.get(f"/api/admin/conversations/{cid}/messages",
                            headers=_as(world["ben"])).json()
    labels = [m["text"] for m in thread if m.get("type") == "system_event"]
    assert "Ben Otieno asked Ann Wanjiru to hand over this chat" in labels
    assert any(lbl.startswith("Transferred — Ann Wanjiru → Ben Otieno") for lbl in labels)
    # The lapsed request can't be answered again.
    assert env.client.post(f"/api/admin/conversations/{cid}/handover-request/accept",
                           headers=_as(world["ann"])).status_code == 409


def test_ann_keeps_it_and_ben_is_told(env, world, held):
    cid, _ = held
    env.client.post(f"/api/admin/conversations/{cid}/handover-request", headers=_as(world["ben"]))
    r = env.client.post(f"/api/admin/conversations/{cid}/handover-request/decline",
                        headers=_as(world["ann"]))
    assert r.status_code == 200 and r.json()["declined"] is True
    row = _row(env, world, cid)
    assert row["assigned_agent_id"] == world["ann"] and row["handover_request"] is None
    thread = env.client.get(f"/api/admin/conversations/{cid}/messages",
                            headers=_as(world["ann"])).json()
    assert "Ann Wanjiru kept the chat" in [m["text"] for m in thread if m.get("type") == "system_event"]
    # Ben may ask again later.
    assert env.client.post(f"/api/admin/conversations/{cid}/handover-request",
                           headers=_as(world["ben"])).status_code == 200


def test_a_request_lapses_when_the_chat_moves_on(env, world, held):
    cid, _ = held
    env.client.post(f"/api/admin/conversations/{cid}/handover-request", headers=_as(world["ben"]))
    env.client.post(f"/api/admin/conversations/{cid}/release", headers=_as(world["ann"]))
    assert _row(env, world, cid)["handover_request"] is None
    # Nobody holds it now: pick it up instead of asking.
    r = env.client.post(f"/api/admin/conversations/{cid}/handover-request", headers=_as(world["ben"]))
    assert r.status_code == 400 and "pick it up" in r.json()["detail"]


def test_asking_for_your_own_chat_is_refused(env, world, held):
    cid, _ = held
    r = env.client.post(f"/api/admin/conversations/{cid}/handover-request", headers=_as(world["ann"]))
    assert r.status_code == 400
