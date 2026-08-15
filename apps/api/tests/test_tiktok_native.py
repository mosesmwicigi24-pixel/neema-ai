"""Native TikTok channel: webhook signature + events, OAuth token lifecycle,
the send_to_channel flip, and the ManyChat cutover guard. Repo fake-db style.

Requires Python 3.11 (SQLAlchemy models). Imports app.main to register the mapper.
"""
import asyncio
import hashlib
import hmac as hmac_mod
import json
import time
import types

import pytest

import app.main  # noqa: F401 — registers all SQLAlchemy models
import app.routers.tiktok_webhook as tw
import app.services.tiktok_native as tn
import app.agent.runtime as runtime
from app.core.config import settings
from app.models.conversation import InterceptMode
from app.models.message import Message, MsgDirection, MsgSender
from fastapi import HTTPException


class _Res:
    def __init__(self, one=None):
        self._one = one
    def scalar_one_or_none(self):
        return self._one


class _FakeDB:
    def __init__(self, results=()):
        self._results, self._i = list(results), 0
        self.added, self.commits = [], 0
        self.settings_rows = {}
    async def execute(self, *a, **k):
        if self._i < len(self._results):
            r = self._results[self._i]; self._i += 1
            return r
        return _Res(None)
    def add(self, o):
        self.added.append(o)
        if getattr(o, "__tablename__", "") == "app_settings":
            self.settings_rows[o.id] = o
    async def flush(self):
        pass
    async def commit(self):
        self.commits += 1
    async def get(self, model, key):
        return self.settings_rows.get(key)


def _sign(raw: bytes, secret: str, ts: int | None = None) -> str:
    ts = ts or int(time.time())
    sig = hmac_mod.new(secret.encode(), f"{ts}.".encode() + raw, hashlib.sha256).hexdigest()
    return f"t={ts},s={sig}"


def _req(redis=None, body=b"{}", sig=None):
    async def _body():
        return body
    headers = {"Tiktok-Signature": sig} if sig else {}
    return types.SimpleNamespace(
        body=_body,
        headers=headers,
        app=types.SimpleNamespace(state=types.SimpleNamespace(redis=redis)))


def _event(name, content: dict, openid="biz_open_id"):
    return json.dumps({"event": name, "user_openid": openid,
                       "content": json.dumps(content)}).encode()


def _dm(text="Do you have cassocks?", from_id="cust_1", to_id="biz_open_id",
        mid="m1", conv="tt_conv_9"):
    return {"conversation_id": conv, "message_id": mid, "type": "text",
            "text": {"body": text}, "timestamp": 1755280000000,
            "from": "gracew", "from_user": {"id": from_id},
            "to": "bethany", "to_user": {"id": to_id}}


# ── signature ────────────────────────────────────────────────────────────────

def test_webhook_inert_then_signature_gate(monkeypatch):
    db = _FakeDB()
    monkeypatch.setattr(settings, "tiktok_app_secret", "", raising=False)
    out = asyncio.run(tw.events(_req(body=b"{}"), db))
    assert out.status_code == 503                     # inert until configured

    monkeypatch.setattr(settings, "tiktok_app_secret", "s3cret", raising=False)
    out = asyncio.run(tw.events(_req(body=b"{}"), db))
    assert out.status_code == 403                     # no signature

    raw = _event("im_mark_read_msg", {})
    out = asyncio.run(tw.events(_req(body=raw, sig=_sign(raw, "wrong")), db))
    assert out.status_code == 403                     # bad secret

    stale = _sign(raw, "s3cret", ts=int(time.time()) - 4000)
    out = asyncio.run(tw.events(_req(body=raw, sig=stale), db))
    assert out.status_code == 403                     # stale timestamp

    out = asyncio.run(tw.events(_req(body=raw, sig=_sign(raw, "s3cret")), db))
    assert out == {"ok": True}                        # valid → acknowledged


# ── inbound DM ───────────────────────────────────────────────────────────────

def _wire_receive(monkeypatch, conv=None):
    called = {}
    conv = conv or types.SimpleNamespace(id="c1", person_id="p1",
                                         intercept_mode=InterceptMode.ai,
                                         last_message_at=None, last_message_preview=None)

    async def fake_person(db, channel, external_id, **kw):
        called["person"] = (channel, external_id, kw)
        return types.SimpleNamespace(person_id="p1",
                                     raw_profile=kw.get("raw_profile") or {})

    async def fake_conv(db, channel, external_id, **kw):
        called["conv"] = (channel, external_id)
        return conv

    async def fake_schedule(redis, channel, external_id, text, dedup_id=None, **kw):
        called["schedule"] = {"channel": channel, "external_id": external_id,
                              "text": text, "dedup_id": dedup_id}
        return True

    monkeypatch.setattr(settings, "tiktok_app_secret", "s3cret", raising=False)
    monkeypatch.setattr("app.services.identity.resolve_or_create_person", fake_person)
    monkeypatch.setattr("app.services.channel.get_or_create_conversation", fake_conv)
    monkeypatch.setattr(runtime, "schedule_meta_reply", fake_schedule)
    return conv, called


def test_receive_persists_and_schedules_async_reply(monkeypatch):
    db = _FakeDB([_Res(None)])          # no duplicate message_id
    conv, called = _wire_receive(monkeypatch)
    raw = _event("im_receive_msg", _dm())
    out = asyncio.run(tw.events(_req(body=raw, sig=_sign(raw, "s3cret")), db))

    assert out == {"ok": True}
    assert called["person"][0:2] == ("tiktok", "cust_1")
    # conversation id (our only send address) stamped on the identity profile
    assert called["person"][2]["raw_profile"]["tt_conversation_id"] == "tt_conv_9"
    inbound = [o for o in db.added if isinstance(o, Message)]
    assert inbound and inbound[0].direction == MsgDirection.inbound \
        and inbound[0].external_id == "cust_1" and inbound[0].waba_msg_id == "m1"
    assert called["schedule"]["channel"] == "tiktok"
    assert called["schedule"]["external_id"] == "cust_1"
    assert called["schedule"]["dedup_id"] == "m1"


def test_receive_dedupes_on_message_id(monkeypatch):
    db = _FakeDB([_Res("existing-id")])   # message_id already stored
    conv, called = _wire_receive(monkeypatch)
    raw = _event("im_receive_msg", _dm())
    asyncio.run(tw.events(_req(body=raw, sig=_sign(raw, "s3cret")), db))
    assert "schedule" not in called and not db.added


def test_receive_holds_agent_under_human_intercept(monkeypatch):
    conv = types.SimpleNamespace(id="c1", person_id="p1",
                                 intercept_mode=InterceptMode.human,
                                 last_message_at=None, last_message_preview=None)
    db = _FakeDB([_Res(None)])
    conv, called = _wire_receive(monkeypatch, conv=conv)
    raw = _event("im_receive_msg", _dm())
    asyncio.run(tw.events(_req(body=raw, sig=_sign(raw, "s3cret")), db))
    assert "schedule" not in called                   # persisted, no AI reply
    assert any(isinstance(o, Message) for o in db.added)


def test_share_post_becomes_buying_signal_text(monkeypatch):
    db = _FakeDB([_Res(None)])
    conv, called = _wire_receive(monkeypatch)
    content = _dm()
    content.pop("text")
    content["type"] = "share_post"
    content["share_post"] = {"embed_url": "https://tiktok.com/v/123"}
    raw = _event("im_receive_msg", content)
    asyncio.run(tw.events(_req(body=raw, sig=_sign(raw, "s3cret")), db))
    assert "shared one of our TikTok videos" in called["schedule"]["text"]


def test_owner_reply_from_tiktok_app_persists_as_human(monkeypatch):
    """im_send_msg we did NOT send (owner typed in the app) → human outbound."""
    db = _FakeDB([_Res(None)])            # unknown message_id
    conv = types.SimpleNamespace(id="c1", person_id="p1",
                                 intercept_mode=InterceptMode.ai,
                                 last_message_at=None, last_message_preview=None)

    async def fake_conv(db_, channel, external_id, **kw):
        return conv

    monkeypatch.setattr(settings, "tiktok_app_secret", "s3cret", raising=False)
    monkeypatch.setattr("app.services.channel.get_or_create_conversation", fake_conv)
    content = _dm(text="Tuko na hizo — nakutumia picha kesho.",
                  from_id="biz_open_id", to_id="cust_1", mid="m9")
    raw = _event("im_send_msg", content)
    asyncio.run(tw.events(_req(body=raw, sig=_sign(raw, "s3cret")), db))
    saved = [o for o in db.added if isinstance(o, Message)]
    assert saved and saved[0].sender == MsgSender.human_agent \
        and saved[0].direction == MsgDirection.outbound \
        and saved[0].external_id == "cust_1"


# ── token lifecycle ──────────────────────────────────────────────────────────

def test_access_token_refreshes_when_expiring(monkeypatch):
    db = _FakeDB()
    from app.models.app_setting import AppSetting
    stale = {"business_id": "biz", "access_token": "old", "refresh_token": "r1",
             "expires_at": "2020-01-01T00:00:00+00:00",
             "refresh_expires_at": "2999-01-01T00:00:00+00:00"}
    db.settings_rows["tiktok_oauth"] = AppSetting(id="tiktok_oauth", value=json.dumps(stale))
    monkeypatch.setattr(settings, "tiktok_app_id", "app", raising=False)
    monkeypatch.setattr(settings, "tiktok_app_secret", "sec", raising=False)

    async def fake_post(path, body):
        assert path.endswith("/refresh_token/")
        assert body["refresh_token"] == "r1"
        return {"access_token": "new", "refresh_token": "r2", "expires_in": 86400,
                "refresh_token_expires_in": 3600 * 24 * 30}

    monkeypatch.setattr(tn, "_oauth_post", fake_post)
    token, biz = asyncio.run(tn.access_token(db))
    assert token == "new" and biz == "biz"
    assert json.loads(db.settings_rows["tiktok_oauth"].value)["refresh_token"] == "r2"


def test_access_token_raises_when_unconnected(monkeypatch):
    monkeypatch.setattr(settings, "tiktok_app_id", "app", raising=False)
    monkeypatch.setattr(settings, "tiktok_app_secret", "sec", raising=False)
    with pytest.raises(tn.TikTokNotConnected):
        asyncio.run(tn.access_token(_FakeDB()))


# ── the send flip ────────────────────────────────────────────────────────────

def test_send_to_channel_uses_native_when_configured(monkeypatch):
    from app.services import meta_send
    sent = {}

    async def fake_send_to_user(external_id, text):
        sent["to"] = (external_id, text)
        return "tt_mid_1"

    monkeypatch.setattr(settings, "tiktok_app_id", "app", raising=False)
    monkeypatch.setattr(settings, "tiktok_app_secret", "sec", raising=False)
    monkeypatch.setattr(tn, "send_to_user", fake_send_to_user)
    out = asyncio.run(meta_send.send_to_channel("tiktok", "cust_1", "Karibu!"))
    assert out == "tt_mid_1" and sent["to"] == ("cust_1", "Karibu!")


def test_send_to_channel_still_refuses_without_app(monkeypatch):
    from app.services import meta_send
    monkeypatch.setattr(settings, "tiktok_app_id", "", raising=False)
    monkeypatch.setattr(settings, "tiktok_app_secret", "", raising=False)
    with pytest.raises(RuntimeError):
        asyncio.run(meta_send.send_to_channel("tiktok", "cust_1", "hi"))


# ── ManyChat cutover guard ───────────────────────────────────────────────────

def test_manychat_relay_steps_aside_when_native_live(monkeypatch):
    import app.routers.manychat as mc

    async def fake_native_live(db):
        return True

    monkeypatch.setattr(tn, "native_live", fake_native_live)
    db = _FakeDB()
    out = asyncio.run(mc.manychat_webhook(
        mc.ManyChatIn(subscriber_id="424242", message="hi"),
        types.SimpleNamespace(app=types.SimpleNamespace(
            state=types.SimpleNamespace(redis=None))), db))
    assert out == {"reply": "", "handled_by": "native"}
    assert not db.added                               # native path owns the record


# ── oauth callback state gate ────────────────────────────────────────────────

def test_oauth_callback_rejects_bad_state(monkeypatch):
    class _Redis:
        async def getdel(self, k):
            return None

    monkeypatch.setattr(settings, "tiktok_app_id", "app", raising=False)
    monkeypatch.setattr(settings, "tiktok_app_secret", "sec", raising=False)
    req = types.SimpleNamespace(app=types.SimpleNamespace(
        state=types.SimpleNamespace(redis=_Redis())))
    with pytest.raises(HTTPException) as e:
        asyncio.run(tw.oauth_callback(req, code="c", state="tampered", db=_FakeDB()))
    assert e.value.status_code == 403
