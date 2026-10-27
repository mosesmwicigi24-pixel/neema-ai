"""The WhatsApp template fits the conversation it lands in (owner, 2026-10-27).

Prof Irungu was mid-chat on WhatsApp, 18 hours of the reply window left, when
"Send template" delivered "We saw your message on Facebook/Messenger. May we
continue here on WhatsApp…" — canned words, and untrue. Real Postgres through
the real admin route, Meta faked; skips cleanly without a database.
"""
import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from tests import test_calls_db as _calls, test_security_db as _sec
from tests.test_security_db import _as

fresh_db, world, env = _sec.fresh_db, _calls.world, _calls.env
pytestmark = _calls.pytestmark


@pytest.fixture
def sent(env, monkeypatch):
    from app.core.config import settings
    from app.services import n8n_bridge
    monkeypatch.setattr(settings, "waba_token", "t", raising=False)
    monkeypatch.setattr(settings, "waba_phone_number_id", "PNID", raising=False)
    monkeypatch.setattr(settings, "wa_followup_template", "", raising=False)
    out = []

    async def fake_send(wa_id, name, lang, body_params=None, **kw):
        out.append((wa_id, name, tuple(body_params or ())))
        return {}
    monkeypatch.setattr(n8n_bridge, "send_wa_template", fake_send)
    return out


def _customer(env, wa, *, wrote_hours_ago=None, also_on=None, name="Ben Irungu"):
    """A WhatsApp customer: a thread (and a message from them `wrote_hours_ago`
    hours ago), optionally the same person on another channel."""
    from app.models.message import Message, MsgDirection, MsgSender
    from app.services.channel import get_or_create_conversation
    from app.services.identity import resolve_or_create_person

    async def go():
        async with env.maker() as db:
            ident = await resolve_or_create_person(db, "whatsapp", wa, display_name=name)
            conv = await get_or_create_conversation(db, "whatsapp", wa,
                                                    person_id=ident.person_id, wa_id=wa)
            if wrote_hours_ago is not None:
                db.add(Message(channel="whatsapp", wa_id=wa, external_id=wa,
                               person_id=ident.person_id, conversation_id=conv.id,
                               direction=MsgDirection.inbound, sender=MsgSender.user,
                               text="I want to do 52 stoles",
                               created_at=datetime.now(timezone.utc) - timedelta(hours=wrote_hours_ago)))
            if also_on:
                from app.models.person import Identity
                db.add(Identity(channel=also_on, external_id=f"psid-{wa}", person_id=ident.person_id))
            await db.commit()
    asyncio.run(go())


def _invite(env, who, wa, name="Ben Irungu"):
    return env.client.post("/api/admin/whatsapp-invite", json={"phone": wa, "name": name},
                           headers=_as(who))


def test_an_open_chat_is_answered_with_a_reply_never_a_template(env, world, sent):
    _customer(env, "254705087768", wrote_hours_ago=5)
    r = _invite(env, world["ann"], "254705087768")
    assert r.status_code == 409 and "just type your reply" in r.json()["detail"]
    assert sent == []


def test_someone_who_wrote_on_whatsapp_never_hears_we_saw_you_on_messenger(env, world, sent, monkeypatch):
    _customer(env, "254705087769", wrote_hours_ago=30)
    r = _invite(env, world["ann"], "254705087769")
    assert r.status_code == 409 and "WA_FOLLOWUP_TEMPLATE" in r.json()["detail"]
    assert sent == []
    # With the follow-up template approved and set, that is what goes.
    from app.core.config import settings
    monkeypatch.setattr(settings, "wa_followup_template", "follow_up", raising=False)
    r = _invite(env, world["ann"], "254705087769")
    assert r.status_code == 200, r.text
    assert sent == [("254705087769", "follow_up", ("Ben",))]
    _assert_signed(env, "254705087769", world["ann"], "following up on your enquiry")


def test_a_caller_who_never_messaged_gets_the_follow_up_not_the_invite(env, world, sent):
    _customer(env, "254705087770")                      # called us: identity, no message
    r = _invite(env, world["ann"], "254705087770")
    assert r.status_code == 409 and "not Messenger" in r.json()["detail"]
    assert sent == []


def test_someone_who_came_from_messenger_gets_the_invite_and_it_is_signed(env, world, sent):
    _customer(env, "254705087771", also_on="messenger")
    r = _invite(env, world["ann"], "254705087771")
    assert r.status_code == 200, r.text
    assert sent == [("254705087771", "whatsapp_invite", ("Ben",))]
    _assert_signed(env, "254705087771", world["ann"], "We saw your message on")


def test_a_number_we_have_never_seen_gets_the_invite(env, world, sent):
    r = _invite(env, world["ann"], "254705087772")
    assert r.status_code == 200, r.text
    assert sent and sent[0][1] == "whatsapp_invite"


def _assert_signed(env, wa, who, text):
    """The recorded template names the colleague who sent it (no anonymous
    "AGENT" bubble)."""
    import sqlalchemy as sa
    eng = sa.create_engine(env.db_url)
    with eng.begin() as c:
        row = c.execute(sa.text(
            "SELECT text, agent_id FROM messages WHERE wa_id = :wa AND direction = 'outbound' "
            "ORDER BY created_at DESC LIMIT 1"), {"wa": wa}).first()
    eng.dispose()
    assert row is not None and text in row[0] and str(row[1]) == str(who)
