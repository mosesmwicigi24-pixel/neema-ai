"""A thread carries ONE handoff briefing — the current one (owner, 2026-08-19).

John Nyaga's Messenger thread showed three internal notes stacked on top of
each other, all saying the same thing: black Round Collar Clergy Shirt, size
26, KES 3,000, Paybill shared, waiting on payment, he wants a photo. Each was
a full model turn, and together they pushed the actual conversation off the
screen — the agent had to scroll past three copies of the summary to reach the
customer.

They were not a race (the 15-minute re-click guard already handles that). They
were the normal cycle during the page-token outage: pick up → auto-release
after 45 idle minutes → flagged again → pick up again, each takeover minting a
fresh briefing hours apart.

Two rules now:
  * nothing new said since the last briefing → that briefing is still true;
    write nothing and spend nothing
  * a new briefing SUPERSEDES the old ones; a stale snapshot sitting beside a
    fresh one is worse than none, because the reader must work out which is
    which
"""
import asyncio
import types

import app.main  # noqa: F401 — registers models
import app.services.copilot as copilot
from app.models.message import Message


class _Res:
    def __init__(self, *, first=None, scalar=None, all_=None):
        self._first, self._scalar, self._all = first, scalar, all_ or []

    def scalars(self):
        return types.SimpleNamespace(first=lambda: self._first,
                                     all=lambda: list(self._all))

    def scalar(self):
        return self._scalar

    def scalar_one_or_none(self):
        return self._first


class _DB:
    """Answers execute() from a queue; overflow answers empty."""

    def __init__(self, results):
        self.results, self.added, self.deleted, self.commits = list(results), [], [], 0

    async def execute(self, *a, **k):
        return self.results.pop(0) if self.results else _Res()

    async def get(self, model, _id):
        return types.SimpleNamespace(id="c1", channel="messenger", wa_id=None,
                                     external_id="psid1", person_id=None)

    def add(self, row):
        self.added.append(row)

    async def delete(self, row):
        self.deleted.append(row)

    async def commit(self):
        self.commits += 1


class _Redis:
    def __init__(self):
        self.kv = {}

    async def set(self, k, v, nx=False, ex=None):
        if nx and k in self.kv:
            return None
        self.kv[k] = v
        return True

    def __getattr__(self, name):
        async def _noop(*a, **kw):
            return None
        return _noop


def _wire(monkeypatch, db, turns):
    import app.database as database
    import app.agent.runtime as runtime

    class _Sess:
        async def __aenter__(self):
            return db

        async def __aexit__(self, *a):
            return False
    monkeypatch.setattr(database, "AsyncSessionLocal", _Sess)

    async def _turn(*a, **kw):
        turns.append(1)
        return "- the sale stands at the Round Collar Clergy Shirt"
    monkeypatch.setattr(runtime, "run_turn", _turn)
    monkeypatch.setattr(runtime, "build_llm", lambda model=None: object())


def _note(text=None, at=None):
    from datetime import datetime, timezone
    return types.SimpleNamespace(
        id="m-old", media_type="note",
        text=text or f"{copilot.BRIEF_HEADING}\n\n- old", 
        created_at=at or datetime(2026, 8, 19, 6, 0, tzinfo=timezone.utc))


def _briefs(db):
    return [m for m in db.added if isinstance(m, Message)]


def test_a_second_takeover_with_nothing_new_writes_nothing(monkeypatch):
    """The customer has not spoken since the last briefing — it is still true.
    No note, and crucially no model turn."""
    db = _DB([_Res(first=_note()),          # the previous briefing
              _Res(scalar=0)])              # inbound messages newer than it
    turns = []
    _wire(monkeypatch, db, turns)
    asyncio.run(copilot._briefing(_Redis(), "c1"))
    assert turns == [], "a briefing was regenerated with nothing new to say"
    assert _briefs(db) == [] and db.deleted == []


def test_a_fresh_briefing_supersedes_the_stale_one(monkeypatch):
    """The customer HAS spoken since — brief again, and leave exactly one."""
    stale = _note()
    db = _DB([_Res(first=stale),            # the previous briefing
              _Res(scalar=2),               # two new customer messages since
              _Res(all_=[stale])])          # …which is then superseded
    turns = []
    _wire(monkeypatch, db, turns)
    asyncio.run(copilot._briefing(_Redis(), "c1"))
    assert len(turns) == 1
    rows = _briefs(db)
    assert len(rows) == 1 and rows[0].text.startswith(copilot.BRIEF_HEADING)
    assert db.deleted == [stale], "the old briefing was left in the thread"
    assert db.commits == 1


def test_the_first_ever_briefing_is_written_normally(monkeypatch):
    db = _DB([_Res(first=None)])            # no previous briefing at all
    turns = []
    _wire(monkeypatch, db, turns)
    asyncio.run(copilot._briefing(_Redis(), "c1"))
    assert len(turns) == 1 and len(_briefs(db)) == 1 and db.deleted == []


def test_the_reclick_guard_still_holds(monkeypatch):
    r = _Redis()
    turns = []
    _wire(monkeypatch, _DB([_Res(first=None)]), turns)
    asyncio.run(copilot._briefing(r, "c1"))
    _wire(monkeypatch, _DB([_Res(first=None)]), turns)
    asyncio.run(copilot._briefing(r, "c1"))
    assert len(turns) == 1, "the 15-minute re-click guard stopped holding"


# ── the thread shows the POST once, its comments under it ────────────────────
# Screen 3: Bartholomew Appiah commented twice on the same cassock reel, and
# the thread rendered the whole post card twice — poster, title, play button —
# with two short comments lost between them. Facebook shows the post once and
# the comments beneath it; so does the thread now.

def test_the_post_card_is_rendered_once_per_post_not_once_per_comment():
    import os
    view = os.path.join(os.path.dirname(__file__), "..", "..", "web", "src",
                        "components", "views", "ConversationsView.tsx")
    s = open(view, encoding="utf-8").read()
    assert "postHeadFor" in s
    assert 'heading="Your post — their comments below"' in s
    # our own public replies must not break the run
    assert "if (!c || c.reply_to) continue;" in s
    # exactly one place still renders the card: the group header
    assert s.count("<CommentContextCard") == 1
