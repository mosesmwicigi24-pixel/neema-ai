"""The conversation buttons respond on click ONCE (owner's audit, 2026-08-19).

Scrutiny of Intercept / Release / Pause found three real defects:

  1. No idempotency: a double-tap (or a retry on slow mobile) journalled a
     SECOND "picked up"/"released" timeline row and re-notified every agent —
     one nervous thumb, two team-wide pings.
  2. The Pause button called release() — handing the thread back to the AI,
     the OPPOSITE of pausing — because no pause endpoint existed at all, even
     though InterceptMode.paused has been in the model from the start.
  3. Even a properly paused conversation kept getting AI replies on WhatsApp:
     the Meta webhook and the sweeper held for `paused`, but both WhatsApp
     gates checked only for `human`.

These tests pin the fixes. (The client side adds in-flight disabling and
spinners on top — belt AND braces.)
"""
import asyncio
import types

import app.main  # noqa: F401 — registers models
from app.models.conversation import InterceptMode
from app.models.intercept import Intercept, InterceptAction
from app.services.conversation import (intercept_conversation, pause_conversation,
                                       release_conversation)


class _Res:
    def __init__(self, one=None):
        self._one = one

    def scalar_one_or_none(self):
        return self._one


class _FakeDB:
    def __init__(self, conv, agents=None):
        self.conv, self.agents = conv, agents or {}
        self.added, self.commits = [], 0

    async def execute(self, *a, **k):
        return _Res(self.conv)

    async def get(self, model, _id):
        return self.agents.get(str(_id))

    def add(self, row):
        self.added.append(row)

    async def commit(self):
        self.commits += 1


def _conv(mode=InterceptMode.ai, assigned=None):
    return types.SimpleNamespace(id="c1", wa_id="254700000001",
                                 intercept_mode=mode, assigned_agent_id=assigned,
                                 intercept_since=None)


def _agent(aid="a1", name="Moses", role="agent", su=False):
    return types.SimpleNamespace(id=aid, name=name, role=role, is_superuser=su)


def _rows(db):
    return [r for r in db.added if isinstance(r, Intercept)]


# ── intercept: one claim, one journal row, one notification ──────────────────

def test_double_intercept_by_the_owner_journals_once():
    conv, me = _conv(), _agent()
    db = _FakeDB(conv)
    out1 = asyncio.run(intercept_conversation(db, "c1", me))
    assert conv.intercept_mode == InterceptMode.human
    assert len(_rows(db)) == 1 and not out1.get("already")

    out2 = asyncio.run(intercept_conversation(db, "c1", me))   # the double-tap
    assert out2.get("already") is True
    assert len(_rows(db)) == 1, "a second 'picked up' row was journalled"


def test_intercepting_anothers_conversation_still_409s():
    import pytest
    from fastapi import HTTPException
    conv = _conv(mode=InterceptMode.human, assigned="owner-9")
    db = _FakeDB(conv, agents={"owner-9": _agent("owner-9", "Grace")})
    with pytest.raises(HTTPException) as e:
        asyncio.run(intercept_conversation(db, "c1", _agent("a2", "Sam")))
    assert e.value.status_code == 409 and "Grace" in e.value.detail


# ── release: releasing what is already released is a no-op ───────────────────

def test_double_release_journals_once():
    conv, me = _conv(mode=InterceptMode.human, assigned="a1"), _agent()
    db = _FakeDB(conv)
    asyncio.run(release_conversation(db, "c1", me))
    assert conv.intercept_mode == InterceptMode.ai and len(_rows(db)) == 1

    out2 = asyncio.run(release_conversation(db, "c1", me))     # the double-tap
    assert out2.get("already") is True
    assert len(_rows(db)) == 1, "a second 'released' row was journalled"


# ── pause: a REAL pause at last ──────────────────────────────────────────────

def test_pause_actually_pauses_and_journals_the_pause():
    conv, me = _conv(), _agent()
    db = _FakeDB(conv)
    out = asyncio.run(pause_conversation(db, "c1", me))
    assert conv.intercept_mode == InterceptMode.paused
    assert out["intercept_mode"] == "paused"
    rows = _rows(db)
    assert len(rows) == 1 and rows[0].action == InterceptAction.pause


def test_double_pause_journals_once():
    conv, me = _conv(), _agent()
    db = _FakeDB(conv)
    asyncio.run(pause_conversation(db, "c1", me))
    out2 = asyncio.run(pause_conversation(db, "c1", me))
    assert out2.get("already") is True
    assert len(_rows(db)) == 1


def test_pausing_anothers_live_conversation_is_refused_for_regular_agents():
    import pytest
    from fastapi import HTTPException
    conv = _conv(mode=InterceptMode.human, assigned="owner-9")
    db = _FakeDB(conv, agents={"owner-9": _agent("owner-9", "Grace")})
    with pytest.raises(HTTPException) as e:
        asyncio.run(pause_conversation(db, "c1", _agent("a2", "Sam")))
    assert e.value.status_code == 409
    # …but an admin can
    conv2 = _conv(mode=InterceptMode.human, assigned="owner-9")
    db2 = _FakeDB(conv2)
    asyncio.run(pause_conversation(db2, "c1", _agent("adm", "Admin", role="admin")))
    assert conv2.intercept_mode == InterceptMode.paused


# ── paused means SILENT on every channel ─────────────────────────────────────

def test_whatsapp_gates_hold_for_paused_not_just_human():
    """Meta's webhook and the sweeper always held for paused; both WhatsApp
    gates checked `== human` and kept replying. They must gate on `!= ai`."""
    import inspect
    import app.services.wa_native as wa
    import app.services.n8n_bridge as bridge
    wa_src = inspect.getsource(wa)
    assert "intercept_mode != InterceptMode.ai" in wa_src
    # the REPLY gate specifically must not be the old human-only check (the
    # media-escalation block legitimately keeps its own `== human` skip)
    assert 'conv.intercept_mode == InterceptMode.human:\n                _log.info("native' not in wa_src
    assert "intercept_mode != InterceptMode.ai" in inspect.getsource(bridge)


def test_the_pause_button_calls_pause_not_release():
    """The UI defect that started this audit: the Pause button was wired to
    release(). Pin the rewire (and the busy-guard state) at the source level —
    the web suite has no component harness for this view."""
    import os
    view = os.path.join(os.path.dirname(__file__), "..", "..", "web", "src",
                        "components", "views", "ConversationsView.tsx")
    s = open(view, encoding="utf-8").read()
    assert "pauseConv(activeConv.id)" in s
    assert "conversationsApi.pause(" in s
    assert 'setConvBusy("intercept")' in s and 'setConvBusy("pause")' in s
    # every conversation control disables while any action is in flight
    assert s.count("disabled={!!convBusy}") >= 5


def test_the_timeline_knows_the_pause_by_name():
    from app.routers import admin
    import inspect
    src = inspect.getsource(admin)
    assert "InterceptAction.pause" in src
    assert "Paused — replies held" in src
