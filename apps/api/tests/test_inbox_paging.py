"""The inbox is paged by ROW — one per person — not by conversation.

The list used to return every conversation: 14,000 rows, 13 MB, rebuilt on a
60-second poll with a 30-second client timeout it could lose to. The inbox
collapses one person's WhatsApp, Messenger and Facebook threads into ONE row,
so paging raw conversations would put someone's WhatsApp thread on page 1 and
their Messenger thread on page 7 as a duplicate row. A page holds whole people.

SQL behaviour (ordering, continuity, completeness) was verified against
production: walking every page returned 12,241 rows, all distinct, equal to a
direct distinct count. These pin the pure pieces CI can run without Postgres.
"""
import asyncio
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.routers import admin


def test_a_cursor_round_trips_exactly():
    ts = datetime(2026, 9, 15, 10, 14, 3, 123456, tzinfo=timezone.utc)
    key = str(uuid.uuid4())

    assert admin._decode_cursor(admin._encode_cursor(ts, key)) == (ts, key)


def test_a_row_with_no_messages_pages_after_everything_else():
    # Eight live conversations have no messages; they sort as -infinity and
    # must still be reachable by the cursor rather than falling off the end.
    cur = admin._encode_cursor(None, "c:abc")

    assert admin._decode_cursor(cur) == ("-infinity", "c:abc")


def test_a_tampered_cursor_is_refused_not_trusted():
    for bad in ("", "not-base64!!", "W10", admin._encode_cursor(datetime.now(timezone.utc), "")):
        assert admin._decode_cursor(bad) is None


def test_the_cursor_is_opaque_to_the_client():
    # URL-safe, no padding — it rides in a query string untouched.
    cur = admin._encode_cursor(datetime.now(timezone.utc), "c:" + str(uuid.uuid4()))
    assert "=" not in cur and "+" not in cur and "/" not in cur


class _IdsDB:
    """Captures the conversation-id lookup a page expands into."""
    def __init__(self, ids):
        self.ids, self.stmt = ids, None

    async def execute(self, stmt):
        self.stmt = stmt
        return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: list(self.ids)))


def test_a_page_expands_to_every_thread_of_its_people():
    person = str(uuid.uuid4())
    solo = str(uuid.uuid4())
    db = _IdsDB(["wa-thread", "msg-thread", solo])

    ids = asyncio.run(admin._conversations_for_rows(db, [person, "c:" + solo]))

    assert ids == ["wa-thread", "msg-thread", solo]
    sql = str(db.stmt.compile(compile_kwargs={"literal_binds": True}))
    assert "person_id IN" in sql and person in sql      # all of that person's threads
    assert solo in sql                                  # the person-less conversation itself


def test_an_empty_page_asks_the_database_nothing():
    db = _IdsDB([])
    assert asyncio.run(admin._conversations_for_rows(db, [])) == []
    assert db.stmt is None


# ── filters are the browser's own definitions, now evaluated by the server ────
# Reconciled against production before merge: for All, Unread, Read, Human,
# Yours, each channel, AI mode, a tag, and Unread+WhatsApp, the people paged
# by the server were EXACTLY the people the browser showed from the full list
# (12,241 / 940 / 11,431 / 7 / 0 / ... — identical sets, zero duplicates).


def _sql(conds):
    from sqlalchemy import and_, select
    from app.models.conversation import Conversation
    return str(select(Conversation.id).where(and_(*conds)).compile(
        compile_kwargs={"literal_binds": True}))


def test_yours_means_human_held_by_me():
    me = uuid.uuid4()
    sql = _sql(admin._inbox_conditions(agent_id=me, tab="yours"))
    assert "intercept_mode" in sql and "assigned_agent_id" in sql
    assert str(me).replace("-", "") in sql.replace("-", "")


def test_unread_ignores_messages_that_belong_to_no_conversation():
    # Eight inbound messages carry no conversation; grouped, they made one
    # phantom "unread conversation" (943 vs the inbox's 942).
    sql = _sql(admin._inbox_conditions(agent_id=None, tab="unread"))
    assert "conversation_id IS NOT NULL" in sql


def test_search_reaches_phones_and_what_was_said():
    # The browser matched only the name and the latest preview, so a phone
    # number found nothing. The server searches every conversation.
    sql = _sql(admin._inbox_conditions(agent_id=None, q="0722"))
    assert "wa_id" in sql and "external_id" in sql
    assert "messages.text" in sql and "display_name" in sql


def test_an_unknown_tab_or_mode_is_a_400_not_an_empty_inbox():
    with pytest.raises(HTTPException) as e:
        admin._inbox_conditions(agent_id=None, tab="everything")
    assert e.value.status_code == 400
    with pytest.raises(HTTPException) as e:
        admin._inbox_conditions(agent_id=None, mode="robot")
    assert e.value.status_code == 400


def test_all_and_blank_filters_add_no_conditions():
    assert admin._inbox_conditions(agent_id=None) == []
    assert admin._inbox_conditions(agent_id=None, tab="all", channel="all", mode="all", q="  ") == []


def test_a_page_size_outside_1_to_200_is_refused():
    for bad in (0, 201):
        with pytest.raises(HTTPException) as e:
            asyncio.run(admin.list_conversations(limit=bad, db=None, agent=None))
        assert e.value.status_code == 400


def test_the_summary_and_id_routes_cannot_swallow_each_other():
    # /conversations/summary must be registered before /conversations/{conv_id},
    # or "summary" is parsed as a UUID and 422s.
    paths = [r.path for r in admin.router.routes]
    assert paths.index("/conversations/summary") < paths.index("/conversations/{conv_id}")
    assert paths.index("/conversations/resolve") < paths.index("/conversations/{conv_id}")
