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


def test_card_wamid_lands_on_the_mirror_row(monkeypatch):
    """The 'this one, but stainless steel' fix: the wamid Graph returns for a
    product card must reach _record_shared_media, so the mirror row carries
    waba_msg_id and a customer reply-quote of the card resolves back to it."""
    monkeypatch.setattr(settings, "media_public_url", "https://shop.example", raising=False)
    monkeypatch.setattr(tools, "_customer_currency", _acoro("KES"))
    monkeypatch.setattr(svc, "catalog_items", _acoro(CATALOG))
    monkeypatch.setattr(svc, "_send_waba_product_card", _acoro("wamid.CARD9"))
    recorded = []

    async def fake_record(ctx, *, media_url, caption, waba_msg_id=None):
        recorded.append({"media_url": media_url, "caption": caption, "waba_msg_id": waba_msg_id})

    monkeypatch.setattr(tools, "_record_shared_media", fake_record)
    ctx = ToolContext(db=object(), redis=None, wa_id="254712345678", channel="whatsapp", currency="KES")
    out = asyncio.run(tools._send_product_cards({"products": ["Ring"]}, ctx))

    assert out["sent_cards"] == 1
    assert recorded[0]["waba_msg_id"] == "wamid.CARD9"


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
        def json(self):
            return {"messages": [{"id": "wamid.CARD1"}]}

    class _Client:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, url, headers=None, json=None, timeout=None):
            sent.append(json)
            return _Resp()

    monkeypatch.setattr(svc.httpx, "AsyncClient", lambda *a, **k: _Client())
    wamid = asyncio.run(svc._send_waba_product_card(
        "254700", image_url="https://i/x.jpg", title="Cross",
        body="KES 4,000", url="https://s/catalog/cross?ccy=KES"))

    p = sent[0]
    assert p["type"] == "interactive"
    assert p["interactive"]["type"] == "cta_url"
    assert p["interactive"]["header"]["image"]["link"] == "https://i/x.jpg"
    assert p["interactive"]["action"]["parameters"]["url"].endswith("cross?ccy=KES")
    assert "*Cross*" in p["interactive"]["body"]["text"]
    # The card's wamid comes back — it's what a customer reply-quote of the
    # card carries as context.message_id, so the mirror row must keep it.
    assert wamid == "wamid.CARD1"


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
        def json(self):
            return {"messages": [{"id": "wamid.FALLBACK1"}]}

    class _Client:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, url, headers=None, json=None, timeout=None):
            calls.append(json)
            return _Resp(len(calls) > 1)   # cta_url rejected, image accepted

    monkeypatch.setattr(svc.httpx, "AsyncClient", lambda *a, **k: _Client())
    wamid = asyncio.run(svc._send_waba_product_card(
        "254700", image_url="https://i/x.jpg", title="Cross", body="KES 4,000", url="https://s/p"))

    assert calls[0]["type"] == "interactive"
    assert calls[1]["type"] == "image"
    assert calls[1]["image"]["caption"].startswith("*Cross*")
    assert "https://s/p" in calls[1]["image"]["caption"]
    assert wamid == "wamid.FALLBACK1"   # the wamid of whichever send SUCCEEDED


# ── Showing the product must survive a hub blip ───────────────────────────────


def test_hub_catalog_serves_last_good_copy_when_the_hub_is_down(monkeypatch):
    """A hub outage must not strip Neema of photos and links: the local table
    has no slug, and a slugless product can never become a card."""
    import json as _json
    from app.core import hub_client as hc

    good = [{"name": "Lay Reader Complete Set", "slug": "lay-reader-set",
             "thumbnail_url": "https://img/lr.jpg", "price": 12000}]

    class _Redis:
        store = {hc._LAST_GOOD_KEY: _json.dumps(good)}
        async def get(self, k): return self.store.get(k)
        async def setex(self, k, ttl, v): self.store[k] = v

    async def _boom(redis):
        raise RuntimeError("hub 503")
    monkeypatch.setattr(hc, "_load_hub_catalog", _boom)

    items = asyncio.run(hc.fetch_hub_catalog(_Redis()))
    assert items == good
    assert items[0]["slug"] and items[0]["thumbnail_url"]   # still cardable


def test_hub_catalog_raises_when_there_is_no_last_good_copy(monkeypatch):
    from app.core import hub_client as hc

    class _Redis:
        async def get(self, k): return None
        async def setex(self, k, ttl, v): ...

    async def _boom(redis):
        raise RuntimeError("hub 503")
    monkeypatch.setattr(hc, "_load_hub_catalog", _boom)

    try:
        asyncio.run(hc.fetch_hub_catalog(_Redis()))
    except RuntimeError:
        pass
    else:
        raise AssertionError("expected the hub failure to propagate")


def test_product_card_without_a_link_still_sends_the_photo(monkeypatch):
    """No storefront link is no reason to fall back to bare text — the photo
    is what builds confidence."""
    posts = []

    class _Resp:
        is_success = True
        status_code = 200
        content = b"{}"
        def json(self): return {"messages": [{"id": "wamid.X"}]}

    class _Client:
        def __init__(self, *a, **k): ...
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, url, **k):
            posts.append(k.get("json"))
            return _Resp()

    monkeypatch.setattr(svc.httpx, "AsyncClient", _Client)

    asyncio.run(svc._send_waba_product_card(
        "254700000000", image_url="https://img/lr.jpg",
        title="Lay Reader Complete Set", body="KES 12,000", url=None))

    assert len(posts) == 1                       # went straight to image+caption
    assert posts[0]["type"] == "image"
    assert posts[0]["image"]["link"] == "https://img/lr.jpg"
    assert "Lay Reader Complete Set" in posts[0]["image"]["caption"]
    assert "None" not in posts[0]["image"]["caption"]   # no stray null link


# ── the album rule (owner, 2026-08-18): a product with several hub photos ─────
# shares them as a BUNCH. History: chat only ever sent the primary photo — the
# galleries the owner uploaded (43 of 93 products carry more than one image,
# one carries 14) were never consumed; the "bunches" customers used to get were
# humans sending photos by hand before image requests stopped escalating
# (43e36dc, 2026-07-23). These pin the native album behaviour.

GALLERY_CATALOG = [
    {"name": "Aluminium 4 Stacked Communion Set", "sku": "AL-4S", "slug": "aluminium-4-stacked",
     "price": 9000, "price_usd": 70, "thumbnail_url": "https://img/al_thumb.jpg",
     "image_url": "https://img/al_1.jpg",
     "images": [{"url": "https://img/al_1.jpg", "thumb": "https://img/al_thumb.jpg"},
                {"url": "https://img/al_2.jpg"}, {"url": "https://img/al_3.jpg"},
                {"url": "https://img/al_4.jpg"}]},
    {"name": "Ring", "sku": "RING-1", "slug": "ring", "price": 1500, "price_usd": 15,
     "thumbnail_url": "https://img/ring.jpg",
     "images": [{"url": "https://img/ring.jpg"}, {"url": "https://img/ring_2.jpg"}]},
]


def _gallery_ctx(channel="whatsapp", wa_id="254712345678"):
    return ToolContext(db=object(), redis=None, wa_id=wa_id, channel=channel, currency="KES")


def _wire_whatsapp(monkeypatch):
    monkeypatch.setattr(settings, "media_public_url", "https://shop.example", raising=False)
    monkeypatch.setattr(tools, "_customer_currency", _acoro("KES"))
    monkeypatch.setattr(svc, "catalog_items", _acoro(GALLERY_CATALOG))
    monkeypatch.setattr(svc, "_send_waba_product_card", _acoro("wamid.CARD"))
    mirrored = []

    async def _rec(ctx, media_url, caption="", waba_msg_id=None):
        mirrored.append({"url": media_url, "caption": caption})
    monkeypatch.setattr(tools, "_record_shared_media", _rec)
    albums = []

    async def _img(wa_id, image_url, caption=""):
        albums.append(image_url)
        return f"wamid.IMG{len(albums)}"
    monkeypatch.setattr(svc, "_send_waba_image", _img)
    return albums, mirrored


def test_single_product_card_is_followed_by_its_gallery_as_an_album(monkeypatch):
    albums, mirrored = _wire_whatsapp(monkeypatch)
    out = asyncio.run(tools._send_product_cards(
        {"products": ["Aluminium 4 Stacked Communion Set"]}, _gallery_ctx()))
    assert out["sent_cards"] == 1
    assert out["album_photos"] == 3
    # gallery[0] is the primary the card already shows — never re-sent
    assert albums == ["https://img/al_2.jpg", "https://img/al_3.jpg", "https://img/al_4.jpg"]
    # every album photo is mirrored to the dashboard thread with its place
    caps = [m["caption"] for m in mirrored]
    assert any("photo 2/4" in c for c in caps) and any("photo 4/4" in c for c in caps)
    assert "gallery" in out["note"] and "album" in out["note"]


def test_multi_product_comparison_never_floods_with_galleries(monkeypatch):
    albums, _ = _wire_whatsapp(monkeypatch)
    out = asyncio.run(tools._send_product_cards(
        {"products": ["Aluminium 4 Stacked Communion Set", "Ring"]}, _gallery_ctx()))
    assert out["sent_cards"] == 2
    assert out.get("album_photos", 0) == 0
    assert albums == []


def test_a_single_photo_product_sends_just_its_card(monkeypatch):
    albums, _ = _wire_whatsapp(monkeypatch)
    monkeypatch.setattr(svc, "catalog_items", _acoro(CATALOG))   # no galleries at all
    out = asyncio.run(tools._send_product_cards({"products": ["Ring"]}, _gallery_ctx()))
    assert out["sent_cards"] == 1 and out.get("album_photos", 0) == 0
    assert albums == []


def test_messenger_carousel_is_followed_by_the_gallery_too(monkeypatch):
    monkeypatch.setattr(settings, "media_public_url", "https://shop.example", raising=False)
    monkeypatch.setattr(tools, "_customer_currency", _acoro("USD"))
    monkeypatch.setattr(svc, "catalog_items", _acoro(GALLERY_CATALOG))
    mirrored = []

    async def _rec(ctx, media_url, caption="", waba_msg_id=None):
        mirrored.append(media_url)
    monkeypatch.setattr(tools, "_record_shared_media", _rec)

    import app.services.meta_send as meta_send
    sent_media, carousels = [], []

    async def _carousel(rid, elements, page_id=None):
        carousels.append(elements)

    async def _media(rid, mtype, url, page_id=None):
        sent_media.append((mtype, url))

    async def _page(channel, rid):
        return "page1"
    monkeypatch.setattr(meta_send, "send_meta_carousel", _carousel)
    monkeypatch.setattr(meta_send, "send_meta_media", _media)
    monkeypatch.setattr(meta_send, "page_of_contact", _page)

    out = asyncio.run(tools._send_product_cards(
        {"products": ["Aluminium 4 Stacked Communion Set"]},
        _gallery_ctx(channel="messenger", wa_id="psid42")))
    assert out["sent_cards"] == 1 and out["album_photos"] == 3
    assert len(carousels) == 1
    assert [u for _, u in sent_media] == ["https://img/al_2.jpg", "https://img/al_3.jpg",
                                          "https://img/al_4.jpg"]


def test_a_broken_album_photo_never_blocks_the_rest(monkeypatch):
    albums, _ = _wire_whatsapp(monkeypatch)

    async def _img_flaky(wa_id, image_url, caption=""):
        if image_url.endswith("al_3.jpg"):
            raise RuntimeError("cdn hiccup")
        albums.append(image_url)
        return "wamid.IMG"
    monkeypatch.setattr(svc, "_send_waba_image", _img_flaky)
    out = asyncio.run(tools._send_product_cards(
        {"products": ["Aluminium 4 Stacked Communion Set"]}, _gallery_ctx()))
    assert out["sent_cards"] == 1
    assert out["album_photos"] == 2                     # the other two still landed
    assert albums == ["https://img/al_2.jpg", "https://img/al_4.jpg"]
