"""A HOLD LINE IS NOT AN ANSWER (2026-10-30).

Production, 2026-08-31 → 2026-10-22: 566 welcome-and-contacts hold lines,
560 of them inside six windows where the Anthropic account was out of credit
(Anthropic's "API access is turned off" mail opens each window, the top-up
receipt closes it, and not one model call succeeded in between). The sweeper
was meant to answer those customers once credit came back — the hold line's
own docstring said so — but the hold line was saved as an ordinary AI reply,
so it became the thread's newest message and the sweeper, which looks for a
customer message still waiting, read every one of those threads as answered.
274 threads heard nothing more; 2 got an answer after the top-up.

Pinned here on a real Postgres: a stamped hold line is looked past — the
customer's question is still waiting and gets answered (WhatsApp and
Messenger, and the window-closed escalation sees it too); an ordinary reply
still counts as an answer; while the AI account is down the sweep stands down
without spending anyone's strikes, and resumes once a turn succeeds; a
sweep retry never sends a second hold line.
"""
import asyncio
import json
import uuid

import pytest
import sqlalchemy as sa

from tests.test_security_db import _reachable, _sync_url, fresh_db  # noqa: F401
from tests.test_holds_reach_a_person_db import _Redis, _ago, _conv, rig  # noqa: F401

pytestmark = pytest.mark.skipif(not _sync_url() or not _reachable(_sync_url()),
                                reason="needs a reachable Postgres (CI migrations job / Docker harness)")

WA = "254700000088"
PSID = "psid-hold-88"


class _DecrRedis(_Redis):
    async def decr(self, k):
        self.kv[k] = int(self.kv.get(k) or 0) - 1
        return self.kv[k]


def _row(rig, cid, *, inbound, at, text, meta=None, channel="whatsapp", ext=WA):  # noqa: F811
    async def go():
        from app.models.message import Message, MsgDirection, MsgSender
        async with rig.maker() as db:
            db.add(Message(id=uuid.uuid4(), conversation_id=cid, channel=channel,
                           wa_id=(ext if channel == "whatsapp" else None), external_id=ext,
                           direction=MsgDirection.inbound if inbound else MsgDirection.outbound,
                           sender=MsgSender.user if inbound else MsgSender.ai,
                           text=text, raw_meta=meta, created_at=at))
            await db.commit()
    asyncio.run(go())


def _hold_meta():
    from app.services.reply_sweeper import HOLD_LINE_META
    return dict(HOLD_LINE_META)


def _held_thread(rig, *, channel="whatsapp", ext=WA, meta="hold"):  # noqa: F811
    cid = _conv(rig, channel=channel, ext=ext, mode="ai")
    _row(rig, cid, inbound=True, at=_ago(minutes=10), text="How much is the cope set?",
         channel=channel, ext=ext)
    _row(rig, cid, inbound=False, at=_ago(minutes=10, seconds=-2),
         text="Hello and welcome to Bethany House 🙏 We are so glad to have you here.",
         meta=(_hold_meta() if meta == "hold" else None), channel=channel, ext=ext)
    return cid


def _wire(rig, monkeypatch, *, went=True, on_attempt=None):  # noqa: F811
    from app.agent import runtime as rt
    from app.services import reply_sweeper as sw
    attempts = []

    async def run_wa(redis, wa_id, text, media=None, **kw):
        attempts.append(("whatsapp", wa_id, text, kw))
        if on_attempt:
            await on_attempt(redis)
        return went

    async def run_meta(redis, channel, ext, text, page_id=None, media=None, **kw):
        attempts.append((channel, ext, text, kw))
        if on_attempt:
            await on_attempt(redis)
        return went

    async def no(*a, **k):
        return False
    monkeypatch.setattr(rt, "_run_and_send", run_wa)
    monkeypatch.setattr(rt, "_run_and_send_meta", run_meta)
    monkeypatch.setattr(rt, "_is_paused", no)
    monkeypatch.setattr(sw, "AsyncSessionLocal", rig.maker)
    return sw, attempts


async def _out_of_credit(redis):
    from app.services.agent_health import record_turn_failure
    await record_turn_failure(redis, "x", RuntimeError(
        "Error code: 400 - Your credit balance is too low to access the Anthropic API."))


# ── the hold line is looked past ─────────────────────────────────────────────

@pytest.mark.parametrize("channel,ext", [("whatsapp", WA), ("messenger", PSID)])
def test_the_question_behind_a_hold_line_is_answered(rig, monkeypatch, channel, ext):  # noqa: F811
    _held_thread(rig, channel=channel, ext=ext)
    sw, attempts = _wire(rig, monkeypatch)
    assert asyncio.run(sw.sweep_missed_replies(rig.redis)) == 1
    assert [(c, e, t) for c, e, t, _ in attempts] == [(channel, ext, "How much is the cope set?")]
    # a retry never sends the customer a second hold line
    assert attempts[0][3].get("hold_line") is False


def test_an_ordinary_reply_still_counts_as_an_answer(rig, monkeypatch):  # noqa: F811
    _held_thread(rig, meta=None)                  # same words, but a real reply row
    sw, attempts = _wire(rig, monkeypatch)
    assert asyncio.run(sw.sweep_missed_replies(rig.redis)) == 0
    assert attempts == []


def test_a_window_closed_dm_behind_a_hold_line_is_still_waiting(rig, monkeypatch):  # noqa: F811
    from app.services import reply_sweeper as sw
    monkeypatch.setattr(sw, "AsyncSessionLocal", rig.maker)
    cid = _conv(rig, channel="messenger", ext=PSID, mode="ai")
    _row(rig, cid, inbound=True, at=_ago(hours=30), text="Price of the stole?",
         channel="messenger", ext=PSID)
    _row(rig, cid, inbound=False, at=_ago(hours=30, seconds=-2), text="Hello and welcome…",
         meta=_hold_meta(), channel="messenger", ext=PSID)
    rows = asyncio.run(sw._unanswered_dms(_ago(hours=23), _ago(days=7), 20))
    assert [m.text for m, _ in rows] == ["Price of the stole?"]


# ── an AI-account outage spends nobody's strikes ─────────────────────────────

def test_the_sweep_stands_down_while_the_account_is_out_of_credit(rig, monkeypatch):  # noqa: F811
    _held_thread(rig)
    sw, attempts = _wire(rig, monkeypatch)
    asyncio.run(_out_of_credit(rig.redis))
    for _ in range(5):
        assert asyncio.run(sw.sweep_missed_replies(rig.redis)) == 0
    assert attempts == []
    assert not [k for k in rig.redis.kv if k.startswith("agent:missed:tries:")]

    # credit restored: the first completed turn clears the state…
    from app.services.agent_health import record_turn_success
    assert asyncio.run(record_turn_success(rig.redis))
    # …and the next pass answers the customer who was left waiting
    assert asyncio.run(sw.sweep_missed_replies(rig.redis)) == 1
    assert [t for _, _, t, _ in attempts] == ["How much is the cope set?"]


def test_an_attempt_that_finds_the_account_down_gives_the_strike_back(rig, monkeypatch):  # noqa: F811
    rig.redis = _DecrRedis()
    _held_thread(rig)
    _held_thread(rig, channel="messenger", ext=PSID)
    sw, attempts = _wire(rig, monkeypatch, went=False, on_attempt=_out_of_credit)
    assert asyncio.run(sw.sweep_missed_replies(rig.redis)) == 0
    assert len(attempts) == 1                     # the pass stops: the rest would fail too
    tries = {k: v for k, v in rig.redis.kv.items() if k.startswith("agent:missed:tries:")}
    assert list(tries.values()) == [0]            # the strike was the account's, not theirs


# ── the hold line is stamped where it is written ─────────────────────────────

def test_the_hold_line_row_is_stamped(rig, monkeypatch):  # noqa: F811
    from app.agent import runtime as rt
    from app.services import n8n_bridge as svc
    import app.services.meta_send as meta_send

    async def fake_waba(to, text, *a, **k):
        return "wamid.hold"

    async def fake_meta(channel, ext, text, *a, **k):
        return None
    monkeypatch.setattr(svc, "_send_waba", fake_waba)
    monkeypatch.setattr(meta_send, "send_to_channel", fake_meta)
    _conv(rig, channel="messenger", ext=PSID, mode="ai")
    asyncio.run(rt._send_hold_line(rig.redis, "whatsapp", WA))
    asyncio.run(rt._send_hold_line(rig.redis, "messenger", PSID))

    async def rows():
        from app.models.message import Message
        async with rig.maker() as db:
            return (await db.execute(sa.select(Message.channel, Message.raw_meta)
                                     .order_by(Message.channel))).all()
    got = asyncio.run(rows())
    assert [(c, json.loads(json.dumps(m))) for c, m in got] == [
        ("messenger", {"v": 1, "kind": "hold_line"}),
        ("whatsapp", {"v": 1, "kind": "hold_line"}),
    ]
