"""Recovery planners on a daily timer (services/recovery_jobs.py), real Postgres.
cart_recovery and payment_followup run once a day at their Nairobi hour under
a fleet lock — only when their own switch is on (OFF by default), with a
dry-run that composes previews and plans nothing, a run history on
/api/health and a "what would be sent today" preview with masked handles.
Since Stage 2 (audit, 2026-11-05) a live run PLANS rows on agent_actions and
the dispatcher (services/actions.process_due) sends them; the 15:00 re-engage
sweep is retired.
"""
import asyncio
import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import sqlalchemy as sa

from tests.test_security_db import fresh_db, pytestmark  # noqa: F401

NBO = timedelta(hours=3)
CART_WA, WAIT_WA, PAY_WA = "254722000001", "254733000002", "254744000003"


def run(coro):
    return asyncio.run(coro)


def at_nbo(day, hour, minute=5):
    return datetime(2026, 10, day, hour, minute, tzinfo=timezone.utc) - NBO


class FakeRedis:
    def __init__(self):
        self.kv: dict = {}
        self.lists: dict = {}

    async def get(self, k):
        return self.kv.get(k)

    async def set(self, k, v, nx=False, ex=None):
        if nx and k in self.kv:
            return None
        self.kv[k] = v
        return True

    async def delete(self, *ks):
        for k in ks:
            self.kv.pop(k, None)

    async def incr(self, k):
        self.kv[k] = int(self.kv.get(k) or 0) + 1
        return self.kv[k]

    async def expire(self, k, s):
        return True

    async def lpush(self, k, v):
        self.lists.setdefault(k, []).insert(0, v)

    async def ltrim(self, k, a, b):
        self.lists[k] = self.lists.get(k, [])[a:b + 1]

    async def lrange(self, k, a, b):
        return list(self.lists.get(k, []))[a:b + 1]

    async def publish(self, ch, msg):
        return 0


@pytest.fixture
def off(monkeypatch):
    """Every switch at its shipped default."""
    from app.core.config import settings
    for f in ("recovery_cart_enabled", "recovery_payment_enabled", "recovery_jobs_dry_run"):
        monkeypatch.setattr(settings, f, False)
    return settings


# ── The timer (no database) ───────────────────────────────────────────────────

def test_every_switch_ships_off():
    from app.core.config import Settings
    s = Settings(_env_file=None)
    assert not (s.recovery_cart_enabled or s.recovery_payment_enabled or s.recovery_jobs_dry_run)
    assert not hasattr(s, "recovery_reengage_enabled")          # retired (owner decision 2)


def test_off_by_default_runs_and_sends_nothing(off, monkeypatch):
    from app.services import recovery_jobs as rj
    calls = []

    async def spy(job, **kw):
        calls.append(job)
        return {}
    monkeypatch.setattr(rj, "_module_run", spy)
    r = FakeRedis()
    for h in range(24):
        assert run(rj.tick(r, now=at_nbo(12, h))) == []
    assert calls == [] and r.kv == {}            # not even the lock is taken


def test_the_lock_lets_one_worker_run_a_tick(off, monkeypatch):
    from app.services import recovery_jobs as rj
    monkeypatch.setattr(off, "recovery_cart_enabled", True)
    calls = []

    async def spy(job, **kw):
        calls.append(job)
        await asyncio.sleep(0.05)
        return {"candidates": 0}
    monkeypatch.setattr(rj, "_module_run", spy)
    r = FakeRedis()

    async def fleet():
        return await asyncio.gather(*(rj.tick(r, now=at_nbo(12, 11)) for _ in range(4)))
    results = run(fleet())
    assert sorted(len(x) for x in results) == [0, 0, 0, 1]
    assert calls == ["cart_recovery"]


def test_each_job_runs_once_a_day_at_its_hour(off, monkeypatch):
    from app.services import recovery_jobs as rj
    for f in ("recovery_cart_enabled", "recovery_payment_enabled"):
        monkeypatch.setattr(off, f, True)
    calls = []

    async def spy(job, **kw):
        calls.append((job, kw["send"]))
        return {"candidates": 1, "sent": 1}
    monkeypatch.setattr(rj, "_module_run", spy)
    r = FakeRedis()

    def tick(day, h, m=5):
        r.kv.pop(rj.LOCK_KEY, None)             # the lock expires between ticks
        return run(rj.tick(r, now=at_nbo(day, h, m)))
    assert tick(12, 9) == []
    assert tick(12, 10) == ["payment_followup"]
    assert tick(12, 10, 40) == []               # same hour, later tick: not again
    assert tick(12, 11) == ["cart_recovery"]
    assert tick(12, 15) == []                   # the 15:00 re-engage sweep is retired
    assert tick(12, 21) == []
    assert tick(13, 11) == ["cart_recovery"]    # the next day, again
    assert calls == [("payment_followup", True), ("cart_recovery", True),
                     ("cart_recovery", True)]


def test_a_failed_run_is_recorded_not_raised(off, monkeypatch):
    from app.services import recovery_jobs as rj
    monkeypatch.setattr(off, "recovery_payment_enabled", True)

    async def boom(job, **kw):
        raise RuntimeError("hub said https://secret.example/token=abc")
    monkeypatch.setattr(rj, "_module_run", boom)
    r = FakeRedis()
    assert run(rj.tick(r, now=at_nbo(12, 10))) == ["payment_followup"]
    entry = json.loads(r.lists["recoveryjobs:history:payment_followup"][0])
    assert entry["error"] == "RuntimeError" and "secret" not in json.dumps(entry)
    assert entry["started"] and entry["finished"]


def test_no_redis_means_no_run(off, monkeypatch):
    from app.services import recovery_jobs as rj
    monkeypatch.setattr(off, "recovery_cart_enabled", True)
    assert run(rj.tick(None, now=at_nbo(12, 11))) == []


# ── Against a database with real candidates ───────────────────────────────────

@pytest.fixture
def world(fresh_db, monkeypatch, off):  # noqa: F811
    """One abandoned cart, one customer gone quiet after a quote, one unpaid order —
    with every send path wired to fail the test if it is ever reached."""
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool
    import app.database as database
    from app.jobs import cart_recovery, payment_followup
    from app.core import hub_client
    from app.services import messaging, meta_send
    from app.models.conversation import Conversation
    from app.models.message import Message, MsgDirection, MsgSender
    from app.models.order_event import OrderEvent
    from app.models.user import User

    eng = sa.create_engine(fresh_db)
    with eng.begin() as c:
        c.execute(sa.text("TRUNCATE agent_actions, deals, messages, order_events, users, "
                          "intercepts, conversations, persons CASCADE"))
    eng.dispose()
    url = fresh_db.replace("postgresql+psycopg2://", "postgresql+asyncpg://")
    maker = async_sessionmaker(create_async_engine(url, poolclass=NullPool),
                               class_=AsyncSession, expire_on_commit=False)
    for m in (cart_recovery, payment_followup, database):
        monkeypatch.setattr(m, "AsyncSessionLocal", maker)
    now = datetime.now(timezone.utc)

    async def seed():
        async with maker() as db:
            db.add(User(wa_id=CART_WA, name="Grace Wanjiru", state={"agent_cart": {"items": [
                {"name": "Aluminium Tray", "qty": 2, "unit_price": 7000}]}}))
            for wa, last in ((CART_WA, now - timedelta(hours=2)),
                             (WAIT_WA, now - timedelta(hours=4)),
                             (PAY_WA, now - timedelta(hours=3))):
                cid = uuid.uuid4()
                db.add(Conversation(id=cid, wa_id=wa, channel="whatsapp", external_id=wa,
                                    last_message_at=last))
                await db.flush()
                if wa == WAIT_WA:
                    # asked, was quoted, went quiet: a re-engage check-in candidate
                    db.add(Message(id=uuid.uuid4(), conversation_id=cid, wa_id=wa,
                                   external_id=wa, channel="whatsapp",
                                   direction=MsgDirection.inbound, sender=MsgSender.user,
                                   text="Do you have red stoles?",
                                   created_at=last - timedelta(minutes=10)))
                db.add(Message(id=uuid.uuid4(), conversation_id=cid, wa_id=wa, external_id=wa,
                               channel="whatsapp", direction=MsgDirection.outbound,
                               sender=MsgSender.ai,
                               text=("Yes 🙏 the Red Stole is KES 3,500. Would you like one?"
                                     if wa == WAIT_WA else "Here you go 🙏"),
                               created_at=last))
            db.add(OrderEvent(id=f"{PAY_WA}_1", wa_id=PAY_WA, event_type="confirmed",
                              hub_order_id=501, hub_order_number="BH-501", hub_total=4500,
                              hub_currency="KES", hub_payment_url="https://pay.example/abc",
                              payment_status="unpaid", created_at=now - timedelta(hours=3)))
            await db.commit()
    run(seed())

    async def status(order_id, redis=None):
        return {"payment_status": "unpaid"}
    monkeypatch.setattr(hub_client, "fetch_order_status", status)

    async def cart_draft(redis, conv, to, items):
        return "Hi Grace 🙏 your 2 Aluminium Trays are still saved — shall I place the order?"
    monkeypatch.setattr(cart_recovery, "_draft", cart_draft)

    monkeypatch.setattr(cart_recovery, "within_quiet_hours", lambda *a, **k: True)
    monkeypatch.setattr("app.services.hub_events.is_quiet_hours", lambda now=None: False)
    monkeypatch.setattr(payment_followup, "within_quiet_hours", lambda *a, **k: True)

    sent = []

    async def no_waba(to, text, *a, **k):
        sent.append((to, text))
        return "wamid.x"

    async def no_meta(channel, to, text, *a, **k):
        sent.append((to, text))
    monkeypatch.setattr(messaging, "_send_waba", no_waba)
    monkeypatch.setattr(meta_send, "send_to_channel", no_meta)
    return {"maker": maker, "sent": sent, "settings": off}


def _all_on(world, monkeypatch, dry):
    s = world["settings"]
    for f in ("recovery_cart_enabled", "recovery_payment_enabled"):
        monkeypatch.setattr(s, f, True)
    monkeypatch.setattr(s, "recovery_jobs_dry_run", dry)


def _day(r, rj, hours=(10, 11)):
    for h in hours:
        r.kv.pop(rj.LOCK_KEY, None)
        run(rj.tick(r, now=at_nbo(12, h)))


def _planned(world):
    from sqlalchemy import select
    from app.models.agent_action import AgentAction

    async def go():
        async with world["maker"]() as db:
            return [(a.kind, a.status, a.source, a.dedupe_key, a.draft) for a in (await db.execute(
                select(AgentAction).order_by(AgentAction.created_at))).scalars().all()]
    return run(go())


def _dispatch(world, monkeypatch, r):
    """The dispatcher's tick: sends what the planners filed."""
    from app.services import actions
    monkeypatch.setattr(world["settings"], "agent_initiative", True, raising=False)

    async def fake_window(db, c): return True
    monkeypatch.setattr("app.services.hub_events._within_window", fake_window)

    async def compose(db, redis, c, reason):
        return "Grace, your 2 Aluminium Trays are still saved — shall I place the order?"
    monkeypatch.setattr(actions, "_compose_follow_up", compose)

    async def go():
        async with world["maker"]() as db:
            return await actions.process_due(db, r)
    return run(go())


def test_dry_run_composes_sends_nothing_and_records_history(world, monkeypatch):
    from app.services import recovery_jobs as rj
    _all_on(world, monkeypatch, dry=True)
    r = FakeRedis()
    _day(r, rj)
    assert world["sent"] == [] and _planned(world) == []
    # no guard was claimed: a real run later is not blocked by the rehearsal
    assert not [k for k in r.kv if k.startswith(("cartnudge:", "payfollow:"))]
    for job in rj.JOBS:
        hist = [json.loads(x) for x in r.lists[f"recoveryjobs:history:{job}"]]
        assert len(hist) == 1
        e = hist[0]
        assert e["mode"] == "dry_run" and e["sent"] == 0 and e["errors"] == 0
        assert e["candidates"] == 1 and e["would_send"] == 1
        assert {"started", "finished", "skipped"} <= set(e)
        assert not any(wa in json.dumps(e) for wa in (CART_WA, WAIT_WA, PAY_WA))
    view = run(rj.health_view(r))
    assert view["dry_run"] is True and view["cart_recovery"]["last_runs"][0]["mode"] == "dry_run"


def test_a_live_run_plans_once_the_dispatcher_sends_once(world, monkeypatch):
    """Stage 2: the planners file rows (nothing is sent by them); the
    dispatcher sends each once; the quiet-after-a-quote customer is NOT
    chased by a re-engage sweep any more."""
    from app.services import recovery_jobs as rj
    _all_on(world, monkeypatch, dry=False)
    r = FakeRedis()
    _day(r, rj)
    assert world["sent"] == []                                   # planners never send
    rows = _planned(world)
    assert sorted((k, s, src) for k, s, src, _, _ in rows) == [
        ("buying_follow_up", "planned", "cart_recovery"),
        ("payment_reminder", "planned", "payment_followup")]
    pay = next(x for x in rows if x[0] == "payment_reminder")
    assert pay[3] == "payment:501" and "https://pay.example/abc" in pay[4] and "KES 4,500" in pay[4]
    for job in rj.JOBS:
        e = json.loads(r.lists[f"recoveryjobs:history:{job}"][0])
        assert (e["mode"], e["sent"], e["errors"]) == ("send", 1, 0), (job, e)
    # the dispatcher speaks — once per customer, with the planned text
    assert _dispatch(world, monkeypatch, r) == 2
    assert sorted(to for to, _ in world["sent"]) == [CART_WA, PAY_WA]
    assert any("https://pay.example/abc" in t and "KES 4,500" in t for _, t in world["sent"])
    assert all(s == "sent" for _, s, _, _, _ in _planned(world))
    assert _dispatch(world, monkeypatch, r) == 0 and len(world["sent"]) == 2
    # a manual run the same day (or tomorrow's timer) hits each planner's own guard
    from app.jobs import cart_recovery, payment_followup
    out_c = run(cart_recovery.run(send=True, redis=r))
    out_p = run(payment_followup.run(send=True, redis=r))
    assert len(world["sent"]) == 2 and out_c["skipped"] == 1 and out_p["skipped"] == 1
    assert len(_planned(world)) == 2


def test_preview_counts_and_masks_three_samples(world, monkeypatch, capsys):
    from app.services import recovery_jobs as rj
    r = FakeRedis()
    out = run(rj.preview(r))
    assert world["sent"] == [] and not r.kv            # nothing sent, no guard claimed
    for job in rj.JOBS:
        p = out[job]
        assert p["enabled"] is False and p["candidates"] == 1 and p["would_send"] == 1
        assert len(p["samples"]) == 1
        assert p["samples"][0]["to"].startswith("…") and len(p["samples"][0]["to"]) == 5
    assert "KES 4,500" in out["payment_followup"]["samples"][0]["text"]
    print("\nPREVIEW " + json.dumps(out, ensure_ascii=False, indent=2))


def test_the_preview_endpoint_is_for_settings_managers_only(world, fresh_db, monkeypatch):  # noqa: F811
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.database import get_db
    from app.routers import admin
    from app.core.security import create_access_token, hash_password
    ids = {"admin": str(uuid.uuid4()), "agent": str(uuid.uuid4())}
    eng = sa.create_engine(fresh_db)
    with eng.begin() as c:
        c.execute(sa.text("DELETE FROM agents"))
        for k, role in (("admin", "admin"), ("agent", "agent")):
            c.execute(sa.text(
                "INSERT INTO agents (id, name, email, password_hash, role, is_available, "
                "is_superuser, active_convs, created_at) VALUES "
                "(:id, :n, :e, :pw, :r, TRUE, FALSE, 0, NOW())"),
                {"id": ids[k], "n": k, "e": f"{k}@x.ke", "pw": hash_password("pass-pass"), "r": role})
    eng.dispose()

    async def _db():
        async with world["maker"]() as s:
            yield s
    app = FastAPI()
    app.include_router(admin.router, prefix="/api/admin")
    app.dependency_overrides[get_db] = _db
    app.state.redis = FakeRedis()

    def h(k):
        return {"Authorization": f"Bearer {create_access_token(ids[k])}"}
    with TestClient(app) as cl:
        assert cl.get("/api/admin/recovery/preview", headers=h("agent")).status_code == 403
        assert cl.get("/api/admin/recovery/preview?job=nope", headers=h("admin")).status_code == 422
        r = cl.get("/api/admin/recovery/preview?job=payment_followup", headers=h("admin"))
    assert r.status_code == 200
    body = r.json()
    assert list(body["jobs"]) == ["payment_followup"]
    assert body["jobs"]["payment_followup"]["would_send"] == 1
    assert world["sent"] == []
