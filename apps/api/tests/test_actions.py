"""Phase B2 — the initiative engine: promises fire, sensitivity gates, veto."""
import asyncio
import types
from datetime import datetime, timedelta, timezone

import pytest

from app.core.config import settings
from app.services import actions as act
from app.services import deals as ds


def test_customer_promise_parser_needs_verb_and_timeword():
    got = ds.detect_customer_promise("I'll confirm after our church meeting.")
    assert got is not None
    due, hint = got
    assert hint.startswith("after")
    assert due.tzinfo is not None
    # verb without timeword → None; timeword without verb → None
    assert ds.detect_customer_promise("I'll get back to you.") is None
    assert ds.detect_customer_promise("The meeting is tomorrow.") is None
    assert ds.detect_customer_promise("Nitaconfirm kesho") is not None


def test_customer_promise_lands_the_morning_after():
    due, hint = ds.detect_customer_promise("We will decide tomorrow, sawa?")
    nbo = due + timedelta(hours=3)
    assert nbo.hour == 10                              # 10:00 Nairobi
    assert nbo.date() > (datetime.now(timezone.utc) + timedelta(hours=3)).date()


def test_deal_total_and_gate_reasons(monkeypatch):
    deal = types.SimpleNamespace(
        id="d1", items_snapshot=[{"name": "Cassock", "qty": 5, "price": 12000}])
    assert act.deal_total(deal) == 60000

    from app.models.conversation import InterceptMode
    conv_ai = types.SimpleNamespace(intercept_mode=InterceptMode.ai)
    conv_h = types.SimpleNamespace(intercept_mode=InterceptMode.human)

    class _CountRes:
        def __init__(self, n): self._n = n
        def scalar_one(self): return self._n

    class _DB:
        def __init__(self, sent=0): self._sent = sent
        async def execute(self, *a, **k): return _CountRes(self._sent)

    # outside window always gates
    out = asyncio.run(act.needs_approval(_DB(), None, conv_ai, in_window=False))
    assert "window" in out
    # human-held gates
    out = asyncio.run(act.needs_approval(_DB(), None, conv_h, in_window=True))
    assert "human" in out
    # big total gates
    out = asyncio.run(act.needs_approval(_DB(), deal, conv_ai, in_window=True))
    assert "50,000" in out
    # nudge cap gates
    small = types.SimpleNamespace(id="d2", items_snapshot=[{"qty": 1, "price": 500}])
    out = asyncio.run(act.needs_approval(_DB(sent=2), small, conv_ai, in_window=True))
    assert "nudged" in out
    # small, fresh, in-window, AI-held → auto-send allowed
    out = asyncio.run(act.needs_approval(_DB(sent=0), small, conv_ai, in_window=True))
    assert out is None


def test_process_due_respects_flag_and_gate(monkeypatch):
    """Flag OFF: safe actions stay planned (trust mode); gated ones flip to
    needs_approval with a draft + notification either way."""
    from app.models.conversation import InterceptMode
    now = datetime.now(timezone.utc)
    action = types.SimpleNamespace(id="a1", status="planned", due_at=now,
                                   conversation_id="c1", deal_id="d1",
                                   reason="Neema promised: check gold thread",
                                   draft=None)
    conv = types.SimpleNamespace(id="c1", channel="whatsapp",
                                 wa_id="254700000001", external_id=None,
                                 intercept_mode=InterceptMode.ai)
    deal = types.SimpleNamespace(id="d1", status="open", items_snapshot=[])

    class _Rows:
        def scalars(self): return types.SimpleNamespace(all=lambda: [action])

    class _DB:
        def __init__(self): self.commits = 0
        async def execute(self, *a, **k): return _Rows()
        async def get(self, model, pk):
            return conv if model.__name__ == "Conversation" else deal
        async def commit(self): self.commits += 1
        async def rollback(self): pass

    async def fake_window(db, c): return True
    monkeypatch.setattr("app.services.hub_events._within_window", fake_window)
    monkeypatch.setattr("app.services.hub_events.is_quiet_hours", lambda now=None: False)

    async def no_gate(db, d, c, in_window): return None
    monkeypatch.setattr(act, "needs_approval", no_gate)
    monkeypatch.setattr(settings, "agent_initiative", False, raising=False)

    n = asyncio.run(act.process_due(_DB(), None, now=now))
    assert n == 0 and action.status == "planned"        # visible, not fired

    # Flag ON → composes and sends.
    monkeypatch.setattr(settings, "agent_initiative", True, raising=False)
    sent = []
    async def fake_compose(db, redis, c, reason): return "Habari! Quick update…"
    async def fake_send(db, redis, c, text): sent.append(text)
    monkeypatch.setattr(act, "_compose_follow_up", fake_compose)
    monkeypatch.setattr(act, "_send", fake_send)
    # This test is about the flag + gate; the repetition guard has its own.
    async def not_a_repeat(db, c, t): return False
    monkeypatch.setattr(act, "_repeats_earlier", not_a_repeat)
    action.status = "planned"
    n = asyncio.run(act.process_due(_DB(), None, now=now))
    assert n == 1 and action.status == "sent" and sent


def test_closed_deal_vetoes_the_follow_up(monkeypatch):
    from app.models.conversation import InterceptMode
    now = datetime.now(timezone.utc)
    action = types.SimpleNamespace(id="a2", status="planned", due_at=now,
                                   conversation_id="c1", deal_id="d1",
                                   reason="follow up", draft=None)
    conv = types.SimpleNamespace(id="c1", channel="whatsapp", wa_id="254700000001",
                                 external_id=None, intercept_mode=InterceptMode.ai)
    deal = types.SimpleNamespace(id="d1", status="won", items_snapshot=[])

    class _Rows:
        def scalars(self): return types.SimpleNamespace(all=lambda: [action])

    class _DB:
        async def execute(self, *a, **k): return _Rows()
        async def get(self, model, pk):
            return conv if model.__name__ == "Conversation" else deal
        async def commit(self): pass
        async def rollback(self): pass

    monkeypatch.setattr("app.services.hub_events.is_quiet_hours", lambda now=None: False)
    asyncio.run(act.process_due(_DB(), None, now=now))
    assert action.status == "vetoed"                    # paid customers aren't nagged


def test_action_routes_registered():
    from app.routers.crm import router
    paths = {(r.path, tuple(sorted(r.methods or []))) for r in router.routes}
    assert ("/actions", ("GET",)) in paths
    assert ("/actions/{action_id}/approve", ("POST",)) in paths
    assert ("/actions/{action_id}/veto", ("POST",)) in paths


# ── Never nudge with a message they already had ───────────────────────────────


def _fake_db_with_outbound(texts):
    class _Result:
        def scalars(self): return self
        def all(self): return texts

    class _DB:
        async def execute(self, stmt): return _Result()
    return _DB()


def test_repeats_earlier_catches_the_echoed_stall():
    """The exact failure seen live: the follow-up re-sent the holding line."""
    db = _fake_db_with_outbound(["One moment — let me check on that for you."])
    conv = types.SimpleNamespace(id="c1")
    assert asyncio.run(act._repeats_earlier(
        db, conv, "One moment — let me check on that for you.")) is True
    # Same sentence with different spacing/case is still the same non-answer.
    assert asyncio.run(act._repeats_earlier(
        db, conv, "one moment  —  LET ME CHECK on that for you.")) is True
    # A short stall wrapped in slightly more words is still a repeat.
    assert asyncio.run(act._repeats_earlier(
        db, conv, "Hi! One moment — let me check on that for you.")) is True


def test_repeats_earlier_allows_a_genuinely_new_follow_up():
    db = _fake_db_with_outbound(["One moment — let me check on that for you."])
    conv = types.SimpleNamespace(id="c1")
    real = ("Hi Ed, just checking in — our Silver Communion Tray (KES 18,000, holds "
            "40 cups, comes with lid, holder and basin) is the closest match to "
            "stainless steel that we stock. Happy to hold one for you.")
    assert asyncio.run(act._repeats_earlier(db, conv, real)) is False


def test_repeats_earlier_treats_an_empty_draft_as_unsendable():
    db = _fake_db_with_outbound([])
    conv = types.SimpleNamespace(id="c1")
    assert asyncio.run(act._repeats_earlier(db, conv, "   ")) is True
    assert asyncio.run(act._repeats_earlier(db, conv, "Something new")) is False
