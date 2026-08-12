"""Reels and videos identify their product like any post (owner, 2026-08-11):
read the caption from the VIDEO node, see the poster frame, score the caption
against the hub's own names and aliases — and bust the price cache the moment
the hub edits a product."""
import asyncio
from types import SimpleNamespace

import app.main  # noqa: F401
from app.agent import runtime as rt
from app.core.config import settings
from app.services import meta_send as ms


CATALOG = [
    {"name": "Refiller", "aliases": ["communion cup filler", "wine filler bottle"],
     "price": 1500, "price_usd": 20},
    {"name": "Aluminium Tray", "aliases": ["aluminum communion tray"],
     "price": 7000, "price_usd": 70},
    {"name": "Silver Communion Tray", "aliases": ["communion cup tray"],
     "price": 18000, "price_usd": 180},
    {"name": "Golden Communion Tray", "aliases": ["communion cup tray"],
     "price": 22000, "price_usd": 220},
]


# ── the caption scorer: the hub's names ARE the intelligence ─────────────────

def test_full_name_in_caption_wins():
    hit = rt._hub_caption_match(CATALOG, "Meet the Refiller — no more spills on the linen!")
    assert hit and hit["name"] == "Refiller"


def test_us_spelling_and_plural_still_hit():
    hit = rt._hub_caption_match(
        CATALOG, "We have Aluminum trays in stocks. Each holds 40 cups")
    assert hit and hit["name"] == "Aluminium Tray"


def test_a_whole_alias_phrase_names_the_product():
    hit = rt._hub_caption_match(CATALOG, "This little communion cup filler saves your linen")
    assert hit and hit["name"] == "Refiller"


def test_shared_alias_between_siblings_refuses_to_guess():
    """'communion cup tray' sits on BOTH the Silver and Golden trays — a caption
    carrying only that phrase must not silently pick one (least of all the
    dearer). The model, which can SEE the frame, decides."""
    assert rt._hub_caption_match(CATALOG, "Our communion cup tray is back!") is None


def test_junk_captions_match_nothing():
    assert rt._hub_caption_match(CATALOG, "Blessed Sunday to all our friends! 🙏") is None
    assert rt._hub_caption_match(CATALOG, "") is None


# ── reels read their caption + poster from the video node ────────────────────

def test_facebook_post_read_falls_back_to_the_video_node(monkeypatch):
    monkeypatch.setattr(settings, "meta_page_token", "T", raising=False)
    calls = []

    class _PostResp:
        is_success = False
        status_code = 400
        def json(self): return {}

    class _VideoResp:
        is_success = True
        status_code = 200
        def json(self):
            return {"description": "The Communion Full Set — everything your church needs",
                    "picture": "https://cdn/poster.jpg",
                    "permalink_url": "/reel/123/"}

    class _Client:
        def __init__(self, *a, **k): ...
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, url, params=None, headers=None, timeout=None):
            calls.append(params["fields"])
            return _PostResp() if "attachments" in params["fields"] else _VideoResp()

    monkeypatch.setattr(ms.httpx, "AsyncClient", _Client)
    ctx = asyncio.run(ms.fetch_post_context("123", channel="facebook"))
    assert len(calls) == 2                              # post shape, then video shape
    assert ctx["title"].startswith("The Communion Full Set")
    assert ctx["thumb"] == "https://cdn/poster.jpg"     # the frame vision will see
    assert ctx["has_video"] is True
    assert ctx["permalink"] == "https://www.facebook.com/reel/123/"


# ── the resolver narrows its search to the scored winner ─────────────────────

def test_resolver_searches_the_winner_by_exact_name(monkeypatch):
    async def no_identity(redis, channel, pctx): return {}
    monkeypatch.setattr(rt, "_post_identity", no_identity)

    async def fake_catalog(db, redis): return CATALOG
    monkeypatch.setattr("app.services.n8n_bridge.catalog_items", fake_catalog)

    class _DB:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
    monkeypatch.setattr("app.database.AsyncSessionLocal", lambda: _DB())

    seen = {}
    async def fake_run_tool(name, args, ctx):
        seen["query"] = args["query"]
        return {}
    monkeypatch.setattr(rt, "run_tool", fake_run_tool)

    asyncio.run(rt._resolve_post_product(
        None, "facebook", "PSID1",
        {"post_id": "P1", "title": "We have Aluminum trays in stocks. Each holds 40 cups "
                                   "and comes with 40 Plastic cups. The finishing is"},
        []))
    assert seen["query"] == "Aluminium Tray"            # not the caption's first 8 words


# ── a hub price edit reaches Neema NOW, not in 10 minutes ────────────────────

def test_catalog_updated_event_busts_the_price_cache():
    from app.services.hub_events import handle_event

    class _Redis:
        def __init__(self): self.deleted = []; self.sets = []
        async def delete(self, k): self.deleted.append(k)
        async def set(self, k, v, ex=None, nx=None): self.sets.append(k); return True

    r = _Redis()
    out = asyncio.run(handle_event(None, r, {"type": "catalog.updated", "id": "e1"}))
    assert out == {"handled": True, "action": "catalog_cache_busted"}
    assert "hub:catalog" in r.deleted
    # product.updated is accepted as the same signal.
    out2 = asyncio.run(handle_event(None, r, {"type": "product.updated", "id": "e2"}))
    assert out2["handled"] is True
