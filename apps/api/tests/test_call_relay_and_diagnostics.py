"""Calls that would not connect (owner, 2026-11-15): our own relay with
short-lived credentials, and a record of why a call's audio failed."""
import asyncio
import base64
import hashlib
import hmac
import inspect

import app.main  # noqa: F401
from app.core.config import settings
from app.services import call_diagnostics as cd, wa_calling


def test_relay_credentials_expire_and_are_derived_from_the_secret():
    got = wa_calling.turn_credentials("s3cret", 3600, now=1_000_000)
    assert got["username"] == "1003600:neema"
    want = base64.b64encode(hmac.new(b"s3cret", b"1003600:neema", hashlib.sha1).digest()).decode()
    assert got["credential"] == want and "s3cret" not in str(got)
    # a silly lifetime is still a lifetime
    assert wa_calling.turn_credentials("s", 0, now=10)["username"].startswith("70:")


def test_our_relay_is_offered_first_with_expiring_credentials(monkeypatch):
    monkeypatch.setattr(settings, "turn_url",
                        "turn:1.2.3.4:3478, turn:1.2.3.4:3478?transport=tcp", raising=False)
    monkeypatch.setattr(settings, "turn_secret", "s3cret", raising=False)
    monkeypatch.setattr(settings, "turn_username", "static", raising=False)
    monkeypatch.setattr(settings, "turn_credential", "static-pass", raising=False)
    first = wa_calling.ice_servers()[0]
    assert first["urls"] == ["turn:1.2.3.4:3478", "turn:1.2.3.4:3478?transport=tcp"]
    assert first["username"].endswith(":neema") and first["credential"] != "static-pass"
    assert wa_calling.relay_configured() is True
    # the static pair still works for a managed relay (no secret)
    monkeypatch.setattr(settings, "turn_secret", "", raising=False)
    assert wa_calling.ice_servers()[0]["username"] == "static"
    monkeypatch.setattr(settings, "turn_url", "", raising=False)
    assert wa_calling.relay_configured() is False


def test_a_report_is_cut_to_a_fixed_set_of_short_fields():
    row = cd.clean({"stage": "connect_guard", "direction": "outbound", "connection": "connecting",
                    "ice": "checking", "gathering": "complete", "local": {"host": 2, "srflx": 1, "x": 9},
                    "remote": {"host": 2}, "pair": "none", "relay_offered": True, "relay_errors": "3",
                    "seconds": 21, "client": "web", "platform": "iPhone · Chrome " + "x" * 200,
                    "network": "cellular", "phone": "+254700000000", "sdp": "v=0…"})
    assert "phone" not in row and "sdp" not in row
    assert row["local"] == {"host": 2, "srflx": 1, "prflx": 0, "relay": 0}
    assert row["relay_errors"] == 3 and len(row["platform"]) <= 60
    # anything unexpected becomes "unknown", never stored as sent
    odd = cd.clean({"stage": "<script>", "connection": "DROP TABLE", "client": "curl"})
    assert odd["stage"] == "unknown" and odd["connection"] == "unknown" and odd["client"] == "unknown"
    assert cd.clean(None)["local"] == {}


def test_each_report_gets_a_plain_reading():
    base = {"stage": "connect_guard", "pair": "none"}
    assert "no network path" in cd.reading(dict(base, local={}))
    assert "No relay of our own" in cd.reading(dict(base, local={"host": 2}, relay_offered=False))
    assert "could not reach it" in cd.reading(dict(base, local={"host": 2, "srflx": 1}, relay_offered=True))
    assert "relay path existed" in cd.reading(dict(base, local={"relay": 1}, relay_offered=True))
    assert "microphone" in cd.reading({"stage": "mic"})


class _R:
    def __init__(self):
        self.rows = []

    async def lpush(self, k, v):
        self.rows.insert(0, v)

    async def ltrim(self, k, a, b):
        self.rows = self.rows[a:b + 1]

    async def lrange(self, k, a, b):
        return self.rows[a:b + 1]


def test_reports_are_kept_newest_first_and_counted_by_reading():
    class _Agent:
        name = "Ann"

    async def go():
        r = _R()
        await cd.record(r, "wacid.HBgMMjU0NzAwMDAwMDAw", _Agent(), {"stage": "connect_guard", "local": {"host": 1}})
        await cd.record(r, "wacid.2", _Agent(), {"stage": "mic"})
        await cd.record(None, "wacid.3", _Agent(), {})          # redis down: never raises
        return await cd.recent(r), await cd.recent(None)
    got, none = asyncio.run(go())
    assert got["count"] == 2 and got["items"][0]["stage"] == "mic"
    assert got["items"][1]["agent"] == "Ann" and len(got["items"][1]["call"]) == 8
    assert sum(got["by_reading"].values()) == 2
    assert none == {"count": 0, "by_reading": {}, "items": []}


def test_an_answered_call_with_no_audio_is_logged_failed_not_completed():
    from app.routers import admin
    from app.services import call_log
    src = inspect.getsource(admin.calls_terminate)
    assert 'status == "answered" and reason == "failed"' in src and "mark_audio_failed" in src
    assert 'only_if=("answered",)' in inspect.getsource(call_log.mark_audio_failed)
    cfg = inspect.getsource(admin.calls_ice_config)
    assert '"relay": relay_configured()' in cfg
