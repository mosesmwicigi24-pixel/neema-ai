"""Push — a call rings phones whose app is closed (owner, 2026-10-24: "The calls
should come through even the app is not open. When any phone is on, route the
call there"). The three call events go to every registered phone as
high-priority Firebase data messages; nothing else does, and a failure never
touches the call. No network: Firebase and Google's token endpoint are faked."""
import asyncio
import json
import time

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app.core.config import settings
from app.services import push


def _key():
    k = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                          serialization.NoEncryption()).decode()
    return k, pem


@pytest.fixture
def account(monkeypatch):
    k, pem = _key()
    acc = {"type": "service_account", "project_id": "neema-test", "client_email": "push@neema-test.iam.gserviceaccount.com",
           "private_key": pem, "token_uri": "https://oauth2.googleapis.com/token"}
    monkeypatch.setattr(settings, "fcm_service_account_json", json.dumps(acc))
    monkeypatch.setattr(push, "_account_cache", None)
    monkeypatch.setattr(push, "_token_cache", {"value": None, "expires": 0.0})
    return k


class Google:
    """Google's token endpoint and FCM, answering per token."""
    def __init__(self, answers=None):
        self.answers = answers or {}
        self.token_calls = 0
        self.sent = []
        self.assertions = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.url.host == "oauth2.googleapis.com":
            self.token_calls += 1
            form = dict(x.split("=", 1) for x in request.content.decode().split("&"))
            self.assertions.append(form["assertion"])
            return httpx.Response(200, json={"access_token": f"at-{self.token_calls}", "expires_in": 3600})
        body = json.loads(request.content)
        self.sent.append((request.url.path, request.headers.get("authorization"), body))
        status, payload = self.answers.get(body["message"]["token"], (200, {"name": "projects/x/messages/1"}))
        return httpx.Response(status, json=payload)


RING = {"type": "incoming_call", "call_id": "wacid.1", "from": "254712345678", "name": "Fr. Peter Kamau",
        "at": 1730000000, "channel": "whatsapp"}


def run(coro):
    return asyncio.run(coro)


def test_off_until_a_service_account_is_set(monkeypatch):
    monkeypatch.setattr(settings, "fcm_service_account_json", "")
    monkeypatch.setattr(push, "_account_cache", None)
    assert not push.configured()
    g = Google()
    assert run(push.send_call_event(RING, tokens=["t" * 40], transport=httpx.MockTransport(g))) == \
        {"sent": 0, "failed": 0, "forgotten": 0}
    assert g.sent == [] and g.token_calls == 0


def test_the_key_may_be_given_base64_or_as_a_file(monkeypatch, tmp_path):
    import base64
    _, pem = _key()
    acc = json.dumps({"project_id": "p", "client_email": "e@x", "private_key": pem})
    monkeypatch.setattr(settings, "fcm_service_account_json", base64.b64encode(acc.encode()).decode())
    monkeypatch.setattr(push, "_account_cache", None)
    assert push.configured()
    f = tmp_path / "key.json"
    f.write_text(acc)
    monkeypatch.setattr(settings, "fcm_service_account_json", str(f))
    assert push._account()["project_id"] == "p"


def test_an_unreadable_service_account_leaves_push_off(monkeypatch):
    monkeypatch.setattr(settings, "fcm_service_account_json", '{"project_id": "x"}')
    monkeypatch.setattr(push, "_account_cache", None)
    assert not push.configured()
    monkeypatch.setattr(settings, "fcm_service_account_json", "not base64 and no such file")
    assert not push.configured()


def test_a_ring_reaches_every_phone_high_priority_as_data(account):
    g = Google()
    out = run(push.send_call_event(RING, tokens=["phone-a" * 6, "phone-b" * 6], transport=httpx.MockTransport(g)))
    assert out == {"sent": 2, "failed": 0, "forgotten": 0}
    assert {b["message"]["token"] for _, _, b in g.sent} == {"phone-a" * 6, "phone-b" * 6}
    path, auth, body = g.sent[0]
    assert path == "/v1/projects/neema-test/messages:send" and auth == "Bearer at-1"
    m = body["message"]
    assert "notification" not in m, "data only: the app draws the call screen"
    assert m["data"] == {"type": "incoming_call", "call_id": "wacid.1", "from": "254712345678",
                         "name": "Fr. Peter Kamau", "at": "1730000000", "channel": "whatsapp"}
    assert all(isinstance(v, str) for v in m["data"].values())
    assert m["android"] == {"priority": "HIGH", "ttl": "60s", "collapse_key": "call-wacid.1"}


def test_the_access_token_is_signed_by_the_service_account_and_reused(account):
    g = Google()
    for _ in range(3):
        run(push.send_call_event(RING, tokens=["phone-a" * 6], transport=httpx.MockTransport(g)))
    assert g.token_calls == 1, "one access token for the hour, not one per call"
    claims = jwt.decode(g.assertions[0], account.public_key(), algorithms=["RS256"],
                        audience="https://oauth2.googleapis.com/token")
    assert claims["iss"] == "push@neema-test.iam.gserviceaccount.com"
    assert claims["scope"] == "https://www.googleapis.com/auth/firebase.messaging"
    assert claims["exp"] - claims["iat"] == 3600 and abs(claims["iat"] - time.time()) < 60


def test_answered_and_ended_stop_the_other_phones_and_messenger_rings_too(account):
    g = Google()
    run(push.send_call_event({"type": "call_answered", "call_id": "wacid.1", "agent_id": "a1",
                              "agent_name": "Ann", "direction": "inbound"}, tokens=["p" * 40],
                             transport=httpx.MockTransport(g)))
    run(push.send_call_event({"type": "call_ended", "call_id": "wacid.1", "outcome": "missed",
                              "duration": None}, tokens=["p" * 40], transport=httpx.MockTransport(g)))
    run(push.send_call_event({"type": "incoming_call", "call_id": "c_msg.9", "from": "7788", "name": None,
                              "channel": "messenger", "external_id": "7788"}, tokens=["p" * 40],
                             transport=httpx.MockTransport(g)))
    answered, ended, messenger = (b["message"] for _, _, b in g.sent)
    assert answered["data"]["type"] == "call_answered" and answered["data"]["agent_name"] == "Ann"
    assert answered["android"]["ttl"] == "120s" and answered["android"]["collapse_key"] == "call-wacid.1"
    assert answered["android"]["priority"] == ended["android"]["priority"] == "NORMAL", \
        "only the ring is urgent: Android lowers silent high-priority messages"
    assert messenger["android"]["priority"] == "HIGH"
    assert ended["data"] == {"type": "call_ended", "call_id": "wacid.1", "outcome": "missed"}
    assert messenger["data"]["channel"] == "messenger" and messenger["data"]["external_id"] == "7788"
    assert "name" not in messenger["data"], "a missing field is left out, never the string 'None'"


def test_nothing_but_call_events_is_pushed(account):
    g = Google()
    for evt in ({"type": "call_update", "call": {}}, {"type": "call_status", "call_id": "x", "status": "ringing"},
                {"type": "incoming_call"}):
        run(push.send_call_event(evt, tokens=["p" * 40], transport=httpx.MockTransport(g)))
    assert g.sent == []


def test_a_dead_token_is_forgotten_and_a_failing_one_kept(account, monkeypatch):
    forgotten = []

    async def forget(tokens):
        forgotten.extend(tokens)
    monkeypatch.setattr(push, "_forget", forget)
    g = Google({
        "gone" * 10: (404, {"error": {"status": "NOT_FOUND"}}),
        "unreg" * 8: (400, {"error": {"message": "x", "details": [{"errorCode": "UNREGISTERED"}]}}),
        "busy" * 10: (503, {"error": {"status": "UNAVAILABLE"}}),
    })
    out = run(push.send_call_event(RING, tokens=["ok" * 20, "gone" * 10, "unreg" * 8, "busy" * 10],
                                   transport=httpx.MockTransport(g)))
    assert out == {"sent": 1, "failed": 3, "forgotten": 2}
    assert sorted(forgotten) == sorted(["gone" * 10, "unreg" * 8]), "a busy Firebase is not a dead phone"


def test_a_refused_access_token_is_fetched_afresh_next_time(account):
    g = Google({"p" * 40: (401, {"error": {"status": "UNAUTHENTICATED"}})})
    run(push.send_call_event(RING, tokens=["p" * 40], transport=httpx.MockTransport(g)))
    g.answers = {}
    run(push.send_call_event(RING, tokens=["p" * 40], transport=httpx.MockTransport(g)))
    assert g.token_calls == 2 and g.sent[-1][1] == "Bearer at-2"


def test_firebase_down_never_raises(account):
    def boom(request):
        raise httpx.ConnectError("no route to host")
    assert run(push.send_call_event(RING, tokens=["p" * 40], transport=httpx.MockTransport(boom))) == \
        {"sent": 0, "failed": 0, "forgotten": 0}


def test_every_call_broadcast_also_schedules_the_push(monkeypatch):
    from app.services import call_log
    seen = []
    monkeypatch.setattr(push, "schedule", lambda e: seen.append(e["type"]))

    class R:
        published = []

        async def publish(self, ch, msg):
            self.published.append((ch, json.loads(msg)["type"]))
    r = R()
    run(call_log.publish(r, dict(RING)))
    run(call_log.publish(None, {"type": "call_ended", "call_id": "wacid.1"}))
    assert seen == ["incoming_call", "call_ended"], "even with redis down, the phones still ring"
    assert r.published == [("ws:channel:calls", "incoming_call")]


def test_a_push_that_cannot_be_scheduled_never_breaks_the_broadcast(monkeypatch):
    from app.services import call_log

    def bad(e):
        raise RuntimeError("scheduler gone")
    monkeypatch.setattr(push, "schedule", bad)

    class R:
        published = []

        async def publish(self, ch, msg):
            self.published.append(ch)
    r = R()
    run(call_log.publish(r, dict(RING)))
    assert r.published == ["ws:channel:calls"]
