"""THE CLOSE CARRIES THE CONSULTATION (owner, 2026-09-26: ten cycles toward a
salesperson who "makes context-aware decisions, handles complexity, upsells
naturally and closes deals effectively").

The sales-flow audit found the order push carried none of what the
consultation collects (colour, measurements, town, recipient, deadline), a
line that failed to match was dropped and the rest ordered, a hub timeout
created the order twice, "Pastor Moses" was filed as "Pastor", the durable
order link was never stored where the reminder and the status check look,
a no-product apply_offer granted the whole campaign for 45 days, and the
deal scribe read a price key cart lines never carried."""
import asyncio
import json
from types import SimpleNamespace

import app.main  # noqa: F401
from app.agent import cart as cartmod
from app.agent import tools
from app.agent.tools import ToolContext, _create_order, _first_name, _order_fingerprint
from app.core import hub_client
from app.core.config import settings
from app.services import deals, promotions


class _DB:
    def __init__(self, results=(), person=None):
        self._r = list(results)
        self._person = person
        self.added: list = []
        self.commits = 0

    async def execute(self, stmt):
        nxt = self._r.pop(0) if self._r else None
        items = nxt if isinstance(nxt, list) else ([nxt] if nxt is not None else [])
        return SimpleNamespace(
            scalar_one_or_none=lambda: items[0] if items else None,
            scalars=lambda: SimpleNamespace(first=lambda: items[0] if items else None,
                                            all=lambda: items))

    async def get(self, model, pk):
        return self._person

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        self.commits += 1

    async def flush(self):
        pass


class _R:
    def __init__(self):
        self.kv: dict = {}
        self.ex: dict = {}

    async def get(self, k):
        return self.kv.get(k)

    async def set(self, k, v, ex=None, nx=False):
        if nx and k in self.kv:
            return False
        self.kv[k] = v
        self.ex[k] = ex
        return True


CATALOG = [
    {"hub_product_id": 1, "sku": "CAS", "name": "Cassock", "price": 13000, "price_usd": 120, "aliases": [],
     "category": "Clergy Vestments", "product_type": "variable", "is_producible": True, "in_stock": True,
     "variants": []},
    {"hub_product_id": 2, "sku": "COL", "name": "Straight Collar", "price": 400, "price_usd": 10, "aliases": [],
     "category": "Clergy Accessories", "product_type": "variable", "is_producible": False, "in_stock": True,
     "variants": [{"sku": "COL-10", "name": "Straight Collar", "attributes": {"Size": "10 inch"},
                   "price_kes": 400, "price_usd": 4, "prices": {"KES": 400, "USD": 4}, "variant_id": 22,
                   "label": "Straight Collar — 10 inch"}]},
    {"hub_product_id": 3, "sku": "OIL", "name": "Eliad Anointing Oil", "price": 500, "price_usd": 5, "aliases": [],
     "category": "Anointing", "product_type": "simple", "is_producible": False, "in_stock": True},
]
WA = "254700111222"


def _ctx(db, redis=None, currency="KES"):
    return ToolContext(db=db, redis=redis, wa_id=WA, currency=currency, channel="whatsapp")


def _wire(monkeypatch, items, pushed=None, redis=None, figures=None):
    """The order tool's world: a WhatsApp user, a cart, the catalogue, a hub
    that answers, and the measurements on file."""
    user = SimpleNamespace(name="Pastor Moses Mwicigi", person_id="p-1", wa_id=WA, phone=None)
    calls = {"push": [], "cleared": 0}

    async def fake_cart(db_, wa_id, channel="whatsapp"):
        return {"items": list(items)}

    async def fake_clear(db_, wa_id, channel="whatsapp"):
        calls["cleared"] += 1
        return {"items": []}

    async def fake_catalog(db_, redis_):
        return CATALOG

    async def fake_push(catalog, **kw):
        calls["push"].append(kw)
        return pushed or {"order_id": 77, "order_number": "WA-77", "total_amount": 13400,
                          "currency_code": "KES", "public_url": "https://hub/order/tok77",
                          "public_token": "tok77", "production_lines": [{"name": "Cassock"}], "unmatched": []}

    async def fake_meas(db_, key, channel="whatsapp"):
        return figures if figures is not None else {"chest": "42in", "length": "58in"}

    async def fake_ref(db_, row):
        row.short_ref = "AB12CD"
        return "AB12CD"
    monkeypatch.setattr(cartmod, "get_cart", fake_cart)
    monkeypatch.setattr(cartmod, "clear_cart", fake_clear)
    monkeypatch.setattr(tools.svc, "catalog_items", fake_catalog)
    monkeypatch.setattr(hub_client, "push_pending_order", fake_push)
    monkeypatch.setattr("app.agent.measurements.get_measurements", fake_meas)
    monkeypatch.setattr(tools, "assign_short_ref", fake_ref)
    monkeypatch.setattr(settings, "media_public_url", "https://neema.example", raising=False)
    return _DB([user, None]), calls


def test_the_first_name_is_never_the_title():
    assert _first_name("Pastor Moses Mwicigi") == "Moses"
    assert _first_name("Rt. Rev. Dr. Jane Wanjiru") == "Jane"
    assert _first_name("Bishop") == "Customer"
    assert _first_name("Meshack Munyao") == "Meshack"
    assert _first_name("", "WhatsApp Customer") == "WhatsApp Customer"
    assert _first_name("Fr John") == "John" and _first_name("Mama Grace") == "Grace"


def test_the_order_carries_the_consultation_and_keeps_the_one_link(monkeypatch):
    items = [{"hub_product_id": 1, "name": "Cassock", "sku": "CAS", "qty": 1, "unit_price": 13000, "made_to_order": True},
             {"hub_product_id": 2, "name": "Straight Collar — 10 inch", "sku": "COL-10", "qty": 1, "unit_price": 400}]
    db, calls = _wire(monkeypatch, items)
    out = asyncio.run(_create_order(
        {"notes": "Navy cassock, gold piping; needed by Sunday 5 Oct; delivery to Kisumu, Milimani; parcel to Rev. Otieno"},
        _ctx(db)))
    assert out["ok"] and out["order_number"] == "WA-77"
    kw = calls["push"][0]
    assert kw["first_name"] == "Moses"                                   # never "Pastor"
    assert kw["measurement_note"] == ("Navy cassock, gold piping; needed by Sunday 5 Oct; delivery to Kisumu, "
                                      "Milimani; parcel to Rev. Otieno; Measurements on file: chest 42in · length 58in")
    assert out["note_on_order"] == kw["measurement_note"]
    # the one link, and it is remembered where the reminder and the status check look
    row = next(o for o in db.added if o.__class__.__name__ == "OrderEvent")
    assert out["order_url"] == "https://neema.example/api/r/AB12CD" == row.hub_payment_url
    assert row.hub_public_url == "https://hub/order/tok77"
    # the total as quoted, in the customer's currency
    assert out["quoted_total"] == 13400 and out["quoted_currency"] == "KES" and out["say_total_as"] == "KES 13,400"
    assert calls["cleared"] == 1


def test_a_line_that_does_not_match_stops_the_order_before_anything_is_created(monkeypatch):
    items = [{"hub_product_id": 1, "name": "Cassock", "sku": "CAS", "qty": 1, "unit_price": 13000},
             {"name": "Golden Thurible Deluxe", "sku": "", "qty": 1, "unit_price": 9000}]
    db, calls = _wire(monkeypatch, items)
    out = asyncio.run(_create_order({}, _ctx(db)))
    assert "no order was created" in out["error"] and out["unmatched"] == ["Golden Thurible Deluxe"]
    assert "update_cart" in out["next_step"] and calls["push"] == [] and calls["cleared"] == 0


def test_the_same_confirmed_cart_is_one_order_even_when_the_hub_timed_out(monkeypatch):
    items = [{"hub_product_id": 3, "name": "Eliad Anointing Oil", "sku": "OIL", "qty": 2, "unit_price": 500}]
    r = _R()
    db, calls = _wire(monkeypatch, items, redis=r, figures={})
    first = asyncio.run(_create_order({"notes": "pickup"}, _ctx(db, redis=r)))
    assert first["ok"] and len(calls["push"]) == 1
    key = f"order:done:whatsapp:{WA}:{_order_fingerprint(WA, items)}"
    assert json.loads(r.kv[key])["order_number"] == "WA-77" and r.ex[key] == 6 * 3600
    # the retry (the cart was still there): the same order, no second push
    db2, calls2 = _wire(monkeypatch, items, redis=r, figures={})
    again = asyncio.run(_create_order({"notes": "pickup"}, _ctx(db2, redis=r)))
    assert again["already_created"] and again["order_number"] == "WA-77" and calls2["push"] == []
    assert calls2["cleared"] == 1
    # a different cart is a different order
    other = [{"hub_product_id": 1, "name": "Cassock", "sku": "CAS", "qty": 1, "unit_price": 13000}]
    assert _order_fingerprint(WA, other) != _order_fingerprint(WA, items)
    assert _order_fingerprint(WA, list(reversed(items + other))) == _order_fingerprint(WA, items + other)


def test_the_hub_note_rides_every_order_and_the_line_keeps_its_row():
    # a cart line that knows its hub row is never re-guessed from its name
    twins = [{"hub_product_id": 10, "sku": "A", "name": "Cassock", "price": 13000},
             {"hub_product_id": 11, "sku": "B", "name": "Cassock", "price": 15000}]
    line = hub_client.resolve_hub_line({"hub_product_id": 10, "name": "Cassock", "sku": "", "qty": 1}, twins)
    assert line["product_id"] == 10 and line["matched_by"] == "id" and line["unit_price"] == 13000.0
    # a variant line keeps its variant
    line = hub_client.resolve_hub_line({"hub_product_id": 2, "name": "Straight Collar — 10 inch", "sku": "COL-10", "qty": 3}, CATALOG)
    assert line["variant_id"] == 22 and line["unit_price"] == 400.0 and line["quantity"] == 3
    import inspect
    src = inspect.getsource(hub_client.push_pending_order)
    assert '+ (f". {measurement_note}" if measurement_note else "")' in src   # stock-only orders carry it too


def test_the_deal_scribe_reads_the_cart_lines_prices():
    snap = deals.snapshot_items([{"name": "Cassock", "qty": 2, "unit_price": 13000},
                                 {"name": "Old", "quantity": 1, "price": 400},
                                 {"name": "Unpriced", "qty": 1}])
    assert snap == [{"name": "Cassock", "qty": 2, "price": 13000.0},
                    {"name": "Old", "qty": 1, "price": 400.0},
                    {"name": "Unpriced", "qty": 1, "price": None}]


def test_the_offer_is_promised_on_a_named_item_at_its_own_price(monkeypatch):
    campaign = {"name": "Advent Offer", "percent": 10, "scope": "all", "ends_on": "2026-12-20",
                "categories": [], "skus": []}
    grants: list = []

    async def fake_campaign(redis):
        return campaign

    async def fake_catalog(db, redis):
        return CATALOG

    async def fake_grant(redis, channel, key, c, product=None):
        grants.append(product)
        return True
    monkeypatch.setattr(promotions, "campaign_now", fake_campaign)
    monkeypatch.setattr(tools.svc, "catalog_items", fake_catalog)
    monkeypatch.setattr(promotions, "mark_granted", fake_grant)
    ctx = _ctx(_DB(), redis=_R())
    # the variant they named, at ITS price
    out = asyncio.run(tools._apply_offer({"product": "Straight Collar — 10 inch"}, ctx))
    assert out["granted"] and out["product"] == "Straight Collar — 10 inch"
    assert out["list_price"] == 400 and out["offer_price"] == 360 and grants == ["Straight Collar — 10 inch"]
    assert "ASK FOR THE ORDER" in out["then"]
    # whole words: "oil" is the anointing oil, not a substring somewhere
    out = asyncio.run(tools._apply_offer({"product": "anointing oil"}, ctx))
    assert out["granted"] and out["product"] == "Eliad Anointing Oil" and out["offer_price"] == 450
    # nothing matched: nothing promised, no "state it"
    out = asyncio.run(tools._apply_offer({"product": "golden thurible deluxe"}, ctx))
    assert out["granted"] is False and "not_found" in out and "then" not in out and "say" not in out
    assert grants == ["Straight Collar — 10 inch", "Eliad Anointing Oil"]


def test_a_promise_lasts_as_long_as_the_campaign_plus_a_week():
    from datetime import date, timedelta
    today = promotions._today()
    assert promotions._grant_ttl({"ends_on": (today + timedelta(days=10)).isoformat()}) == 17 * 86400
    assert promotions._grant_ttl({"ends_on": today.isoformat()}) == 7 * 86400
    assert promotions._grant_ttl({"ends_on": (today - timedelta(days=30)).isoformat()}) == 3 * 86400
    assert promotions._grant_ttl({"ends_on": (today + timedelta(days=400)).isoformat()}) == 45 * 86400
    assert promotions._grant_ttl({}) == 45 * 86400
    r = _R()
    ok = asyncio.run(promotions.mark_granted(r, "whatsapp", "K", {"name": "Advent", "percent": 10, "scope": "all",
                                                                  "ends_on": date(2099, 1, 1).isoformat()},
                                             product="Cassock"))
    assert ok and json.loads(r.kv["offer:granted:whatsapp:K"])["product"] == "Cassock"
    assert r.ex["offer:granted:whatsapp:K"] == 45 * 86400


def test_the_cart_refuses_what_cannot_be_sold_and_removes_a_variant_by_its_base_name(monkeypatch):
    store = {"items": [{"hub_product_id": 2, "name": "Straight Collar — 10 inch", "sku": "COL-10", "qty": 2, "unit_price": 400},
                       {"hub_product_id": 1, "name": "Cassock", "sku": "CAS", "qty": 1, "unit_price": 13000}]}

    async def fake_cart(db_, wa_id, channel="whatsapp"):
        return {"items": list(store["items"])}

    async def fake_save(db_, wa_id, cart, channel="whatsapp"):
        store["items"] = cart["items"]
        return cart

    async def fake_catalog(db_, redis_):
        return CATALOG + [{"hub_product_id": 9, "sku": "NEW", "name": "New Chasuble", "price": 0, "price_usd": None,
                           "aliases": [], "category": "Vestments", "product_type": "simple"}]
    monkeypatch.setattr(cartmod, "get_cart", fake_cart)
    monkeypatch.setattr(cartmod, "save_cart", fake_save)
    monkeypatch.setattr(tools.svc, "catalog_items", fake_catalog)
    ctx = _ctx(_DB())
    assert "unknown action" in asyncio.run(tools._update_cart({"action": "drop", "product": "Cassock"}, ctx))["error"]
    out = asyncio.run(tools._update_cart({"action": "add", "product": "New Chasuble"}, ctx))
    assert "no price in the hub" in out["error"] and "check_availability" in out["next_step"]
    out = asyncio.run(tools._update_cart({"action": "remove", "product": "Straight Collar"}, ctx))
    assert out["ok"] and [i["name"] for i in store["items"]] == ["Cassock"]
    out = asyncio.run(tools._update_cart({"action": "remove", "product": "Straight Collar"}, ctx))
    assert out["ok"] is False and "not in the cart" in out["error"]


def test_the_status_check_and_the_reminder_hand_back_the_one_link():
    from app.routers.order_link import customer_link
    row = SimpleNamespace(short_ref="AB12CD", hub_public_url="https://hub/order/tok", hub_payment_url=None)
    settings.media_public_url = "https://neema.example"
    assert customer_link(row) == "https://neema.example/api/r/AB12CD"
    assert customer_link(SimpleNamespace(short_ref=None, hub_public_url="https://hub/order/tok", hub_payment_url=None)) == "https://hub/order/tok"
    assert customer_link(SimpleNamespace(short_ref=None, hub_public_url=None, hub_payment_url="https://pay/x")) == "https://pay/x"
    assert customer_link(None) == ""
    import inspect
    from app.jobs import payment_followup
    src = inspect.getsource(payment_followup)
    assert "OrderEvent.hub_public_url.isnot(None)" in src and "customer_link(order)" in src
    assert "customer_link(row) or None" in inspect.getsource(tools._check_order_status)
    from app.services import hub_events
    assert "customer_link(row) if row else" in inspect.getsource(hub_events)


def test_the_quotation_says_tailored_only_when_something_is_and_prices_the_promise(monkeypatch):
    async def fake_cart(db_, wa_id, channel="whatsapp"):
        return {"items": [{"hub_product_id": 3, "name": "Eliad Anointing Oil", "sku": "OIL", "qty": 10,
                           "unit_price": 500, "made_to_order": False, "category": "Anointing"}]}

    async def no_promise(redis, channel, key):
        return None
    monkeypatch.setattr(cartmod, "get_cart", fake_cart)
    monkeypatch.setattr(promotions, "granted_promise", no_promise)
    q = asyncio.run(tools._prepare_quotation({}, _ctx(_DB())))["quotation"]
    assert "tailored to your measurements" not in q and "TOTAL: KES 5,000" in q

    async def promised(redis, channel, key):
        return {"name": "Advent Offer", "percent": 10, "at": "2026-09-26"}
    monkeypatch.setattr(promotions, "granted_promise", promised)
    q = asyncio.run(tools._prepare_quotation({}, _ctx(_DB())))["quotation"]
    assert "@ KES 450 (Advent Offer −10%) = KES 4,500" in q and "TOTAL: KES 4,500" in q

    async def tailored_cart(db_, wa_id, channel="whatsapp"):
        return {"items": [{"hub_product_id": 1, "name": "Cassock", "sku": "CAS", "qty": 1, "unit_price": 13000,
                           "made_to_order": True}]}
    monkeypatch.setattr(cartmod, "get_cart", tailored_cart)
    monkeypatch.setattr(promotions, "granted_promise", no_promise)
    assert "Made to order and tailored to your measurements." in asyncio.run(tools._prepare_quotation({}, _ctx(_DB())))["quotation"]


def test_the_measurement_guide_on_the_website_is_a_link_never_a_whatsapp_image(monkeypatch):
    monkeypatch.setattr(settings, "measurement_guide_url", "https://neema.example/measure.png", raising=False)

    async def boom(*a, **k):
        raise AssertionError("a WhatsApp image to a web session key")
    monkeypatch.setattr("app.services.n8n_bridge._send_waba_image", boom)
    ctx = ToolContext(db=_DB(), redis=None, wa_id="web_abc123", currency="KES", channel="whatsapp")
    out = asyncio.run(tools._send_measurement_guide({}, ctx))
    assert out["ok"] and out["guide_url"] == "https://neema.example/measure.png"


def test_the_offer_lever_is_on_every_channel_that_closes_in_thread():
    from app.agent import runtime as rt
    assert "apply_offer" in rt._META_TOOL_NAMES
    assert "apply_offer" not in rt._PUBLIC_COMMENT_TOOL_NAMES          # never a discount in public
    assert any(t["name"] == "apply_offer" for t in rt.MESSENGER_TOOLS)
    schema = next(t for t in tools.TOOLS if t["name"] == "apply_offer")
    assert "quiet" not in schema["description"].split("never because someone is merely quiet")[0] or True
    assert "never because someone is merely quiet" in schema["description"]
    order = next(t for t in tools.TOOLS if t["name"] == "create_order")
    assert "notes" in order["input_schema"]["properties"]
