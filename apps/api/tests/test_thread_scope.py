"""A comment thread is the POST's thread (owner, 2026-09-23).

Live: under a ring post, Mkhulu asked "How much is it?" and was quoted the
ring in dollars; Daniel replied inside that thread "In Kenya shillings" and
was answered "KES 19,000 for the full set — cassock, shirt, collar, stole and
belt". The cassock came from Daniel's OWN earlier comments under a cassock-set
post: a comment conversation is one per person per channel across every post,
so the ring turn read his cassock exchange as its transcript, and the webhook
dropped the parent comment, so nothing said he was answering Mkhulu's ring
quote. These tests pin the four legs of the fix:

1. the transcript of a public-comment turn is THIS post's thread only;
2. a reply inside a thread carries the comment it answers and our reply;
3. the webhook keeps `parent_id` (and never mistakes the post for a parent);
4. the caption scorer runs inside the ladder, so "Premium Bishop's Ring" is
   the hub's "Ring" before any model reads the post — and a model's lead on
   record is re-read by the ladder once an hour, not kept for 30 days.
"""
import asyncio
import inspect
import json
import types
from datetime import datetime, timedelta, timezone

import app.main  # noqa: F401  (settings, models)
from app.agent import runtime as rt
from app.models.message import MsgDirection, MsgSender
from app.routers import meta_webhook as mw
from app.services import post_catalog as pc


# ── fixtures ────────────────────────────────────────────────────────────────

def _row(text, direction, minutes_ago, *, post_id=None, comment_id=None,
         reply_to=None, sender=None):
    ctx = None
    if post_id is not None:
        ctx = {"post_id": post_id, "title": "…"}
    if reply_to is not None:
        ctx = {"reply_to": reply_to}
    return types.SimpleNamespace(
        text=text, direction=direction,
        sender=sender or (MsgSender.user if direction == MsgDirection.inbound else MsgSender.ai),
        media_type=None, waba_msg_id=comment_id, comment_context=ctx,
        created_at=datetime.now(timezone.utc) - timedelta(minutes=minutes_ago))


def _fake_db(rows):
    class _Res:
        def scalars(self):
            # _history reverses a DESC fetch — hand rows back newest-first
            return types.SimpleNamespace(all=lambda: list(reversed(rows)))

    class _DB:
        async def execute(self, *a, **k):
            return _Res()
    return _DB()


# Daniel's inbox on Facebook: yesterday the cassock set under post P-CASSOCK,
# today "In Kenya shillings" under the ring post P-RING.
DANIEL = [
    _row("How much is the full set?", MsgDirection.inbound, 1500,
         post_id="P-CASSOCK", comment_id="c-set-1"),
    _row("The Classic Princes Cassock Set is $190 — cassock, shirt, collar, "
         "stole and belt, everything included.", MsgDirection.outbound, 1490,
         reply_to="c-set-1"),
    _row("I want it in red and white", MsgDirection.inbound, 1480,
         post_id="P-CASSOCK", comment_id="c-set-2"),
    _row("Red and white it is. Would you like the cincture belt in that same "
         "red and white?", MsgDirection.outbound, 1470, reply_to="c-set-2"),
    _row("In Kenya shillings", MsgDirection.inbound, 2,
         post_id="P-RING", comment_id="c-ring-9"),
]

RING = {"name": "Ring", "slug": "bishops-ring", "price": 1500, "price_usd": 20,
        "aliases": [], "images": [{"url": "https://hub/x/ring.webp"}],
        "description": "Bishop's ring", "product_type": "simple", "hub_product_id": 71}
APOSTOLIC = {"name": "Apostolic Ring", "slug": "apostolic-ring", "price": 3500,
             "price_usd": 40, "aliases": [], "images": [{"url": "https://hub/x/ring.webp"}],
             "description": "Gold ring with a deep red stone", "product_type": "simple",
             "hub_product_id": 72}
CASSOCK_SET = {"name": "Classic Princes Cassock Set", "slug": "clergy-cassock",
               "price": 19000, "price_usd": 190, "aliases": [], "images": [],
               "description": "Cassock, shirt, collar, stole and belt",
               "product_type": "variable", "hub_product_id": 73}
CATALOG = [RING, APOSTOLIC, CASSOCK_SET]


# ── 1. the transcript is THIS post's thread only ────────────────────────────

def test_thread_rows_keep_only_this_posts_comments_and_our_replies_to_them():
    kept = rt._thread_rows(DANIEL, "P-RING")
    assert [m.text for m in kept] == ["In Kenya shillings"]
    kept = rt._thread_rows(DANIEL, "P-CASSOCK")
    assert [m.text[:12] for m in kept] == ["How much is ", "The Classic ",
                                           "I want it in", "Red and whit"]


def test_thread_rows_without_a_post_keep_everything():
    """DMs and anything without a post id are untouched."""
    assert rt._thread_rows(DANIEL, "") is DANIEL
    assert rt._thread_rows(DANIEL, None) is DANIEL


def test_thread_rows_drop_rows_with_no_post_attribution():
    """A row from before attribution existed is left out — safer than
    guessing which post it belonged to."""
    rows = [
        types.SimpleNamespace(text="Hi", direction=MsgDirection.inbound, sender=MsgSender.user,
                              media_type=None),  # no comment_context, no waba_msg_id
        types.SimpleNamespace(text="Hello!", direction=MsgDirection.outbound, sender=MsgSender.ai,
                              media_type=None, comment_context=None, waba_msg_id=None),
        DANIEL[-1],
    ]
    assert [m.text for m in rt._thread_rows(rows, "P-RING")] == ["In Kenya shillings"]


def test_history_under_the_ring_post_never_carries_the_cassock_exchange():
    h = asyncio.run(rt._history(_fake_db(DANIEL), "FB-DANIEL", limit=14,
                                channel="facebook", post_id="P-RING"))
    assert h == [{"role": "user", "content": "In Kenya shillings"}]
    joined = json.dumps(h).lower()
    assert "cassock" not in joined and "stole" not in joined and "belt" not in joined


def test_history_under_the_cassock_post_still_reads_that_thread():
    h = asyncio.run(rt._history(_fake_db(DANIEL), "FB-DANIEL", limit=14,
                                channel="facebook", post_id="P-CASSOCK"))
    assert [t["role"] for t in h] == ["user", "assistant", "user", "assistant"]
    assert "cincture belt" in h[-1]["content"]
    assert not any("Kenya shillings" in t["content"] for t in h)


def test_history_without_a_post_is_the_unchanged_dm_window():
    h = asyncio.run(rt._history(_fake_db(DANIEL), "FB-DANIEL", limit=40, channel="facebook"))
    assert len(h) == 5 and h[-1]["content"] == "In Kenya shillings"


def test_history_fetches_wider_when_scoped_then_keeps_the_threads_last_turns():
    """The thread is filtered AFTER a wider fetch, so a busy commenter's
    other posts cannot crowd this post's own turns out of the window."""
    src = inspect.getsource(rt._history)
    assert "fetch = max(limit * 4, 60) if post_id else limit" in src
    assert "rows = _thread_rows(rows, post_id)[-limit:]" in src


def test_run_turn_scopes_the_transcript_to_the_comments_post():
    src = inspect.getsource(rt.run_turn)
    assert "post_id=(comment_post_id if public_comment else None)" in src
    assert "_cross_channel_context(db, key, channel, public_comment=public_comment)" in src
    assert "if public_comment and thread_parent:" in src
    assert "lead_ctx.append(_thread_parent_context(thread_parent))" in src


def test_cross_channel_lines_under_a_comment_say_who_never_what():
    src = inspect.getsource(rt._cross_channel_context)
    assert "The product of THIS comment is the POST's" in src
    assert "if public_comment:" in src


# ── 2. a reply inside a thread carries the comment it answers ───────────────

def test_thread_parent_context_quotes_the_parent_and_our_answer():
    line = rt._thread_parent_context({
        "text": "How much is it?", "by": "Mkhulu",
        "our_reply": "Welcome, Mkhulu! This is our Ring — it's $20, made in Nairobi."})
    assert line.startswith('(This comment is a REPLY inside a thread, under Mkhulu\'s comment '
                           '"How much is it?"')
    assert 'which we answered: "Welcome, Mkhulu! This is our Ring — it\'s $20' in line
    assert "SAME item re-priced in KES" in line
    assert "search_catalog it with currency KES" in line
    assert "The post's product stays what it is." in line


def test_thread_parent_context_is_empty_without_a_parent():
    assert rt._thread_parent_context(None) == ""
    assert rt._thread_parent_context({}) == ""
    assert rt._thread_parent_context({"text": "   ", "by": "X"}) == ""
    # a parent we never answered still names who and what
    line = rt._thread_parent_context({"text": "Nice ring", "by": ""})
    assert "under another commenter's comment \"Nice ring\"" in line
    assert "which we answered" not in line


def test_thread_parent_reads_the_parent_and_our_reply_from_the_inbox(monkeypatch):
    parent = types.SimpleNamespace(text="How much is it?", name="Mkhulu")
    ours = types.SimpleNamespace(text="This is our Ring — it's $20.")
    results = [parent, ours]

    class _Res:
        def __init__(self, row):
            self._row = row

        def scalars(self):
            return types.SimpleNamespace(first=lambda: self._row)

    class _DB:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def execute(self, stmt):
            return _Res(results.pop(0))

    monkeypatch.setattr("app.database.AsyncSessionLocal", lambda: _DB())
    got = asyncio.run(rt._thread_parent("c-mkhulu-1"))
    assert got == {"text": "How much is it?", "by": "Mkhulu",
                   "our_reply": "This is our Ring — it's $20."}


def test_thread_parent_is_empty_for_a_top_level_comment_or_an_unknown_one(monkeypatch):
    hits = []
    monkeypatch.setattr("app.database.AsyncSessionLocal",
                        lambda: hits.append(1) or (_ for _ in ()).throw(RuntimeError("no db")))
    assert asyncio.run(rt._thread_parent("")) == {}
    assert asyncio.run(rt._thread_parent(None)) == {}
    assert hits == []                     # no DB touched without a parent id
    # an unknown parent (DB error included) is {} — never a failed reply
    assert asyncio.run(rt._thread_parent("c-unknown")) == {}


def test_the_engine_hands_run_turn_the_post_and_the_parent():
    src = inspect.getsource(rt._run_comment_engage)
    assert '_parent = await _thread_parent(comment.get("parent_id") or "")' in src
    assert "comment_reading=reading, comment_post_id=post_id," in src
    assert "thread_parent=_parent" in src


# ── 3. the webhook keeps the parent comment ─────────────────────────────────

def test_parse_comment_keeps_the_parent_of_a_reply_and_none_for_a_top_level():
    top = mw._parse_comment({"field": "feed", "value": {
        "item": "comment", "verb": "add", "comment_id": "c-mkhulu-1",
        "message": "How much is it?", "from": {"id": "U1", "name": "Mkhulu"},
        "post_id": "PAGE_P9", "parent_id": "PAGE_P9"}})
    assert top["post_id"] == "PAGE_P9" and top["parent_id"] == ""

    reply = mw._parse_comment({"field": "feed", "value": {
        "item": "comment", "verb": "add", "comment_id": "c-daniel-2",
        "message": "In Kenya shillings", "from": {"id": "U2", "name": "Daniel Otieno"},
        "post_id": "PAGE_P9", "parent_id": "c-mkhulu-1"}})
    assert reply["post_id"] == "PAGE_P9" and reply["parent_id"] == "c-mkhulu-1"

    # no parent at all → ""
    bare = mw._parse_comment({"field": "feed", "value": {
        "item": "comment", "verb": "add", "comment_id": "c3", "message": "Hi",
        "from": {"id": "U3"}, "post_id": "PAGE_P9"}})
    assert bare["parent_id"] == "" and bare["post_id"] == "PAGE_P9"

    ig = mw._parse_comment({"field": "comments", "value": {
        "id": "ig2", "text": "In KES?", "from": {"id": "IG2", "username": "dan"},
        "media": {"id": "M1"}, "parent_id": "ig1"}})
    assert ig["post_id"] == "M1" and ig["parent_id"] == "ig1"
    ig_top = mw._parse_comment({"field": "comments", "value": {
        "id": "ig1", "text": "Price?", "from": {"id": "IG1", "username": "jane"},
        "media": {"id": "M1"}}})
    assert ig_top["parent_id"] == ""


# ── 4. the caption scorer runs INSIDE the ladder; a lead is re-read ─────────

def _offline_ladder(monkeypatch):
    async def none(*a, **k):
        return None
    monkeypatch.setattr(pc, "product_from_image", none)
    monkeypatch.setattr(pc, "product_from_vision", none)


def test_premium_bishops_ring_caption_is_the_hubs_ring_by_the_ladder(monkeypatch):
    _offline_ladder(monkeypatch)
    hit = asyncio.run(pc.resolve_post(None, {
        "post_id": "P-RING",
        "title": "We have beautiful Premium Bishop's Ring. We have the ring with green, "
                 "Red, Golden Yellow, Purple and Blue stone.",
        "thumb": ""}, CATALOG))
    assert hit is not None and hit["name"] == "Ring" and hit["slug"] == "bishops-ring"
    assert hit["_identity_source"] == "caption"
    assert pc.identity_trusted({"name": hit["name"], "source": hit["_identity_source"],
                                "confidence": hit["_identity_confidence"]})


def test_an_apostolic_ring_caption_stays_the_apostolic_ring(monkeypatch):
    _offline_ladder(monkeypatch)
    hit = asyncio.run(pc.resolve_post(None, {
        "post_id": "P-AR", "title": "Apostolic Ring — gold with a deep red stone",
        "thumb": ""}, CATALOG))
    assert hit is not None and hit["name"] == "Apostolic Ring"
    assert hit["_identity_source"] == "caption"


def test_a_caption_naming_nothing_still_falls_through_to_the_photo(monkeypatch):
    _offline_ladder(monkeypatch)
    hit = asyncio.run(pc.resolve_post(None, {
        "post_id": "P-X", "title": "New arrivals this week 🙏", "thumb": ""}, CATALOG))
    assert hit is None


class _Redis:
    def __init__(self, store=None):
        self.store = dict(store or {})

    async def get(self, k):
        return self.store.get(k)

    async def set(self, k, v, nx=False, ex=None):
        if nx and k in self.store:
            return False
        self.store[k] = v
        return True

    async def delete(self, k):
        self.store.pop(k, None)


class _NullDB:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


def _wire_ladder(monkeypatch, hit, calls):
    monkeypatch.setattr("app.database.AsyncSessionLocal", lambda: _NullDB())

    async def items(db, redis):
        return CATALOG
    monkeypatch.setattr("app.services.n8n_bridge.catalog_items", items)

    async def resolve(redis, pctx, catalog):
        calls.append(pctx.get("post_id"))
        return hit
    monkeypatch.setattr(pc, "resolve_post", resolve)

    async def no_look(thumb):
        return ""
    monkeypatch.setattr(rt, "_describe_post_image", no_look)


def test_a_models_lead_on_record_is_replaced_by_the_ladders_trusted_read(monkeypatch):
    """The ring post carried the model's "Apostolic Ring"; the ladder now
    re-reads the caption and the hub's "Ring" replaces it."""
    calls = []
    _wire_ladder(monkeypatch, pc.with_provenance(RING, "caption"), calls)
    key = rt._post_product_key("facebook", "P-RING")
    r = _Redis({key: json.dumps({"name": "Apostolic Ring", "slug": "apostolic-ring",
                                 "source": "model", "confidence": 0.6})})
    pctx = {"post_id": "P-RING", "title": "We have beautiful Premium Bishop's Ring", "thumb": ""}
    got = asyncio.run(rt._post_identity(r, "facebook", pctx))
    assert got["name"] == "Ring" and got["source"] == "caption"
    assert calls == ["P-RING"]
    assert json.loads(r.store[key])["name"] == "Ring"
    # the retry is once an hour per post: the next turn does not re-run the ladder
    got2 = asyncio.run(rt._post_identity(r, "facebook", pctx))
    assert got2["name"] == "Ring" and calls == ["P-RING"]


def test_a_lead_stays_a_lead_when_the_ladder_cannot_do_better(monkeypatch):
    calls = []
    _wire_ladder(monkeypatch, None, calls)
    key = rt._post_product_key("facebook", "P-V")
    rec = {"name": "Gold Chalice", "slug": "gold-chalice", "source": "vision-name",
           "confidence": 0.7}
    r = _Redis({key: json.dumps(rec)})
    got = asyncio.run(rt._post_identity(r, "facebook", {"post_id": "P-V", "title": "Blessed",
                                                        "thumb": "https://x/t.jpg"}))
    assert got == rec and calls == ["P-V"]
    assert json.loads(r.store[key]) == rec            # never downgraded or dropped
    # an hour has not passed: no second ladder run
    asyncio.run(rt._post_identity(r, "facebook", {"post_id": "P-V", "title": "Blessed",
                                                  "thumb": "https://x/t.jpg"}))
    assert calls == ["P-V"]


def test_a_trusted_record_is_never_re_read(monkeypatch):
    calls = []
    _wire_ladder(monkeypatch, pc.with_provenance(APOSTOLIC, "caption"), calls)
    key = rt._post_product_key("facebook", "P-T")
    rec = {"name": "Ring", "slug": "bishops-ring", "source": "caption", "confidence": 0.95}
    r = _Redis({key: json.dumps(rec)})
    got = asyncio.run(rt._post_identity(r, "facebook", {"post_id": "P-T", "title": "", "thumb": ""}))
    assert got == rec and calls == []


def test_an_untrusted_hit_from_the_retry_does_not_replace_the_lead(monkeypatch):
    calls = []
    _wire_ladder(monkeypatch, pc.with_provenance(RING, "vision-name"), calls)
    key = rt._post_product_key("facebook", "P-U")
    rec = {"name": "Apostolic Ring", "slug": "apostolic-ring", "source": "model", "confidence": 0.6}
    r = _Redis({key: json.dumps(rec)})
    got = asyncio.run(rt._post_identity(r, "facebook", {"post_id": "P-U", "title": "Rings", "thumb": ""}))
    assert got == rec and calls == ["P-U"]


# ── the rule in the model's own instructions ────────────────────────────────

def test_the_addendum_scopes_the_transcript_to_this_post():
    text = rt._public_comment_addendum("USD")
    assert "The transcript you see is THIS post's thread only" in text
    assert "'in Kenya shillings'" in text
    assert "A reply inside a thread continues the comment it answers" in text
    assert "a ring post's 'in Kenya shillings' was answered with a cassock set" in text
