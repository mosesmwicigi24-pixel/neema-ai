"""Push registration — the phone each agent signs in on is kept against them,
so a call rings it with the app closed (services/push.py). Real Postgres
through the real admin routes; skips cleanly without a database."""
import asyncio

import sqlalchemy as sa

from tests import test_calls_db as _calls, test_security_db as _sec
from tests.test_security_db import _as

fresh_db, world, env = _sec.fresh_db, _calls.world, _calls.env
pytestmark = _calls.pytestmark

TOKEN_A = "fcm-token-a-" + "x" * 140
TOKEN_B = "fcm-token-b-" + "y" * 140


def _rows(fresh_db):
    eng = sa.create_engine(fresh_db)
    with eng.connect() as c:
        rows = c.execute(sa.text("SELECT token, agent_id, platform, app_version, device FROM push_devices ORDER BY token")).all()
    eng.dispose()
    return rows


def test_a_phone_registers_once_and_moves_with_whoever_signs_in(env, world, fresh_db):
    body = {"token": TOKEN_A, "platform": "android", "app_version": "1.0.0 (90)", "device": "samsung SM-X910"}
    for _ in range(2):
        r = env.client.post("/api/admin/push/register", json=body, headers=_as(world["ann"]))
        assert r.status_code == 200 and r.json()["ok"] is True
    assert [(t, a) for t, a, *_ in _rows(fresh_db)] == [(TOKEN_A, world["ann"])]
    env.client.post("/api/admin/push/register", json=body, headers=_as(world["ben"]))
    rows = _rows(fresh_db)
    assert len(rows) == 1 and rows[0][1] == world["ben"], "one phone, one owner"
    assert rows[0][2:] == ("android", "1.0.0 (90)", "samsung SM-X910")


def test_signing_out_takes_only_your_own_phone_off(env, world, fresh_db):
    env.client.post("/api/admin/push/register", json={"token": TOKEN_A}, headers=_as(world["ann"]))
    env.client.post("/api/admin/push/register", json={"token": TOKEN_B}, headers=_as(world["ben"]))
    env.client.post("/api/admin/push/unregister", json={"token": TOKEN_B}, headers=_as(world["ann"]))
    assert len(_rows(fresh_db)) == 2, "Ann cannot silence Ben's phone"
    env.client.post("/api/admin/push/unregister", json={"token": TOKEN_A}, headers=_as(world["ann"]))
    assert [t for t, *_ in _rows(fresh_db)] == [TOKEN_B]


def test_a_registration_needs_a_token_and_a_signed_in_app(env, world):
    assert env.client.post("/api/admin/push/register", json={"token": "short"},
                           headers=_as(world["ann"])).status_code == 422
    assert env.client.post("/api/admin/push/register", json={"token": TOKEN_A}).status_code in (401, 403)


def test_a_removed_agent_s_phone_never_rings(env, world, fresh_db):
    from app.services import push
    env.client.post("/api/admin/push/register", json={"token": TOKEN_A}, headers=_as(world["ann"]))
    env.client.post("/api/admin/push/register", json={"token": TOKEN_B}, headers=_as(world["ben"]))
    assert sorted(asyncio.run(push._tokens())) == sorted([TOKEN_A, TOKEN_B])
    eng = sa.create_engine(fresh_db)
    with eng.begin() as c:
        c.execute(sa.text("DELETE FROM agents WHERE id = :id"), {"id": world["ben"]})
    eng.dispose()
    assert asyncio.run(push._tokens()) == [TOKEN_A]
    asyncio.run(push._forget([TOKEN_A]))
    assert [t for t, *_ in _rows(fresh_db)] == [TOKEN_B]
