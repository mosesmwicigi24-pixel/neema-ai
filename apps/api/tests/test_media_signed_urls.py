"""Signed, expiring media links (owner decision, follow-up to the calls & audio
programme): /api/admin/media/{name} serves a file only to a holder of a valid
?exp=&sig= link — the API signs every media URL it hands out, at read time.

Rollout switch MEDIA_SIGNED_URLS_REQUIRED: off = unsigned still served (and
logged) so a deploy can't break playback mid-flight; on = unsigned refused.
A request that carries a signature is checked in BOTH modes.
"""
import asyncio
import hashlib
import hmac
import json
import time
from urllib.parse import parse_qs, urlsplit

import pytest

NAME = "wa_1234567890123456.ogg"


def run(coro):
    return asyncio.run(coro)


def _qs(url):
    q = parse_qs(urlsplit(url).query)
    return int(q["exp"][0]), q["sig"][0]


# ── 1. the signer ────────────────────────────────────────────────────────────

def test_a_signed_link_verifies_and_any_tampering_does_not():
    from app.core import media_urls as mu
    url = mu.sign_media_url(f"https://neema.x/api/admin/media/{NAME}")
    assert url.startswith(f"https://neema.x/api/admin/media/{NAME}?exp=")
    exp, sig = _qs(url)
    assert mu.verify(NAME, exp, sig)
    assert not mu.verify("call_other.webm", exp, sig)                 # another file
    assert not mu.verify(NAME, exp + 1, sig)                           # a later expiry
    flipped = ("0" if sig[0] != "0" else "1") + sig[1:]
    assert not mu.verify(NAME, exp, flipped)                           # a forged signature
    for bad_exp, bad_sig in ((None, sig), (exp, None), ("", ""), ("12a", sig), (exp, sig[:-1]),
                             (-5, sig), (exp, "zz" * 32)):
        assert not mu.verify(NAME, bad_exp, bad_sig)


def test_an_expired_link_does_not_verify():
    from app.core import media_urls as mu
    url = mu.sign_media_url(f"/api/admin/media/{NAME}", 600, now=time.time() - 7200)
    exp, sig = _qs(url)
    assert exp < time.time()
    assert not mu.verify(NAME, exp, sig)


def test_the_key_comes_from_secret_key_unless_media_url_secret_overrides_it(monkeypatch):
    from app.core import media_urls as mu
    from app.core.config import settings
    monkeypatch.setattr(settings, "media_url_secret", "")
    exp = int(time.time()) + 3600
    base = hmac.new(settings.secret_key.encode(), b"neema-media-url-v1", hashlib.sha256).digest()
    want = hmac.new(base, f"{NAME}\n{exp}".encode(), hashlib.sha256).hexdigest()
    assert mu.signature(NAME, exp) == want
    monkeypatch.setattr(settings, "media_url_secret", "a-separate-media-secret")
    assert mu.signature(NAME, exp) != want                 # rotating it voids old links


def test_only_our_media_urls_are_signed():
    from app.core import media_urls as mu
    for foreign in ("https://scontent.xx.fbcdn.net/v/t1/abc.jpg?oh=1&oe=2",
                    "https://hub.bethanyhouse.co.ke/storage/products/stole.webp",
                    "https://bethanyhouse.co.ke/product/stole",
                    "https://neema.x/api/admin/media/",            # no file
                    "https://neema.x/api/admin/media/a/b.jpg",     # a sub-path
                    "/api/admin/media/.write_check",               # hidden
                    "ftp://neema.x/api/admin/media/x.jpg",
                    "", None):
        assert mu.sign_media_url(foreign) == foreign, foreign
    # absolute (any host), rooted, and a bare stored name are ours
    for ours, base in ((f"https://neema.x/api/admin/media/{NAME}", f"https://neema.x/api/admin/media/{NAME}"),
                       (f"/api/admin/media/{NAME}", f"/api/admin/media/{NAME}"),
                       (NAME, NAME)):
        signed = mu.sign_media_url(ours)
        assert signed.split("?")[0] == base and mu.verify(NAME, *_qs(signed))


def test_resigning_a_signed_link_replaces_its_query_and_storage_strips_it():
    from app.core import media_urls as mu
    once = mu.sign_media_url(f"https://neema.x/api/admin/media/{NAME}", now=time.time() - 50_000)
    twice = mu.sign_media_url(once)
    assert twice.count("?") == 1 and mu.verify(NAME, *_qs(twice))
    assert mu.canonical_media_url(once) == f"https://neema.x/api/admin/media/{NAME}"
    assert mu.canonical_media_url("https://cdn.x/p.jpg?a=1") == "https://cdn.x/p.jpg?a=1"


def test_links_signed_within_one_bucket_are_identical_and_last_at_least_the_ttl():
    """A 20 s thread poll must not change every <img src> (re-download,
    flicker), and a live event must equal the next poll's link."""
    from app.core import media_urls as mu
    t0 = 1_800_000_000.0                       # a bucket boundary for a 3600 s ttl (900 s buckets)
    a = mu.sign_media_url(NAME, 3600, now=t0 + 1)
    b = mu.sign_media_url(NAME, 3600, now=t0 + 600)
    assert a == b
    exp, _ = _qs(a)
    assert t0 + 600 + 3600 <= exp <= t0 + 1 + 3600 + 900


def test_meta_links_carry_the_long_lifetime_dashboard_links_the_short_one():
    from app.core import media_urls as mu
    now = time.time()
    dash, _ = _qs(mu.sign_media_url(f"https://n.x/api/admin/media/{NAME}"))
    meta, _ = _qs(mu.sign_for_meta(f"https://n.x/api/admin/media/{NAME}"))
    assert now + 3600 <= dash <= now + 3600 + 900
    assert now + 86400 <= meta <= now + 86400 + 21600


def test_a_payload_has_every_media_key_signed_nested_and_nothing_else_touched():
    from app.core import media_urls as mu
    payload = {"type": "new_message", "text": f"see /api/admin/media/{NAME}",
               "mediaUrl": f"https://n.x/api/admin/media/{NAME}",
               "reply_to": {"media_url": f"/api/admin/media/{NAME}"},
               "items": [{"recording_url": "call_ab.webm"}],
               "image": f"https://n.x/api/admin/media/{NAME}"}
    out = mu.sign_media_fields(payload)
    assert mu.verify(NAME, *_qs(out["mediaUrl"]))
    assert mu.verify(NAME, *_qs(out["reply_to"]["media_url"]))
    assert mu.verify("call_ab.webm", *_qs(out["items"][0]["recording_url"]))
    assert out["text"] == payload["text"] and out["image"] == payload["image"]
    assert payload["mediaUrl"] == f"https://n.x/api/admin/media/{NAME}"     # input not mutated


# ── 2. the route ─────────────────────────────────────────────────────────────

@pytest.fixture
def media_app(tmp_path, monkeypatch):
    import app.routers.media as media_router
    from fastapi import FastAPI
    d = tmp_path / "media"
    d.mkdir()
    (d / NAME).write_bytes(b"VOICE")
    monkeypatch.setattr(media_router, "MEDIA_DIR", str(d))
    a = FastAPI()
    a.include_router(media_router.router, prefix="/api")
    return a


def _get(app, path, query=""):
    out = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(m):
        out.append(m)

    scope = {"type": "http", "method": "GET", "path": path, "raw_path": path.encode(),
             "query_string": query.encode(), "headers": [(b"user-agent", b"pytest")],
             "http_version": "1.1", "scheme": "http", "server": ("t", 80), "client": ("c", 1),
             "root_path": ""}
    try:
        run(app(scope, receive, send))
    except Exception as exc:
        return 500, repr(exc).encode()
    start = next(m for m in out if m["type"] == "http.response.start")
    return start["status"], b"".join(m.get("body", b"") for m in out if m["type"] == "http.response.body")


def _signed_query(name=NAME, ttl=None, now=None):
    from app.core import media_urls as mu
    return mu.sign_media_url(name, ttl, now=now).split("?", 1)[1]


@pytest.fixture(params=[False, True], ids=["lenient", "required"])
def mode(request, monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "media_signed_urls_required", request.param)
    return request.param


def test_a_valid_signed_link_is_served_in_both_modes(media_app, mode):
    assert _get(media_app, f"/api/admin/media/{NAME}", _signed_query()) == (200, b"VOICE")


def test_an_unsigned_request_is_refused_only_when_required(media_app, mode, caplog):
    import logging
    with caplog.at_level(logging.INFO, logger="neema.media"):
        status, body = _get(media_app, f"/api/admin/media/{NAME}")
    if mode:
        assert status == 404 and body != b"VOICE"
    else:
        assert (status, body) == (200, b"VOICE")
        assert any("media.unsigned" in r.getMessage() for r in caplog.records)


def test_tampered_or_expired_links_are_404_in_both_modes(media_app, mode, tmp_path):
    import app.routers.media as media_router
    (tmp_path / "media" / "call_secret.webm").write_bytes(b"OTHER")
    good = _signed_query()
    exp = good.split("&")[0]
    sig = good.split("sig=")[1]
    forged = ("0" if sig[0] != "0" else "1") + sig[1:]
    cases = [
        ("/api/admin/media/call_secret.webm", good),                   # signature for another file
        (f"/api/admin/media/{NAME}", f"exp={int(exp[4:]) + 900}&sig={sig}"),   # pushed expiry
        (f"/api/admin/media/{NAME}", f"{exp}&sig={forged}"),            # forged signature
        (f"/api/admin/media/{NAME}", exp),                               # sig missing
        (f"/api/admin/media/{NAME}", f"sig={sig}"),                      # exp missing
        (f"/api/admin/media/{NAME}", _signed_query(ttl=600, now=time.time() - 7200)),  # expired
    ]
    for path, q in cases:
        status, body = _get(media_app, path, q)
        assert status == 404 and body not in (b"VOICE", b"OTHER"), (path, q, status)
    # refused exactly like a file that does not exist: nothing confirms the name
    missing = _get(media_app, "/api/admin/media/nope.ogg", _signed_query("nope.ogg"))
    refused = _get(media_app, "/api/admin/media/call_secret.webm", good)
    assert missing == refused
    assert media_router.MEDIA_DIR.endswith("media")


def test_containment_still_holds_for_a_validly_signed_dot_name(media_app, mode):
    from app.core import media_urls as mu
    e = int(time.time()) + 3600
    for name in ("..", "."):
        status, _ = _get(media_app, f"/api/admin/media/{name}", f"exp={e}&sig={mu.signature(name, e)}")
        assert status == 404


# ── 3. what leaves for Meta is signed with the long lifetime ─────────────────

class _Resp:
    is_success = True
    status_code = 200
    text = "{}"

    def json(self):
        return {"messages": [{"id": "wamid.X"}]}

    def raise_for_status(self):
        return None


def _capture_httpx(monkeypatch):
    import httpx
    sent = []

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json=None, **k):
            sent.append(json)
            return _Resp()

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    return sent


def _assert_meta_signed(url, name=NAME):
    from app.core import media_urls as mu
    exp, sig = _qs(url)
    assert mu.verify(name, exp, sig)
    assert exp >= time.time() + 86400 - 5


def test_whatsapp_media_send_hands_meta_a_24h_signed_link(monkeypatch):
    from app.services import conversation
    sent = _capture_httpx(monkeypatch)
    run(conversation._send_waba_media("254700000001", "audio",
                                      f"https://n.x/api/admin/media/{NAME}", None, None))
    _assert_meta_signed(sent[0]["audio"]["link"])


def test_whatsapp_image_audio_and_product_card_links_are_signed_for_meta(monkeypatch):
    from app.services import n8n_bridge as svc
    sent = _capture_httpx(monkeypatch)
    img = "https://n.x/api/admin/media/img_abc.jpg"
    run(svc._send_waba_image("254700000001", img))
    run(svc._send_waba_audio("254700000001", f"https://n.x/api/admin/media/{NAME}"))
    run(svc._send_waba_product_card("254700000001", image_url=img, title="Stole", body="KES 1",
                                    url="https://bethanyhouse.co.ke/product/stole"))
    _assert_meta_signed(sent[0]["image"]["link"], "img_abc.jpg")
    _assert_meta_signed(sent[1]["audio"]["link"])
    _assert_meta_signed(sent[2]["interactive"]["header"]["image"]["link"], "img_abc.jpg")
    # a hub photo is not ours: it goes out exactly as it was
    run(svc._send_waba_image("254700000001", "https://hub.x/p.jpg"))
    assert sent[3]["image"]["link"] == "https://hub.x/p.jpg"


def test_messenger_attachment_and_carousel_links_are_signed_for_meta(monkeypatch):
    from app.services import meta_send
    bodies = []

    async def fake_post(path, body, what, page_id=None):
        bodies.append(body)

    monkeypatch.setattr(meta_send, "_graph_post", fake_post)
    run(meta_send.send_meta_media("psid1", "image", "https://n.x/api/admin/media/img_abc.jpg"))
    run(meta_send.send_meta_carousel("psid1", [
        {"title": "A", "image_url": "https://n.x/api/admin/media/img_abc.jpg"},
        {"title": "B", "image_url": "https://hub.x/b.jpg"}, {"title": "C"}]))
    _assert_meta_signed(bodies[0]["message"]["attachment"]["payload"]["url"], "img_abc.jpg")
    els = bodies[1]["message"]["attachment"]["payload"]["elements"]
    _assert_meta_signed(els[0]["image_url"], "img_abc.jpg")
    assert els[1]["image_url"] == "https://hub.x/b.jpg" and "image_url" not in els[2]


# ── 4. the live socket: every frame's media links signed at delivery ─────────

def test_a_websocket_frame_reaches_the_dashboard_with_signed_links(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.core import media_urls as mu
    from app.routers import websocket as ws

    published = [
        json.dumps({"type": "new_message", "conversationId": "c1",
                    "mediaUrl": f"https://n.x/api/admin/media/{NAME}"}),
        json.dumps({"type": "typing", "conversationId": "c1"}),
    ]

    class PubSub:
        async def psubscribe(self, *_):
            return None

        async def punsubscribe(self, *_):
            return None

        async def aclose(self):
            return None

        async def listen(self):
            for p in published:
                yield {"type": "pmessage", "data": p}
            await asyncio.sleep(3600)

    class Redis:
        def pubsub(self):
            return PubSub()

    async def ok(token, agent_id):
        return True

    monkeypatch.setattr(ws, "_authorised", ok)
    app = FastAPI()
    app.include_router(ws.router)
    app.state.redis = Redis()
    with TestClient(app) as cl, cl.websocket_connect("/ws/a1?token=t") as sock:
        first = json.loads(sock.receive_text())
        second = sock.receive_text()
    assert mu.verify(NAME, *_qs(first["mediaUrl"]))
    assert second == published[1]                     # a frame without media: byte-identical


def test_a_non_json_frame_is_relayed_as_is():
    from app.core.media_urls import sign_ws_text
    assert sign_ws_text("mediaUrl not json") == "mediaUrl not json"
    assert sign_ws_text(b"bytes") == b"bytes"
