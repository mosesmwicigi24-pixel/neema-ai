"""Who owes a comment a reply is written on the comment (services/
comment_ledger) — proved here on a real Postgres, where the JSONB reads and
writes actually run. The handler-level behaviour is in test_comment_catchup.

The two cases the third review asked for, at the level of the record:
a comment saved and never handled is still found as owed with no Redis at
all; and the staff follow-up is rewritten when a day runs out.
"""
import asyncio
import types
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import sqlalchemy as sa

from tests.test_security_db import _reachable, _sync_url, fresh_db  # noqa: F401

pytestmark = pytest.mark.skipif(not _sync_url() or not _reachable(_sync_url()),
                                reason="needs a reachable Postgres (CI migrations job / Docker harness)")

CH, EXT = "facebook", "u-77"


@pytest.fixture
def rig(fresh_db, monkeypatch):  # noqa: F811
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool
    import app.database as dbmod
    eng = sa.create_engine(fresh_db)
    with eng.begin() as c:
        c.execute(sa.text("TRUNCATE intercepts, messages, conversations CASCADE"))
    eng.dispose()
    url = fresh_db.replace("postgresql+psycopg2://", "postgresql+asyncpg://")
    maker = async_sessionmaker(create_async_engine(url, poolclass=NullPool),
                               class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(dbmod, "AsyncSessionLocal", maker)

    async def conv():
        from app.models.conversation import Conversation
        async with maker() as db:
            c = Conversation(id=uuid.uuid4(), wa_id=None, channel=CH, external_id=EXT)
            db.add(c)
            await db.commit()
            return c.id
    return types.SimpleNamespace(maker=maker, conv_id=asyncio.run(conv()))


def _comment(rig, cid, text, *, post="p1", minutes_ago=0, stamped=True, sender="user", reply_to=None,
             context=True, meta=None):
    """A row as the webhook saves an inbound comment (or one of our replies)."""
    from app.models.message import Message, MsgDirection, MsgSender
    from app.services import comment_ledger as ledger

    async def go():
        async with rig.maker() as db:
            inbound = sender == "user"
            db.add(Message(
                channel=CH, external_id=EXT, wa_id=None, conversation_id=rig.conv_id,
                direction=MsgDirection.inbound if inbound else MsgDirection.outbound,
                sender=MsgSender(sender), text=text,
                waba_msg_id=cid if inbound else None,
                raw_meta=({"v": 1, ledger.KEY: ledger.opening({"PAGE"}, "PAGE", None, post)}
                          if inbound and stamped else meta),
                comment_context=(({"post_id": post, "caption": "Cassock set"} if context else None)
                                 if inbound else {"reply_to": reply_to}),
                created_at=datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)))
            await db.commit()
    asyncio.run(go())


def test_a_saved_comment_is_owed_on_the_record_before_any_handler_runs(rig):
    from app.services import comment_ledger as ledger
    _comment(rig, "c1", "How much is the cassock?", minutes_ago=20)       # saved … and the process restarts
    assert asyncio.run(ledger.keys_owed()) == [(CH, EXT, "p1")]           # found with no Redis at all
    rows = asyncio.run(ledger.unresolved(CH, EXT, "p1"))
    assert [(r["cid"], r["state"], r["decided"], r["text"]) for r in rows] == [
        ("c1", ledger.OWED, False, "How much is the cassock?")]
    assert rows[0]["own_pages"] == ["PAGE"] and rows[0]["page_id"] == "PAGE" and rows[0]["post_id"] == "p1"
    assert rows[0]["post_context"]["caption"] == "Cassock set"
    assert 19 * 60 < (datetime.now(timezone.utc).timestamp() - rows[0]["at"]) < 21 * 60


def test_the_state_moves_only_by_a_recorded_decision(rig):
    from app.services import comment_ledger as ledger
    _comment(rig, "c1", "How much?", minutes_ago=5)
    _comment(rig, "c2", "Do you deliver?", minutes_ago=4)
    _comment(rig, "x1", "Chalice?", post="p2", minutes_ago=3)
    _comment(rig, "old", "from before the state existed", minutes_ago=2, stamped=False)
    go = asyncio.run
    assert go(ledger.mark(CH, EXT, ["c1"], decided=True, reason="model")) == 1
    assert go(ledger.mark(CH, EXT, ["c1"], only_undecided=True, state=ledger.RESOLVED)) == 0   # decided: left
    assert go(ledger.mark(CH, EXT, ["c2"], only_undecided=True, state=ledger.RESOLVED, by="handled")) == 1
    assert go(ledger.mark(CH, EXT, ["old"], state=ledger.STAFF)) == 0          # no state: not invented
    assert go(ledger.mark(CH, EXT, ["old"], create=True, state=ledger.STAFF, decided=True)) == 1
    assert [r["cid"] for r in go(ledger.unresolved(CH, EXT, "p1"))] == ["c1", "old"]
    assert [r["cid"] for r in go(ledger.unresolved(CH, EXT, "p2"))] == ["x1"]      # another post, untouched
    assert sorted(go(ledger.keys_owed())) == [(CH, EXT, "p1"), (CH, EXT, "p2")]
    go(ledger.mark(CH, EXT, ["c1"], state=ledger.VERIFY, why="check the thread"))
    st = go(ledger.state_of(CH, EXT, "c1"))
    assert st["state"] == ledger.VERIFY and st["why"] == "check the thread" and st["reason"] == "model"
    assert go(ledger.keys_owed()) == [(CH, EXT, "p2")]                            # verify is not "owed"
    assert go(ledger.state_of(CH, EXT, "nope")) is None
    assert go(ledger.existing(CH, EXT, ["c1", "c2", "gone"])) == {"c1", "c2"}


def test_a_reply_is_found_under_the_comment_it_answered(rig):
    from app.services import comment_ledger as ledger
    _comment(rig, "c1", "How much?")
    _comment(rig, "c2", "Do you deliver?")
    _comment(rig, None, "It is KES 45,000.", sender="human_agent", reply_to="c1")
    _comment(rig, None, "Yes, by DHL.", sender="ai", reply_to="c2")
    go = asyncio.run
    assert go(ledger.replied_ids(CH, EXT, ["c1", "c2"], staff_only=True)) == {"c1"}
    assert go(ledger.replied_ids(CH, EXT, ["c1", "c2"])) == {"c1", "c2"}


def test_one_follow_up_is_written_rewritten_and_closed_from_the_record(rig):
    from app.models.intercept import Intercept
    from app.services import comment_catchup as cc, comment_ledger as ledger
    key = cc.key_of(CH, "p1", EXT)
    _comment(rig, "c1", "How much is the cassock?", minutes_ago=5)
    _comment(rig, "c2", "Do you deliver to Tarime?", minutes_ago=4)
    go = asyncio.run
    go(ledger.mark(CH, EXT, ["c1", "c2"], decided=True, reason="model"))

    def notes():
        async def read():
            async with rig.maker() as db:
                return [r.note for r in (await db.execute(sa.select(Intercept).where(
                    Intercept.conversation_id == rig.conv_id))).scalars().all()]
        return go(read())

    assert go(cc.refresh_followup(None, key)) == "new"
    assert len(notes()) == 1 and "WAITING FOR AN ANSWER (2)" in notes()[0] and "Neema will answer" in notes()[0]
    assert go(ledger.followup_id(CH, EXT, "p1"))                               # its id is on the comment
    # a day runs out with no Redis anywhere: the question moves to staff, in the same follow-up
    go(cc.hand_to_staff(None, key, "more than a day has passed"))
    assert go(cc.refresh_followup(None, key, ring=True)) == "updated"
    assert len(notes()) == 1 and "will NOT answer" in notes()[0] and "more than a day has passed" in notes()[0]
    assert "1. How much is the cassock?" in notes()[0] and "2. Do you deliver to Tarime?" in notes()[0]
    assert go(ledger.keys_owed()) == []                                        # Neema owes nothing more here
    # a colleague replies under c1: only c1 is resolved; then c2; then the follow-up closes
    assert go(cc.staff_replied(None, CH, EXT, "c1")) is True
    assert "(1)" in notes()[0] and "How much is the cassock?" not in notes()[0]
    assert go(cc.staff_replied(None, CH, EXT, "c2")) is True
    assert len(notes()) == 1 and "answered" in notes()[0]
    assert go(cc.waiting(None, key)) == []


def test_a_comment_whose_post_lookup_failed_is_still_found_after_a_restart(rig):
    from app.services import comment_ledger as ledger
    # the webhook saved it with no enriched post context … and the process restarted
    _comment(rig, "c1", "How much is the cassock?", minutes_ago=20, context=False)
    go = asyncio.run
    assert go(ledger.keys_owed()) == [(CH, EXT, "p1")]                    # by the webhook's own post id
    rows = go(ledger.unresolved(CH, EXT, "p1"))
    assert [(r["cid"], r["state"], r["post_id"], r["post_context"]) for r in rows] == [
        ("c1", ledger.OWED, "p1", {})]
    # a row from before the post id was stamped is still found by its context
    from app.models.message import Message

    async def strip():
        async with rig.maker() as db:
            _comment_ctx = (await db.execute(sa.select(Message).where(Message.waba_msg_id == "c1"))).scalar_one()
            meta = dict(_comment_ctx.raw_meta)
            meta[ledger.KEY] = {k: v for k, v in meta[ledger.KEY].items() if k != "post_id"}
            _comment_ctx.raw_meta = meta
            _comment_ctx.comment_context = {"post_id": "p1"}
            await db.commit()
    go(strip())
    assert go(ledger.keys_owed()) == [(CH, EXT, "p1")]
    assert [r["cid"] for r in go(ledger.unresolved(CH, EXT, "p1"))] == ["c1"]


def test_a_reply_whose_delivery_is_unknown_does_not_count_as_a_reply(rig):
    from app.services import comment_ledger as ledger
    _comment(rig, "c1", "How much?")
    _comment(rig, None, "It is KES 45,000.", sender="ai", reply_to="c1", meta={"v": 1, "delivery": "unknown"})
    assert asyncio.run(ledger.replied_ids(CH, EXT, ["c1"])) == set()
    _comment(rig, None, "It is KES 45,000.", sender="ai", reply_to="c1")
    assert asyncio.run(ledger.replied_ids(CH, EXT, ["c1"])) == {"c1"}


def test_a_backlog_from_the_old_queue_lands_on_the_rows(rig):
    import json
    import time
    from app.services import comment_catchup as cc, comment_ledger as ledger
    _comment(rig, "c1", "How much is the cassock?", minutes_ago=30, stamped=False)
    _comment(rig, "c2", "Can I pay later?", minutes_ago=29, stamped=False)
    key = cc.key_of(CH, "p1", EXT)

    class R:
        kv, lists, sets = {}, {}, {"comment:catchup:index": {key}}

        async def smembers(self, k):
            return set(self.sets.get(k, set()))

        async def get(self, k):
            return self.kv.get(k)

        async def lrange(self, k, a, b):
            return list(self.lists.get(k, []))

        async def delete(self, *ks):
            for k in ks:
                self.kv.pop(k, None)
                self.lists.pop(k, None)

        async def srem(self, k, v):
            self.sets.get(k, set()).discard(v)
    r = R()
    r.lists["comment:catchup:q:" + key] = [
        json.dumps({"at": time.time() - 1800, "cid": "c1", "reason": "model", "own_pages": ["PAGE"],
                    "post_id": "p1", "page_id": "PAGE", "parent_id": None}),
        json.dumps({"at": time.time() - 1700, "cid": "c2", "reason": "cap", "own_pages": ["PAGE"],
                    "post_id": "p1", "page_id": "PAGE", "parent_id": None}),
        json.dumps({"at": time.time() - 1600, "cid": "deleted-since", "reason": "model"})]
    go = asyncio.run
    assert go(cc.adopt_old_queue(r)) == 2                                  # the deleted one is not invented
    rows = {x["cid"]: x for x in go(ledger.unresolved(CH, EXT, "p1"))}
    assert rows["c1"]["state"] == ledger.OWED and rows["c1"]["decided"] and rows["c1"]["own_pages"] == ["PAGE"]
    assert rows["c2"]["state"] == ledger.STAFF and "limit" in rows["c2"]["why"]
    assert go(ledger.keys_owed()) == [(CH, EXT, "p1")]
    assert r.lists == {} and r.sets["comment:catchup:index"] == set()
    assert go(cc.adopt_old_queue(r)) == 0
