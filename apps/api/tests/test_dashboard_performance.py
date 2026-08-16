"""The inbox got slow and hung on interaction (owner, 2026-08-13).

Two causes, both pinned here.

1. `messages.conversation_id` had NO index. Postgres does not index a foreign
   key automatically, and every OTHER table's conversation_id was indexed —
   messages, the largest and hottest table, was the single omission. So every
   inbox aggregate and, worse, every "open a chat" read sequentially scanned
   the whole messages table. That cost grows with every message the business
   ever exchanges: the classic "it used to be fine" curve.

2. The thread query was UNBOUNDED while the inbox renders every message it is
   given straight into the DOM (no virtualisation). A long-running customer
   meant thousands of nodes built in one synchronous pass — a frozen tab.
"""
import app.main  # noqa: F401 — registers all models
from app.models.message import Message


def test_messages_are_indexed_by_conversation_and_time():
    """The composite (not a bare conversation_id): the trailing created_at
    serves the ORDER BY and the MAX(created_at) grouping from the index, so
    neither needs a sort step."""
    idx = {i.name: [c.name for c in i.columns] for i in Message.__table__.indexes}
    assert "ix_messages_conversation_id_created_at" in idx, (
        "the dashboard's hottest access path must be indexed")
    assert idx["ix_messages_conversation_id_created_at"] == ["conversation_id", "created_at"]


def test_the_migration_creates_it_idempotently():
    """A box already hurting may have had the index added by hand; the
    migration must still apply cleanly there."""
    from pathlib import Path
    mig = Path(__file__).resolve().parents[1] / "alembic" / "versions"
    src = next(p for p in mig.glob("*messages_conversation_index*")).read_text()
    assert "CREATE INDEX IF NOT EXISTS" in src
    assert "(conversation_id, created_at)" in src
    assert "DROP INDEX IF EXISTS" in src          # reversible


def test_opening_a_chat_is_bounded():
    import inspect
    from app.routers import admin
    assert admin.THREAD_LIMIT == 500
    src = inspect.getsource(admin.get_thread)
    assert ".limit(THREAD_LIMIT)" in src
    # newest N, then flipped so the UI still reads oldest-first
    assert "Message.created_at.desc()" in src
    assert "list(reversed(" in src


def test_the_inbox_resolves_each_country_once():
    """_list_country parses a phone number when a row has no stored country,
    and it was being called twice per row — on every 60s poll."""
    import inspect
    from app.routers import admin
    src = inspect.getsource(admin.list_conversations)
    assert "country_map = {str(c.id): _list_country(c) for c in conversations}" in src
    assert src.count("_list_country(c)") == 1     # built once, read from the map
