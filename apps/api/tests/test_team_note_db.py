"""ONE TEAM NOTE PER THREAD (owner, 2026-11-15).

Notes piled up in the chat as separate yellow cards — "too many and too long".
A thread now keeps one note the team edits in place, in a floating panel above
the reply box. Pinned on a real Postgres: reading an empty note, saving and
replacing it (who and when recorded), clearing it, the length limit, a stale
edit refused with the colleague's version, and the note never becoming a
message row (so it can never reach the model or the customer).
"""
import types
import uuid

import pytest
import sqlalchemy as sa

from tests.test_security_db import _as, _reachable, _sync_url, fresh_db  # noqa: F401

pytestmark = pytest.mark.skipif(
    not _sync_url() or not _reachable(_sync_url()),
    reason="needs a reachable Postgres (CI migrations job / Docker harness)")

WA = "254700555010"


@pytest.fixture
def env(fresh_db, monkeypatch):  # noqa: F811
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool
    import app.database as database
    from app.database import get_db
    from app.routers import admin

    async_url = fresh_db.replace("postgresql+psycopg2://", "postgresql+asyncpg://")
    engine = create_async_engine(async_url, poolclass=NullPool)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(database, "AsyncSessionLocal", maker)

    ids = {"ann": str(uuid.uuid4()), "ben": str(uuid.uuid4()), "conv": str(uuid.uuid4())}
    eng = sa.create_engine(fresh_db)
    with eng.begin() as c:
        c.execute(sa.text("TRUNCATE messages, conversations, agents CASCADE"))
        for key, name in (("ann", "Ann Wanjiru"), ("ben", "Ben Otieno")):
            c.execute(sa.text(
                "INSERT INTO agents (id, name, email, password_hash, role, is_available, "
                "is_superuser, active_convs, created_at) VALUES "
                "(:id, :n, :e, 'x', 'agent', TRUE, FALSE, 0, NOW())"),
                {"id": ids[key], "n": name, "e": f"{key}@x.ke"})
        c.execute(sa.text(
            "INSERT INTO conversations (id, wa_id, channel, external_id, intercept_mode, status, created_at, updated_at) "
            "VALUES (:id, :wa, 'whatsapp', :wa, 'ai', 'open', NOW(), NOW())"), {"id": ids["conv"], "wa": WA})
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
    app.dependency_overrides[get_db] = _db
    app.state.redis = None
    with TestClient(app) as cl:
        yield types.SimpleNamespace(client=cl, db_url=fresh_db, ids=ids)


def _url(env):
    return f"/api/admin/conversations/{env.ids['conv']}/team-note"


def test_a_thread_starts_with_no_note(env):
    r = env.client.get(_url(env), headers=_as(env.ids["ann"]))
    assert r.status_code == 200
    assert r.json() == {"text": "", "by_name": None, "at": None}


def test_a_note_is_saved_replaced_and_cleared_in_place(env):
    r = env.client.put(_url(env), json={"text": "  Bayanda pays in rand; DHL to Durban.  "},
                       headers=_as(env.ids["ann"]))
    assert r.status_code == 200, r.text
    first = r.json()
    assert first["text"] == "Bayanda pays in rand; DHL to Durban."
    assert first["by_name"] == "Ann Wanjiru" and first["at"]

    # A colleague replaces it — still one note, now theirs.
    r = env.client.put(_url(env), json={"text": "Paid. Ship Monday.", "expected_at": first["at"]},
                       headers=_as(env.ids["ben"]))
    assert r.status_code == 200, r.text
    assert env.client.get(_url(env), headers=_as(env.ids["ann"])).json()["text"] == "Paid. Ship Monday."
    assert env.client.get(_url(env), headers=_as(env.ids["ann"])).json()["by_name"] == "Ben Otieno"

    # Empty clears it.
    r = env.client.put(_url(env), json={"text": ""}, headers=_as(env.ids["ben"]))
    assert r.status_code == 200 and r.json()["text"] == ""

    # The note is a field on the thread, never a message row: it cannot reach
    # the model's history or the customer.
    eng = sa.create_engine(env.db_url)
    with eng.connect() as c:
        assert c.execute(sa.text("SELECT count(*) FROM messages")).scalar() == 0
    eng.dispose()


def test_a_stale_edit_is_refused_with_the_colleagues_version(env):
    r = env.client.put(_url(env), json={"text": "v1"}, headers=_as(env.ids["ann"]))
    v1 = r.json()["at"]
    env.client.put(_url(env), json={"text": "v2 by Ben", "expected_at": v1}, headers=_as(env.ids["ben"]))

    # Ann was still editing v1.
    r = env.client.put(_url(env), json={"text": "v2 by Ann", "expected_at": v1}, headers=_as(env.ids["ann"]))
    assert r.status_code == 409
    cur = r.json()["detail"]["current"]
    assert cur["text"] == "v2 by Ben" and cur["by_name"] == "Ben Otieno"
    assert env.client.get(_url(env), headers=_as(env.ids["ann"])).json()["text"] == "v2 by Ben"

    # The first save on an empty thread expects no note at all.
    env.client.put(_url(env), json={"text": ""}, headers=_as(env.ids["ann"]))


def test_limits_and_unknown_threads(env):
    r = env.client.put(_url(env), json={"text": "x" * 1001}, headers=_as(env.ids["ann"]))
    assert r.status_code == 422
    r = env.client.put(_url(env), json={"text": 5}, headers=_as(env.ids["ann"]))
    assert r.status_code == 422
    r = env.client.get(f"/api/admin/conversations/{uuid.uuid4()}/team-note", headers=_as(env.ids["ann"]))
    assert r.status_code == 404
    r = env.client.get("/api/admin/conversations/not-a-uuid/team-note", headers=_as(env.ids["ann"]))
    assert r.status_code == 404
    assert env.client.get(_url(env)).status_code in (401, 403)
