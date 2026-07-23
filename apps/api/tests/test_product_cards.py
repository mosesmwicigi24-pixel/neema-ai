"""WhatsApp product cards: catalogue matching, price formatting, the send_product_cards
tool (rich cards on WhatsApp, text-link fallback elsewhere), and the cta_url sender.

Repo fake style (no DB fixture). Requires Python 3.11 (SQLAlchemy models).
"""
import asyncio

import app.main  # noqa: F401 — registers all SQLAlchemy models
import app.agent.tools as tools
import app.services.n8n_bridge as svc
from app.agent.tools import ToolContext
from app.core.config import settings


CATALOG = [
    {"name": "Pectoral Cross — Gold Finish", "sku": "PC-GOLD", "slug": "pectoral-cross-gold",
     "price": 4000, "price_usd": 40, "thumbnail_url": "https://img/pc.jpg",
     "image_url": "https://img/pc_full.jpg"},
    {"name": "Ring", "sku": "RING-1", "slug": "ring", "price": 1500, "price_usd": 15,
     "thumbnail_url": "https://img/ring.jpg"},
    {"name": "No Slug Item", "sku": "NS-1", "slug": "", "price": 100},
]


def _acoro(value):
    async def f(*a, **k):
        return value
    return f


# ── matching + formatting ─────────────────────────────────────────────────────

def test_match_product():
    assert tools._match_product("ring", CATALOG)["slug"] == "ring"
    assert tools._match_product("Pectoral Cross — Gold Finish", CATALOG)["slug"] == "pectoral-cross-gold"
    assert tools._match_product("PC-GOLD", CATALOG)["slug"] == "pectoral-cross-gold"   # sku exact
    assert tools._match_product("No Slug Item", CATALOG) is None   # no slug → not linkable
    assert tools._match_product("", CATALOG) is None


def test_fmt_price():
    assert tools._fmt_price(4000, "KES") == "KES 4,000"
    assert tools._fmt_price(40, "USD") == "$40"
    assert tools._fmt_price(0.5, "USD") == "$0.50"
    assert tools._fmt_price(None, "KES") == ""


# ── send_product_cards tool ───────────────────────────────────────────────────

def test_send_product_cards_whatsapp_sends_rich_cards(monkeypatch):
    monkeypatch.setattr(settings, "media_public_url", "https://shop.example", raising=False)
    monkeypatch.setattr(tools, "_customer_currency", _acoro("KES"))
    monkeypatch.setattr(svc, "catalog_items", _acoro(CATALOG))
    sent = []

    async def fake_card(wa_id, *, image_url, title, body, url, button="View"):
        sent.append({"wa_id": wa_id, "image": image_url, "title": title, "body": body, "url": url})

    monkeypatch.setattr(svc, "_send_waba_product_card", fake_card)
    ctx = ToolContext(db=object(), redis=None, wa_id="254712345678", channel="whatsapp", currency="KES")
    out = asyncio.run(tools._send_product_cards(
        {"products": ["Pectoral Cross — Gold Finish", "Ring"]}, ctx))

    assert out["sent_cards"] == 2
    assert sent[0]["title"] == "Pectoral Cross — Gold Finish"
    assert sent[0]["body"] == "KES 4,000"
    assert sent[0]["image"] == "https://img/pc.jpg"      # thumbnail preferred
    assert sent[0]["url"] == "https://bethanyhouse.co.ke/product/pectoral-cross-gold"
    assert sent[1]["url"].endswith("/product/ring")


def test_send_meta_carousel_builds_generic_template(monkeypatch):
    from app.services import meta_send as ms
    calls = []

    async def fake_graph(path, body, what, page_id=None):
        calls.append(body)
        return {}

    monkeypatch.setattr(ms, "_graph_post", fake_graph)
    els = [{"title": "Cross", "subtitle": "KES 4,000", "image_url": "https://i/x.jpg",
            "buttons": [{"type": "web_url", "url": "https://s/p", "title": "View"}]}]
    asyncio.run(ms.send_meta_carousel("PSID", els, page_id="P1"))
    payload = calls[0]["message"]["attachment"]["payload"]
    assert payload["template_type"] == "generic"
    assert payload["elements"][0]["title"] == "Cross"


def test_send_product_cards_messenger_sends_native_carousel(monkeypatch):
    monkeypatch.setattr(settings, "media_public_url", "https://shop.example", raising=False)
    monkeypatch.setattr(tools, "_customer_currency", _acoro("USD"))

    async def fake_catalog(db, redis):
        return [{"name": "Ring", "sku": "R1", "slug": "ring",
                 "prices": {"KES": 1500, "USD": 15}, "price": 1500, "price_usd": 15,
                 "thumbnail_url": "https://i/r.jpg"}]

    monkeypatch.setattr(svc, "catalog_items", fake_catalog)
    sent = {}

    async def fake_carousel(recipient, elements, page_id=None):
        sent.update(recipient=recipient, elements=elements, page=page_id)

    async def fake_page(channel, ext):
        return "P1"

    monkeypatch.setattr("app.services.meta_send.send_meta_carousel", fake_carousel)
    monkeypatch.setattr("app.services.meta_send.page_of_contact", fake_page)

    ctx = ToolContext(db=object(), redis=None, wa_id="26414904614761138",
                      channel="messenger", currency="USD")
    out = asyncio.run(tools._send_product_cards({"products": ["Ring"]}, ctx))

    assert out["sent_cards"] == 1
    assert sent["recipient"] == "26414904614761138"
    el = sent["elements"][0]
    assert el["title"] == "Ring"
    assert el["image_url"] == "https://i/r.jpg"
    assert el["buttons"][0]["url"].endswith("/product/ring")
    assert el["subtitle"] == "$15"


def test_send_product_cards_non_whatsapp_returns_links(monkeypatch):
    """Web session keys / Meta PSIDs are not phones → no WhatsApp send; the tool
    hands back the product details so the model shares them as text links."""
    monkeypatch.setattr(settings, "media_public_url", "https://shop.example", raising=False)
    monkeypatch.setattr(tools, "_customer_currency", _acoro("USD"))
    monkeypatch.setattr(svc, "catalog_items", _acoro(CATALOG))
    calls = {"n": 0}

    async def fake_card(*a, **k):
        calls["n"] += 1

    monkeypatch.setattr(svc, "_send_waba_product_card", fake_card)
    ctx = ToolContext(db=object(), redis=None, wa_id="web_abc123def", channel="whatsapp", currency="USD")
    out = asyncio.run(tools._send_product_cards({"products": ["Ring"]}, ctx))

    assert out["sent_cards"] == 0
    assert calls["n"] == 0
    assert out["products"][0]["link"] == "https://bethanyhouse.co.ke/product/ring"
    assert out["products"][0]["price"] == "$15"


def test_send_product_cards_no_match_errors(monkeypatch):
    monkeypatch.setattr(settings, "media_public_url", "https://shop.example", raising=False)
    monkeypatch.setattr(tools, "_customer_currency", _acoro("KES"))
    monkeypatch.setattr(svc, "catalog_items", _acoro(CATALOG))
    ctx = ToolContext(db=object(), redis=None, wa_id="254712345678", channel="whatsapp", currency="KES")
    out = asyncio.run(tools._send_product_cards({"products": ["Nonexistent Widget"]}, ctx))
    assert "error" in out


# ── the cta_url sender ────────────────────────────────────────────────────────

def test_send_waba_product_card_builds_cta_url(monkeypatch):
    monkeypatch.setattr(settings, "waba_token", "T", raising=False)
    monkeypatch.setattr(settings, "waba_phone_number_id", "PNID", raising=False)
    sent = []

    class _Resp:
        is_success = True
        status_code = 200
        text = "{}"

    class _Client:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, url, headers=None, json=None, timeout=None):
            sent.append(json)
            return _Resp()

    monkeypatch.setattr(svc.httpx, "AsyncClient", lambda *a, **k: _Client())
    asyncio.run(svc._send_waba_product_card(
        "254700", image_url="https://i/x.jpg", title="Cross",
        body="KES 4,000", url="https://s/catalog/cross?ccy=KES"))

    p = sent[0]
    assert p["type"] == "interactive"
    assert p["interactive"]["type"] == "cta_url"
    assert p["interactive"]["header"]["image"]["link"] == "https://i/x.jpg"
    assert p["interactive"]["action"]["parameters"]["url"].endswith("cross?ccy=KES")
    assert "*Cross*" in p["interactive"]["body"]["text"]


def test_send_waba_product_card_falls_back_to_image_on_reject(monkeypatch):
    monkeypatch.setattr(settings, "waba_token", "T", raising=False)
    monkeypatch.setattr(settings, "waba_phone_number_id", "PNID", raising=False)
    calls = []

    class _Resp:
        def __init__(self, ok):
            self.is_success = ok
            self.status_code = 200 if ok else 400
            self.text = "err"
        def raise_for_status(self):
            pass

    class _Client:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, url, headers=None, json=None, timeout=None):
            calls.append(json)
            return _Resp(len(calls) > 1)   # cta_url rejected, image accepted

    monkeypatch.setattr(svc.httpx, "AsyncClient", lambda *a, **k: _Client())
    asyncio.run(svc._send_waba_product_card(
        "254700", image_url="https://i/x.jpg", title="Cross", body="KES 4,000", url="https://s/p"))

    assert calls[0]["type"] == "interactive"
    assert calls[1]["type"] == "image"
    assert calls[1]["image"]["caption"].startswith("*Cross*")
    assert "https://s/p" in calls[1]["image"]["caption"]
