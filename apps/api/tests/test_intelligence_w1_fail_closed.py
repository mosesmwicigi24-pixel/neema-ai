"""Workstream 1 (intelligence programme, 2026-11-06): the protections that
used to fail open now fail closed, and the opt-out door exists on every
channel that can receive a message."""
from __future__ import annotations

import asyncio
import inspect

import pytest

from app.agent import runtime as rt


# ── the gate ──────────────────────────────────────────────────────────────────

def test_a_gate_error_holds_the_draft_instead_of_sending_it(monkeypatch):
    """A draft the gate could not verify is treated as a held draft: the
    holding line goes out (private thread), the colleague is flagged, the
    verdict is tallied as held — the unverified words never reach the customer."""
    flagged, verdicts = [], []

    async def _flag(db, channel, key, issues, draft, redis=None):
        flagged.append((channel, key, issues, draft))

    async def _record(redis, outcome, **kw):
        verdicts.append(outcome)

    async def _held_recently(redis, channel, key):
        return False

    monkeypatch.setattr(rt, "_flag_held_reply", _flag)
    from app.agent import review as rv
    monkeypatch.setattr(rv, "record_verdict", _record)
    monkeypatch.setattr(rv, "held_recently", _held_recently)
    reply, held, outcome = asyncio.run(rt._gate_failed_closed(
        "The chasuble is KES 999,999.", db=None, redis=None, channel="whatsapp", key="2547000",
        public_comment=False, closer=False, swahili=False, error="boom"))
    assert outcome == "held" and reply == rt._REVIEW_HOLD_DM
    assert "999,999" not in reply
    assert flagged and flagged[0][3] == "The chasuble is KES 999,999." and "gate could not run" in flagged[0][2][0]
    assert verdicts == ["held"]


def test_a_gate_error_on_a_closer_or_a_public_comment_is_silence(monkeypatch):
    async def _record(redis, outcome, **kw):
        pass
    from app.agent import review as rv
    monkeypatch.setattr(rv, "record_verdict", _record)
    for kw in ({"closer": True, "public_comment": False}, {"closer": False, "public_comment": True}):
        reply, _, outcome = asyncio.run(rt._gate_failed_closed(
            "draft", db=None, redis=None, channel="messenger", key="psid", swahili=False, error="x", **kw))
        assert (reply, outcome) == ("", "held")


def test_the_gate_call_site_no_longer_falls_through_to_the_send():
    src = inspect.getsource(rt.run_turn)
    assert "reply gate failed open" not in src
    assert "_gate_failed_closed(" in src


# ── the takeover re-check ────────────────────────────────────────────────────

def test_the_takeover_check_returns_none_when_it_cannot_read_the_thread(monkeypatch):
    from sqlalchemy.exc import OperationalError

    class _Boom:
        async def __aenter__(self):
            raise OperationalError("SELECT 1", {}, Exception("connection refused"))
        async def __aexit__(self, *a):
            return False
    import app.database as _db
    monkeypatch.setattr(_db, "AsyncSessionLocal", lambda: _Boom())
    assert asyncio.run(rt._still_ai("whatsapp", "2547000")) is None


def test_a_programming_error_in_the_takeover_check_does_not_mute_the_agent(monkeypatch):
    class _Odd:
        async def __aenter__(self):
            raise AttributeError("fake session")
        async def __aexit__(self, *a):
            return False
    import app.database as _db
    monkeypatch.setattr(_db, "AsyncSessionLocal", lambda: _Odd())
    assert asyncio.run(rt._still_ai("whatsapp", "2547000")) is True


def test_both_senders_treat_an_unverifiable_takeover_as_not_sent():
    for fn in (rt._run_and_send, rt._run_and_send_meta):
        src = inspect.getsource(fn)
        assert "_ai = await _still_ai(" in src and "if _ai is None:" in src, fn.__name__


# ── the opt-out door on every channel ────────────────────────────────────────

def test_the_meta_scheduler_has_the_same_door_as_whatsapp():
    src = inspect.getsource(rt.schedule_meta_reply)
    assert "_intent.is_opt_out(text)" in src and "_handle_opt_out(redis, channel, external_id, text)" in src
    # and it sits before the closer gate and the dedup, as on WhatsApp
    assert src.index("is_opt_out") < src.index("closer_gate")


@pytest.mark.asyncio
async def test_the_meta_door_records_before_any_model_turn(monkeypatch):
    calls = []

    async def _handle(redis, channel, key, text):
        calls.append((channel, key, text))

    async def _paused(*a, **k):
        return False
    monkeypatch.setattr(rt, "_handle_opt_out", _handle)
    monkeypatch.setattr(rt, "_is_paused", _paused)
    out = await rt.schedule_meta_reply(None, "instagram", "igsid-1", "Please stop messaging me", dedup_id="m1")
    assert out is True and calls == [("instagram", "igsid-1", "Please stop messaging me")]


def test_web_chat_and_the_tiktok_relay_record_an_opt_out_before_the_model():
    from app.routers import manychat, web_chat
    for mod in (web_chat, manychat):
        src = inspect.getsource(mod)
        assert "_intent.is_opt_out(text)" in src and "record_opt_out(" in src, mod.__name__
        assert src.index("is_opt_out(text)") < src.index("run_turn(")


def test_the_sweepers_cross_channel_bridge_honours_the_opt_out():
    from app.services import reply_sweeper as sw
    src = inspect.getsource(sw._try_continue_elsewhere)
    assert "_opted_out(db, redis, sib)" in src and src.index("_opted_out(") < src.index("_compose_bridge(")


@pytest.mark.asyncio
async def test_the_opt_out_door_reads_the_words_even_with_a_photo_attached(monkeypatch):
    calls = []

    async def _handle(redis, channel, key, text):
        calls.append((channel, key))

    async def _paused(*a, **k):
        return False
    monkeypatch.setattr(rt, "_handle_opt_out", _handle)
    monkeypatch.setattr(rt, "_is_paused", _paused)
    out = await rt.schedule_reply(None, "254700000002", "Please stop messaging me", dedup_id="m2",
                                  media={"type": "image", "url": "x"})
    assert out is True and calls == [("whatsapp", "254700000002")]
    out = await rt.schedule_meta_reply(None, "messenger", "psid-2", "Stop messaging me", dedup_id="m3",
                                       media={"type": "image", "url": "x"})
    assert out is True and calls[-1] == ("messenger", "psid-2")
