"""The web storefront channel (POST /web/chat) — the agent as the website widget.

Covers the two seams that make web different from WhatsApp/Meta:
  1. runtime.run_turn(channel="web") — client-supplied transcript, the web tool
     set (no cart/order tools), and structured output collected on `web_sink`.
  2. the router shaping — auth, currency gate, product cards with hub slugs, the
     wa.me handoff link, and quick replies.
All with fakes: no DB, no network, no model. Requires Python 3.11.
"""
import asyncio
import types

import app.agent.runtime as runtime
from app.agent.llm import FakeLLM
from app.agent.tools import ToolContext, _recommend_products, _handoff_to_human


# ── run_turn on the web channel ───────────────────────────────────────────────

class _Res:
    def __init__(self, one=None, many=None):
        self._one, self._many = one, many or []

    def scalar_one_or_none(self):
        return self._one

    def scalars(self):
        return types.SimpleNamespace(all=lambda: self._many,
                                     first=lambda: (self._many[0] if self._many else None))


class _FakeDB:
    def __init__(self, results):
        self._results, self._i = list(results), 0

    async def execute(self, *a, **k):
        r = self._results[self._i] if self._i < len(self._results) else _Res()
        self._i += 1
        return r

    async def get(self, *a, **k):
        return None


def test_web_turn_collects_products_and_uses_client_history(monkeypatch):
    """A web turn recommends a product; run_turn threads the tool result and the
    reply, and the recommendation lands on web_sink (slug + reason + quick reply)."""
    async def fake_run_tool(name, args, ctx):
        if name == "search_catalog":
            return {"count": 1, "currency": "KES",
                    "results": [{"name": "White Cassock", "sku": "CAS-1", "price": 12000,
                                 "currency": "KES"}]}
        if name == "recommend_products":
            # exercise the real handler so slug resolution is covered
            return await _recommend_products(args, ctx)
        return {"ok": True}

    monkeypatch.setattr(runtime, "run_tool", fake_run_tool)
    # recommend_products resolves names→hub products against the cached catalogue
    async def fake_catalog(db, redis):
        return [{"hub_product_id": 7, "name": "White Cassock", "sku": "CAS-1",
                 "slug": "white-cassock"}]
    from app.services import n8n_bridge as svc
    monkeypatch.setattr(svc, "catalog_items", fake_catalog)

    llm = FakeLLM([
        {"tools": [{"name": "search_catalog", "input": {"query": "cassock"}}]},
        {"tools": [{"name": "recommend_products", "input": {
            "products": [{"product": "White Cassock", "reason": "a classic choice",
                          "action": "view_product"}],
            "quick_replies": ["Show colours", "How much?"]}}]},
        {"text": "Our White Cassock is a lovely choice — would you like to see the colours?"},
    ])

    sink = {}
    db = _FakeDB([])            # web path makes no User/history DB reads
    reply = asyncio.run(runtime.run_turn(
        db, None, wa_id="", user_text="do you have cassocks?", llm=llm,
        channel="web", external_id="sess-abc",
        history=[{"role": "user", "content": "hi"},
                 {"role": "assistant", "content": "Hello! How can I help?"}],
        page_context={"path": "/", "category": "clergy"},
        currency="KES", web_sink=sink,
    ))

    assert "White Cassock" in reply
    assert sink["products"] == [{"slug": "white-cassock", "name": "White Cassock",
                                 "reason": "a classic choice", "action": "view_product"}]
    assert sink["quick_replies"] == ["Show colours", "How much?"]


def test_web_uses_web_tool_set_no_cart_or_order():
    """The web channel must expose recommend_products but NOT the transacting
    tools — cart + payment live on the storefront."""
    names = {t["name"] for t in runtime.WEB_TOOLS}
    assert "recommend_products" in names
    assert "search_catalog" in names and "handoff_to_human" in names
    assert not ({"update_cart", "create_order", "whatsapp_checkout_link"} & names)


# ── the structured tools in isolation ─────────────────────────────────────────

def test_recommend_products_drops_uninvented_and_keeps_hub_slug(monkeypatch):
    async def fake_catalog(db, redis):
        return [{"hub_product_id": 1, "name": "Purple Cope", "sku": "COPE-P", "slug": "purple-cope"}]
    from app.services import n8n_bridge as svc
    monkeypatch.setattr(svc, "catalog_items", fake_catalog)

    ctx = ToolContext(db=None, redis=None, wa_id="sess", channel="web", sink={})
    out = asyncio.run(_recommend_products({
        "products": [
            {"product": "Purple Cope", "reason": "matches your set", "action": "add_to_cart"},
            {"product": "Invented Item", "reason": "nope"},         # not in catalogue → dropped
        ],
        "quick_replies": ["Add to cart", "See more"],
    }, ctx))

    assert out["shown"] == ["purple-cope"] and out["dropped"] == ["Invented Item"]
    assert ctx.sink["products"] == [{"slug": "purple-cope", "name": "Purple Cope",
                                     "reason": "matches your set", "action": "add_to_cart"}]


def test_recommend_products_noop_off_web_channel():
    ctx = ToolContext(db=None, redis=None, wa_id="2547", channel="whatsapp", sink=None)
    out = asyncio.run(_recommend_products({"products": [{"product": "x"}]}, ctx))
    assert out["ok"] is False


def test_handoff_records_on_sink_for_web():
    """On web, handoff_to_human stamps the sink even when no conversation row
    exists yet (the endpoint turns it into a wa.me link)."""
    class _DB:
        async def execute(self, *a, **k):
            return _Res(one=None, many=[])
    ctx = ToolContext(db=_DB(), redis=None, wa_id="sess", channel="web", sink={})
    out = asyncio.run(_handoff_to_human({"reason": "wants a refund"}, ctx))
    assert ctx.sink["handoff"] == {"reason": "wants a refund"}
    assert out["ok"] is True


# ── router helpers (pure) ─────────────────────────────────────────────────────

def test_web_currency_gate():
    from app.routers.web_chat import _web_currency
    assert _web_currency("en-KE", None) == "KES"
    assert _web_currency("en-US", None) == "USD"
    assert _web_currency(None, "254712345678") == "KES"     # Kenyan phone → KES
    assert _web_currency("en-US", "254712345678") == "KES"  # phone prefix wins
    assert _web_currency(None, None) == "USD"


def test_handoff_url_and_action_labels(monkeypatch):
    from app.core.config import settings
    from app.routers.web_chat import _wa_handoff_url, _action_label, _qr_id
    monkeypatch.setattr(settings, "whatsapp_handoff_number", "254700111222", raising=False)
    url = _wa_handoff_url({"product_slug": "purple-cope"})
    assert url.startswith("https://wa.me/254700111222?text=")
    assert _action_label("add_to_cart", "Cope") == "Add Cope to cart"
    assert _action_label("view_product", "Cope") == "View Cope"
    assert _action_label("request_quote", "Cope") == "Request a quote — Cope"
    assert _qr_id("How much?", 0) == "how-much"
    assert _qr_id("", 2) == "qr-3"


def test_verify_storefront_key(monkeypatch):
    from fastapi import HTTPException
    from app.core.config import settings
    from app.routers.web_chat import verify_storefront_key

    # unset → 503 (channel off)
    monkeypatch.setattr(settings, "storefront_key", "", raising=False)
    try:
        asyncio.run(verify_storefront_key("anything"))
        assert False, "expected 503"
    except HTTPException as e:
        assert e.status_code == 503

    # set → wrong/missing key 401, correct key passes
    monkeypatch.setattr(settings, "storefront_key", "s3cret", raising=False)
    for bad in (None, "", "nope"):
        try:
            asyncio.run(verify_storefront_key(bad))
            assert False, "expected 401"
        except HTTPException as e:
            assert e.status_code == 401
    asyncio.run(verify_storefront_key("s3cret"))     # no raise


def test_sanitize_history_alternates_and_starts_on_user():
    h = [{"role": "assistant", "content": "leading bot turn — dropped"},
         {"role": "user", "content": "hi"},
         {"role": "user", "content": "still me"},
         {"role": "assistant", "content": "hello"},
         {"role": "system", "content": ""}]           # empty/other → skipped
    out = runtime._sanitize_history(h)
    assert out == [{"role": "user", "content": "hi\nstill me"},
                   {"role": "assistant", "content": "hello"}]
