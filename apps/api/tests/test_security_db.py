"""Backend security gaps (owner, 2026-09-26: "fix the backend security gaps"),
proven against a real Postgres.

Before this, the API checked only that a caller was signed in. The dashboard
hid the Team and Roles controls, but any agent could call the endpoints and
reset the admin's password, make themselves an admin, or rewrite the
protected Super Admin role; /admin/me handed back the password hash; a
refresh token worked as a month-long access token; and a follow-up could be
sent twice, or sent after it was vetoed.

Runs wherever DATABASE_URL_SYNC reaches a Postgres (the CI migrations job,
the Docker harness); skips cleanly elsewhere. Each test gets a throwaway
database with the real schema (models + main.py's startup DDL).
"""
import asyncio
import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import sqlalchemy as sa


def _sync_url() -> str | None:
    return os.environ.get("DATABASE_URL_SYNC")


def _reachable(url: str) -> bool:
    try:
        eng = sa.create_engine(url, connect_args={"connect_timeout": 3})
        with eng.connect():
            return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _sync_url() or not _reachable(_sync_url()),
    reason="needs a reachable Postgres (CI migrations job / Docker harness)")


# ── A throwaway database with the real schema ────────────────────────────────

@pytest.fixture(scope="module")
def fresh_db():
    import importlib
    import pkgutil
    import app.main  # noqa: F401
    import app.models as models_pkg
    from app.main import MIGRATION_STATEMENTS
    from app.models import Base
    # Some models are imported lazily by the code that uses them — register all.
    for mod in pkgutil.iter_modules(models_pkg.__path__):
        importlib.import_module(f"app.models.{mod.name}")

    base = _sync_url()
    admin = sa.create_engine(base, isolation_level="AUTOCOMMIT")
    name = f"sectest_{uuid.uuid4().hex[:10]}"
    with admin.connect() as c:
        c.execute(sa.text(f'CREATE DATABASE "{name}"'))
    sync_url = base.rsplit("/", 1)[0] + f"/{name}"
    eng = sa.create_engine(sync_url)
    Base.metadata.create_all(eng)
    with eng.begin() as c:
        for stmt in MIGRATION_STATEMENTS[:3]:     # custom_roles + agents columns
            c.execute(sa.text(stmt))
    eng.dispose()
    try:
        yield sync_url
    finally:
        with admin.connect() as c:
            c.execute(sa.text(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                f"WHERE datname = '{name}' AND pid <> pg_backend_pid()"))
            c.execute(sa.text(f'DROP DATABASE IF EXISTS "{name}"'))
        admin.dispose()


@pytest.fixture
def world(fresh_db):
    """Seed a team: a legacy admin, a legacy agent, a readonly, a superuser, a
    'Team lead' custom role holding manage_agents, and a custom-role holder
    whose per-agent override is []. Returns ids by nickname."""
    from app.core.security import hash_password
    eng = sa.create_engine(fresh_db)
    ids = {k: str(uuid.uuid4()) for k in ("admin", "agent", "readonly", "su", "lead", "empty")}
    pw = hash_password("original-pass")
    with eng.begin() as c:
        c.execute(sa.text("TRUNCATE agent_actions, agents, custom_roles CASCADE"))
        c.execute(sa.text(
            "INSERT INTO custom_roles (id, name, permissions, protected) VALUES "
            "('super_admin', 'Super Admin', '[\"manage_agents\",\"manage_roles\"]', TRUE), "
            "('lead', 'Team lead', '[\"view_conversations\",\"manage_agents\"]', FALSE)"))
        rows = [
            ("admin", "Ann Admin", "ann@x.ke", "admin", False, None, None),
            ("agent", "Ben Agent", "ben@x.ke", "agent", False, None, None),
            ("readonly", "Rita Read", "rita@x.ke", "readonly", False, None, None),
            ("su", "Sam Super", "sam@x.ke", "agent", True, None, None),
            ("lead", "Lea Lead", "lea@x.ke", "agent", False, "lead", None),
            ("empty", "Emma Empty", "emma@x.ke", "agent", False, "lead", "[]"),
        ]
        for key, name, email, role, su, crole, cperms in rows:
            c.execute(sa.text(
                "INSERT INTO agents (id, name, email, password_hash, role, is_available, "
                "is_superuser, active_convs, custom_role_id, custom_permissions, created_at) VALUES "
                "(:id, :n, :e, :pw, :r, TRUE, :su, 0, :cr, CAST(:cp AS jsonb), NOW())"),
                {"id": ids[key], "n": name, "e": email, "pw": pw, "r": role, "su": su,
                 "cr": crole, "cp": cperms})
    eng.dispose()
    return ids


@pytest.fixture
def client(fresh_db):
    """The real admin / CRM / roles routers on the fresh database."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool
    from app.database import get_db
    from app.routers import admin, crm, roles

    async_url = fresh_db.replace("postgresql+psycopg2://", "postgresql+asyncpg://")
    engine = create_async_engine(async_url, poolclass=NullPool)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

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
    app.include_router(crm.router, prefix="/api/admin")
    app.include_router(roles.router, prefix="/api/admin")
    app.dependency_overrides[get_db] = _db
    app.state.redis = None
    with TestClient(app) as c:
        c.maker = maker
        yield c


def _as(agent_id: str) -> dict:
    from app.core.security import create_access_token
    return {"Authorization": f"Bearer {create_access_token(agent_id)}"}


def _row(fresh_db, sql, **p):
    eng = sa.create_engine(fresh_db)
    with eng.connect() as c:
        r = c.execute(sa.text(sql), p).fetchone()
    eng.dispose()
    return r


# ── Agents: only someone who manages agents manages them ─────────────────────

def test_an_agent_cannot_take_over_another_account(client, world, fresh_db):
    ben = _as(world["agent"])
    ann = world["admin"]
    before = _row(fresh_db, "SELECT password_hash, role FROM agents WHERE id = :i", i=ann)
    assert client.patch(f"/api/admin/agents/{ann}", json={"password": "hijacked-1"}, headers=ben).status_code == 403
    assert client.patch(f"/api/admin/agents/{ann}", json={"email": "me@evil.ke"}, headers=ben).status_code == 403
    assert client.patch(f"/api/admin/agents/{ann}", json={"is_available": False}, headers=ben).status_code == 403
    assert client.delete(f"/api/admin/agents/{ann}", headers=ben).status_code == 403
    assert client.post("/api/admin/agents", json={"name": "X", "email": "x@x.ke", "password": "longenough"},
                       headers=ben).status_code == 403
    assert client.patch(f"/api/admin/agents/{world['agent']}/role", json={"custom_role_id": "super_admin"},
                        headers=ben).status_code == 403
    assert _row(fresh_db, "SELECT password_hash, role FROM agents WHERE id = :i", i=ann) == before
    assert _row(fresh_db, "SELECT custom_role_id FROM agents WHERE id = :i", i=world["agent"])[0] is None


def test_an_agent_can_still_run_their_own_account(client, world, fresh_db):
    me = world["agent"]
    ben = _as(me)
    r = client.patch(f"/api/admin/agents/{me}", json={"name": "Benjamin", "is_available": False}, headers=ben)
    assert r.status_code == 200
    assert client.patch(f"/api/admin/agents/{me}", json={"password": "a-new-pass"}, headers=ben).status_code == 200
    # …but not promote themselves.
    assert client.patch(f"/api/admin/agents/{me}", json={"role": "admin"}, headers=ben).status_code == 403
    row = _row(fresh_db, "SELECT name, is_available, role FROM agents WHERE id = :i", i=me)
    assert (row[0], row[1], str(row[2])) == ("Benjamin", False, "agent")


def test_a_manager_manages_by_legacy_role_or_custom_role(client, world, fresh_db):
    # Legacy admin.
    r = client.patch(f"/api/admin/agents/{world['agent']}", json={"role": "readonly", "password": "reset-pass-1"},
                     headers=_as(world["admin"]))
    assert r.status_code == 200
    # A custom role granting manage_agents, on a legacy "agent".
    r = client.post("/api/admin/agents", json={"name": "Nia", "email": "nia@x.ke", "password": "longenough"},
                    headers=_as(world["lead"]))
    assert r.status_code == 200 and "password_hash" not in r.json()
    # An empty per-agent override falls back to the LEGACY role (agent): no manage_agents.
    r = client.post("/api/admin/agents", json={"name": "Z", "email": "z@x.ke", "password": "longenough"},
                    headers=_as(world["empty"]))
    assert r.status_code == 403


def test_agent_accounts_are_validated(client, world):
    ann = _as(world["admin"])
    r = client.post("/api/admin/agents", json={"name": "Dup", "email": "BEN@x.ke", "password": "longenough"}, headers=ann)
    assert r.status_code == 409                                  # was a bare 500
    r = client.post("/api/admin/agents", json={"name": "S", "email": "s@x.ke", "password": "short"}, headers=ann)
    assert r.status_code == 422
    r = client.post("/api/admin/agents", json={"name": "R", "email": "r@x.ke", "password": "longenough",
                                               "role": "god"}, headers=ann)
    assert r.status_code == 422
    r = client.patch(f"/api/admin/agents/{world['agent']}", json={"email": "ann@x.ke"}, headers=ann)
    assert r.status_code == 409


def test_only_a_superuser_touches_a_superuser(client, world, fresh_db):
    ann = _as(world["admin"])
    su = world["su"]
    assert client.patch(f"/api/admin/agents/{su}", json={"password": "taken-over"}, headers=ann).status_code == 403
    assert client.delete(f"/api/admin/agents/{su}", headers=ann).status_code == 403
    assert client.patch(f"/api/admin/agents/{su}/role", json={"custom_role_id": "lead"}, headers=ann).status_code == 403
    # Availability is not an account change: a manager may still set it.
    assert client.patch(f"/api/admin/agents/{su}", json={"is_available": False}, headers=ann).status_code == 200
    assert client.patch(f"/api/admin/agents/{world['admin']}", json={"password": "sam-resets-1"},
                        headers=_as(su)).status_code == 200


def test_the_team_always_keeps_an_admin(client, world, fresh_db):
    # Remove the superuser so Ann is the only one who can run the team.
    eng = sa.create_engine(fresh_db)
    with eng.begin() as c:
        c.execute(sa.text("DELETE FROM agents WHERE id = :i"), {"i": world["su"]})
    eng.dispose()
    ann = world["admin"]
    assert client.delete(f"/api/admin/agents/{ann}", headers=_as(ann)).status_code == 409      # yourself
    assert client.delete(f"/api/admin/agents/{ann}", headers=_as(world["lead"])).status_code == 409  # last admin
    assert client.patch(f"/api/admin/agents/{ann}", json={"role": "agent"}, headers=_as(ann)).status_code == 409
    assert client.delete(f"/api/admin/agents/{world['readonly']}", headers=_as(ann)).status_code == 200


def test_me_never_shows_the_password_hash(client, world):
    me = _as(world["agent"])
    r = client.get("/api/admin/me", headers=me)
    assert r.status_code == 200
    assert "password_hash" not in r.json() and r.json()["email"] == "ben@x.ke"
    r = client.patch("/api/admin/me", json={"name": "Ben A."}, headers=me)
    assert r.status_code == 200 and "password_hash" not in r.json()
    assert client.patch("/api/admin/me", json={"email": "ann@x.ke"}, headers=me).status_code == 409
    assert client.patch("/api/admin/me", json={"password": "short"}, headers=me).status_code == 422


def test_a_refresh_token_is_not_an_access_token(client, world):
    from app.core.security import create_refresh_token
    r = client.get("/api/admin/me", headers={"Authorization": f"Bearer {create_refresh_token(world['agent'])}"})
    assert r.status_code == 401


# ── Roles ─────────────────────────────────────────────────────────────────────

def test_roles_are_written_only_by_role_managers(client, world):
    assert client.get("/api/admin/roles", headers=_as(world["agent"])).status_code == 200
    body = {"id": "role_new", "name": "New", "permissions": ["view_conversations"]}
    assert client.post("/api/admin/roles", json=body, headers=_as(world["agent"])).status_code == 403
    assert client.patch("/api/admin/roles/lead", json={"permissions": ["manage_roles"]},
                        headers=_as(world["agent"])).status_code == 403
    assert client.delete("/api/admin/roles/lead", headers=_as(world["agent"])).status_code == 403
    assert client.post("/api/admin/roles", json=body, headers=_as(world["admin"])).status_code == 200


def test_creating_a_role_never_overwrites_one(client, world, fresh_db):
    ann = _as(world["admin"])
    r = client.post("/api/admin/roles", json={"id": "super_admin", "name": "Hacked", "permissions": []}, headers=ann)
    assert r.status_code == 409
    row = _row(fresh_db, "SELECT name, protected FROM custom_roles WHERE id = 'super_admin'")
    assert tuple(row) == ("Super Admin", True)
    r = client.post("/api/admin/roles", json={"name": "Odd", "permissions": ["fly"]}, headers=ann)
    assert r.status_code == 422


# ── Planned actions: sent at most once, never after a veto ───────────────────

def _action(fresh_db, status="needs_approval", minutes_ago=0):
    aid = str(uuid.uuid4())
    eng = sa.create_engine(fresh_db)
    with eng.begin() as c:
        c.execute(sa.text(
            "INSERT INTO agent_actions (id, due_at, kind, reason, draft, status, created_by, updated_at) "
            "VALUES (:id, NOW(), 'follow_up', 'check in', 'Habari!', :st, 'ai', :up)"),
            {"id": aid, "st": status, "up": datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)})
    eng.dispose()
    return aid


def test_two_simultaneous_claims_send_once(client, world, fresh_db):
    from app.models.agent_action import AgentAction
    from app.services import actions as act
    aid = _action(fresh_db)

    async def one():
        async with client.maker() as db:
            row = await db.get(AgentAction, uuid.UUID(aid))
            return await act.claim(db, row, act.PENDING)

    async def race():
        return await asyncio.gather(*(one() for _ in range(8)))

    wins = asyncio.run(race())
    assert wins.count(True) == 1
    assert _row(fresh_db, "SELECT status FROM agent_actions WHERE id = :i", i=aid)[0] == "sending"


def test_a_veto_stands_and_a_sent_action_cannot_be_vetoed(client, world, fresh_db):
    ben = _as(world["agent"])
    aid = _action(fresh_db, "planned")
    assert client.post(f"/api/admin/actions/{aid}/veto", headers=ben).status_code == 200
    # The scheduler, having read it as planned before the veto, can't claim it.
    from app.models.agent_action import AgentAction
    from app.services import actions as act

    async def late_scheduler():
        async with client.maker() as db:
            from sqlalchemy.orm.attributes import set_committed_value
            row = await db.get(AgentAction, uuid.UUID(aid))
            set_committed_value(row, "status", "planned")   # what it read before the veto
            return await act.claim(db, row, ("planned",))
    assert asyncio.run(late_scheduler()) is False
    assert _row(fresh_db, "SELECT status FROM agent_actions WHERE id = :i", i=aid)[0] == "vetoed"

    sent = _action(fresh_db, "sent")
    assert client.post(f"/api/admin/actions/{sent}/veto", headers=ben).status_code == 409
    assert _row(fresh_db, "SELECT status FROM agent_actions WHERE id = :i", i=sent)[0] == "sent"


def test_approve_sends_once_and_a_failed_send_goes_back(client, world, fresh_db, monkeypatch):
    from app.services import actions as act
    from sqlalchemy.orm import Session
    from app.models.conversation import Conversation
    conv_id = str(uuid.uuid4())
    eng = sa.create_engine(fresh_db)
    with Session(eng) as s:              # the model's own defaults fill the rest
        s.add(Conversation(id=uuid.UUID(conv_id), wa_id="254700000001", channel="whatsapp"))
        s.commit()
    eng.dispose()
    aid = _action(fresh_db)
    eng = sa.create_engine(fresh_db)
    with eng.begin() as c:
        c.execute(sa.text("UPDATE agent_actions SET conversation_id = :c WHERE id = :i"), {"c": conv_id, "i": aid})
    eng.dispose()

    sent = []

    async def fake_send(db, redis, conv, text):
        sent.append(text)
    monkeypatch.setattr(act, "_send", fake_send)
    ben = _as(world["agent"])
    assert client.post(f"/api/admin/actions/{aid}/approve", json={}, headers=ben).status_code == 200
    assert client.post(f"/api/admin/actions/{aid}/approve", json={}, headers=ben).status_code == 409
    assert sent == ["Habari!"]
    assert _row(fresh_db, "SELECT status FROM agent_actions WHERE id = :i", i=aid)[0] == "sent"

    again = _action(fresh_db)
    eng = sa.create_engine(fresh_db)
    with eng.begin() as c:
        c.execute(sa.text("UPDATE agent_actions SET conversation_id = :c WHERE id = :i"), {"c": conv_id, "i": again})
    eng.dispose()

    async def broken_send(db, redis, conv, text):
        raise RuntimeError("Graph said no")
    monkeypatch.setattr(act, "_send", broken_send)
    with pytest.raises(RuntimeError):
        client.post(f"/api/admin/actions/{again}/approve", json={}, headers=ben)
    assert _row(fresh_db, "SELECT status FROM agent_actions WHERE id = :i", i=again)[0] == "needs_approval"


def test_an_interrupted_send_comes_back_for_a_human(client, world, fresh_db):
    from app.services import actions as act
    stuck = _action(fresh_db, "sending", minutes_ago=30)
    fresh = _action(fresh_db, "sending", minutes_ago=1)

    async def sweep():
        async with client.maker() as db:
            return await act._recover_interrupted(db, datetime.now(timezone.utc))
    assert asyncio.run(sweep()) == 1
    status, reason = _row(fresh_db, "SELECT status, reason FROM agent_actions WHERE id = :i", i=stuck)
    assert status == "needs_approval" and "check the thread" in reason
    assert _row(fresh_db, "SELECT status FROM agent_actions WHERE id = :i", i=fresh)[0] == "sending"


# ── The live feed ─────────────────────────────────────────────────────────────

def test_the_live_feed_opens_only_for_a_current_agent(world, fresh_db, monkeypatch):
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool
    import app.database
    from app.core.security import create_access_token
    from app.routers import websocket as ws

    engine = create_async_engine(fresh_db.replace("postgresql+psycopg2://", "postgresql+asyncpg://"),
                                 poolclass=NullPool)
    monkeypatch.setattr(app.database, "AsyncSessionLocal",
                        async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False))
    ben = world["agent"]
    assert asyncio.run(ws._authorised(create_access_token(ben), ben)) is True
    gone = str(uuid.uuid4())
    assert asyncio.run(ws._authorised(create_access_token(gone), gone)) is False
