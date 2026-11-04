"""The super admin is never locked out of a chat (owner, 2026-11-04): "the
super admin should be able to attend to any conversation whether it's picked
by someone else … but to note that the super admin has picked up that
conversation because sometimes if someone has not released that conversation
we are stuck."

Taking over moves the chat to the super admin (or an admin), writes "… took
over from Evelyn" in the timeline and tells the team. A regular agent is still
held off a colleague's chat.
"""
import asyncio
import types

import pytest
from fastapi import HTTPException

import app.main  # noqa: F401 — registers models
from app.models.conversation import InterceptMode
from app.models.intercept import Intercept
from app.services import conversation as cs


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

    async def refresh(self, row):
        pass

    async def rollback(self):
        pass


class _Redis:
    def __init__(self):
        self.sent = []

    async def delete(self, *a):
        return 1


def _conv(mode=InterceptMode.human, assigned="evelyn"):
    return types.SimpleNamespace(id="c1", wa_id="254700000001", external_id=None, person_id=None,
                                 channel="whatsapp", intercept_mode=mode, assigned_agent_id=assigned,
                                 intercept_since=None, last_message_at=None, last_message_preview=None)


def _agent(aid, name, role="agent", su=False):
    return types.SimpleNamespace(id=aid, name=name, role=role, is_superuser=su)


EVELYN = _agent("evelyn", "Evelyn")
SUPER = _agent("boss", "Super Admin", role="agent", su=True)


@pytest.fixture
def broadcasts(monkeypatch):
    sent = []

    async def _b(redis, channel, payload):
        sent.append((channel, payload))
    monkeypatch.setattr(cs, "_broadcast", _b)
    return sent


def _rows(db):
    return [r for r in db.added if isinstance(r, Intercept)]


def test_the_super_admin_takes_over_a_chat_someone_else_holds_and_it_is_noted(broadcasts):
    conv = _conv()
    db = _FakeDB(conv, agents={"evelyn": EVELYN})
    out = asyncio.run(cs.intercept_conversation(db, "c1", SUPER, _Redis()))
    assert conv.assigned_agent_id == "boss" and conv.intercept_mode == InterceptMode.human
    assert out["taken_over_from"] == "Evelyn"
    (row,) = _rows(db)
    assert row.note == "Took over from Evelyn" and row.agent_id == "boss"
    team = [p for ch, p in broadcasts if ch == "agents:all"][0]
    assert team["title"] == "🙋 Super Admin took over from Evelyn"
    live = [p for ch, p in broadcasts if ch == "c1"][0]
    assert live["takenFrom"] == "Evelyn" and live["assignedAgentId"] == "boss"


def test_an_admin_may_take_over_too():
    conv = _conv()
    db = _FakeDB(conv, agents={"evelyn": EVELYN})
    asyncio.run(cs.intercept_conversation(db, "c1", _agent("ad", "Grace", role="admin")))
    assert conv.assigned_agent_id == "ad"


def test_a_regular_agent_is_still_held_off_a_colleagues_chat():
    conv = _conv()
    db = _FakeDB(conv, agents={"evelyn": EVELYN})
    with pytest.raises(HTTPException) as e:
        asyncio.run(cs.intercept_conversation(db, "c1", _agent("sam", "Sam")))
    assert e.value.status_code == 409 and "Evelyn" in e.value.detail
    assert conv.assigned_agent_id == "evelyn" and not _rows(db)


def test_a_plain_pickup_still_reads_picked_up(broadcasts):
    conv = _conv(mode=InterceptMode.ai, assigned=None)
    db = _FakeDB(conv)
    out = asyncio.run(cs.intercept_conversation(db, "c1", SUPER, _Redis()))
    assert "taken_over_from" not in out and _rows(db)[0].note == "Super Admin"
    assert [p for ch, p in broadcasts if ch == "agents:all"][0]["title"] == "🙋 Super Admin picked up"


def test_the_super_admin_replying_in_evelyns_chat_takes_it_over_first(monkeypatch, broadcasts):
    conv = _conv()
    db = _FakeDB(conv, agents={"evelyn": EVELYN})

    async def _deliver(db, conv, text, quoted=None):
        return "wamid.1"

    async def _none(*a, **k):
        return None
    monkeypatch.setattr(cs, "_deliver_agent_reply", _deliver)
    monkeypatch.setattr(cs, "_claim_reply_id", _none)
    monkeypatch.setattr(cs, "_remember_reply_id", _none)
    monkeypatch.setattr(cs, "_draft_origin", _none)
    out = asyncio.run(cs.send_agent_reply(db, "c1", SUPER, "Hello, I'm here to help."))
    assert out["text"] == "Hello, I'm here to help."
    assert conv.assigned_agent_id == "boss"
    assert [r.note for r in _rows(db)] == ["Took over from Evelyn"]


def test_a_regular_agent_replying_in_evelyns_chat_is_refused():
    conv = _conv()
    db = _FakeDB(conv, agents={"evelyn": EVELYN})
    with pytest.raises(HTTPException) as e:
        asyncio.run(cs.send_agent_reply(db, "c1", _agent("sam", "Sam"), "hi"))
    assert e.value.status_code == 409


def test_who_may_override():
    assert cs.can_override(SUPER) and cs.can_override(_agent("x", "X", role="admin"))
    assert not cs.can_override(EVELYN)
    from app.models.agent import AgentRole
    assert cs.can_override(_agent("y", "Y", role=AgentRole.admin))


def test_the_timeline_says_who_took_over_from_whom():
    import inspect
    from app.routers import admin
    src = inspect.getsource(admin)
    assert src.count('took over from {e.note[len(TAKEOVER_PREFIX):]}') == 2
