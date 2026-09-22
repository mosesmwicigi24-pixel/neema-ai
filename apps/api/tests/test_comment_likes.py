"""LIKE EVERY ANSWERED COMMENT (owner, 2026-09-22).

The Page's Professional dashboard: "Reply to 400 comments" half done, "React
to 400 comments" at 0. Neema answered every non-spam comment within seconds
and reacted to none — there was no Like anywhere in the code. Now the Page's
Like follows every public reply that landed: a question, a hello, a cheer, an
"amen", a live-stream welcome. Never on a complaint, never on spam (no reply,
no Like), never on Instagram (the Graph API has no such edge), and never in a
way that could delay or fail the reply.

Repo fake style (no DB fixture). Requires Python 3.11 (SQLAlchemy models).
"""
import asyncio
import inspect

import app.main  # noqa: F401 — registers all SQLAlchemy models
from app.agent import runtime as rt
from app.core.config import settings
from app.services import meta_send as ms


def _graph(monkeypatch, fail: bool = False):
    calls = []

    async def fake_graph_post(path, body, what, page_id=None):
        calls.append((path, body, what, page_id))
        if fail:
            raise RuntimeError("Meta like comment failed (400): (#10) permission")
        return {"success": True}
    monkeypatch.setattr(ms, "_graph_post", fake_graph_post)
    return calls


# ── 1. the Like itself ───────────────────────────────────────────────────────

def test_like_posts_to_the_comments_likes_edge_with_the_pages_token(monkeypatch):
    calls = _graph(monkeypatch)
    assert asyncio.run(ms.like_comment("123_456", page_id="P1")) is True
    assert calls == [("123_456/likes", {}, "like comment", "P1")]


def test_a_failed_like_is_false_never_an_error(monkeypatch):
    calls = _graph(monkeypatch, fail=True)
    assert asyncio.run(ms.like_comment("123_456")) is False
    assert len(calls) == 1


def test_instagram_and_empty_ids_are_never_liked(monkeypatch):
    calls = _graph(monkeypatch)
    assert asyncio.run(ms.like_comment("178_9", channel="instagram")) is False
    assert asyncio.run(ms.like_comment("", channel="facebook")) is False
    assert calls == []


# ── 2. the engine: a Like follows every reply that landed, and only those ────

def test_the_engine_likes_after_every_landed_reply():
    src = inspect.getsource(rt._run_comment_engage)
    # the reply reports whether it landed, and the Like follows only then
    assert "async def _post_public(text: str) -> bool:" in src
    assert src.count("posted = await _post_public(") == 2     # the light path and the answer path
    assert src.count("if posted:\n") == 2 and src.count("await _like_answered()") == 2
    # never a complaint, never spam, never Instagram, and a switch for the day Meta objects
    assert 'if not settings.meta_comment_like or intent in ("negative", "spam"):' in src
    assert 'if channel == "instagram":' in src
    # a beat after the reply, best-effort, never in the reply's way
    assert "await asyncio.sleep(random.uniform(1.0, 3.0))" in src
    assert "if await like_comment(cid, page_id=comment.get(\"page_id\"), channel=channel):" in src
    # the Like comes after the reply AND its bookkeeping, in both places
    light = src.index("posted = await _post_public(text)")
    assert light < src.index("saving light reply failed", light) < src.index("await _like_answered()", light)
    answer = src.index("posted = await _post_public(public_text)")
    assert answer < src.index("saving public reply to thread failed", answer) < src.index("await _like_answered()", answer)


def test_the_switch_defaults_on():
    assert settings.meta_comment_like is True
    assert "meta_comment_like: bool = True" in inspect.getsource(type(settings))
