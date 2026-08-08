"""The post catalogue: comments look up, they never guess.

The reframe behind it: a page has a FINITE set of posts and the business knows
what it posted — so product identification is an INDEX, not a per-comment
inference. Each post is resolved once by a deterministic ladder (caption
slug/alias → image fingerprint against our own catalogue photos → team
override), remembered for 30 days, and swept daily so posts are identified
BEFORE the first comment lands.

The fingerprint threshold is not a guess: validated against the live hub
images, distinct tray products sit 21–36 bits apart while the same image
after Facebook's resize/recompression moves 0–8 bits.
"""
import asyncio
import io
import types

import app.main  # noqa: F401 — registers all SQLAlchemy models
from app.services import post_catalog as pc


_CATALOG = [
    {"name": "Aluminium Tray", "slug": "aluminium-tray", "hub_product_id": 71,
     "aliases": ["aluminum tray", "stackable tray"],
     "images": [{"url": "https://hub/img/alu.jpg"}]},
    {"name": "Silver Communion Tray", "slug": "silver-communion-tray", "hub_product_id": 51,
     "aliases": ["silver tray", "sinia"],
     "images": [{"url": "https://hub/img/silver.jpg"}]},
    {"name": "Communion Wafer Bread 500PCS", "slug": "communion-wafer-bread-500pcs",
     "hub_product_id": 40, "aliases": ["mkate wa ushirika"], "images": []},
]


# ── rungs 1+2: caption ground truth ──────────────────────────────────────────

def test_storefront_link_in_caption_is_exact():
    hit = pc.product_from_caption(
        "New arrivals! Order: https://bethanyhouse.co.ke/product/aluminium-tray?ref=X",
        _CATALOG)
    assert hit["slug"] == "aluminium-tray"


def test_alias_match_longest_wins():
    # "silver communion tray" contains "silver tray" too — the longer, more
    # specific name must win.
    hit = pc.product_from_caption("Our Silver Communion Tray, made to serve", _CATALOG)
    assert hit["slug"] == "silver-communion-tray"
    # Swahili alias from the hub's own alias lists.
    hit2 = pc.product_from_caption("Mkate wa ushirika sasa unapatikana", _CATALOG)
    assert hit2["slug"] == "communion-wafer-bread-500pcs"
    assert pc.product_from_caption("Blessed Sunday to all!", _CATALOG) is None
    assert pc.product_from_caption("", _CATALOG) is None


# ── rung 3: the image fingerprint ────────────────────────────────────────────

def _png(painter, size=(320, 320)):
    from PIL import Image
    img = Image.new("L", size)
    px = img.load()
    for x in range(size[0]):
        for y in range(size[1]):
            px[x, y] = painter(x, y)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


_GRADIENT = _png(lambda x, y: (x * 255) // 320)
_CHECKER = _png(lambda x, y: 255 if (x // 40 + y // 40) % 2 else 0)


def test_dhash_separates_and_survives_recompression():
    from PIL import Image
    g, c = pc.dhash_bytes(_GRADIENT), pc.dhash_bytes(_CHECKER)
    assert g is not None and c is not None
    assert pc.hamming(g, c) > pc.HASH_MATCH_MAX          # distinct images: far apart
    # The same image resized + re-encoded as JPEG stays within threshold.
    im = Image.open(io.BytesIO(_GRADIENT)).resize((720, 700))
    buf = io.BytesIO()
    im.convert("RGB").save(buf, "JPEG", quality=70)
    assert pc.hamming(g, pc.dhash_bytes(buf.getvalue())) <= pc.HASH_MATCH_MAX
    assert pc.dhash_bytes(b"not an image") is None


class _Redis:
    def __init__(self): self.kv = {}
    async def get(self, k): return self.kv.get(k)
    async def set(self, k, v, nx=None, ex=None):
        self.kv[k] = v
        return True


def test_image_match_finds_the_reposted_catalogue_photo(monkeypatch):
    bytes_by_url = {"https://hub/img/alu.jpg": _GRADIENT,
                    "https://hub/img/silver.jpg": _CHECKER,
                    "https://fb/thumb.jpg": _GRADIENT}   # the post IS the alu photo

    async def _fake_fetch(url):
        return bytes_by_url.get(url)
    monkeypatch.setattr(pc, "_fetch_bytes", _fake_fetch)

    r = _Redis()
    hit = asyncio.run(pc.product_from_image(r, "https://fb/thumb.jpg", _CATALOG))
    assert hit["slug"] == "aluminium-tray"
    assert any(k.startswith("imghash:") for k in r.kv)   # fingerprints cached
    # An image matching nothing → None, never a forced pick. Built to be
    # provably far from both catalogue fingerprints (synthetic images can
    # collide under dHash by accident, so the premise is constructed).
    g, c = pc.dhash_bytes(_GRADIENT), pc.dhash_bytes(_CHECKER)
    far = None
    for k in range(2, 10):
        cand = _png(lambda x, y, k=k: 255 if ((x * k + y) // 30) % 2 else 0)
        h = pc.dhash_bytes(cand)
        if min(pc.hamming(h, g), pc.hamming(h, c)) > pc.HASH_MATCH_MAX:
            far = cand
            break
    assert far is not None
    bytes_by_url["https://fb/other.jpg"] = far
    assert asyncio.run(pc.product_from_image(r, "https://fb/other.jpg", _CATALOG)) is None


def test_caption_outranks_the_image(monkeypatch):
    async def _boom(*a, **k):
        raise AssertionError("image rung must not run when the caption already answers")
    monkeypatch.setattr(pc, "product_from_image", _boom)
    hit = asyncio.run(pc.resolve_post(
        None, {"title": "Silver Communion Tray offer", "thumb": "https://x/t.jpg"},
        _CATALOG))
    assert hit["slug"] == "silver-communion-tray"


# ── the sweep: identified before the first comment ───────────────────────────

def test_sweep_resolves_and_counts(monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "meta_page_id", "page1")
    monkeypatch.setattr(settings, "meta_page_token", "tok")

    class _Resp:
        is_success = True
        def json(self):
            return {"data": [{"id": "postA"}, {"id": "postB"}, {"id": "postC"}]}

    class _Client:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, *a, **k): return _Resp()
    monkeypatch.setattr(pc.httpx, "AsyncClient", _Client)

    async def _ctx(pid, redis=None, channel="facebook"):
        return {"post_id": pid,
                "title": "Aluminium Tray restock" if pid == "postA" else ""}
    monkeypatch.setattr("app.routers.meta_webhook._post_context", _ctx)

    async def _catalog(db, redis): return _CATALOG
    monkeypatch.setattr("app.services.n8n_bridge.catalog_items", _catalog)

    remembered = {}
    async def _recall(redis, channel, pid):
        return {"name": "Known"} if pid == "postB" else {}
    async def _remember(redis, channel, pid, product):
        remembered[pid] = product.get("slug")
    monkeypatch.setattr("app.agent.runtime._recall_post_product", _recall)
    monkeypatch.setattr("app.agent.runtime._remember_post_product", _remember)

    async def _no_image(redis, thumb, catalog): return None
    monkeypatch.setattr(pc, "product_from_image", _no_image)

    r = _Redis()
    out = asyncio.run(pc.sweep_page_posts(None, r, limit=10))
    # postB already known (skipped); postA resolved by caption; postC unresolved.
    assert out == {"checked": 2, "resolved": 1, "unresolved": 1}
    assert remembered == {"postA": "aluminium-tray"}
    assert r.kv.get(pc.UNRESOLVED_KEY) == "1"


def test_sweep_is_inert_without_page_config(monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "meta_page_id", "")
    out = asyncio.run(pc.sweep_page_posts(None, None))
    assert out == {"checked": 0, "resolved": 0, "unresolved": 0}


# ── wiring: lookup everywhere, sweep on the heartbeat, override for the team ─

def test_runtime_uses_the_identity_everywhere():
    import inspect
    import app.agent.runtime as runtime
    assert "_post_identity" in inspect.getsource(runtime._resolve_post_product)
    assert "_post_identity" in inspect.getsource(runtime.run_turn)


def test_daily_sweep_rides_the_heartbeat():
    import inspect
    from app.services import actions
    assert "sweep_page_posts" in inspect.getsource(actions.actions_loop)


def test_team_override_sets_the_post_identity(monkeypatch):
    from app.routers import admin

    async def _catalog(db, redis): return _CATALOG
    monkeypatch.setattr("app.services.n8n_bridge.catalog_items", _catalog)
    stored = {}
    async def _remember(redis, channel, pid, product):
        stored[pid] = (channel, product.get("slug"))
    monkeypatch.setattr("app.agent.runtime._remember_post_product", _remember)

    req = types.SimpleNamespace(app=types.SimpleNamespace(
        state=types.SimpleNamespace(redis=None)))
    out = asyncio.run(admin.set_post_product(
        "post9", req, {"product": "aluminium-tray"}, None,
        types.SimpleNamespace(id="a1")))
    assert out["ok"] and out["slug"] == "aluminium-tray"
    assert stored["post9"] == ("facebook", "aluminium-tray")
