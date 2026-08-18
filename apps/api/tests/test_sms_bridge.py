"""The SMS bridge — the business SIM's texts land in the Neema inbox.

WhatsApp strips business-sent OTPs before they reach Cloud API numbers
(131051), so verification codes must arrive as plain SMS on the SIM; a
phone-side forwarder POSTs them here. Receive-only, token-gated, and the
phone-sibling identity rule binds an SMS to the same person as their WhatsApp.
"""
import asyncio
import types

import pytest
from fastapi import HTTPException

from app.routers.sms import inbound_sms


class _Req:
    class app:
        class state:
            redis = None


def test_disabled_without_a_token(monkeypatch):
    from app.core import config
    monkeypatch.setattr(config.settings, "sms_inbound_token", "", raising=False)
    with pytest.raises(HTTPException) as e:
        asyncio.run(inbound_sms({"from": "254700", "body": "hi"}, _Req(), db=None,
                                authorization="Bearer x"))
    assert e.value.status_code == 404


def test_rejects_a_bad_token(monkeypatch):
    from app.core import config
    monkeypatch.setattr(config.settings, "sms_inbound_token", "sekrit", raising=False)
    with pytest.raises(HTTPException) as e:
        asyncio.run(inbound_sms({"from": "254700", "body": "hi"}, _Req(), db=None,
                                authorization="Bearer wrong"))
    assert e.value.status_code == 403


def test_requires_sender_and_body(monkeypatch):
    from app.core import config
    monkeypatch.setattr(config.settings, "sms_inbound_token", "sekrit", raising=False)
    with pytest.raises(HTTPException) as e:
        asyncio.run(inbound_sms({"from": "+1 (217) 582-9831", "body": "  "}, _Req(),
                                db=None, authorization="Bearer sekrit"))
    assert e.value.status_code == 422


def test_stores_the_text_and_holds_the_conversation_human(monkeypatch):
    from app.core import config
    import app.services.identity as identity
    import app.services.channel as channel_svc
    from app.models.conversation import InterceptMode

    monkeypatch.setattr(config.settings, "sms_inbound_token", "sekrit", raising=False)

    conv = types.SimpleNamespace(id="c1", intercept_mode=InterceptMode.ai,
                                 last_message_at=None, last_message_preview=None)
    seen = {}

    async def fake_resolve(db, ch, ext, **kw):
        seen["identity"] = (ch, ext)
        return types.SimpleNamespace(person_id="p1")

    async def fake_conv(db, ch, ext, **kw):
        seen["conv"] = (ch, ext, kw.get("person_id"))
        return conv

    monkeypatch.setattr(identity, "resolve_or_create_person", fake_resolve)
    monkeypatch.setattr(channel_svc, "get_or_create_conversation", fake_conv)

    class _DB:
        def __init__(self): self.added = []
        def add(self, o): self.added.append(o)
        async def commit(self): seen["committed"] = True

    db = _DB()
    out = asyncio.run(inbound_sms(
        {"from": "+1 (217) 582-9831", "body": " Your TikTok code is 482913 "},
        _Req(), db=db, authorization="Bearer sekrit"))

    assert out["ok"] is True
    # The number is normalised to bare digits for the phone-sibling adoption.
    assert seen["identity"] == ("sms", "12175829831")
    assert seen["conv"] == ("sms", "12175829831", "p1")
    assert seen["committed"]
    assert conv.intercept_mode == InterceptMode.human       # AI never engages
    assert db.added and db.added[0].text == "Your TikTok code is 482913"
    assert conv.last_message_preview.startswith("Your TikTok code")
