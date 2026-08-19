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
    # The bound evolved (2026-08-19): the query limit is the requested PAGE
    # (default 50), clamped so THREAD_LIMIT stays the unbreakable ceiling.
    assert ".limit(page)" in src
    assert "min(int(limit or 50), THREAD_LIMIT)" in src
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


# ── Thread pagination (owner, 2026-08-19): "load latest 50 … until one scrolls
# past 50, you load the next 50 — keep the app light, not painting all the
# threads at one go." The 500-cap stopped the tab-freeze; paging in 50s makes
# the OPEN itself light, on every thread, every time.

def test_thread_serves_pages_of_fifty_newest_first():
    import inspect
    from app.routers import admin
    src = inspect.getsource(admin.get_thread)
    assert "limit: int = 50" in src                  # the owner's page size
    assert "before" in src and "_parse_before" in src
    assert "min(int(limit or 50), THREAD_LIMIT)" in src   # cap survives as ceiling


def test_older_pages_carry_messages_only():
    """Page one delivers the full event timeline; an older page must add
    messages alone, or every scroll-up would duplicate the event pills."""
    import inspect
    from app.routers import admin
    src = inspect.getsource(admin.get_thread)
    seg = src.split("if before_dt is not None:", 2)[-1]
    assert "_shape_messages_into" in seg.split("return thread", 1)[0]


def test_a_bad_cursor_degrades_to_first_page_never_a_500():
    from app.routers.admin import _parse_before
    assert _parse_before(None) is None
    assert _parse_before("") is None
    assert _parse_before("not-a-date") is None
    assert _parse_before("2026-08-19T07:00:00Z") is not None
    assert _parse_before("2026-08-19T07:00:00+00:00") is not None


def test_the_inbox_fetches_and_merges_pages_not_repaints():
    """Frontend contract, pinned at source (no component harness): opens ask
    for THREAD_PAGE, scrolling up asks `before` the oldest loaded message,
    silent refreshes MERGE so loaded pages survive the 20s poll, and the
    prepend pins the reader's scroll position."""
    import os
    view = os.path.join(os.path.dirname(__file__), "..", "..", "web", "src",
                        "components", "views", "ConversationsView.tsx")
    s = open(view, encoding="utf-8").read()
    assert "const THREAD_PAGE = 50" in s
    assert "function mergeThread(" in s
    assert "before: oldest.created_at" in s
    assert "silent ? mergeThread(" in s
    assert "el2.scrollHeight - prevH + prevTop" in s
    assert "holdAutoScroll" in s
