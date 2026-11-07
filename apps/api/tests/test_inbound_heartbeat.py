"""Are customer messages still arriving? Every inbound door stamps the
channel when it accepts a customer message; /api/health reports, per
channel, when the last one landed and how many came in the rolling hour.
Twice the owner reported "no new inbound chats" and nothing outside the box
could answer; now one curl does. Coarse on purpose: a channel, a time, a
count — never a number, a handle or a text."""
import asyncio
import types
from datetime import datetime, timedelta, timezone

import app.main  # noqa: F401 — registers models
from app.core.config import settings
from app.routers import whatsapp_webhook as ww
from app.routers.health import health
from app.services import inbound_health as ih


class _Redis:
    def __init__(self, kv=None):
        self.kv = dict(kv or {})
        self.expires = {}

    async def get(self, k):
        return self.kv.get(k)

    async def set(self, k, v, nx=False, ex=None):
        if nx and k in self.kv:
            return False
        self.kv[k] = v
        if ex:
            self.expires[k] = ex
        return True

    async def incr(self, k):
        self.kv[k] = int(self.kv.get(k) or 0) + 1
        return self.kv[k]

    async def expire(self, k, ttl):
        self.expires[k] = ttl
        return True

    async def publish(self, ch, msg):
        pass


def _req(redis):
    return types.SimpleNamespace(app=types.SimpleNamespace(state=types.SimpleNamespace(redis=redis)))


def test_a_stamp_records_the_time_and_counts_the_rolling_hour():
    r = _Redis()
    asyncio.run(ih.stamp(r, "whatsapp"))
    asyncio.run(ih.stamp(r, "whatsapp"))
    asyncio.run(ih.stamp(r, "messenger"))
    out = asyncio.run(ih.read(r))
    assert out["whatsapp"]["last_hour"] == 2 and out["whatsapp"]["last_at"]
    assert out["messenger"]["last_hour"] == 1
    assert out["instagram"] == {"last_at": None, "last_hour": 0, "silent_for_min": None}
    assert out["whatsapp"]["silent_for_min"] == 0 and out["quiet_for_min"] == 0
    # the hour count expires; the last-seen mark survives a quiet month
    assert r.expires["inbound:count:whatsapp"] == 3600
    assert r.expires["inbound:last:whatsapp"] == 30 * 24 * 3600


def test_silence_is_measured_from_the_newest_channel():
    now = datetime(2026, 11, 7, 12, 0, tzinfo=timezone.utc)
    r = _Redis({
        "inbound:last:whatsapp": (now - timedelta(hours=4, minutes=10)).isoformat(timespec="seconds"),
        "inbound:last:messenger": (now - timedelta(minutes=25)).isoformat(timespec="seconds"),
        "inbound:count:messenger": "1",
    })
    out = asyncio.run(ih.read(r, now=now))
    assert out["whatsapp"]["silent_for_min"] == 250 and out["whatsapp"]["last_hour"] == 0
    assert out["messenger"]["silent_for_min"] == 25 and out["messenger"]["last_hour"] == 1
    assert out["quiet_for_min"] == 25


def test_an_unknown_channel_and_a_dead_redis_cost_nothing():
    asyncio.run(ih.stamp(None, "whatsapp"))
    r = _Redis()
    asyncio.run(ih.stamp(r, "carrier-pigeon"))
    assert r.kv == {}

    class _Broken:
        async def get(self, k): raise RuntimeError("redis down")
        async def set(self, *a, **k): raise RuntimeError("redis down")
        async def incr(self, k): raise RuntimeError("redis down")
    asyncio.run(ih.stamp(_Broken(), "whatsapp"))          # swallowed
    out = asyncio.run(ih.read(_Broken()))
    assert out["whatsapp"] == {"last_at": None, "last_hour": 0, "silent_for_min": None}
    assert out["quiet_for_min"] is None


def test_health_carries_the_inbound_block():
    r = _Redis()
    asyncio.run(ih.stamp(r, "instagram"))
    out = asyncio.run(health(_req(r)))
    assert out["inbound"]["instagram"]["last_hour"] == 1
    assert set(out["inbound"]) == set(ih.CHANNELS) | {"quiet_for_min"}
    # never anything but a channel, a time and a count
    for ch in ih.CHANNELS:
        assert set(out["inbound"][ch]) == {"last_at", "last_hour", "silent_for_min"}


def test_the_whatsapp_door_stamps_only_when_a_message_was_ingested(monkeypatch):
    monkeypatch.setattr(settings, "meta_app_secret", "", raising=False)
    from app.services import wa_native
    r = _Redis()
    for name in ("_handle_calls", "_tap_inbound_wamids", "_tap_call_permission",
                 "_tap_voicemail", "_tap_account_updates"):
        async def _noop(*a, **k): return None
        monkeypatch.setattr(ww, name, _noop)
    async def _one(payload, redis): return (1, 0)
    monkeypatch.setattr(wa_native, "handle_webhook", _one)
    body = b'{"object":"whatsapp_business_account","entry":[]}'
    asyncio.run(ww.process_payload(_req(r), body, None))
    assert int(r.kv["inbound:count:whatsapp"]) == 1 and r.kv["inbound:last:whatsapp"]
    # a delivery that carried no customer message (read receipts only) stamps nothing
    async def _none(payload, redis): return (0, 0)
    monkeypatch.setattr(wa_native, "handle_webhook", _none)
    r2 = _Redis()
    asyncio.run(ww.process_payload(_req(r2), body, None))
    assert "inbound:count:whatsapp" not in r2.kv
