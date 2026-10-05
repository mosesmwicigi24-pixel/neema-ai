"""Signed media links end to end on a real Postgres: rows keep the UNSIGNED
URL they always had (old rows included), the API re-signs on every read, and
the link it returns opens the file even with MEDIA_SIGNED_URLS_REQUIRED on —
while the stored, unsigned one no longer does.

Skips cleanly without a database (the Docker harness / CI migrations job has one).
"""
import io
import time
import types
import uuid
from urllib.parse import parse_qs, urlsplit

import pytest
import sqlalchemy as sa

from tests.test_security_db import _as, _reachable, _sync_url, fresh_db  # noqa: F401 — the throwaway-database fixture

pytestmark = pytest.mark.skipif(
    not _sync_url() or not _reachable(_sync_url()),
    reason="needs a reachable Postgres (CI migrations job / Docker harness)")

WA = "254700777001"
BASE = "https://neema.test"
VOICE = "wa_9988776655443322.ogg"
PHOTO = "f0e1d2c3b4a5968778695a4b3c2d1e0f.jpg"
CALL = "call_0f3e9a2b7c4d41e8a6b5c3d2e1f0a9b8.webm"


def _qs(url):
    q = parse_qs(urlsplit(url).query)
    return int(q["exp"][0]), q["sig"][0]


@pytest.fixture
def env(fresh_db, monkeypatch, tmp_path):  # noqa: F811
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool
    import app.database as database
    import app.routers.media as media_router
    from app.core.config import settings
    from app.database import get_db
    from app.routers import admin, media

    media_dir = tmp_path / "media"
    media_dir.mkdir()
    for name, data in ((VOICE, b"VOICE"), (PHOTO, b"PHOTO"), (CALL, b"CALL")):
        (media_dir / name).write_bytes(data)
    monkeypatch.setattr(media_router, "MEDIA_DIR", str(media_dir))
    monkeypatch.setattr(settings, "media_dir", str(media_dir))
    monkeypatch.setattr(settings, "media_public_url", BASE)
    monkeypatch.setattr(settings, "call_recording_enabled", True)
    monkeypatch.setattr(settings, "whisper_enabled", False)

    async_url = fresh_db.replace("postgresql+psycopg2://", "postgresql+asyncpg://")
    engine = create_async_engine(async_url, poolclass=NullPool)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(database, "AsyncSessionLocal", maker)

    ids = {"ann": str(uuid.uuid4()), "conv": str(uuid.uuid4()),
           "voice": str(uuid.uuid4()), "photo": str(uuid.uuid4()), "quote": str(uuid.uuid4())}
    eng = sa.create_engine(fresh_db)
    with eng.begin() as c:
        c.execute(sa.text("TRUNCATE calls, messages, conversations, users, persons, agents CASCADE"))
        c.execute(sa.text(
            "INSERT INTO agents (id, name, email, password_hash, role, is_available, "
            "is_superuser, active_convs, created_at) VALUES "
            "(:id, 'Ann Wanjiru', 'ann@x.ke', 'x', 'agent', TRUE, FALSE, 0, NOW())"), {"id": ids["ann"]})
        c.execute(sa.text(
            "INSERT INTO conversations (id, wa_id, channel, external_id, intercept_mode, status, created_at, updated_at) "
            "VALUES (:id, :wa, 'whatsapp', :wa, 'ai', 'open', NOW(), NOW())"), {"id": ids["conv"], "wa": WA})
        # OLD rows: stored before signing existed — absolute, and a bare name.
        for key, url, kind, mins in (("voice", f"{BASE}/api/admin/media/{VOICE}", "audio", 30),
                                     ("photo", PHOTO, "image", 20)):
            c.execute(sa.text(
                "INSERT INTO messages (id, wa_id, channel, external_id, conversation_id, direction, sender, "
                "text, media_type, media_url, created_at) VALUES (:id, :wa, 'whatsapp', :wa, :c, 'inbound', "
                "'user', '', :k, :u, NOW() - make_interval(mins => :m))"),
                {"id": ids[key], "wa": WA, "c": ids["conv"], "k": kind, "u": url, "m": mins})
        c.execute(sa.text(
            "INSERT INTO messages (id, wa_id, channel, external_id, conversation_id, direction, sender, "
            "text, reply_to_id, reply_to_text, created_at) VALUES (:id, :wa, 'whatsapp', :wa, :c, 'outbound', "
            "'human_agent', 'this one?', :q, '[image]', NOW() - interval '10 minutes')"),
            {"id": ids["quote"], "wa": WA, "c": ids["conv"], "q": ids["photo"]})
        c.execute(sa.text(
            "INSERT INTO calls (id, call_id, wa_id, channel, direction, status, started_at, recording_url, "
            "transcript_status) VALUES (:id, 'wacid.REC', :wa, 'whatsapp', 'inbound', 'completed', "
            "NOW() - interval '2 hours', :rec, 'recorded')"),
            {"id": str(uuid.uuid4()), "wa": WA, "rec": f"{BASE}/api/admin/media/{CALL}"})
    eng.dispose()

    async def _db():
        async with maker() as s:
            try:
                yield s
                await s.commit()
            except Exception:
                await s.rollback()
                raise

    app = FastAPI()
    app.include_router(admin.router, prefix="/api/admin")
    app.include_router(media.router, prefix="/api")
    app.dependency_overrides[get_db] = _db
    app.state.redis = None
    with TestClient(app) as cl:
        yield types.SimpleNamespace(client=cl, db_url=fresh_db, ids=ids)


def _required(monkeypatch, on=True):
    from app.core.config import settings
    monkeypatch.setattr(settings, "media_signed_urls_required", on)


def _open(env, url):
    """Fetch a link the API returned, the way a browser on the same origin would."""
    parts = urlsplit(url)
    path = parts.path if parts.path.startswith("/") else f"/api/admin/media/{parts.path}"
    return env.client.get(f"{path}?{parts.query}" if parts.query else path)


def _thread(env):
    r = env.client.get(f"/api/admin/conversations/{env.ids['conv']}/messages",
                       headers=_as(env.ids["ann"]))
    assert r.status_code == 200, r.text
    return {i["id"]: i for i in r.json() if i.get("type") == "message"}


def test_old_unsigned_rows_render_through_re_signed_links(env, monkeypatch):
    from app.core import media_urls as mu
    _required(monkeypatch)
    items = _thread(env)
    voice, photo = items[env.ids["voice"]]["media_url"], items[env.ids["photo"]]["media_url"]
    assert voice.startswith(f"{BASE}/api/admin/media/{VOICE}?exp=")
    assert photo.startswith(f"{PHOTO}?exp=")                  # a bare stored name stays bare (+ query)
    assert mu.verify(VOICE, *_qs(voice)) and mu.verify(PHOTO, *_qs(photo))
    quoted = items[env.ids["quote"]]["reply_to"]["media_url"]
    assert mu.verify(PHOTO, *_qs(quoted))
    r = _open(env, voice)
    assert (r.status_code, r.content) == (200, b"VOICE")
    assert _open(env, photo).content == b"PHOTO"
    # the stored, unsigned URL is refused now that signing is required
    assert env.client.get(f"/api/admin/media/{VOICE}").status_code == 404
    # nothing signed was written back to the rows
    eng = sa.create_engine(env.db_url)
    with eng.connect() as c:
        stored = c.execute(sa.text("SELECT media_url FROM messages WHERE media_url IS NOT NULL")).scalars().all()
    eng.dispose()
    assert stored and all("?" not in u for u in stored)


def test_unsigned_links_still_play_while_signing_is_not_required(env, monkeypatch):
    _required(monkeypatch, False)
    assert env.client.get(f"/api/admin/media/{VOICE}").content == b"VOICE"
    assert _open(env, _thread(env)[env.ids["voice"]]["media_url"]).content == b"VOICE"


def test_a_call_recording_url_is_signed_and_plays(env, monkeypatch):
    from app.core import media_urls as mu
    _required(monkeypatch)
    r = env.client.get("/api/admin/calls/wacid.REC/transcript", headers=_as(env.ids["ann"]))
    assert r.status_code == 200, r.text
    url = r.json()["recording_url"]
    assert mu.verify(CALL, *_qs(url))
    assert _open(env, url).content == b"CALL"


def test_upload_stores_unsigned_and_returns_a_signed_link(env, monkeypatch):
    from app.core import media_urls as mu
    from app.services import conversation
    _required(monkeypatch)
    meta = []

    async def fake_send(wa_id, media_type, media_url, caption, filename):
        meta.append(media_url)     # _send_waba_media signs it for Meta (test_media_signed_urls)

    monkeypatch.setattr(conversation, "_send_waba_media", fake_send)
    r = env.client.post(f"/api/admin/conversations/{env.ids['conv']}/upload-media",
                        headers=_as(env.ids["ann"]),
                        files={"file": ("collar.jpg", io.BytesIO(b"\xff\xd8JPEG"), "image/jpeg")})
    assert r.status_code == 200, r.text
    returned = r.json()["media_url"]
    name = urlsplit(returned).path.rsplit("/", 1)[1]
    assert mu.verify(name, *_qs(returned))
    assert _open(env, returned).status_code == 200
    eng = sa.create_engine(env.db_url)
    with eng.connect() as c:
        stored = c.execute(sa.text("SELECT media_url FROM messages WHERE media_url LIKE :n"),
                           {"n": f"%{name}"}).scalar_one()
    eng.dispose()
    assert stored == f"{BASE}/api/admin/media/{name}"
    assert meta == [stored]


def test_a_signed_link_handed_back_by_a_client_is_stored_unsigned(env, monkeypatch):
    """Forwarding a photo already in the thread: the client posts the signed
    link it was given — the row must not keep a signature that will expire."""
    from app.core import media_urls as mu
    from app.services import conversation
    sent = []

    async def fake_send(wa_id, media_type, media_url, caption, filename):
        sent.append(media_url)

    monkeypatch.setattr(conversation, "_send_waba_media", fake_send)
    signed = mu.sign_media_url(f"{BASE}/api/admin/media/{PHOTO}", now=time.time() - 30_000)
    r = env.client.post(f"/api/admin/conversations/{env.ids['conv']}/reply-media",
                        headers=_as(env.ids["ann"]),
                        json={"media_url": signed, "media_type": "image"})
    assert r.status_code == 200, r.text
    assert sent == [f"{BASE}/api/admin/media/{PHOTO}"]          # the sender signs it for Meta itself
    assert mu.verify(PHOTO, *_qs(r.json()["media_url"]))
    eng = sa.create_engine(env.db_url)
    with eng.connect() as c:
        rows = c.execute(sa.text("SELECT media_url FROM messages WHERE direction = 'outbound' "
                                 "AND media_url IS NOT NULL")).scalars().all()
    eng.dispose()
    assert rows == [f"{BASE}/api/admin/media/{PHOTO}"]


def test_recover_media_answers_with_a_signed_link(env, monkeypatch):
    from app.core import media_urls as mu
    _required(monkeypatch)
    r = env.client.post(f"/api/admin/messages/{env.ids['voice']}/recover-media",
                        headers=_as(env.ids["ann"]))
    assert r.status_code == 200, r.text
    url = r.json()["media_url"]
    assert mu.verify(VOICE, *_qs(url)) and _open(env, url).content == b"VOICE"
