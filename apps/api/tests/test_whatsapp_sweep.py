"""A thread in Neema's hands is never "unread" (owner, 2026-10-27), so a reply
she lost must be found and answered — or handed to a person — on WhatsApp
too, not only on Messenger and Instagram. The sweep answers real questions,
leaves her deliberate silences, reactions, the slow lane and web chat alone,
and after three attempts hands the thread to a human."""
import asyncio
import types

import app.main  # noqa: F401 — registers all SQLAlchemy models
from app.agent import runtime
from tests.test_cost_circuit_breaker import _FakeDB, _Redis, _Res


def _sessions(msg, conv):
    from app.models.message import MsgDirection
    sessions = [_FakeDB([_Res(many=[(msg, conv)])]),       # the sweep query
                _FakeDB([_Res(one=MsgDirection.inbound)])]  # the fresh recheck

    class _Sess:
        def __init__(self):
            self.db = sessions.pop(0) if sessions else _FakeDB([_Res(one=None)])

        async def __aenter__(self):
            return self.db

        async def __aexit__(self, *a):
            return False
    return _Sess


def _wa(text="how much is the cope set?", raw_meta=None, wa_id="254705087768"):
    msg = types.SimpleNamespace(id=7, text=text, media_type=None, media_url=None,
                                external_id=None, wa_id=wa_id, created_at=None, raw_meta=raw_meta)
    conv = types.SimpleNamespace(id="c1", channel="whatsapp", wa_id=wa_id,
                                 external_id=wa_id, person_id=None)
    return msg, conv


def _wire(monkeypatch, msg, conv):
    import app.services.reply_sweeper as sweeper
    monkeypatch.setattr(sweeper, "AsyncSessionLocal", _sessions(msg, conv))
    ran, escalated = [], []

    async def _run(redis, wa_id, text, media=None, **kw):
        ran.append((wa_id, text))
        return True

    async def _esc(channel, ext, note):
        escalated.append((channel, ext, note))
        return True

    async def _no(*a, **kw):
        return False
    monkeypatch.setattr(runtime, "_run_and_send", _run)
    monkeypatch.setattr(runtime, "escalate_to_human", _esc)
    monkeypatch.setattr(runtime, "_is_paused", _no)
    return sweeper, ran, escalated


def test_a_lost_whatsapp_reply_is_answered(monkeypatch):
    msg, conv = _wa()
    sweeper, ran, _ = _wire(monkeypatch, msg, conv)
    assert asyncio.run(sweeper.sweep_missed_replies(_Redis())) == 1
    assert ran == [("254705087768", "how much is the cope set?")]


def test_a_reaction_or_sticker_is_never_answered(monkeypatch):
    for meta, text in (({"kind": "reaction"}, "🙏 (reacted to your message)"),
                       ({"kind": "sticker"}, "🙂 Sent a sticker")):
        msg, conv = _wa(text=text, raw_meta=meta)
        sweeper, ran, _ = _wire(monkeypatch, msg, conv)
        asyncio.run(sweeper.sweep_missed_replies(_Redis()))
        assert ran == [], text


def test_a_chat_on_the_slow_lane_waits_for_it(monkeypatch):
    class _LaneRedis(_Redis):
        async def exists(self, k):
            return 1 if k.startswith("cool:lanelock:whatsapp:") else 0
    msg, conv = _wa()
    sweeper, ran, _ = _wire(monkeypatch, msg, conv)
    asyncio.run(sweeper.sweep_missed_replies(_LaneRedis()))
    assert ran == []


def test_web_chat_is_not_swept(monkeypatch):
    msg, conv = _wa(wa_id="web_abc123")
    sweeper, ran, _ = _wire(monkeypatch, msg, conv)
    asyncio.run(sweeper.sweep_missed_replies(_Redis()))
    assert ran == []


def test_after_three_attempts_a_person_has_it(monkeypatch):
    msg, conv = _wa()
    sweeper, ran, escalated = _wire(monkeypatch, msg, conv)
    asyncio.run(sweeper.sweep_missed_replies(_Redis({"agent:missed:tries:7": 3})))
    assert ran == []
    assert escalated and escalated[0][0] == "whatsapp" and "WhatsApp number" in escalated[0][2]


def test_a_deliberate_whatsapp_silence_is_recorded(monkeypatch):
    """The silence is a decision: recorded like Messenger's, so the sweep does
    not re-run it three times and then hand a 👍 to a person as a failure."""
    import app.database as database
    from tests.test_cost_circuit_breaker import _turn_db

    class _Sess:
        async def __aenter__(self):
            return _turn_db()

        async def __aexit__(self, *a):
            return False
    monkeypatch.setattr(database, "AsyncSessionLocal", _Sess)

    async def _silent(*a, **kw):
        return ""
    monkeypatch.setattr(runtime, "run_turn", _silent)
    monkeypatch.setattr(runtime, "build_llm", lambda **kw: object())
    r = _Redis()
    assert asyncio.run(runtime._run_and_send(r, "254705087768", "okay")) is False
    assert "agent:missed:silenced:whatsapp:254705087768" in r.kv
