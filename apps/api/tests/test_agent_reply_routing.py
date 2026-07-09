"""Human-agent reply routing: a Facebook/Instagram COMMENT conversation replies
on the comment edge (not the DM Send API, which 400s for a commenter with no open
thread — the old 500). DMs/WhatsApp use the normal transport.
"""
import asyncio
from types import SimpleNamespace

from app.services import conversation as convmod
from app.models.message import MsgDirection  # noqa: F401 (ensures models import)


class _Res:
    def __init__(self, item):
        self._item = item

    def scalar_one_or_none(self):
        return self._item


class _FakeDB:
    def __init__(self, latest):
        self._latest = latest

    async def execute(self, stmt):
        return _Res(self._latest)


def test_facebook_comment_replies_on_the_comment_edge(monkeypatch):
    calls = {}

    async def fake_reply_to_comment(cid, text):
        calls["comment"] = (cid, text)

    async def fake_send_to_channel(ch, rec, text):
        calls["dm"] = (ch, rec, text)

    monkeypatch.setattr("app.services.meta_send.reply_to_comment", fake_reply_to_comment)
    monkeypatch.setattr(convmod, "send_to_channel", fake_send_to_channel)

    latest = SimpleNamespace(waba_msg_id="POST_COMMENT_ID", comment_context={"title": "x"})
    conv = SimpleNamespace(id="c1", channel="facebook", external_id="U1", wa_id=None)
    asyncio.run(convmod._deliver_agent_reply(_FakeDB(latest), conv, "We're in Nairobi"))

    assert calls == {"comment": ("POST_COMMENT_ID", "We're in Nairobi")}   # public comment reply, no DM


def test_messenger_dm_uses_send_to_channel(monkeypatch):
    calls = {}

    async def fake_send_to_channel(ch, rec, text):
        calls["dm"] = (ch, rec, text)

    monkeypatch.setattr(convmod, "send_to_channel", fake_send_to_channel)

    latest = SimpleNamespace(waba_msg_id="m_123", comment_context=None)   # a DM, not a comment
    conv = SimpleNamespace(id="c2", channel="messenger", external_id="PSID1", wa_id=None)
    asyncio.run(convmod._deliver_agent_reply(_FakeDB(latest), conv, "hello"))

    assert calls == {"dm": ("messenger", "PSID1", "hello")}


def test_whatsapp_unchanged(monkeypatch):
    calls = {}

    async def fake_send_to_channel(ch, rec, text):
        calls["dm"] = (ch, rec, text)

    monkeypatch.setattr(convmod, "send_to_channel", fake_send_to_channel)

    conv = SimpleNamespace(id="c3", channel="whatsapp", external_id="254700", wa_id="254700")
    asyncio.run(convmod._deliver_agent_reply(_FakeDB(None), conv, "habari"))

    assert calls == {"dm": ("whatsapp", "254700", "habari")}
