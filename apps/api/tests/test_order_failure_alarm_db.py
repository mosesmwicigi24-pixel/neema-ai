"""AN ORDER THAT FAILS IS NEVER SILENT (2026-10-05).

From 2026-08-24 to 2026-10-05 the hub refused every order Neema placed (403 on
POST /api/v1/admin/pos/pending-order): 151 attempts across 76+ conversations.
The failure was only a tool result the model read — customers heard "a
colleague is placing the order for you right now", no one was told, nothing
was flagged. Pinned here, on a real Postgres, through the REAL
push_pending_order against a mocked hub: a refused or timed-out order moves the
thread to HUMAN (the Human tab finds it), rings the team ONCE with the cart in
the body, leaves a flag with the full cart and the error so a colleague can
place it by hand, keeps the cart, and tells the model in plain words that
nothing was placed. A retry of the same cart is quiet. A placed order is
unchanged.
"""
import asyncio
import json
import types
import uuid

import httpx
import pytest
import sqlalchemy as sa

from tests.test_security_db import _reachable, _sync_url, fresh_db  # noqa: F401

pytestmark = pytest.mark.skipif(not _sync_url() or not _reachable(_sync_url()),
                                reason="needs a reachable Postgres (CI migrations job / Docker harness)")

WA = "254700000123"
TRAY = {"hub_product_id": 50, "sku": "XYULGK29K-5D98", "slug": "golden-communion-tray",
        "name": "Golden Communion Tray", "price": 22000, "price_usd": 198,
        "prices": {"KES": 22000, "USD": 198}, "aliases": [], "category": "Communion Items",
        "product_type": "simple", "is_producible": False, "in_stock": True, "variants": []}
CART = [{"hub_product_id": 50, "name": "Golden Communion Tray", "sku": "XYULGK29K-5D98",
         "qty": 2, "unit_price": 22000}]


class _Redis:
    def __init__(self):
        self.kv: dict = {}
        self.published: list = []

    async def get(self, k):
        return self.kv.get(k)

    async def set(self, k, v, nx=False, ex=None):
        if nx and k in self.kv:
            return None
        self.kv[k] = v
        return True

    async def publish(self, channel, payload):
        self.published.append((channel, json.loads(payload)))


@pytest.fixture
def rig(fresh_db, monkeypatch):  # noqa: F811
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool
    import app.main  # noqa: F401
    from app.agent import cart as cartmod
    from app.agent import tools
    from app.core import hub_client

    eng = sa.create_engine(fresh_db)
    with eng.begin() as c:
        c.execute(sa.text("TRUNCATE intercepts, order_events, conversations CASCADE"))
    eng.dispose()
    url = fresh_db.replace("postgresql+psycopg2://", "postgresql+asyncpg://")
    maker = async_sessionmaker(create_async_engine(url, poolclass=NullPool),
                               class_=AsyncSession, expire_on_commit=False)
    state = {"cleared": 0, "hub": None, "posts": 0}

    async def fake_cart(db_, wa_id, channel="whatsapp"):
        return {"items": [dict(i) for i in CART]}

    async def fake_clear(db_, wa_id, channel="whatsapp"):
        state["cleared"] += 1
        return {"items": []}

    async def fake_catalog(db_, redis_):
        return [TRAY]

    async def fake_identity(ctx):
        return WA, "Joy", None

    async def no_promise(*a, **k):
        return None

    async def fake_meas(*a, **k):
        return {}

    async def fake_ref(db_, row):
        return "AB12CD"

    def hub(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/customers/search"):
            return httpx.Response(200, json={"data": []})
        state["posts"] += 1
        return state["hub"](request)

    real_client = httpx.AsyncClient
    monkeypatch.setattr(hub_client.httpx, "AsyncClient",
                        lambda *a, **k: real_client(*a, transport=httpx.MockTransport(hub), **k))
    monkeypatch.setattr(cartmod, "get_cart", fake_cart)
    monkeypatch.setattr(cartmod, "clear_cart", fake_clear)
    monkeypatch.setattr(tools.svc, "catalog_items", fake_catalog)
    monkeypatch.setattr(tools, "_order_identity", fake_identity)
    monkeypatch.setattr(tools, "assign_short_ref", fake_ref)
    monkeypatch.setattr("app.services.promotions.granted_promise", no_promise)
    monkeypatch.setattr("app.agent.measurements.get_measurements", fake_meas)

    async def conv():
        from app.models.conversation import Conversation
        async with maker() as db:
            c = Conversation(id=uuid.uuid4(), wa_id=WA, channel="whatsapp", external_id=WA)
            db.add(c)
            await db.commit()
            return c.id
    return types.SimpleNamespace(maker=maker, tools=tools, conv_id=asyncio.run(conv()),
                                 redis=_Redis(), state=state)


def _order(rig, notes="Delivery to Nakuru"):
    async def go():
        async with rig.maker() as db:
            ctx = rig.tools.ToolContext(db=db, redis=rig.redis, wa_id=WA, currency="KES",
                                        channel="whatsapp")
            return await rig.tools.run_tool("create_order", {"notes": notes}, ctx)
    return asyncio.run(go())


def _db_state(rig):
    async def go():
        from app.models.conversation import Conversation
        from app.models.intercept import Intercept
        from app.routers.admin import _inbox_conditions
        async with rig.maker() as db:
            c = await db.get(Conversation, rig.conv_id)
            human_tab = (await db.execute(sa.select(Conversation.id).where(
                *_inbox_conditions(agent_id=None, tab="human")))).scalars().all()
            flags = (await db.execute(sa.select(Intercept).where(
                Intercept.conversation_id == rig.conv_id))).scalars().all()
            return c.intercept_mode.value, list(human_tab), flags
    return asyncio.run(go())


def _alerts(rig):
    return [p for ch, p in rig.redis.published
            if ch == "ws:channel:agents:all" and p.get("type") == "draft_ready"]


def _assert_not_placed(out):
    assert out["order_placed"] is False and "ORDER NOT PLACED" in out["error"]
    assert out["team_has_it"] is True
    assert "colleague" in out["rule"] and "never give or promise an order number" in out["rule"]
    assert "One of our team has your order details" in out["say_to_customer"]
    assert "order_number" not in out and "order_url" not in out


def test_a_hub_refusal_hands_the_order_and_its_cart_to_the_team(rig):
    rig.state["hub"] = lambda r: httpx.Response(403, json={"message": "This action is unauthorized."})
    out = _order(rig)
    _assert_not_placed(out)
    assert "403" in out["error"]
    mode, human_tab, flags = _db_state(rig)
    assert mode == "human" and rig.conv_id in human_tab
    assert len(flags) == 1 and flags[0].action.value == "flag"
    note = flags[0].note
    assert "ORDER NOT PLACED" in note and "hub 403 (This action is unauthorized.)" in note
    assert "Golden Communion Tray ×2 @ 22000" in note and "KES 44,000" in note
    assert WA in note and "Delivery to Nakuru" in note
    alerts = _alerts(rig)
    assert len(alerts) == 1
    a = alerts[0]
    assert a["conv_id"] == str(rig.conv_id) and a["wa_id"] == WA and len(a["body"]) <= 200
    assert "403" in a["body"] and "Golden Communion Tray ×2" in a["body"] and "KES 44,000" in a["body"]
    assert rig.state["cleared"] == 0                     # the cart stays for the colleague
    # the order path itself is now visibly failing
    from app.services import hub_health
    health = json.loads(rig.redis.kv[hub_health.STATE_KEY])
    assert health["status"] == "failing" and health["kind"] == "forbidden"


def test_a_hub_timeout_is_handled_the_same_and_warns_it_may_exist(rig):
    def slow(request):
        raise httpx.ReadTimeout("timed out", request=request)
    rig.state["hub"] = slow
    out = _order(rig)
    _assert_not_placed(out)
    assert "timeout" in out["error"]
    mode, _tab, flags = _db_state(rig)
    assert mode == "human" and len(flags) == 1
    assert "may have created it anyway" in flags[0].note
    assert len(_alerts(rig)) == 1


def test_a_retry_of_the_same_cart_does_not_ring_twice(rig):
    rig.state["hub"] = lambda r: httpx.Response(500, text="Server Error")
    first, again = _order(rig), _order(rig)
    _assert_not_placed(first)
    _assert_not_placed(again)
    assert rig.state["posts"] == 2
    mode, _tab, flags = _db_state(rig)
    assert mode == "human" and len(flags) == 1
    assert len(_alerts(rig)) == 1


def test_a_placed_order_is_unchanged(rig):
    rig.state["hub"] = lambda r: httpx.Response(200, json={
        "order_id": 9, "order_number": "WA-9", "total_amount": 44000, "currency_code": "KES",
        "public_url": "https://hub/order/tok9", "public_token": "tok9"})
    out = _order(rig)
    assert out["ok"] is True and out["order_number"] == "WA-9" and "error" not in out
    assert out["say_total_as"] == "KES 44,000"
    mode, _tab, flags = _db_state(rig)
    assert mode == "ai" and flags == []
    assert _alerts(rig) == []
    assert rig.state["cleared"] == 1
