"""OUTBOUND COMMUNICATION, STAGE 5 — the rollout control on a real Postgres and
through the real router: an admin flips a rule from the dashboard, the next
sweep reads it, a non-admin cannot. Skips without a reachable Postgres."""
import types
import uuid

import sqlalchemy as sa

from tests.test_outreach_stage2_db import maker, run  # noqa: F401 — the fixture
from tests.test_security_db import fresh_db, pytestmark  # noqa: F401
from app.core.config import settings


class _Redis:
    def __init__(self):
        self.store, self.hashes = {}, {}
    async def get(self, k): return self.store.get(k)
    async def set(self, k, v, ex=None, nx=False): self.store[k] = v
    async def delete(self, k): self.store.pop(k, None)
    async def hgetall(self, k): return self.hashes.get(k, {})


def _client(maker, *, admin: bool):  # noqa: F811 — the fixture
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.database import get_db
    from app.routers import admin as admin_router, crm
    app = FastAPI()
    app.include_router(crm.router, prefix="/api/admin")

    async def _db():
        async with maker() as s:
            yield s

    async def _agent():
        return types.SimpleNamespace(id=uuid.uuid4(), name="Ann", role="admin" if admin else "agent",
                                     is_superuser=admin)
    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[admin_router.get_current_agent] = _agent
    app.state.redis = _Redis()
    return TestClient(app), app.state.redis


def _rows(fresh_db, *, clear=False):  # noqa: F811
    eng = sa.create_engine(fresh_db)
    with eng.begin() as c:
        if clear:
            c.execute(sa.text("DELETE FROM app_settings WHERE id LIKE 'outreach_%'"))
        out = dict(c.execute(sa.text("SELECT id, value FROM app_settings WHERE id LIKE 'outreach_%'")).all())
    eng.dispose()
    return out


def test_an_admin_switches_one_rule_on_and_the_next_sweep_reads_it(maker, fresh_db, monkeypatch):  # noqa: F811
    monkeypatch.setattr(settings, "outreach_mode", "shadow", raising=False)
    monkeypatch.setattr(settings, "outreach_enforce_rules", "", raising=False)
    assert _rows(fresh_db, clear=True) == {}
    c, redis = _client(maker, admin=True)
    before = c.get("/api/admin/settings/outreach").json()
    assert before["mode"] == "shadow" and before["enforced_rules"] == []
    assert [r["id"] for r in before["rules"]] == ["customer_replied", "colleague_replied", "daily_cap"]
    assert before["default"] == {"mode": "shadow", "rules": []}

    r = c.put("/api/admin/settings/outreach", json={"enforced_rules": ["customer_replied"]})
    assert r.status_code == 200 and r.json() == {"ok": True, "mode": "shadow", "enforced_rules": ["customer_replied"]}
    assert _rows(fresh_db) == {"outreach_enforce_rules": "customer_replied"}

    from app.services import actions
    async def sweep_reads():
        async with maker() as db:
            return await actions._control(db, redis)
    assert run(sweep_reads()) == {"mode": "shadow", "rules": ["customer_replied"]}

    r = c.put("/api/admin/settings/outreach", json={"mode": "enforce"})
    assert r.json()["mode"] == "enforce"
    assert run(sweep_reads())["mode"] == "enforce"
    r = c.put("/api/admin/settings/outreach", json={"mode": "shadow", "enforced_rules": []})
    assert r.json() == {"ok": True, "mode": "shadow", "enforced_rules": []}
    assert _rows(fresh_db) == {"outreach_mode": "shadow", "outreach_enforce_rules": "-"}
    assert run(sweep_reads()) == {"mode": "shadow", "rules": []}

    for bad in ({"mode": "loud"}, {"enforced_rules": ["nope"]}, {}):
        assert c.put("/api/admin/settings/outreach", json=bad).status_code == 422


def test_a_non_admin_can_read_but_not_flip(maker, fresh_db, monkeypatch):  # noqa: F811
    monkeypatch.setattr(settings, "outreach_mode", "shadow", raising=False)
    assert _rows(fresh_db, clear=True) == {}
    c, _ = _client(maker, admin=False)
    assert c.get("/api/admin/settings/outreach").status_code == 200
    assert c.put("/api/admin/settings/outreach", json={"mode": "enforce"}).status_code == 403
    assert _rows(fresh_db) == {}
