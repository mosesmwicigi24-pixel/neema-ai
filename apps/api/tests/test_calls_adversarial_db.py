"""Calling under production conditions — adversarial storms on a real Postgres.

Meta promises neither ordering nor exactly-once delivery
(docs/research/META_CALLING_2026-09.md §3.2), gives 30–60 s to answer, rate
limits, expires tokens and has outages; agents tap at the same instant; redis
and the database blip. Each test drives the REAL webhook front doors
(`whatsapp_webhook.process_payload`, `meta_webhook.receive_webhook`) and the
REAL /calls routes concurrently, in one event loop, against a pooled engine
sized like production — then checks what docs/CALLING_UX.md promises:

  I1  every call ends in exactly one terminal status that matches what really
      happened; nothing is left ringing / answered once its end arrived
  I2  Meta `accept` at most once per call; `connect` never retried; one row per call
  I3  events: every ending is announced; a repeat carries the SAME outcome (the
      documented no_answer → rejected correction excepted); nothing says
      "answered" / "ringing" / "incoming" about a call after its call_ended
  I4  message ingestion keeps working when the calls taps raise
  I5  missed-call follow-up: ≤ 1 per customer per cooldown, never for answered calls

Skips cleanly without a database (the CI real-database step runs it).
"""
import asyncio
import contextvars
import json
import random
import statistics
import time
import types
import uuid
from collections import Counter
from datetime import datetime, timedelta, timezone

import httpx
import pytest
import sqlalchemy as sa

from tests import test_calls_db as _calls, test_security_db as _sec
from tests.test_calls_db import TRANSCRIPT_DOC, _inbound_message
from tests.test_security_db import _as
from tests.test_wa_calling_meta import _Resp

fresh_db, world = _sec.fresh_db, _calls.world
pytestmark = _calls.pytestmark

_AsyncClient = httpx.AsyncClient          # captured before any test fakes httpx for Graph
PAGE = "106378625516323"
_DB_DOWN = contextvars.ContextVar("db_down", default=False)


# ── Fakes: redis that really interleaves, redis that is down, Meta ──────────

class Redis:
    """What calling uses of redis. Every op yields to the loop first — like a
    network round trip — so concurrent handlers genuinely interleave."""

    def __init__(self):
        self.store: dict = {}
        self.published: list = []
        self.before_set = None          # async hook(key, value) — a racer lands here

    async def set(self, key, value, nx=False, ex=None):
        await asyncio.sleep(0)
        if self.before_set is not None:
            await self.before_set(key, value)
        if nx and key in self.store:
            return None
        self.store[key] = value
        return True

    async def get(self, key):
        await asyncio.sleep(0)
        return self.store.get(key)

    async def delete(self, key):
        await asyncio.sleep(0)
        self.store.pop(key, None)

    async def publish(self, channel, message):
        await asyncio.sleep(0)
        if channel == "ws:channel:calls":
            self.published.append(json.loads(message))

    def events(self, kind=None, call_id=None):
        return [e for e in self.published if (kind is None or e["type"] == kind)
                and (call_id is None or e.get("call_id") == call_id)]


class BrokenRedis:
    """Redis is down: every call raises (connection refused mid-flight)."""
    published: list = []

    async def _down(self, *a, **k):
        await asyncio.sleep(0)
        raise ConnectionError("redis: connection refused")

    set = get = delete = publish = _down

    def events(self, *a, **k):
        return []


class Meta:
    """WhatsApp + Messenger Graph as the platform behaves: first accept wins,
    an ended call can't be accepted, terminate is idempotent, and every end
    produces Meta's own terminate webhook (maybe twice, maybe late)."""

    def __init__(self):
        self.calls: dict = {}
        self.log: list = []
        self.fail: dict = {}             # action -> [exception | None, …] consumed in order
        self.jitter = (0, 0.004)
        self.on_end = None               # (cid, duration, channel) → deliver Meta's terminate
        self.connect_hooks = {}          # to -> async (cid): webhooks that beat /calls/connect's row
        self.perm = {}                   # wa_id | psid -> Meta's raw permission answer
        self.request_hook = None
        self.after_terminate = {}        # cid -> async () — Meta's webhook beating our HTTP response
        self.n = 0
        self.violations: list = []      # accepts that should never have been sent

    def st(self, cid):
        return self.calls.setdefault(cid, {"accepted": False, "ended": False, "by": None,
                                           "accepted_by": None, "declines": 0})

    async def _net(self, action, cid):
        self.log.append((action, cid))
        await asyncio.sleep(random.uniform(*self.jitter))
        q = self.fail.get(action)
        if q:
            exc = q.pop(0)
            if exc is not None:
                raise exc

    def count(self, action, cid=None):
        return sum(1 for a, c in self.log if a == action and (cid is None or c == cid))

    async def _accept(self, action, cid, agent=None):
        """Records a violation for an accept sent while another for the same
        call is in flight, or after one succeeded (a retry after a REFUSED
        accept is fine — that's the colleague's Try again)."""
        from app.services.wa_calling import MetaError
        st = self.st(cid)
        if st.get("inflight") or st["accepted"]:
            self.violations.append((action, cid))
        st["inflight"] = True
        try:
            await self._net(action, cid)
        finally:
            st["inflight"] = False
        if st["ended"]:
            raise MetaError(f"call {action} failed (400): call is no longer available", status=400)
        if st["accepted"]:
            raise MetaError(f"call {action} failed (400): already accepted", status=400)
        st["accepted"], st["accepted_by"] = True, agent

    def _end(self, cid, by, channel):
        st = self.st(cid)
        if st["ended"]:
            return
        st["ended"], st["by"] = True, by
        if self.on_end:
            self.on_end(cid, 17 if st["accepted"] else None, channel)

    def hangup(self, cid, channel="whatsapp"):
        """The customer hangs up (or gives up ringing)."""
        self._end(cid, "customer", channel)

    # WhatsApp
    async def wa_accept(self, cid, sdp, **kw):
        from app.services.wa_calling import parse_opaque
        await self._accept("accept", cid, parse_opaque(kw.get("biz_opaque")).get("agent_id"))

    async def wa_terminate(self, cid):
        await self._net("terminate", cid)
        st = self.st(cid)
        if not st["accepted"]:
            st["declines"] += 1
        self._end(cid, "business", "whatsapp")
        hook = self.after_terminate.pop(cid, None)
        if hook:
            await hook()

    async def wa_connect(self, to, sdp, **kw):
        await self._net("connect", to)
        self.n += 1
        cid = f"wacid.out.{to}.{self.n}"
        self.st(cid)["opaque"] = kw.get("biz_opaque")
        hook = self.connect_hooks.pop(to, None)
        if hook:
            await hook(cid)
        return {"calls": [{"id": cid}]}

    async def wa_request(self, to, text=None):
        await self._net("request", to)
        if self.request_hook:
            await self.request_hook(to)
        return {}

    async def wa_request_template(self, to, name, lang, params):
        await self._net("request", to)
        return {}

    async def wa_get_perm(self, wa_id):
        from app.services import wa_calling
        await self._net("get_permission", wa_id)
        if wa_id not in self.perm:
            raise wa_calling.MetaError("WA call-permission read failed (network)", status=0)
        return wa_calling.normalize_permission(self.perm[wa_id])

    # Messenger
    async def m_accept(self, cid, sdp, *, page_id):
        await self._accept("m_accept", cid)
        return {"answer": "v=0 meta-answer", "renegotiation": None}

    async def m_reject(self, cid, *, page_id):
        await self._net("m_reject", cid)
        self._end(cid, "business", "messenger")
        return {"success": True}

    async def m_terminate(self, cid, *, page_id):
        await self._net("m_terminate", cid)
        self._end(cid, "business", "messenger")
        return {"success": True}

    async def m_connect(self, psid, sdp, *, page_id):
        await self._net("m_connect", psid)
        self.n += 1
        return {"id": f"c_out_{psid}_{self.n}", "answer": "v=0 meta-answer", "renegotiation": None}

    async def m_get_perm(self, psid, page_id=None):
        from app.services import messenger_calling, wa_calling
        await self._net("m_get_permission", psid)
        if psid not in self.perm:
            raise wa_calling.MetaError("Messenger call-permission read failed (network)", status=0)
        return messenger_calling.normalize_permission(self.perm[psid])

    async def m_request(self, psid, page_id=None):
        await self._net("m_request", psid)
        return {"recipient": {"id": psid}, "message_id": "m_1"}


# ── The rig: fresh database, 10 agents, the real front doors and routes ─────

def _make_rig(fresh_db, world, monkeypatch, *, fake_meta=True):  # noqa: F811
    from app.core.config import settings
    from app.routers import meta_webhook as mw
    from app.services import (conversation, identity, meta_send, messenger_calling, missed_call,
                              n8n_bridge, wa_calling, wa_native, call_log)
    eng = sa.create_engine(fresh_db)
    agents = [world["ann"], world["ben"], world["boss"]]
    with eng.begin() as c:
        for i in range(7):
            aid = str(uuid.uuid4())
            agents.append(aid)
            c.execute(sa.text(
                "INSERT INTO agents (id, name, email, password_hash, role, is_available, is_superuser, "
                "active_convs, created_at) VALUES (:id, :n, :e, 'x', 'agent', TRUE, FALSE, 0, NOW())"),
                {"id": aid, "n": f"Agent {i + 4}", "e": f"a{i}.{aid[:6]}@x.ke"})
    eng.dispose()

    rig = types.SimpleNamespace(db_url=fresh_db, world=world, agents=agents, monkeypatch=monkeypatch,
                                redis=Redis(), meta=Meta(), tasks=set(), latency=[], ingested=[],
                                captured=[], sent_msgs=[], db_down_all=False, statements=None)
    monkeypatch.setattr(wa_calling, "RETRY_JITTER", (0, 0))
    monkeypatch.setattr(settings, "meta_app_secret", "", raising=False)
    monkeypatch.setattr(settings, "whatsapp_app_secret", "", raising=False)
    monkeypatch.setattr(settings, "messenger_calling_enabled", True, raising=False)
    monkeypatch.setattr(settings, "meta_page_token", "page-token", raising=False)
    monkeypatch.setattr(settings, "missed_call_message_enabled", False, raising=False)

    async def no_person(db, wa_id, source=None):
        return None
    monkeypatch.setattr(identity, "resolve_person_id_for_wa_id", no_person)
    m = rig.meta
    if fake_meta:
        for name, fn in (("accept", m.wa_accept), ("terminate", m.wa_terminate), ("connect", m.wa_connect),
                         ("request_call_permission", m.wa_request),
                         ("request_call_permission_template", m.wa_request_template),
                         ("get_call_permission", m.wa_get_perm)):
            monkeypatch.setattr(wa_calling, name, fn)
    for name, fn in (("accept", m.m_accept), ("reject", m.m_reject), ("terminate", m.m_terminate),
                     ("connect", m.m_connect), ("get_call_permission", m.m_get_perm),
                     ("request_call_permission", m.m_request)):
        monkeypatch.setattr(messenger_calling, name, fn)

    # Ingestion (what the calls taps must never break) — recorded, not run.
    async def ingest(payload, redis):
        n = sum(len((ch.get("value") or {}).get("messages") or [])
                for e in payload.get("entry", []) for ch in e.get("changes", []))
        if n:
            rig.ingested.append(payload)
        return n, 0
    monkeypatch.setattr(wa_native, "handle_webhook", ingest)

    async def capture(db, channel, payload, redis=None):
        rig.captured.append((channel, payload))

    async def capture_comments(db, channel, payload, redis=None):
        return None
    monkeypatch.setattr(mw, "_capture_events", capture)
    monkeypatch.setattr(mw, "_capture_comment_events", capture_comments)

    # The missed-call message's side effects.
    async def send(channel, to, text, **kw):
        rig.sent_msgs.append((channel, to))
        return "wamid.x"

    async def save(*a, **k):
        return None
    monkeypatch.setattr(meta_send, "send_to_channel", send)
    monkeypatch.setattr(n8n_bridge, "save_outbound_message", save)
    monkeypatch.setattr(n8n_bridge, "save_outbound_channel_message", save)
    monkeypatch.setattr(conversation, "record_escalation", save)
    monkeypatch.setattr(missed_call, "_local_cooldown", {}, raising=False)
    monkeypatch.setattr(call_log, "_local_requests", {}, raising=False)
    return rig


@pytest.fixture
def rig(fresh_db, world, monkeypatch):  # noqa: F811
    return _make_rig(fresh_db, world, monkeypatch)


@pytest.fixture
def graph_rig(fresh_db, world, monkeypatch):  # noqa: F811
    """The real wa_calling Graph client, over a scripted HTTP layer."""
    from app.core.config import settings
    for k, v in (("waba_token", "T"), ("waba_phone_number_id", "PNID"), ("waba_api_version", "v21.0"),
                 ("waba_calling_api_version", "v23.0"), ("call_meta_recording", False),
                 ("call_meta_transcription", False)):
        monkeypatch.setattr(settings, k, v, raising=False)
    return _make_rig(fresh_db, world, monkeypatch, fake_meta=False)


def run(rig, scenario):
    """Run `scenario()` in one loop with a pooled engine (production's size),
    the admin routes on an ASGI client, and every background task drained."""
    async def main():
        from fastapi import FastAPI
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
        import app.database as database
        from app.database import get_db
        from app.routers import admin
        from app.services import call_log, call_transcribe
        url = rig.db_url.replace("postgresql+psycopg2://", "postgresql+asyncpg://")
        engine = create_async_engine(url, pool_size=10, max_overflow=20, pool_timeout=30)
        real = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        def maker():
            if rig.db_down_all or _DB_DOWN.get():
                raise ConnectionRefusedError("database: connection refused")
            return real()
        for mod in (database, call_log, call_transcribe):
            rig.monkeypatch.setattr(mod, "AsyncSessionLocal", maker)
        rig.maker, rig.engine = real, engine

        async def _db():
            async with real() as s:
                try:
                    yield s
                    await s.commit()
                except Exception:
                    await s.rollback()
                    raise
        app = FastAPI()
        app.include_router(admin.router, prefix="/api/admin")
        app.dependency_overrides[get_db] = _db
        app.state.redis = rig.redis
        rig.app = app
        async with _AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t",
                                timeout=60) as client:
            rig.client = client
            try:
                return await scenario()
            finally:
                await drain(rig)
                await engine.dispose()
    return asyncio.run(main())


def spawn(rig, coro):
    t = asyncio.get_running_loop().create_task(coro)
    rig.tasks.add(t)
    return t


async def drain(rig):
    from app.services import call_transcribe, missed_call
    errors = []
    for _ in range(100):
        pending = [t for t in (*rig.tasks, *missed_call._bg, *call_transcribe._bg_tasks) if not t.done()]
        if not pending:
            break
        for r in await asyncio.gather(*pending, return_exceptions=True):
            if isinstance(r, BaseException):
                errors.append(r)
    for t in list(rig.tasks):
        if t.done() and not t.cancelled() and t.exception() is not None:
            errors.append(t.exception())
    rig.tasks.clear()
    if errors:
        raise errors[0]


# ── Deliveries through the real front doors ─────────────────────────────────

def _wa_payload(calls=(), statuses=(), contacts=(), messages=()):
    changes = []
    meta = {"messaging_product": "whatsapp", "metadata": {"phone_number_id": "PNID"}}
    if calls or statuses:
        v = {**meta, "contacts": list(contacts)}
        if calls:
            v["calls"] = list(calls)
        if statuses:
            v["statuses"] = list(statuses)
        changes.append({"field": "calls", "value": v})
    if messages:
        changes.append({"field": "messages", "value": {**meta, "contacts": list(contacts),
                                                       "messages": list(messages)}})
    return {"object": "whatsapp_business_account", "entry": [{"id": "WABA", "changes": changes}]}


async def wa_post(rig, payload, *, db_down=False):
    """One WhatsApp webhook delivery; asserts Meta gets its 200 (and times it)."""
    from app.routers import whatsapp_webhook as ww
    tok = _DB_DOWN.set(db_down)
    try:
        req = types.SimpleNamespace(app=types.SimpleNamespace(state=types.SimpleNamespace(redis=rig.redis)))
        t0 = time.perf_counter()
        resp = await ww.process_payload(req, json.dumps(payload).encode(), None)
        rig.latency.append(time.perf_counter() - t0)
    finally:
        _DB_DOWN.reset(tok)
    assert resp.status_code == 200, resp
    return resp


class _PageReq:
    def __init__(self, payload, redis):
        self._raw = json.dumps(payload).encode()
        self.headers = {}
        self.app = types.SimpleNamespace(state=types.SimpleNamespace(redis=redis))

    async def body(self):
        return self._raw

    async def json(self):
        return json.loads(self._raw)


async def page_post(rig, *calls, **entry):
    from app.routers import meta_webhook as mw
    payload = {"object": "page", "entry": [{"id": PAGE, "time": 1, **({"calls": list(calls)} if calls else {}),
                                            **entry}]}
    resp = await mw.receive_webhook(_PageReq(payload, rig.redis), None)
    assert resp.status_code == 200
    return resp


def ring_ev(cid, frm):
    return {"id": cid, "event": "connect", "from": frm, "to": "254785000000", "direction": "USER_INITIATED",
            "timestamp": "1", "session": {"sdp_type": "offer", "sdp": "v=0 offer"}}


def end_ev(cid, duration=None, **kw):
    ev = {"id": cid, "event": "terminate", "status": "COMPLETED", **kw}
    if duration is not None:
        ev["duration"] = duration
    return ev


async def ring(rig, cid, frm, name="Grace"):
    await wa_post(rig, _wa_payload([ring_ev(cid, frm)], contacts=[{"wa_id": frm, "profile": {"name": name}}]))


async def terminate_webhook(rig, cid, duration, channel="whatsapp", *, dup=0.3, delay=(0, 0.01)):
    """Meta's own terminate — late, and sometimes twice."""
    for _ in range(2 if random.random() < dup else 1):
        await asyncio.sleep(random.uniform(*delay))
        if channel == "messenger":
            ev = {"id": cid, "event": "terminate", "status": "Completed", "timestamp": 2}
            if duration:
                ev["duration"] = duration
            await page_post(rig, ev)
        else:
            await wa_post(rig, _wa_payload([end_ev(cid, duration)]))


def meta_ends_calls(rig, **kw):
    rig.meta.on_end = lambda cid, dur, ch: spawn(rig, terminate_webhook(rig, cid, dur, ch, **kw))


async def post(rig, path, who, body=None):
    return await rig.client.post(f"/api/admin{path}", json=body if body is not None else {}, headers=_as(who))


async def get(rig, path, who):
    return await rig.client.get(f"/api/admin{path}", headers=_as(who))


async def rows(rig) -> dict:
    from app.models.call import Call
    async with rig.maker() as db:
        return {c.call_id: c for c in (await db.execute(sa.select(Call))).scalars().all()}


# ── Invariants ───────────────────────────────────────────────────────────────

def check_events(rig, cid, final):
    """I3 for one call, against the order everything was published in."""
    evs = rig.redis.events(call_id=cid)
    ends = [i for i, e in enumerate(evs) if e["type"] == "call_ended"]
    assert ends, f"{cid}: its end ({final}) was never announced — some screen keeps ringing"
    outcomes = [evs[i]["outcome"] for i in ends]
    allowed = {final} | ({"no_answer"} if final == "rejected" else set())
    assert set(outcomes) <= allowed, f"{cid}: contradictory endings {outcomes}, logged {final}"
    assert outcomes[-1] == final, f"{cid}: last word {outcomes[-1]}, logged {final}"
    if final == "rejected":
        first_rej = outcomes.index("rejected")
        assert "no_answer" not in outcomes[first_rej:], f"{cid}: rejected went back to no_answer"
    late = [e["type"] for e in evs[ends[0] + 1:]
            if e["type"] in ("call_answered", "incoming_call", "outbound_answer")
            or (e["type"] == "call_status" and e.get("status") == "ringing")]
    assert not late, f"{cid}: {late} published after call_ended"
    assert len([e for e in evs if e["type"] == "call_answered"]) <= 1, f"{cid}: answered twice"
    assert len([e for e in evs if e["type"] == "incoming_call"]) <= 1, f"{cid}: rang twice"


def check_rows(logged: dict, truth: dict):
    """I1: every call over, in a status the true sequence allows."""
    for cid, allowed in truth.items():
        allowed = {allowed} if isinstance(allowed, str) else set(allowed)
        c = logged.get(cid)
        assert c is not None, f"{cid}: never logged"
        assert c.status not in ("ringing", "answered"), f"{cid}: stuck {c.status}"
        assert c.status in allowed, f"{cid}: logged {c.status}, really {allowed}"


# ═════════════════════════════════════════════════════════════════════════════
# (1) 50 calls ringing at once, 5 agents answering random ones, callers hanging up
# ═════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("seed", [1, 2, 3])
def test_storm_fifty_calls_five_agents_answer_decline_and_callers_hang_up(rig, seed):
    random.seed(seed)
    n = 50
    cids = [f"wacid.s1.{seed}.{i}" for i in range(n)]
    agents = rig.agents[:5]
    answers = []
    meta_ends_calls(rig)

    async def scenario():
        await asyncio.gather(*(ring(rig, cid, f"2547100{seed}{i:04d}") for i, cid in enumerate(cids)))
        assert len(rig.redis.events("incoming_call")) == n

        async def agent(aid):
            for _ in range(25):
                cid = random.choice(cids)
                if random.random() < 0.8:
                    r = await post(rig, f"/calls/{cid}/answer", aid, {"sdp": "v=0 answer"})
                    assert r.status_code in (200, 409, 410, 502), r.text
                    answers.append((aid, cid, r.status_code))
                    if r.status_code == 200 and random.random() < 0.5:
                        await asyncio.sleep(random.uniform(0, 0.01))
                        h = await post(rig, f"/calls/{cid}/terminate", aid)
                        assert h.status_code == 200, h.text
                else:
                    r = await post(rig, f"/calls/{cid}/terminate", aid)      # decline
                    assert r.status_code in (200, 409), r.text
                await asyncio.sleep(random.uniform(0, 0.004))

        async def callers():
            for cid in random.sample(cids, n):           # every caller hangs up at some point
                await asyncio.sleep(random.uniform(0, 0.012))
                rig.meta.hangup(cid)
        await asyncio.gather(*(agent(a) for a in agents), callers())
        await drain(rig)
        return await rows(rig)
    logged = run(rig, scenario)

    truth = {}
    for cid in cids:
        st = rig.meta.st(cid)
        if st["accepted"]:
            truth[cid] = "completed"
        elif st["by"] == "business":
            truth[cid] = "declined"
        else:
            truth[cid] = {"missed", "declined"} if st["declines"] else "missed"
    check_rows(logged, truth)
    assert len(logged) == n
    for cid in cids:
        # I2: never two accepts for one call in flight, none after one succeeded.
        assert not [v for v in rig.meta.violations if v[1] == cid], f"{cid}: duplicate accept"
        check_events(rig, cid, logged[cid].status)
        st = rig.meta.st(cid)
        if st["accepted"]:
            # Logged against the agent Meta actually connected.
            assert str(logged[cid].agent_id) == st["accepted_by"], cid
            assert logged[cid].answered_at is not None and logged[cid].duration is not None
    won = Counter(cid for _, cid, code in answers if code == 200)
    assert all(v == 1 for v in won.values()), won
    assert sum(1 for c in logged.values() if c.status == "completed") == sum(
        1 for cid in cids if rig.meta.st(cid)["accepted"])


# ═════════════════════════════════════════════════════════════════════════════
# (2) every webhook twice, shuffled, some ahead of the row / of each other
# ═════════════════════════════════════════════════════════════════════════════

def _outbound_scenarios(to, cid_of, opaque):
    """Meta's webhooks for OUR call, per ending. Shuffled by the caller."""
    ans = {"event": "connect", "direction": "BUSINESS_INITIATED", "to": to,
           "session": {"sdp_type": "answer", "sdp": "v=0 their-answer"}}
    return {
        "completed": [("status", "RINGING"), ("call", ans), ("status", "ACCEPTED"),
                      ("call", {"event": "terminate", "status": "COMPLETED", "duration": 25, "to": to})],
        "rejected": [("status", "RINGING"), ("status", "REJECTED"),
                     ("call", {"event": "terminate", "status": "COMPLETED", "to": to})],
        "no_answer": [("status", "RINGING"), ("call", {"event": "terminate", "status": "COMPLETED", "to": to})],
    }


async def _deliver_outbound(rig, cid, kind, item, with_opaque):
    if kind == "status":
        st = {"id": cid, "type": "call", "status": item, "recipient_id": "x"}
        if with_opaque:
            st["biz_opaque_callback_data"] = rig.meta.st(cid).get("opaque")
        await wa_post(rig, _wa_payload(statuses=[st]))
    else:
        ev = {"id": cid, **item}
        if with_opaque:
            ev["biz_opaque_callback_data"] = rig.meta.st(cid).get("opaque")
        await wa_post(rig, _wa_payload([ev]))


@pytest.mark.parametrize("seed", range(6))
def test_storm_duplicated_shuffled_and_early_webhooks_converge(rig, seed):
    random.seed(100 + seed)
    rig.meta.jitter = (0, 0.002)
    truth, rang_first = {}, {}
    ann, ben = rig.agents[0], rig.agents[1]

    async def inbound(i, ending):
        cid, frm = f"wacid.s2.{seed}.{i}", f"25471200{seed}{i:03d}"
        truth[cid] = ending
        if ending == "missed":
            evs = [_wa_payload([ring_ev(cid, frm)]), _wa_payload([end_ev(cid)])] * 2
            random.shuffle(evs)
            rang_first[cid] = "connect" in json.dumps(evs[0])
            for e in evs:
                await wa_post(rig, e)
                await asyncio.sleep(random.uniform(0, 0.003))
            return
        await ring(rig, cid, frm)
        if ending == "completed":
            r = await post(rig, f"/calls/{cid}/answer", ann, {"sdp": "v=0"})
            assert r.status_code == 200, r.text
            evs = [_wa_payload([ring_ev(cid, frm)]), _wa_payload([end_ev(cid, 40)]),
                   _wa_payload([end_ev(cid, 40)])]
        else:   # declined: Meta's terminate webhook may beat our own HTTP response
            async def decline_race(c=cid):
                await wa_post(rig, _wa_payload([end_ev(c)]))
            rig.meta.after_terminate[cid] = decline_race
            r = await post(rig, f"/calls/{cid}/terminate", ben)
            assert r.status_code == 200 and r.json()["outcome"] == "declined", r.text
            evs = [_wa_payload([ring_ev(cid, frm)]), _wa_payload([end_ev(cid)])]
        random.shuffle(evs)
        for e in evs:
            await wa_post(rig, e)

    async def outbound(i, ending):
        to = f"25471300{seed}{i:03d}"
        plan = {}

        async def beat_the_row(cid):
            # Meta faster than /calls/connect: some webhooks land before its row.
            items = _outbound_scenarios(to, None, None)[ending]
            items = items + random.sample(items, k=len(items))          # every one twice
            random.shuffle(items)
            if ending == "completed" and random.random() < 0.5:
                # the terminate (with its duration) ahead of the customer's answer
                items.sort(key=lambda it: 0 if it[0] == "call" and it[1].get("event") == "terminate" else 1)
            cut = random.randint(0, len(items))
            plan[cid] = items[cut:]
            for kind, item in items[:cut]:
                await _deliver_outbound(rig, cid, kind, item, with_opaque=random.random() < 0.5)
        rig.meta.connect_hooks[to] = beat_the_row
        r = await post(rig, "/calls/connect", ann, {"to": to, "sdp": "v=0 offer"})
        assert r.status_code == 200, r.text
        cid = r.json()["call_id"]
        truth[cid] = ending
        for kind, item in plan[cid]:
            await asyncio.sleep(random.uniform(0, 0.003))
            await _deliver_outbound(rig, cid, kind, item, with_opaque=random.random() < 0.5)

    async def scenario():
        jobs = []
        for i in range(6):
            jobs.append(inbound(i, ("missed", "completed", "declined")[i % 3]))
        for i in range(6):
            jobs.append(outbound(i, ("completed", "rejected", "no_answer")[i % 3]))
        # Sequential per call (a route and its webhooks), concurrent across calls.
        await asyncio.gather(*jobs)
        await drain(rig)
        return await rows(rig)
    logged = run(rig, scenario)
    check_rows(logged, truth)
    for cid, final in truth.items():
        check_events(rig, cid, final)
        if rang_first.get(cid) is False:
            assert not rig.redis.events("incoming_call", cid), f"{cid}: rang a call that was already over"
    # I2: one connect per placed call, one row per call id.
    assert rig.meta.count("connect") == 6
    assert len(logged) == len(truth)
    outbound_rows = [c for c in logged.values() if c.direction == "outbound"]
    assert len(outbound_rows) == 6 and all(str(c.agent_id) == ann for c in outbound_rows)
    for c in logged.values():
        if c.status == "completed":
            assert c.answered_at is not None and c.duration


# ═════════════════════════════════════════════════════════════════════════════
# (3) Meta flaky: 429 / 500 / timeout / expired token on every calling request
# ═════════════════════════════════════════════════════════════════════════════

R429 = _Resp(429, {"error": {"message": "(#130429) Rate limit hit", "code": 130429}})
R500 = _Resp(500, {"error": {"message": "An unknown error has occurred.", "code": 1, "is_transient": True}})
R190 = _Resp(401, {"error": {"message": "Error validating access token: Session has expired on Friday.",
                             "type": "OAuthException", "code": 190}})
FAILURES = {"429": (R429, "rate_limited", "wait", True),
            "500": (R500, "meta_unavailable", "retry", True),
            "timeout": ("timeout", "meta_unavailable", "retry", True),
            "190": (R190, "190", "admin", False)}


class Graph:
    """Graph's HTTP layer, scripted per endpoint (POST /calls split by action)."""

    def __init__(self):
        self.plan: dict = {}
        self.requests: list = []

    def on(self, key, *steps):
        self.plan.setdefault(key, []).extend(steps)

    def count(self, key):
        return sum(1 for k in self.requests if k == key)

    def client(self, *a, **k):
        graph = self

        class _C:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def _next(self, method, url, body):
                edge = url.rsplit("/", 1)[-1]
                key = f"{method} {edge}" + (f":{body.get('action')}" if edge == "calls" and body else "")
                graph.requests.append(key)
                await asyncio.sleep(0)
                steps = graph.plan.get(key) or []
                step = steps.pop(0) if steps else None
                if step == "timeout":
                    raise httpx.ReadTimeout("timed out")
                if step is not None:
                    return step
                if key == "POST calls:connect":
                    return _Resp(200, {"calls": [{"id": f"wacid.g.{len(graph.requests)}"}]})
                if key == "GET call_permissions":
                    return _Resp(200, {"permission": {"status": "no_permission"}, "actions": []})
                if key == "GET settings":
                    return _Resp(200, {"calling": {"status": "ENABLED", "call_hours": {
                        "status": "ENABLED", "timezone_id": "Africa/Nairobi", "weekly_operating_hours": [],
                        "holiday_schedule": [{"date": "2026-12-25", "start_time": "0000", "end_time": "2359"}]}}})
                return _Resp(200, {"success": True})

            async def post(self, url, headers=None, json=None, timeout=None):
                return await self._next("POST", url, json)

            async def get(self, url, headers=None, params=None, timeout=None):
                return await self._next("GET", url, None)
        return _C()


@pytest.mark.parametrize("failure", list(FAILURES))
def test_meta_flaky_every_request_gets_the_right_code_action_and_nothing_sticks(graph_rig, failure):
    rig = graph_rig
    resp, code, action, retryable = FAILURES[failure]
    ann, ben, boss = rig.agents[0], rig.agents[1], rig.world["boss"]
    g = Graph()
    wa_in_window = "254714000001"
    _inbound_message(rig, wa_in_window, hours_ago=1)

    def expect(r, status):
        assert r.status_code == status, r.text
        assert r.json()["code"] == code and r.json()["action"] == action, r.json()
        assert r.headers["X-Neema-Reason"] == code

    async def scenario():
        from app.services import wa_calling
        rig.monkeypatch.setattr(wa_calling.httpx, "AsyncClient", g.client)
        # accept: never retried; the lock is released so a colleague can answer.
        await ring(rig, "wacid.g.acc", "254714000010")
        g.on("POST calls:accept", resp)
        expect(await post(rig, "/calls/wacid.g.acc/answer", ann, {"sdp": "v=0"}), 502)
        assert g.count("POST calls:accept") == 1
        r = await post(rig, "/calls/wacid.g.acc/answer", ben, {"sdp": "v=0"})
        assert r.status_code == 200, r.text
        assert g.count("POST calls:accept") == 2

        # connect: never retried, no row, the agent may try again.
        g.on("POST calls:connect", resp)
        expect(await post(rig, "/calls/connect", ann, {"to": "254714000020", "sdp": "v=0"}), 502)
        assert g.count("POST calls:connect") == 1
        # terminate: idempotent → retried once on 429 / 5xx / network, not on 190.
        await ring(rig, "wacid.g.term", "254714000030")
        g.on("POST calls:terminate", resp, resp)
        expect(await post(rig, "/calls/wacid.g.term/terminate", ann), 502)
        assert g.count("POST calls:terminate") == (2 if retryable else 1)
        # The decline never happened: still ringing, and a colleague can still answer.
        r = await post(rig, "/calls/wacid.g.term/answer", ben, {"sdp": "v=0"})
        assert r.status_code == 200, r.text

        # permission read: retried once, then our store — never an error.
        g.on("GET call_permissions", resp, resp)
        r = await get(rig, "/calls/permission?wa_id=254714000040", ann)
        assert r.status_code == 200 and r.json()["source"] == "store", r.text
        assert g.count("GET call_permissions") == (2 if retryable else 1)

        # permission request: never retried; the claim is released for Try again.
        g.on("POST messages", resp)
        r = await post(rig, "/calls/request-permission", ann, {"to": wa_in_window})
        assert r.status_code == 502 and r.json()["code"] == code and r.json()["action"] == action, r.text
        assert g.count("POST messages") == 1
        r = await post(rig, "/calls/request-permission", ann, {"to": wa_in_window})
        assert r.status_code == 200, r.text
        assert g.count("POST messages") == 2

        # settings: read retried once; a change needing the current value writes nothing.
        g.on("GET settings", resp, resp)
        expect(await get(rig, "/calls/settings", boss), 502)
        g.on("GET settings", resp, resp)
        r = await post(rig, "/calls/settings", boss, {"call_hours": {"status": "DISABLED"}})
        assert r.status_code == 503 and r.json()["action"] == "retry", r.text
        assert g.count("POST settings") == 0
        g.on("POST settings", resp)
        expect(await post(rig, "/calls/settings", boss, {"status": "DISABLED"}), 502)
        assert g.count("POST settings") == 1

        # Nothing sticks: Meta's terminates close what rang; a lost one is swept.
        await wa_post(rig, _wa_payload([end_ev("wacid.g.acc", 30), end_ev("wacid.g.term", 12)]))
        await ring(rig, "wacid.g.lost", "254714000050")
        async with rig.maker() as db:
            await db.execute(sa.text("UPDATE calls SET started_at = NOW() - INTERVAL '5 minutes' "
                                     "WHERE call_id = 'wacid.g.lost'"))
            await db.commit()
        assert (await get(rig, "/calls", ann)).status_code == 200
        return await rows(rig)
    logged = run(rig, scenario)
    check_rows(logged, {"wacid.g.acc": "completed", "wacid.g.term": "completed", "wacid.g.lost": "missed"})
    assert str(logged["wacid.g.acc"].agent_id) == ben and str(logged["wacid.g.term"].agent_id) == ben
    assert not [c for c in logged.values() if c.direction == "outbound"]     # the failed connect left no row


# ═════════════════════════════════════════════════════════════════════════════
# (4) Redis unavailable: None, or every call raising
# ═════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("mode", ["none", "broken"])
def test_redis_down_degrades_never_500s_and_still_one_accept(rig, mode):
    rig.redis = None if mode == "none" else BrokenRedis()
    agents = rig.agents
    wa = "254715000001"
    _inbound_message(rig, wa, hours_ago=1)
    rig.meta.perm[wa] = _calls._meta_perm("temporary")

    async def scenario():
        # Ring: every delivery acked 200 and logged.
        await asyncio.gather(*(ring(rig, f"wacid.r.{mode}.{i}", f"2547150001{i}") for i in range(5)))
        await page_post(rig, {"id": f"c_r_{mode}", "to": PAGE, "from": "5275811702400001", "event": "connect",
                              "call_direction": "user_initiated"})
        logged = await rows(rig)
        assert all(logged[f"wacid.r.{mode}.{i}"].status == "ringing" for i in range(5))
        assert logged[f"c_r_{mode}"].channel == "messenger"
        # Ten agents answer the same call at once: exactly one reaches Meta.
        res = await asyncio.gather(*(post(rig, f"/calls/wacid.r.{mode}.0/answer", a, {"sdp": "v=0"})
                                     for a in agents))
        codes = Counter(r.status_code for r in res)
        assert codes[200] == 1 and set(codes) <= {200, 409}, codes
        assert rig.meta.count("accept", f"wacid.r.{mode}.0") == 1 and not rig.meta.violations
        # Meta refuses an answer: the claim is released, a colleague retries.
        from app.services.wa_calling import MetaError
        rig.meta.fail["accept"] = [MetaError("WA call accept failed (503)", status=503)]
        r = await post(rig, f"/calls/wacid.r.{mode}.1/answer", agents[0], {"sdp": "v=0"})
        assert r.status_code == 502 and r.json()["action"] == "retry", r.text
        r = await post(rig, f"/calls/wacid.r.{mode}.1/answer", agents[1], {"sdp": "v=0"})
        assert r.status_code == 200, r.text
        # Decline, Messenger answer, terminates.
        r = await post(rig, f"/calls/wacid.r.{mode}.2/terminate", agents[2])
        assert r.status_code == 200 and r.json()["outcome"] == "declined", r.text
        r = await post(rig, f"/calls/wacid.r.{mode}.3/callback", agents[3])
        assert r.status_code == 200, r.text
        await wa_post(rig, _wa_payload([end_ev(f"wacid.r.{mode}.0", 33), end_ev(f"wacid.r.{mode}.1", 9),
                                        end_ev(f"wacid.r.{mode}.2"), end_ev(f"wacid.r.{mode}.4")]))
        await page_post(rig, {"id": f"c_r_{mode}", "event": "terminate", "status": "Completed"})
        # Permission read / request / our own call.
        r = await get(rig, f"/calls/permission?wa_id={wa}", agents[0])
        assert r.status_code == 200 and r.json()["status"] == "granted", r.text
        res = await asyncio.gather(*(post(rig, "/calls/request-permission", a, {"to": wa}) for a in agents[:4]))
        assert Counter(r.status_code for r in res) == Counter({200: 1, 409: 3}), [r.text for r in res]
        assert rig.meta.count("request", wa) == 1
        r = await post(rig, "/calls/connect", agents[0], {"to": wa, "sdp": "v=0"})
        assert r.status_code == 200, r.text
        out = r.json()["call_id"]
        r = await post(rig, f"/calls/{out}/terminate", agents[0])
        assert r.status_code == 200 and r.json()["outcome"] == "cancelled", r.text
        r = await get(rig, "/calls?limit=50", agents[0])
        assert r.status_code == 200
        return await rows(rig), out
    logged, out = run(rig, scenario)
    check_rows(logged, {f"wacid.r.{mode}.0": "completed", f"wacid.r.{mode}.1": "completed",
                        f"wacid.r.{mode}.2": "declined", f"wacid.r.{mode}.3": "callback",
                        f"wacid.r.{mode}.4": "missed", f"c_r_{mode}": "missed", out: "cancelled"})
    assert str(logged[f"wacid.r.{mode}.1"].agent_id) == agents[1]


# ═════════════════════════════════════════════════════════════════════════════
# (5) the database down in the middle of a webhook
# ═════════════════════════════════════════════════════════════════════════════

def test_database_down_mid_webhook_acks_fast_and_converges(rig):
    async def scenario():
        # A: the connect's row is lost to the blip (only for this delivery — a
        # concurrent call is untouched); the terminate later writes it, missed.
        t0 = time.perf_counter()
        await asyncio.gather(
            wa_post(rig, _wa_payload([ring_ev("wacid.db.a", "254716000001")]), db_down=True),
            ring(rig, "wacid.db.ok", "254716000009"))
        assert time.perf_counter() - t0 < 1.0
        assert rig.redis.events("incoming_call", "wacid.db.a")          # it rang
        assert "wacid.db.a" not in await rows(rig)
        await wa_post(rig, _wa_payload([end_ev("wacid.db.a")]))
        # B: a redelivered connect writes it; the sweep closes it when its end never comes.
        await wa_post(rig, _wa_payload([ring_ev("wacid.db.b", "254716000002")]), db_down=True)
        await wa_post(rig, _wa_payload([ring_ev("wacid.db.b", "254716000002")]))
        async with rig.maker() as db:
            await db.execute(sa.text("UPDATE calls SET started_at = NOW() - INTERVAL '5 minutes' "
                                     "WHERE call_id = 'wacid.db.b'"))
            await db.commit()
        assert (await get(rig, "/calls/wacid.db.b", rig.agents[0])).json()["status"] == "missed"
        # C: the terminate hits the blip; Meta's redelivery applies it (no 2-min wait).
        await ring(rig, "wacid.db.c", "254716000003")
        r = await post(rig, "/calls/wacid.db.c/answer", rig.agents[0], {"sdp": "v=0"})
        assert r.status_code == 200
        await wa_post(rig, _wa_payload([end_ev("wacid.db.c", 50)]), db_down=True)
        await wa_post(rig, _wa_payload([end_ev("wacid.db.c", 50)]))
        # D: a terminate that beat its connect, both hitting the blip, then redelivered.
        await wa_post(rig, _wa_payload([end_ev("wacid.db.d")]), db_down=True)
        await wa_post(rig, _wa_payload([ring_ev("wacid.db.d", "254716000004")]), db_down=True)
        await wa_post(rig, _wa_payload([ring_ev("wacid.db.d", "254716000004")]))
        await wa_post(rig, _wa_payload([end_ev("wacid.db.ok")]))
        return await rows(rig)
    logged = run(rig, scenario)
    truth = {"wacid.db.a": "missed", "wacid.db.b": "missed", "wacid.db.c": "completed",
             "wacid.db.d": "missed", "wacid.db.ok": "missed"}
    check_rows(logged, truth)
    assert logged["wacid.db.c"].duration == 50
    for cid in ("wacid.db.a", "wacid.db.c", "wacid.db.d", "wacid.db.ok"):
        check_events(rig, cid, truth[cid])
    assert not rig.redis.events("incoming_call", "wacid.db.d")
    assert max(rig.latency) < 1.0


# ═════════════════════════════════════════════════════════════════════════════
# (6) the AI down / answering garbage while transcribing
# ═════════════════════════════════════════════════════════════════════════════

def _seed_call(rig, cid, wa, status="completed"):
    eng = sa.create_engine(rig.db_url)
    with eng.begin() as c:
        c.execute(sa.text(
            "INSERT INTO calls (id, call_id, wa_id, channel, direction, status, started_at, answered_at, ended_at, "
            "duration, transcript_status) VALUES (:i, :c, :w, 'whatsapp', 'inbound', :s, NOW(), NOW(), NOW(), 60, "
            "'none')"), {"i": str(uuid.uuid4()), "c": cid, "w": wa, "s": status})
    eng.dispose()


def test_ai_down_or_garbage_never_breaks_a_call_or_loses_the_transcript(rig, tmp_path):
    from app.services import call_transcribe as ct, wa_calling
    import app.agent.runtime as runtime
    downloads, analyses = [], []

    async def download(media_id):
        downloads.append(media_id)
        await asyncio.sleep(0.01)
        return json.dumps(TRANSCRIPT_DOC).encode(), "application/json"

    async def no_update(cid):
        return None

    async def no_note(db, wa_id, summary):
        return None
    rig.monkeypatch.setattr(wa_calling, "download_media", download)
    rig.monkeypatch.setattr(ct, "_publish_update", no_update)
    rig.monkeypatch.setattr(ct, "_save_call_note", no_note)
    replies = {}

    class LLM:
        async def complete(self, system, messages, tools):
            analyses.append(1)
            reply = replies["next"]
            if isinstance(reply, Exception):
                raise reply
            return types.SimpleNamespace(text=reply)
    rig.monkeypatch.setattr(runtime, "build_llm", lambda **k: LLM())
    cases = {
        "down": RuntimeError("anthropic: 529 overloaded"),
        "prose": "I'm sorry, I can't help with that.",
        "wrong_types": '{"summary": ["a", "b"], "products": 5, "intent": {"x": 1}, '
                       '"commitments": "call back Friday", "sentiment": null, "objections": [{"a": 1}]}',
        "not_json": "{summary: nope",
    }
    for i, name in enumerate(cases):
        _seed_call(rig, f"wacid.ai.{name}", f"25471700000{i}")
    _seed_call(rig, "wacid.ai.dup", "254717000009")
    _seed_call(rig, "wacid.ai.local", "254717000008")
    audio = tmp_path / "call.webm"
    audio.write_bytes(b"x")

    def event(cid, media):
        return {"id": cid, "event": "call_transcription_available", "transcription": {"id": media}}

    async def scenario():
        for name, reply in cases.items():
            replies["next"] = reply
            await wa_post(rig, _wa_payload([event(f"wacid.ai.{name}", f"m.{name}")]))
            await drain(rig)
        # Meta delivers the same transcript event twice at once (redis blind): analysed once.
        replies["next"] = '{"summary": "Wants two cassocks.", "next_action": "Send price"}'
        rig.app.state.redis = rig.redis = None
        await asyncio.gather(*(wa_post(rig, _wa_payload([event("wacid.ai.dup", "m.dup")])) for _ in range(3)))
        await drain(rig)
        # Our own recording, transcribed here, with the AI down.
        replies["next"] = RuntimeError("anthropic down")
        async with rig.maker() as db:
            await db.execute(sa.text("UPDATE calls SET recording_url = 'call.webm', transcript_status = 'pending' "
                                     "WHERE call_id = 'wacid.ai.local'"))
            await db.commit()
        rig.monkeypatch.setattr(ct, "_local_path", lambda url: str(audio))
        rig.monkeypatch.setattr(ct, "_transcribe_sync", lambda path: ("Agent: habari\nCustomer: sawa", "sw"))
        await ct._process("wacid.ai.local")
        return await rows(rig)
    before = len(analyses)
    logged = run(rig, scenario)
    for cid, c in logged.items():
        assert c.status == "completed", cid                       # the call itself is untouched
        assert c.transcript and c.transcript.startswith("Agent: "), cid   # the transcript is never lost
    assert logged["wacid.ai.down"].transcript_status == "failed" and logged["wacid.ai.down"].summary is None
    assert logged["wacid.ai.local"].transcript_status == "failed"
    assert logged["wacid.ai.prose"].transcript_status == "done"
    assert logged["wacid.ai.prose"].insights is None
    wt = logged["wacid.ai.wrong_types"]
    assert wt.transcript_status == "done"
    assert wt.insights == {"products": ["5"], "commitments": ["call back Friday"]}
    assert logged["wacid.ai.not_json"].transcript_status == "done"
    dup = logged["wacid.ai.dup"]
    assert dup.transcript_status == "done" and dup.summary == "Wants two cassocks."
    assert downloads.count("m.dup") == 1
    assert len(analyses) - before == len(cases) + 1 + 1          # once each, once for the dup, once local


def test_garbage_from_analyse_call_itself_is_contained(rig):
    from app.services import call_transcribe as ct

    async def garbage(text):
        return 12345, ["not", "a", "dict"]

    async def no_update(cid):
        return None
    rig.monkeypatch.setattr(ct, "analyse_call", garbage)
    rig.monkeypatch.setattr(ct, "_publish_update", no_update)
    _seed_call(rig, "wacid.ai.g", "254717100000")

    async def scenario():
        assert await ct._finish("wacid.ai.g", "254717100000", "Agent: hi", "en") is True
        return await rows(rig)
    c = run(rig, scenario)["wacid.ai.g"]
    assert c.transcript_status == "done" and c.summary is None and c.insights is None
    assert c.transcript == "Agent: hi" and c.status == "completed"


# ═════════════════════════════════════════════════════════════════════════════
# (7) permissions: expiry, a revoke racing a connect, the request limit under taps
# ═════════════════════════════════════════════════════════════════════════════

def test_expired_temporary_permission_is_not_a_permission(rig):
    from app.services.wa_calling import MetaError
    wa = "254718000001"
    past = int((datetime.now(timezone.utc) - timedelta(hours=1)).timestamp())
    rig.meta.perm[wa] = {"permission": {"status": "temporary", "expiration_time": past}}

    async def scenario():
        # Our own record says granted — but it expired too.
        from app.services import call_log
        await call_log.note_permission_reply(rig.redis, wa, {
            "response": "accept", "expiration_timestamp": str(past)})
        p = (await get(rig, f"/calls/permission?wa_id={wa}", rig.agents[0])).json()
        assert p["status"] == "unknown" and p["meta_status"] == "no_permission" and p["can_call"] is False
        rig.meta.fail["connect"] = [MetaError('WA call connect failed (400): {"error":{"code":138006}}',
                                              status=400, code=138006)]
        r = await post(rig, "/calls/connect", rig.agents[0], {"to": wa, "sdp": "v=0"})
        assert r.status_code == 409 and r.json()["code"] == "138006"
        assert r.json()["action"] == "request_permission"
        return await rows(rig)
    assert run(rig, scenario) == {}
    assert rig.meta.count("connect") == 1


def test_a_revoke_racing_a_refused_connect_is_never_lost(rig):
    """WhatsApp revokes the permission (4 unanswered calls) while our connect is
    being refused for it: the revoke must survive whatever the connect path writes."""
    from app.services import call_log
    from app.services.wa_calling import MetaError
    wa = "254718000002"
    revoke = {"from": wa, "id": "wamid.r", "type": "interactive", "interactive": {
        "type": "call_permission_reply", "call_permission_reply": {
            "response": "reject", "response_source": "automatic"}}}
    fired = []

    async def racer(key, value):
        # The revoke lands between the connect path's read and its write.
        if key == f"wa:call:perm:{wa}" and '"unknown"' in str(value) and not fired:
            fired.append(1)
            rig.redis.before_set = None
            await wa_post(rig, _wa_payload(messages=[revoke]))
            rig.redis.before_set = racer

    async def scenario():
        await call_log.set_permission(rig.redis, wa, "granted",
                                      expires_at=datetime.now(timezone.utc) + timedelta(days=3))
        rig.meta.fail["connect"] = [MetaError('WA call connect failed (400): {"error":{"code":138006}}',
                                              status=400, code=138006)]
        rig.redis.before_set = racer
        r = await post(rig, "/calls/connect", rig.agents[0], {"to": wa, "sdp": "v=0"})
        rig.redis.before_set = None
        assert r.status_code == 409
        if not fired:
            await wa_post(rig, _wa_payload(messages=[revoke]))
        st = await call_log.stored_permission(rig.redis, wa)
        assert st["status"] == "denied" and st["revoked"] is True, st
        p = (await get(rig, f"/calls/permission?wa_id={wa}", rig.agents[0])).json()   # Meta unreachable
        assert p["status"] == "denied" and p["revoked"] is True and p["source"] == "store"
        # The stale grant stays stale; a NEW grant after it wins.
        await call_log.note_permission_reply(rig.redis, wa, {"response": "accept", "is_permanent": True})
        assert (await call_log.stored_permission(rig.redis, wa))["status"] == "granted"
    run(rig, scenario)


def test_a_stale_grant_is_dropped_but_a_later_grant_is_kept(rig):
    from app.services import call_log
    from app.services.wa_calling import MetaError
    wa = "254718000003"

    async def scenario():
        await call_log.set_permission(rig.redis, wa, "granted", permanent=True)
        rig.meta.fail["connect"] = [MetaError('{"error":{"code":138006}}', status=400, code=138006)]
        r = await post(rig, "/calls/connect", rig.agents[0], {"to": wa, "sdp": "v=0"})
        assert r.status_code == 409
        assert (await call_log.stored_permission(rig.redis, wa))["status"] == "unknown"
        await asyncio.sleep(0.001)
        await call_log.note_permission_reply(rig.redis, wa, {"response": "accept"})
        assert (await call_log.stored_permission(rig.redis, wa))["status"] == "granted"
    run(rig, scenario)


def test_ten_agents_tapping_send_call_request_send_one(rig):
    wa, psid = "254718000004", "5275811702400004"
    _inbound_message(rig, wa, hours_ago=1)
    rig.meta.perm[wa] = _calls._meta_perm("no_permission", can_call=False)
    rig.meta.jitter = (0.005, 0.02)

    async def scenario():
        res = await asyncio.gather(*(post(rig, "/calls/request-permission", a, {"to": wa}) for a in rig.agents))
        codes = Counter(r.status_code for r in res)
        assert codes == Counter({200: 1, 409: 9}), [r.text for r in res]
        for r in res:
            if r.status_code == 409:
                assert r.json()["code"] == "138009" and r.json()["action"] == "wait"
        assert rig.meta.count("request", wa) == 1
        # Once it went out, the limit is known: say when, don't ask Meta to refuse.
        p = (await get(rig, f"/calls/permission?wa_id={wa}", rig.agents[0])).json()
        assert p["status"] == "requested" and p["can_request"] is False and p["request_available_at"]
        r = await post(rig, "/calls/request-permission", rig.agents[0], {"to": wa})
        assert r.status_code == 409 and r.json()["request_available_at"]
        assert rig.meta.count("request", wa) == 1
        # Messenger: the same taps, one calling_optin.
        res = await asyncio.gather(*(post(rig, "/calls/request-permission", a,
                                          {"channel": "messenger", "psid": psid}) for a in rig.agents[:5]))
        assert Counter(r.status_code for r in res) == Counter({200: 1, 409: 4}), [r.text for r in res]
        assert rig.meta.count("m_request", psid) == 1
        assert all(r.json()["action"] == "wait" for r in res if r.status_code == 409)
    run(rig, scenario)


def test_metas_own_138009_is_a_wait_and_frees_the_claim(rig):
    from app.services.wa_calling import MetaError
    wa = "254718000005"
    _inbound_message(rig, wa, hours_ago=1)

    async def scenario():
        rig.meta.fail["request"] = [MetaError('WA call-permission request failed (400): '
                                              '{"error":{"code":138009}}', status=400, code=138009)]
        r = await post(rig, "/calls/request-permission", rig.agents[0], {"to": wa})
        assert r.status_code == 409 and r.json()["code"] == "138009" and r.json()["action"] == "wait"
        r = await post(rig, "/calls/request-permission", rig.agents[1], {"to": wa})
        assert r.status_code == 200, r.text                # Meta's limit lifted: nothing of ours blocks it
    run(rig, scenario)


# ═════════════════════════════════════════════════════════════════════════════
# (8) the same person calling on WhatsApp and Messenger at once
# ═════════════════════════════════════════════════════════════════════════════

def test_same_person_on_whatsapp_and_messenger_at_once(rig):
    from app.core.config import settings
    rig.monkeypatch.setattr(settings, "missed_call_message_enabled", True, raising=False)
    wa, psid = "254719000001", "5275811702499001"
    meta_ends_calls(rig, dup=0.5)

    async def scenario():
        await asyncio.gather(
            ring(rig, "wacid.x.1", wa),
            page_post(rig, {"id": "c_x_1", "to": PAGE, "from": psid, "event": "connect",
                            "call_direction": "user_initiated"}))
        await asyncio.gather(            # they call again on both, a moment later
            ring(rig, "wacid.x.2", wa),
            page_post(rig, {"id": "c_x_2", "to": PAGE, "from": psid, "event": "connect",
                            "call_direction": "user_initiated"}))
        res = await asyncio.gather(*(post(rig, f"/calls/{cid}/answer", a, {"sdp": "v=0"})
                                     for a in rig.agents[:5] for cid in ("wacid.x.1", "c_x_1")))
        by_call = {"wacid.x.1": [], "c_x_1": []}
        for (a, cid), r in zip([(a, c) for a in rig.agents[:5] for c in ("wacid.x.1", "c_x_1")], res):
            by_call[cid].append(r.status_code)
        assert by_call["wacid.x.1"].count(200) == 1 and by_call["c_x_1"].count(200) == 1, by_call
        assert rig.meta.count("accept") == 1 and rig.meta.count("m_accept") == 1 and not rig.meta.violations
        rig.meta.hangup("wacid.x.1")
        rig.meta.hangup("c_x_1", "messenger")
        rig.meta.hangup("wacid.x.2")                          # nobody answered either second call
        rig.meta.hangup("c_x_2", "messenger")
        # Both permission requests at once: separate stores, both sent.
        _r1, _r2 = await asyncio.gather(
            post(rig, "/calls/request-permission", rig.agents[0], {"channel": "messenger", "psid": psid}),
            get(rig, f"/calls/permission?channel=messenger&psid={psid}", rig.agents[1]))
        assert _r1.status_code == 200 and _r2.status_code == 200
        await drain(rig)
        return await rows(rig)
    logged = run(rig, scenario)
    truth = {"wacid.x.1": "completed", "c_x_1": "completed", "wacid.x.2": "missed", "c_x_2": "missed"}
    check_rows(logged, truth)
    for cid, final in truth.items():
        check_events(rig, cid, final)
    assert logged["c_x_1"].channel == "messenger" and logged["c_x_1"].external_id == psid
    assert logged["wacid.x.1"].channel == "whatsapp" and logged["wacid.x.1"].wa_id == wa
    assert all(e.get("channel") == "messenger" for e in rig.redis.events("call_ended", "c_x_2"))
    # One missed-call message per channel, never for the answered pair.
    assert sorted(rig.sent_msgs) == [("messenger", psid), ("whatsapp", wa)]


# ═════════════════════════════════════════════════════════════════════════════
# I4 / I5: ingestion when the calls taps raise; the missed-call message
# ═════════════════════════════════════════════════════════════════════════════

def test_message_ingestion_survives_every_calls_tap_raising(rig):
    from app.services import call_log

    async def boom(*a, **k):
        raise RuntimeError("calls tap exploded")
    for name in ("record_ringing", "known_call", "note_permission_reply", "link_voicemail", "mark_ended",
                 "publish"):
        rig.monkeypatch.setattr(call_log, name, boom)
    rig.redis = BrokenRedis()
    msg = {"from": "254720000001", "id": "wamid.m1", "type": "text", "text": {"body": "Bei ya cassock?"}}
    perm = {"from": "254720000001", "id": "wamid.p", "type": "interactive", "interactive": {
        "type": "call_permission_reply", "call_permission_reply": {"response": "accept"}}}
    vm = {"from": "254720000001", "id": "wacid.vm", "type": "audio", "audio": {"id": "a1"}}

    async def scenario():
        await wa_post(rig, {"object": "whatsapp_business_account", "entry": [{"id": "W", "changes": [
            {"field": "calls", "value": {"calls": [ring_ev("wacid.i4", "254720000001"), end_ev("wacid.i4")]}},
            {"field": "messages", "value": {"messages": [msg, perm, vm]}}]}]})
        await page_post(rig, {"id": "c_i4", "to": PAGE, "from": "5275811702400009", "event": "connect",
                              "call_direction": "user_initiated"},
                        messaging=[{"sender": {"id": "5275811702400009"}, "recipient": {"id": PAGE},
                                    "message": {"mid": "m.1", "text": "hello"},
                                    "call_permission_reply": {"response": "approve"}}])
    run(rig, scenario)
    assert len(rig.ingested) == 1 and "Bei ya cassock?" in json.dumps(rig.ingested[0])
    assert len(rig.captured) == 1 and rig.captured[0][0] == "messenger"


@pytest.mark.parametrize("mode", ["redis", "none"])
def test_n_missed_calls_ending_at_once_send_one_message(rig, mode):
    from app.core.config import settings
    from app.services import call_log
    rig.monkeypatch.setattr(settings, "missed_call_message_enabled", True, raising=False)
    if mode == "none":
        rig.redis = None
    wa, answered_wa = "254721000001", "254721000002"

    async def scenario():
        cids = [f"wacid.mc.{mode}.{i}" for i in range(8)]
        await asyncio.gather(*(ring(rig, c, wa) for c in cids), ring(rig, f"wacid.mc.{mode}.ans", answered_wa))
        r = await post(rig, f"/calls/wacid.mc.{mode}.ans/answer", rig.agents[0], {"sdp": "v=0"})
        assert r.status_code == 200
        async with rig.maker() as db:     # half of them are stale: the sweep races the terminates
            await db.execute(sa.text("UPDATE calls SET started_at = NOW() - INTERVAL '5 minutes' "
                                     "WHERE call_id = ANY(:c)"), {"c": cids[:4]})
            await db.commit()

        async def sweep():
            async with rig.maker() as db:
                await call_log.sweep_stale(db, rig.redis)
        # Every terminate twice, all at once, plus the sweep and the answered call's end.
        await asyncio.gather(*(wa_post(rig, _wa_payload([end_ev(c)])) for c in cids + cids), sweep(),
                             wa_post(rig, _wa_payload([end_ev(f"wacid.mc.{mode}.ans", 45)])))
        await drain(rig)
        return await rows(rig)
    logged = run(rig, scenario)
    assert rig.sent_msgs == [("whatsapp", wa)], rig.sent_msgs
    assert logged[f"wacid.mc.{mode}.ans"].status == "completed"
    assert all(c.status == "missed" for k, c in logged.items() if not k.endswith(".ans"))


# ═════════════════════════════════════════════════════════════════════════════
# (9) a burst of 200 deliveries: handler latency, and no N+1 in the Calls list
# ═════════════════════════════════════════════════════════════════════════════

def test_burst_of_200_deliveries_latency_and_calls_list_query_count(rig):
    random.seed(9)
    stats = {}

    async def scenario():
        from app.models.conversation import Conversation
        deliveries = []
        for i in range(100):
            cid, frm = f"wacid.b.{i}", f"25472200{i:04d}"
            deliveries += [(0, _wa_payload([ring_ev(cid, frm)], contacts=[{"wa_id": frm, "profile": {"name": "G"}}])),
                           (1, _wa_payload([end_ev(cid, 30 if i % 3 == 0 else None)]))]
        random.shuffle(deliveries)             # a call's terminate often lands before its connect
        gate = asyncio.Semaphore(10)           # ten deliveries in flight at any moment

        async def one(p):
            async with gate:
                await wa_post(rig, p)
        rig.latency.clear()
        t0 = time.perf_counter()
        await asyncio.gather(*(one(p) for _, p in deliveries))
        stats["wall"] = time.perf_counter() - t0
        stats["lat"] = sorted(rig.latency)
        # Give the list real joins to make: chats, agents, people, follow-ups, both channels.
        async with rig.maker() as db:
            for i in range(0, 100, 2):
                db.add(Conversation(channel="whatsapp", external_id=f"25472200{i:04d}", wa_id=f"25472200{i:04d}"))
            await db.execute(sa.text("UPDATE calls SET agent_id = :a WHERE call_id LIKE 'wacid.b.1%'"),
                             {"a": rig.agents[1]})
            await db.commit()
        for i in range(10):
            await page_post(rig, {"id": f"c_b_{i}", "to": PAGE, "from": f"52758117024{i:05d}",
                                  "event": "connect", "call_direction": "user_initiated"})
        counts = {}

        def count(conn, cursor, statement, params, context, executemany):
            counts["n"] = counts.get("n", 0) + 1
        await get(rig, "/calls?limit=100", rig.agents[0])          # warm
        sa.event.listen(rig.engine.sync_engine, "before_cursor_execute", count)
        for limit in (10, 100):
            counts["n"] = 0
            r = await get(rig, f"/calls?limit={limit}", rig.agents[0])
            assert r.status_code == 200 and len(r.json()) == limit
            stats[f"q{limit}"] = counts["n"]
        counts["n"] = 0
        r = await get(rig, "/calls?limit=100&view=follow_up", rig.agents[0])
        stats["q_follow"] = counts["n"]
        sa.event.remove(rig.engine.sync_engine, "before_cursor_execute", count)
        return await rows(rig)
    logged = run(rig, scenario)
    lat = stats["lat"]
    p50, p95 = statistics.median(lat), lat[int(len(lat) * 0.95) - 1]
    print(f"\nburst: 200 deliveries in {stats['wall']:.2f}s, p50 {p50 * 1000:.1f} ms, "
          f"p95 {p95 * 1000:.1f} ms, max {lat[-1] * 1000:.1f} ms; "
          f"GET /calls statements: limit=10 → {stats['q10']}, limit=100 → {stats['q100']}, "
          f"follow_up → {stats['q_follow']}")
    assert len(lat) == 200
    assert p95 < 0.2, f"p95 {p95 * 1000:.0f} ms"
    # No N+1: a 100-row page (people, agents, chats and follow-ups on both
    # channels to join) costs a small constant — the batch lookups, never one per row.
    assert stats["q10"] <= 12 and stats["q100"] <= 12, stats
    assert stats["q_follow"] <= 12, stats
    for i in range(100):
        c = logged[f"wacid.b.{i}"]
        assert c.status == ("completed" if i % 3 == 0 else "missed"), (i, c.status)
