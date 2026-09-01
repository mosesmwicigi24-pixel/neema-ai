"""The live check itself: does this post belong to a broadcast running now?

Everything downstream of `is_live` — not reading the video frame, not recording
a post identity, welcoming the room instead of pitching at it — is only as good
as this answer. Two ways it used to be wrong:

  * it asked whether the video id appeared ANYWHERE inside the post id, which
    also says yes when those digits fall inside a page id or a longer run;
  * a Graph error was cached for 60s as "nothing is live", so one expired token
    put the guard to sleep for the next minute of a broadcast.
"""
import asyncio
import json

import httpx
import pytest

from app.core.config import settings
from app.services import meta_send


# ── post_is_live ─────────────────────────────────────────────────────────────

def test_a_feed_comment_on_the_broadcast_is_live():
    # The real shape: a feed comment carries {page_id}_{video_id}.
    assert meta_send.post_is_live("111222_999888", {"999888"})


def test_the_bare_video_id_is_also_the_broadcast():
    assert meta_send.post_is_live("999888", {"999888"})


@pytest.mark.parametrize("post_id", [
    "999888111222_5",     # the id is a prefix of the PAGE half, not the video
    "111222_9998881",     # a longer run that merely starts with it
    "111222_1999888",     # a longer run that merely ends with it
    "111222_999888_7",    # the video half is not the last segment
])
def test_digits_that_merely_contain_the_id_are_not_the_broadcast(post_id):
    assert not meta_send.post_is_live(post_id, {"999888"})


@pytest.mark.parametrize("post_id", ["", "   ", None])
def test_a_missing_post_id_is_never_live(post_id):
    assert not meta_send.post_is_live(post_id, {"999888"})


def test_nothing_is_live_when_nothing_is_broadcasting():
    assert not meta_send.post_is_live("111222_999888", set())


# ── live_video_ids ───────────────────────────────────────────────────────────

class _Redis:
    """Just enough redis to see what the lookup chose to remember."""
    def __init__(self):
        self.store = {}
    async def get(self, k):
        return self.store.get(k)
    async def set(self, k, v, **kw):
        self.store[k] = v
        return True


def _client(status, payload):
    class _R:
        status_code = status
        is_success = 200 <= status < 300
        def json(self):
            return payload
    class _C:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, url, **kw): return _R()
    return lambda *a, **k: _C()


@pytest.fixture(autouse=True)
def _page_creds(monkeypatch):
    monkeypatch.setattr(settings, "meta_page_token", "T", raising=False)
    monkeypatch.setattr(settings, "meta_page_id", "111222", raising=False)


def test_a_running_broadcast_is_found_and_remembered(monkeypatch):
    monkeypatch.setattr(httpx, "AsyncClient", _client(200, {"data": [
        {"id": "999888", "status": "LIVE"},
        {"id": "777", "status": "VOD"},          # finished — not broadcasting
    ]}))
    r = _Redis()
    assert asyncio.run(meta_send.live_video_ids(r)) == {"999888"}
    assert json.loads(r.store["meta:live_video_ids"]) == ["999888"]


def test_an_expired_token_is_not_remembered_as_nothing_is_live(monkeypatch):
    # A 401 says we could not find out. Caching that for 60s would put the
    # guard to sleep for the next minute of a live broadcast.
    monkeypatch.setattr(httpx, "AsyncClient", _client(401, {"error": {"code": 190}}))
    r = _Redis()
    assert asyncio.run(meta_send.live_video_ids(r)) == set()
    assert "meta:live_video_ids" not in r.store


def test_a_genuine_no_broadcast_answer_is_remembered(monkeypatch):
    # An empty 200 IS an answer, and worth the 60s — most comments arrive when
    # nothing is live, and that is the path we must not pay Graph for.
    monkeypatch.setattr(httpx, "AsyncClient", _client(200, {"data": []}))
    r = _Redis()
    assert asyncio.run(meta_send.live_video_ids(r)) == set()
    assert r.store["meta:live_video_ids"] == "[]"


def test_a_transport_error_is_not_remembered(monkeypatch):
    class _C:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, *a, **kw): raise RuntimeError("connection reset")
    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **k: _C())
    r = _Redis()
    assert asyncio.run(meta_send.live_video_ids(r)) == set()
    assert "meta:live_video_ids" not in r.store


def test_the_cached_answer_is_reused(monkeypatch):
    def _boom(*a, **k):
        raise AssertionError("cache miss — Graph must not be called again")
    r = _Redis()
    r.store["meta:live_video_ids"] = json.dumps(["999888"])
    monkeypatch.setattr(httpx, "AsyncClient", _boom)
    assert asyncio.run(meta_send.live_video_ids(r)) == {"999888"}


def test_no_page_credentials_means_no_lookup(monkeypatch):
    monkeypatch.setattr(settings, "meta_page_token", "", raising=False)
    monkeypatch.setattr(httpx, "AsyncClient",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("no call")))
    assert asyncio.run(meta_send.live_video_ids(None)) == set()
