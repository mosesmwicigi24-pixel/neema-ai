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
        return True                                   # the flag landed: someone owns the hold

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


def test_the_hold_line_is_not_promised_when_nobody_could_be_told(monkeypatch):
    """Verification 1.7 (and pass 3): the REAL flag with a database that
    raises reports failure instead of swallowing it; the handover is tried;
    when that fails or raises too, the outcome is "unowned" — never the
    promise, and never "silence" the sweep would honour."""
    from app.agent import review as rv

    async def _record(redis, outcome, **kw): pass
    monkeypatch.setattr(rv, "record_verdict", _record)
    async def _not_recent(*a, **k): return False
    monkeypatch.setattr(rv, "held_recently", _not_recent)

    class _DeadDB:                                   # the outage the gate error most likely is
        async def execute(self, *a, **k): raise RuntimeError("connection refused")
        def add(self, o): pass
        async def commit(self): pass

    # the flag itself, unpatched, says it could not land
    assert asyncio.run(rt._flag_held_reply(_DeadDB(), "whatsapp", "2547000", ["x"], "draft")) is False

    handed = []
    async def _escalate_ok(channel, ext, note, draft=None, redis=None):
        handed.append((channel, ext, note, draft))
        return True
    monkeypatch.setattr(rt, "escalate_to_human", _escalate_ok)
    reply, issues, outcome = asyncio.run(rt._gate_failed_closed(
        "The chasuble is KES 999,999.", db=_DeadDB(), redis=None, channel="whatsapp", key="2547000",
        public_comment=False, closer=False, swahili=False, error="boom"))
    assert outcome == "held" and reply == rt._REVIEW_HOLD_DM          # someone owns it: the promise stands
    assert handed and handed[0][3] == "The chasuble is KES 999,999." and "gate could not run" in handed[0][2]

    for broken in (lambda *a, **k: False, None):
        async def _escalate_fail(*a, **k):
            if broken is None:
                raise RuntimeError("redis down")
            return False
        monkeypatch.setattr(rt, "escalate_to_human", _escalate_fail)
        reply, issues, outcome = asyncio.run(rt._gate_failed_closed(
            "The chasuble is KES 999,999.", db=_DeadDB(), redis=None, channel="whatsapp", key="2547000",
            public_comment=False, closer=False, swahili=False, error="boom"))
        assert (reply, outcome) == ("", "unowned")                      # nobody told: the sweep's, not silence
        assert any("missed-reply sweep" in i for i in issues)


def test_an_unowned_hold_reaches_the_sender_as_a_miss_not_silence(monkeypatch):
    """Through run_turn: a gate that raises, a database that is down for the
    flag, a handover that fails — the turn returns no text AND marks the
    facts `unowned_hold`, which the senders read before calling it silence."""
    import types
    from tests.test_agent_flow import _FakeDB, _Res

    async def _gate_boom(*a, **k): raise RuntimeError("rule code bug")
    monkeypatch.setattr(rt, "_gate_turn_reply", _gate_boom)
    async def _flag_fails(*a, **k): return False
    monkeypatch.setattr(rt, "_flag_held_reply", _flag_fails)
    async def _escalate_fail(*a, **k): return False
    monkeypatch.setattr(rt, "escalate_to_human", _escalate_fail)
    from app.agent import review as rv
    async def _record(redis, outcome, **kw): pass
    monkeypatch.setattr(rv, "record_verdict", _record)

    class _L:
        async def complete(self, *, system, messages, tools, **kw):
            return types.SimpleNamespace(text="The cope set is KES 45,000.", tool_calls=[],
                                         assistant_content=[], usage={}, stop_reason="end_turn")
    user = types.SimpleNamespace(name="Moses")
    db = _FakeDB([_Res(one=user), _Res(one=None), _Res(one=None), _Res(one=None), _Res(many=[])])
    facts: dict = {}
    out = asyncio.run(rt.run_turn(db, None, "254700000001", "how much is the cope set?", _L(), turn_facts=facts))
    assert out == "" and facts.get("unowned_hold") is True



# ── the opt-out outlives redis even for a contact with no person ─────────────

def test_an_opt_out_from_a_contact_with_no_person_makes_one_and_lands_on_it(monkeypatch):
    """Verification 1.3: before, a comment-DM or early-funnel contact's "stop"
    lived in redis for a year and died with a flush. Now the resolver makes
    the person, the preference lands on it, the thread is linked, and a later
    read with no person on the thread still finds it through the identity."""
    import types
    import uuid
    from app.services import intent, identity

    person = types.SimpleNamespace(id=uuid.uuid4(), state={})
    ident = types.SimpleNamespace(person_id=person.id, channel="messenger", external_id="PSID_9")
    made = []

    async def fake_resolve(db, channel, external_id, **kw):
        made.append((channel, external_id))
        assert kw.get("source") == "opt_out" and kw.get("confidence") == "deterministic"
        return ident
    monkeypatch.setattr(identity, "resolve_or_create_person", fake_resolve)
    monkeypatch.setattr("app.services.intent.flag_modified", lambda *a, **k: None, raising=False)

    class _DB:
        def __init__(self): self.added = []
        async def get(self, model, pk): return person if pk == person.id else None
        def add(self, o): self.added.append(o)
        async def commit(self): pass
        async def rollback(self): pass

    conv = types.SimpleNamespace(id="conv9", person_id=None, channel="messenger", external_id="PSID_9", wa_id=None)
    asyncio.run(intent.record_opt_out(_DB(), None, conv, "stop messaging me", channel="messenger", key="PSID_9"))
    assert made == [("messenger", "PSID_9")]
    assert person.state["contact_preferences"]["opt_out"]["said"] == "stop messaging me"
    assert conv.person_id == person.id                                  # the thread now knows its person

    # a synthetic thread (no person, no redis) still reads the preference through the identity
    async def fake_select(db, channel, external_id):
        return ident if (channel, external_id) == ("messenger", "PSID_9") else None
    monkeypatch.setattr(identity, "_select_identity", fake_select)
    synthetic = types.SimpleNamespace(person_id=None, channel="messenger", external_id="PSID_9", wa_id=None)
    assert asyncio.run(intent.opted_out(_DB(), None, synthetic)) is True
    stranger = types.SimpleNamespace(person_id=None, channel="messenger", external_id="PSID_0", wa_id=None)
    assert asyncio.run(intent.opted_out(_DB(), None, stranger)) is False


def test_a_web_chat_opt_out_never_mints_a_whatsapp_person(monkeypatch):
    """Verification pass 3: a web visitor rides the WhatsApp channel with a
    web_… key; the resolver must not make a phantom (whatsapp, web_…) person.
    The preference still lands in redis."""
    import types
    from app.services import intent, identity

    async def boom(*a, **k): raise AssertionError("resolver must not be called")
    monkeypatch.setattr(identity, "resolve_or_create_person", boom)

    class _DB:
        async def get(self, model, pk): return None
        def add(self, o): pass
        async def commit(self): pass
        async def rollback(self): pass

    class _R:
        def __init__(self): self.set_calls = []
        async def set(self, k, v, ex=None): self.set_calls.append(k)

    r = _R()
    conv = types.SimpleNamespace(id="c-web", person_id=None, channel="whatsapp", external_id=None, wa_id="web_abc123")
    asyncio.run(intent.record_opt_out(_DB(), r, conv, "stop", channel="whatsapp", key="web_abc123"))
    assert r.set_calls and conv.person_id is None
