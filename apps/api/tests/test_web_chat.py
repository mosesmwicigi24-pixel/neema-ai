"""Website storefront → Neema web chat: shared-secret auth, synchronous turn,
per-session threading, and human-intercept hold. Repo fake-db style (no DB fixture).

Requires Python 3.11 (SQLAlchemy models). Imports app.main to register the mapper.
"""
import asyncio
import types

import pytest

import app.main  # noqa: F401 — registers all SQLAlchemy models
import app.routers.web_chat as wc
import app.agent.runtime as runtime
import app.services.n8n_bridge as n8n
from app.core.config import settings
from app.models.conversation import InterceptMode
from app.models.message import Message, MsgDirection
from app.models.user import User
from fastapi import HTTPException


# ── fake db / request ─────────────────────────────────────────────────────────

class _Res:
    def __init__(self, one=None):
        self._one = one
    def scalar_one_or_none(self):
        return self._one


class _FakeDB:
    def __init__(self, results):
        self._results, self._i = list(results), 0
        self.added, self.commits, self.flushes = [], 0, 0
    async def execute(self, *a, **k):
        r = self._results[self._i]; self._i += 1
        return r
    def add(self, o):
        self.added.append(o)
    async def flush(self):
        self.flushes += 1
    async def commit(self):
        self.commits += 1


def _req(redis=None):
    return types.SimpleNamespace(app=types.SimpleNamespace(state=types.SimpleNamespace(redis=redis)))


# ── session key ───────────────────────────────────────────────────────────────

def test_web_wa_id_is_deterministic_bounded_and_non_numeric():
    a = wc._web_wa_id("visitor-123")
    b = wc._web_wa_id("visitor-123")
    c = wc._web_wa_id("visitor-999")
    assert a == b and a != c
    assert a.startswith("web_") and len(a) <= 30
    assert not a[4:].isdigit()   # never mistaken for a phone / Meta PSID


# ── auth ──────────────────────────────────────────────────────────────────────

def test_verify_storefront_key(monkeypatch):
    monkeypatch.setattr(settings, "storefront_key", "", raising=False)
    with pytest.raises(HTTPException) as e1:
        wc.verify_storefront_key("anything")
    assert e1.value.status_code == 503   # disabled until configured

    monkeypatch.setattr(settings, "storefront_key", "s3cret", raising=False)
    with pytest.raises(HTTPException) as e2:
        wc.verify_storefront_key("wrong")
    assert e2.value.status_code == 401

    assert wc.verify_storefront_key("s3cret") is None   # correct key passes


# ── synchronous turn ──────────────────────────────────────────────────────────

def test_web_chat_runs_agent_and_returns_reply(monkeypatch):
    called = {}

    async def fake_run_turn(db, redis, wa_id, text, llm, media=None):
        called["wa_id"] = wa_id
        called["text"] = text
        return "Karibu Bethany House! Yes, we stock cassocks."

    async def fake_save_outbound(db, redis, wa_id, text):
        called["outbound"] = (wa_id, text)

    monkeypatch.setattr(runtime, "run_turn", fake_run_turn)
    monkeypatch.setattr(runtime, "build_llm", lambda model=None: object())
    monkeypatch.setattr(runtime, "route_model", lambda t: "m")
    monkeypatch.setattr(n8n, "save_outbound_message", fake_save_outbound)

    db = _FakeDB([_Res(None), _Res(None)])   # no existing User, no existing Conversation
    body = wc.WebChatIn(session_id="sess-1", message="Do you have cassocks?", name="Grace")
    out = asyncio.run(wc.web_chat(body, _req(), db))

    assert out["handled_by"] == "ai"
    assert out["reply"].startswith("Karibu")
    assert out["session_id"] == "sess-1"
    # persisted an inbound message + created the profile
    assert any(isinstance(o, Message) and o.direction == MsgDirection.inbound for o in db.added)
    assert any(isinstance(o, User) and o.name == "Grace" for o in db.added)
    assert called["wa_id"].startswith("web_")
    assert called["outbound"][1].startswith("Karibu")   # reply persisted


def test_web_chat_holds_when_human_intercepted(monkeypatch):
    ran = {"agent": False}

    async def fake_run_turn(*a, **k):
        ran["agent"] = True
        return "should not run"

    monkeypatch.setattr(runtime, "run_turn", fake_run_turn)
    monkeypatch.setattr(runtime, "build_llm", lambda model=None: object())
    monkeypatch.setattr(runtime, "route_model", lambda t: "m")

    conv = types.SimpleNamespace(id="c1", intercept_mode=InterceptMode.human,
                                 last_message_at=None, last_message_preview=None)
    db = _FakeDB([_Res(None), _Res(conv)])   # no User, existing HUMAN-intercepted conversation
    body = wc.WebChatIn(session_id="sess-2", message="hi")
    out = asyncio.run(wc.web_chat(body, _req(), db))

    assert out["handled_by"] == "human"
    assert ran["agent"] is False              # AI stays silent under human takeover
    assert any(isinstance(o, Message) and o.direction == MsgDirection.inbound for o in db.added)


def test_web_chat_rejects_empty_message():
    db = _FakeDB([])
    with pytest.raises(HTTPException) as e:
        asyncio.run(wc.web_chat(wc.WebChatIn(session_id="s", message="   "), _req(), db))
    assert e.value.status_code == 400
