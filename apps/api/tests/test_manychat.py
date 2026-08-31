"""ManyChat relay (TikTok DMs) → Neema: shared-secret auth, synchronous turn on
the (tiktok, subscriber_id) spine, the 9s reply budget, human-intercept hold,
and the closer gate's budget-saving silence. Repo fake-db style (no DB fixture).

Requires Python 3.11 (SQLAlchemy models). Imports app.main to register the mapper.
"""
import asyncio
import types

import pytest

import app.main  # noqa: F401 — registers all SQLAlchemy models
import app.routers.manychat as mc
import app.agent.runtime as runtime
from app.core.config import settings
from app.models.conversation import InterceptMode
from app.models.message import Message, MsgDirection
from fastapi import HTTPException


# ── fake db / request ─────────────────────────────────────────────────────────

class _FakeDB:
    def __init__(self):
        self.added, self.commits, self.rollbacks = [], 0, 0
    def add(self, o):
        self.added.append(o)
    async def flush(self):
        pass
    async def commit(self):
        self.commits += 1
    async def rollback(self):
        self.rollbacks += 1


def _req(redis=None):
    return types.SimpleNamespace(app=types.SimpleNamespace(state=types.SimpleNamespace(redis=redis)))


def _conv(intercept=InterceptMode.ai):
    return types.SimpleNamespace(id="c1", person_id="p1", intercept_mode=intercept,
                                 last_message_at=None, last_message_preview=None)


def _wire(monkeypatch, conv=None, reply="Karibu! Yes, we stock cassocks.",
          saved=None, called=None):
    """Patch the identity/conversation seams + agent for a happy-path turn."""
    conv = conv or _conv()
    called = called if called is not None else {}

    async def fake_person(db, channel, external_id, **kw):
        called["person"] = (channel, external_id, kw)
        return types.SimpleNamespace(person_id="p1")

    async def fake_conv(db, channel, external_id, **kw):
        called["conv"] = (channel, external_id)
        return conv

    async def fake_run_turn(db, redis, wa_id, text, llm, media=None, **kw):
        called["turn"] = {"wa_id": wa_id, "text": text, **kw}
        return reply

    async def fake_save(db, redis, channel, external_id, text):
        (saved if saved is not None else []).append((channel, external_id, text))
        called["saved"] = (channel, external_id, text)

    monkeypatch.setattr("app.services.identity.resolve_or_create_person", fake_person)
    monkeypatch.setattr("app.services.channel.get_or_create_conversation", fake_conv)
    monkeypatch.setattr(runtime, "run_turn", fake_run_turn)
    monkeypatch.setattr(runtime, "build_llm", lambda model=None: object())
    monkeypatch.setattr(runtime, "route_model", lambda t: "m")
    monkeypatch.setattr("app.services.n8n_bridge.save_outbound_channel_message", fake_save)
    return conv, called


# ── auth ──────────────────────────────────────────────────────────────────────

def test_verify_manychat_key(monkeypatch):
    monkeypatch.setattr(settings, "manychat_webhook_key", "", raising=False)
    with pytest.raises(HTTPException) as e1:
        mc.verify_manychat_key("anything")
    assert e1.value.status_code == 503   # disabled until configured

    monkeypatch.setattr(settings, "manychat_webhook_key", "s3cret", raising=False)
    with pytest.raises(HTTPException) as e2:
        mc.verify_manychat_key("wrong")
    assert e2.value.status_code == 401

    assert mc.verify_manychat_key("s3cret") is None   # correct key passes


# ── validation ────────────────────────────────────────────────────────────────

def test_rejects_empty_message_and_missing_subscriber():
    with pytest.raises(HTTPException) as e:
        asyncio.run(mc.manychat_webhook(
            mc.ManyChatIn(subscriber_id="123", message="   "), _req(), _FakeDB()))
    assert e.value.status_code == 400
    with pytest.raises(HTTPException) as e2:
        asyncio.run(mc.manychat_webhook(
            mc.ManyChatIn(subscriber_id=" ", message="hi"), _req(), _FakeDB()))
    assert e2.value.status_code == 400


def test_rejects_non_tiktok_channel():
    """A flow misconfigured to relay Messenger/IG here must fail loudly — those
    have native webhooks, and ManyChat ids are the wrong namespace for them."""
    with pytest.raises(HTTPException) as e:
        asyncio.run(mc.manychat_webhook(
            mc.ManyChatIn(subscriber_id="123", message="hi", channel="instagram"),
            _req(), _FakeDB()))
    assert e.value.status_code == 400


# ── synchronous turn ──────────────────────────────────────────────────────────

def test_happy_path_runs_agent_on_tiktok_spine(monkeypatch):
    db = _FakeDB()
    conv, called = _wire(monkeypatch)
    out = asyncio.run(mc.manychat_webhook(
        mc.ManyChatIn(subscriber_id="424242", message="Do you have cassocks?",
                      name="Grace W", channel="tiktok"),
        _req(), db))

    assert out == {"reply": "Karibu! Yes, we stock cassocks.", "handled_by": "ai"}
    assert called["person"][0:2] == ("tiktok", "424242")
    assert called["conv"] == ("tiktok", "424242")
    # the agent ran keyed on the subscriber id, channel-tagged tiktok
    assert called["turn"]["wa_id"] == "424242"
    assert called["turn"]["channel"] == "tiktok"
    assert called["turn"]["external_id"] == "424242"
    # inbound persisted on the (tiktok, subscriber) spine, reply persisted too
    inbound = [o for o in db.added if isinstance(o, Message)
               and o.direction == MsgDirection.inbound]
    assert inbound and inbound[0].channel == "tiktok" \
        and inbound[0].external_id == "424242" and inbound[0].wa_id is None
    assert called["saved"] == ("tiktok", "424242", out["reply"])


def test_human_intercept_holds_once_then_silence(monkeypatch):
    class _Redis:
        def __init__(self):
            self.keys = set()
        async def set(self, k, v, nx=False, ex=None):
            if nx and k in self.keys:
                return None
            self.keys.add(k)
            return True

    redis = _Redis()
    ran = {"agent": False}

    async def fake_run_turn(*a, **k):
        ran["agent"] = True
        return "should not run"

    db = _FakeDB()
    conv, called = _wire(monkeypatch, conv=_conv(InterceptMode.human))
    monkeypatch.setattr(runtime, "run_turn", fake_run_turn)

    body = mc.ManyChatIn(subscriber_id="77", message="hello?")
    first = asyncio.run(mc.manychat_webhook(body, _req(redis), db))
    second = asyncio.run(mc.manychat_webhook(body, _req(redis), db))

    assert first["handled_by"] == "human" and first["reply"]      # told once
    assert second == {"reply": "", "handled_by": "human"}         # then silence
    assert ran["agent"] is False              # AI stays out under human takeover


def test_budget_overrun_returns_resend_line(monkeypatch):
    db = _FakeDB()

    async def slow_turn(*a, **k):
        await asyncio.sleep(0.2)
        return "too late"

    conv, called = _wire(monkeypatch)
    monkeypatch.setattr(runtime, "run_turn", slow_turn)
    monkeypatch.setattr(settings, "manychat_reply_budget_s", 0.05, raising=False)

    out = asyncio.run(mc.manychat_webhook(
        mc.ManyChatIn(subscriber_id="99", message="price of full set?"), _req(), db))

    assert out["handled_by"] == "ai"
    assert out["reply"] == mc._BUDGET_LINE    # never ManyChat's null-response error
    assert db.rollbacks >= 1                  # cancelled turn's session reset
    assert called["saved"][2] == mc._BUDGET_LINE   # history shows what was delivered


def test_agent_failure_returns_hold_line_and_flags(monkeypatch):
    db = _FakeDB()

    async def boom(*a, **k):
        raise RuntimeError("llm down")

    conv, called = _wire(monkeypatch)
    monkeypatch.setattr(runtime, "run_turn", boom)

    out = asyncio.run(mc.manychat_webhook(
        mc.ManyChatIn(subscriber_id="55", message="hi there"), _req(), db))

    assert out["handled_by"] == "ai"
    assert out["reply"] == runtime._hold_line(mc.CHANNEL)
    from app.models.intercept import Intercept
    assert any(isinstance(o, Intercept) for o in db.added)   # team flagged


def test_closer_gate_silences_politeness_pingpong(monkeypatch):
    """Second bare 'asante' in a row → empty reply, model never called: on
    TikTok silence is also a saved message from the 10-per-48h budget."""
    class _Redis:
        def __init__(self):
            self.store = {}
        async def get(self, k):
            return self.store.get(k)
        async def set(self, k, v, nx=False, ex=None):
            self.store[k] = v
            return True
        async def expire(self, k, ttl):
            return True
        async def delete(self, k):
            self.store.pop(k, None)

    redis = _Redis()
    db = _FakeDB()
    ran = {"count": 0}

    async def fake_run_turn(*a, **k):
        ran["count"] += 1
        return "Karibu sana 🙏"

    conv, called = _wire(monkeypatch)
    monkeypatch.setattr(runtime, "run_turn", fake_run_turn)

    body = mc.ManyChatIn(subscriber_id="31", message="asante")
    first = asyncio.run(mc.manychat_webhook(body, _req(redis), db))
    second = asyncio.run(mc.manychat_webhook(body, _req(redis), db))

    assert first["reply"] == "Karibu sana 🙏" and ran["count"] == 1
    assert second == {"reply": "", "handled_by": "ai"} and ran["count"] == 1
