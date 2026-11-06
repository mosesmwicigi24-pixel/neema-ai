"""STAGE 8 on a real Postgres: the trace JSON over real rows (contact masked,
origins and delivery read from the stamps), the prompt-inputs view, and the
Basic-auth login through the real router. Skips without a reachable Postgres."""
import base64
import types
import uuid

from tests.test_outreach_stage2_db import _msg, _seed, maker, run  # noqa: F401 — the fixture
from tests.test_security_db import fresh_db, pytestmark  # noqa: F401

GRACE = "254722000111"


def _client(maker, *, admin=True, agent_override=True):  # noqa: F811
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.database import get_db
    from app.routers import admin as admin_router, auth, crm
    app = FastAPI()
    app.include_router(crm.router, prefix="/api/admin")
    app.include_router(auth.router, prefix="/api/auth")

    async def _db():
        async with maker() as s:
            yield s

    async def _agent():
        return types.SimpleNamespace(id=uuid.uuid4(), name="Ann", role="admin" if admin else "agent",
                                     is_superuser=admin)
    app.dependency_overrides[get_db] = _db
    if agent_override:
        app.dependency_overrides[admin_router.get_current_agent] = _agent
    app.state.redis = None
    return TestClient(app)


def test_the_trace_reads_the_rows_and_masks_the_contact(maker):  # noqa: F811
    from app.services import actions, outreach_log as ol
    cid = _seed(maker, GRACE, name="Grace W.")
    _msg(maker, cid, GRACE, "inbound", "How much is the stole?", minutes_ago=30)
    _msg(maker, cid, GRACE, "outbound", "The Purple Stole is $45.", minutes_ago=29)
    _msg(maker, cid, GRACE, "outbound", "Still thinking about the stole?", minutes_ago=5,
         raw_meta={**ol.stamp("actions", ol.ROUTINE, kind="buying_follow_up"),
                   "delivery": {"status": "delivered"}})

    async def plan():
        async with maker() as db:
            await actions.plan(db, conversation_id=cid, kind="check_in", due_at=__import__("datetime").datetime.now(
                __import__("datetime").timezone.utc), reason="Customer-agreed check-in (WhatsApp): Thursday",
                source="tool", dedupe_key="check_in:purchase_decision")
    run(plan())

    c = _client(maker)
    r = c.get("/api/admin/outreach/trace", params={"handle": GRACE, "days": 7})
    assert r.status_code == 200, r.text
    t = r.json()
    assert t["contact"].endswith("0111") and GRACE not in t["contact"]
    assert [m["direction"] for m in t["thread"]] == ["in", "out", "out"]
    assert t["thread"][2]["origin"] and "buying_follow_up" in t["thread"][2]["origin"]
    assert t["thread"][2]["delivery"] and "delivered" in t["thread"][2]["delivery"]
    assert t["actions"][0]["kind"] == "check_in" and t["actions"][0]["dedupe_key"] == "check_in:purchase_decision"
    # by conversation id too; an unknown handle is a 404, not an empty trace
    assert c.get("/api/admin/outreach/trace", params={"handle": str(cid)}).status_code == 200
    assert c.get("/api/admin/outreach/trace", params={"handle": "000000000000"}).status_code == 404
    assert _client(maker, admin=False).get("/api/admin/outreach/trace", params={"handle": GRACE}).status_code == 403


def test_the_prompt_inputs_view_shows_what_the_dashboard_feeds_the_turn(maker):  # noqa: F811
    from app.services.app_settings import set_value

    async def seed():
        async with maker() as db:
            await set_value(db, "operator_directives", "Push copes this week.")
            await set_value(db, "learned_rules", "Quote lead times in days.")
    run(seed())
    c = _client(maker)
    r = c.get("/api/admin/settings/prompt-inputs")
    assert r.status_code == 200, r.text
    v = r.json()
    assert v["directives"]["text"] == "Push copes this week." and v["directives"]["cap"] == 600
    assert v["learned_rules"]["text"] == "Quote lead times in days."
    assert v["base_prompt"]["chars"] > 50_000 and v["base_prompt"]["approx_tokens"] > 10_000
    assert _client(maker, admin=False).get("/api/admin/settings/prompt-inputs").status_code == 403


def test_basic_login_through_the_real_router(maker):  # noqa: F811
    from app.core.security import hash_password
    from app.models.agent import Agent

    async def seed():
        async with maker() as db:
            db.add(Agent(email="owner@example.com", name="Owner", password_hash=hash_password("correct horse"),
                         role="admin", is_superuser=True))
            await db.commit()
    run(seed())
    c = _client(maker, agent_override=False)
    good = "Basic " + base64.b64encode(b"owner@example.com:correct horse").decode()
    r = c.post("/api/auth/login-basic", headers={"Authorization": good})
    assert r.status_code == 200 and r.json()["token_type"] == "bearer" and r.json()["is_superuser"] is True
    bad = "Basic " + base64.b64encode(b"owner@example.com:wrong").decode()
    assert c.post("/api/auth/login-basic", headers={"Authorization": bad}).status_code == 401
    assert c.post("/api/auth/login-basic").status_code == 401
