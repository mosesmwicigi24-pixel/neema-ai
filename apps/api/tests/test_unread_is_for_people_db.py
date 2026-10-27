"""Unread means a PERSON owes the customer an answer (owner, 2026-10-27:
"apart from the messages that are in human, all these should be read").

A thread in Neema's hands is hers — she answers it, stays quiet on purpose
(a 👍, an "okay", spam), or hands it to a human, which moves it to Human and
back into Unread. Counting her deliberate silences made 1,516 threads look
neglected. Real Postgres through the real inbox routes; skips without one.
"""
import asyncio
from datetime import datetime, timedelta, timezone

from tests import test_calls_db as _calls, test_security_db as _sec
from tests.test_security_db import _as

fresh_db, world, env = _sec.fresh_db, _calls.world, _calls.env
pytestmark = _calls.pytestmark


def _thread(env, wa, mode, *, last="inbound"):
    """A WhatsApp thread in `mode` whose latest message is from `last`."""
    from app.models.conversation import InterceptMode
    from app.models.message import Message, MsgDirection, MsgSender
    from app.services.channel import get_or_create_conversation
    from app.services.identity import resolve_or_create_person

    async def go():
        async with env.maker() as db:
            ident = await resolve_or_create_person(db, "whatsapp", wa, display_name=f"C {wa[-3:]}")
            conv = await get_or_create_conversation(db, "whatsapp", wa,
                                                    person_id=ident.person_id, wa_id=wa)
            conv.intercept_mode = InterceptMode(mode)
            now = datetime.now(timezone.utc)
            rows = [(MsgDirection.outbound, MsgSender.ai, "Welcome to Bethany House", 30),
                    (MsgDirection.inbound, MsgSender.user, "👍", 20)]
            if last == "outbound":
                rows.append((MsgDirection.outbound, MsgSender.human_agent, "Noted, thank you", 10))
            for d, s, t, mins in rows:
                db.add(Message(channel="whatsapp", wa_id=wa, external_id=wa,
                               person_id=ident.person_id, conversation_id=conv.id,
                               direction=d, sender=s, text=t,
                               created_at=now - timedelta(minutes=mins)))
            conv.last_message_at = now
            await db.commit()
            return str(conv.id)
    return asyncio.run(go())


def test_only_threads_a_person_holds_are_unread(env, world):
    neemas = _thread(env, "254700000101", "ai")                    # she stayed quiet on a 👍
    human = _thread(env, "254700000102", "human")                  # a colleague owes an answer
    paused = _thread(env, "254700000103", "paused")                # paused: a person decides
    answered = _thread(env, "254700000104", "human", last="outbound")

    s = env.client.get("/api/admin/conversations/summary", headers=_as(world["ann"])).json()
    assert s["unread"] == 2
    assert s["unread_messages"]["whatsapp"] == 2

    unread = env.client.get("/api/admin/conversations?tab=unread&limit=50", headers=_as(world["ann"])).json()
    ids = {c["id"] for c in unread["items"]}
    assert ids == {human, paused}

    read = env.client.get("/api/admin/conversations?tab=read&limit=50", headers=_as(world["ann"])).json()
    assert {neemas, answered} <= {c["id"] for c in read["items"]}

    rows = {c["id"]: c for c in env.client.get("/api/admin/conversations?limit=50",
                                               headers=_as(world["ann"])).json()["items"]}
    assert rows[neemas]["unread"] == 0 and rows[human]["unread"] == 1
