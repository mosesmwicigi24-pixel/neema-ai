"""NEVER PRICE A GUESS (owner, 2026-09-21).

Three live misfires in one afternoon, each a canned "first contact" line filled
from a hub row nothing had confirmed:

  - a post captioned "We have restocked Tallits / Prayer shawls…" answered
    "How much" with "the Eliad Anointing Oil is $50";
  - a post captioned "Our client from South Africa gave us this design…"
    answered "Share more designs for ladies, interested." with "the BELL is $40";
  - a caption-less post of a purple cope answered "What is an apostolic ring"
    with "the Apostolic Ring is $40" — and stood to record the ring as the
    cope post's identity.

The holes, closed here: the resolver fed the caption's first eight words to
search_catalog, whose any-token fallback matched stop-words as substrings
("at" in "boat", "us" in "usher") and returned an arbitrary row; the canned
line sold whatever row it was handed; a model's guess (or the comment's own
product) could become the post's identity for thirty days.

Repo fake style (no DB fixture). Requires Python 3.11 (SQLAlchemy models).
"""
import asyncio
import inspect
import json

import app.main  # noqa: F401 — registers all SQLAlchemy models
from app.agent import runtime as rt
from app.agent import tools
from app.agent.prompt import build_system_prompt
from app.agent.tools import ToolContext, _search_catalog
from app.services import post_catalog as pc


def _row(pid, name, kes, usd, slug=None, image=None, aliases=()):
    return {"hub_product_id": pid, "name": name, "sku": f"S{pid}",
            "slug": slug or name.lower().replace(" ", "-").replace("(", "").replace(")", ""),
            "price": kes, "price_usd": usd, "category": "Church Items",
            "aliases": list(aliases), "product_type": "simple", "is_producible": False,
            "description": "", "images": ([{"url": image}] if image else [])}


# The live shelf, as it stood — every row the misfires named, and the ones
# that should have answered.
CATALOG = [
    _row(1, "Eliad Anointing Oil", 5000, 50, image="https://hub/img/oil.jpg"),
    _row(2, "BELL", 4000, 40),
    _row(3, "Large bell", 6000, 60),
    _row(4, "Apostolic Ring", 4000, 40),
    _row(5, "Ring", 3000, 30),
    _row(6, "Usher Belt", 1000, 10),
    _row(7, "Tallit (Prayer Shawl) - Medium", 6000, 60, slug="tallit-medium",
         image="https://hub/img/tallit-m.jpg"),
    _row(8, "Large Prayer Shawl / Tallit", 8000, 80, slug="tallit-large",
         image="https://hub/img/tallit-l.jpg"),
    _row(9, "Boat and spoon.", 1200, 12),
    _row(10, "Cope — Complete Set", 45000, 450, image="https://hub/img/cope.jpg"),
    _row(11, "Custom Designed Dress", 10000, 100),
    _row(12, "Silver Communion Tray", 18000, 180),
    _row(13, "Silver Communion Cups", 100, 1),
    _row(14, "Golden Communion Tray", 22000, 220),
]

TALLIT_CAPTION = ("We have restocked Tallits / Prayer shawls at Bethany House. Make your "
                  "order today by calling 0727 891989 or by calling ++254785490805....")
DESIGN_CAPTION = ("Our client from South Africa gave us this design. We are going to show "
                  "you the finished we irk, stay tuned")


class _Redis:
    def __init__(self):
        self.kv = {}

    async def get(self, k):
        return self.kv.get(k)

    async def set(self, k, v, nx=None, ex=None):
        self.kv[k] = v
        return True


def _ctx(monkeypatch, currency="USD"):
    async def fake_catalog(db, redis):
        return CATALOG
    monkeypatch.setattr(tools.svc, "catalog_items", fake_catalog)

    async def no_campaign(redis):
        return None
    from app.services import promotions
    monkeypatch.setattr(promotions, "campaign_now", no_campaign)
    return ToolContext(db=None, redis=None, wa_id="PSID1", currency=currency, channel="facebook")


# ── 1. search_catalog: words, not substrings; stop-words carry no product ────

def test_the_tallit_captions_lead_words_find_only_tallits(monkeypatch):
    out = asyncio.run(_search_catalog({"query": " ".join(TALLIT_CAPTION.split()[:8])},
                                      _ctx(monkeypatch)))
    names = [r["name"] for r in out["results"]]
    assert names and all("Tallit" in n for n in names), names
    assert "Eliad Anointing Oil" not in names and "Boat and spoon." not in names


def test_the_design_captions_lead_words_find_nothing(monkeypatch):
    out = asyncio.run(_search_catalog({"query": " ".join(DESIGN_CAPTION.split()[:8])},
                                      _ctx(monkeypatch)))
    assert out["results"] == [] and "no product words" in out.get("note", "")
    # "us" is not "Usher", "at" is not "Boat", "we" is not "jewel"
    out2 = asyncio.run(_search_catalog({"query": "we have it at our shop for us"}, _ctx(monkeypatch)))
    assert out2["results"] == []


def test_any_token_fallback_rows_are_marked_partial(monkeypatch):
    out = asyncio.run(_search_catalog({"query": "silver tray for communion cups"}, _ctx(monkeypatch)))
    # no row carries all four words → the fallback answers, and says it is partial
    assert out["results"] and all(r.get("match") == "partial" for r in out["results"])
    assert all("confirm" in r.get("caution", "") for r in out["results"])
    exact = asyncio.run(_search_catalog({"query": "silver communion tray"}, _ctx(monkeypatch)))
    assert exact["results"][0]["name"] == "Silver Communion Tray"
    assert "match" not in exact["results"][0]


def test_an_empty_query_still_browses_the_shelf(monkeypatch):
    out = asyncio.run(_search_catalog({"query": ""}, _ctx(monkeypatch)))
    assert out["count"] > 0 and "note" not in out


# ── 2. the caption scorer: sizes of one item are one identity ─────────────────

def test_a_tallit_caption_names_the_tallit_family_priced_from_the_cheapest():
    hit = rt._hub_caption_match(CATALOG, TALLIT_CAPTION)
    assert hit is not None
    assert hit["name"] == "Tallit (Prayer Shawl)"
    assert set(hit["family"]) == {"tallit-medium", "tallit-large"}
    assert hit["price_from"] is True and hit["price_usd"] == 60 and hit["slug"] == "tallit-medium"


def test_a_size_word_that_is_the_product_is_kept():
    # "Large bell" is not a size of "BELL" in the caption's eyes unless the
    # caption says bell; and "Small cross" never merges into a Pectoral Cross.
    hit = rt._hub_caption_match(CATALOG, "Our brass BELL is back in stock")
    assert hit is not None and hit["name"] in ("BELL", "Large bell")
    assert rt._hub_caption_match(CATALOG, DESIGN_CAPTION) is None
    assert rt._size_family([CATALOG[11], CATALOG[13]], {"communion", "tray"}) is None   # silver ≠ golden


# ── 3. the resolver: identity or nothing ─────────────────────────────────────

def _resolver_env(monkeypatch, redis):
    async def fake_catalog(db, redis_):
        return CATALOG
    monkeypatch.setattr("app.services.n8n_bridge.catalog_items", fake_catalog)

    class _DB:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
    monkeypatch.setattr("app.database.AsyncSessionLocal", lambda: _DB())

    async def no_vision(redis_, thumb, catalog, caption=""):
        return None
    monkeypatch.setattr(pc, "product_from_vision", no_vision)

    async def no_image(redis_, thumb, catalog):
        return None
    monkeypatch.setattr(pc, "product_from_image", no_image)

    async def no_describe(thumb):
        return ""
    monkeypatch.setattr(rt, "_describe_post_image", no_describe)

    queries = []

    async def fake_run_tool(name, args, ctx):
        queries.append(args["query"])
        for p in CATALOG:
            if p["name"].lower() == args["query"].lower() or p["slug"] == args["query"]:
                ctx.seen_products.append(dict(p))
        return {}
    monkeypatch.setattr(rt, "run_tool", fake_run_tool)
    return queries


def test_the_design_post_resolves_to_no_product_at_all(monkeypatch):
    r = _Redis()
    queries = _resolver_env(monkeypatch, r)
    sink: list = []
    asyncio.run(rt._resolve_post_product(r, "facebook", "PSID1",
                                         {"post_id": "P-design", "title": DESIGN_CAPTION}, sink))
    assert queries == [] and sink == []                 # no lead-words search, ever
    assert r.kv.get(rt._post_product_key("facebook", "P-design")) is None


def test_the_tallit_post_resolves_to_the_family_from_its_caption(monkeypatch):
    r = _Redis()
    queries = _resolver_env(monkeypatch, r)
    sink: list = []
    asyncio.run(rt._resolve_post_product(r, "facebook", "PSID1",
                                         {"post_id": "P-tallit", "title": TALLIT_CAPTION}, sink))
    assert queries and queries[0] == "Tallit (Prayer Shawl)"          # the family, by name
    rec = json.loads(r.kv[rt._post_product_key("facebook", "P-tallit")])
    assert rec["name"] == "Tallit (Prayer Shawl)" and rec["source"] == "caption"
    assert rec["confidence"] >= 0.9 and rec["price_from"] is True
    assert pc.identity_trusted(rec)
    assert sink and sink[0]["name"] == "Tallit (Prayer Shawl)" and sink[0]["price_from"] is True
    assert sink[0]["price_usd"] == 60


# ── 4. the identity record: provenance, trust, no downgrade ──────────────────

def test_trust_is_source_and_confidence():
    for src, ok in (("team", True), ("link", True), ("caption", True), ("image", True),
                    ("vision", True), ("vision-name", False), ("model", False), ("legacy", False)):
        rec = {"name": "X", "source": src, "confidence": pc.SOURCE_CONFIDENCE[src]}
        assert pc.identity_trusted(rec) is ok, src
    assert pc.identity_trusted({"name": "X"}) is False          # a record from before provenance
    assert pc.identity_trusted({}) is False


def test_a_model_read_never_downgrades_a_caption_identity(monkeypatch):
    async def no_describe(thumb):
        return ""
    monkeypatch.setattr(rt, "_describe_post_image", no_describe)
    r = _Redis()
    asyncio.run(rt._remember_post_product(r, "facebook", "P1",
                                          pc.with_provenance(CATALOG[11], "caption")))
    asyncio.run(rt._remember_post_product(r, "facebook", "P1", dict(CATALOG[11])))   # unstamped = model
    rec = json.loads(r.kv[rt._post_product_key("facebook", "P1")])
    assert rec["source"] == "caption" and rec["confidence"] == 0.95
    # and a bare model read records as "model", untrusted
    asyncio.run(rt._remember_post_product(r, "facebook", "P2", dict(CATALOG[3])))
    rec2 = json.loads(r.kv[rt._post_product_key("facebook", "P2")])
    assert rec2["source"] == "model" and not pc.identity_trusted(rec2)


def test_the_comments_own_product_is_never_the_posts_identity():
    ring = CATALOG[3]
    # the cope post has no caption; the commenter asked what a ring is
    assert rt._post_identity_compatible({}, "", ring, comment_text="What is an apostolic ring",
                                        saw_image=True) is False
    # a caption-less post records what the model SAW, never a text-only guess
    assert rt._post_identity_compatible({}, "", CATALOG[9], comment_text="how much", saw_image=True) is True
    assert rt._post_identity_compatible({}, "", CATALOG[9], comment_text="how much", saw_image=False) is False
    # the design caption supports neither a bell nor a dress
    assert rt._post_identity_compatible({}, DESIGN_CAPTION, CATALOG[1],
                                        comment_text="Share more designs for ladies, interested.") is False
    assert rt._post_identity_compatible({}, DESIGN_CAPTION, CATALOG[10]) is False


# ── 5. the canned line: a trusted identity, or no price at all ───────────────

def test_an_unidentified_price_ask_asks_which_item():
    out = rt._comment_public_reply("", dm_sent=False, name_tag=" Pro", seed="s",
                                   product_known=False, ask_which=True)
    assert any(out == line.replace("{name}", " Pro") for line in rt._LIVE_WHICH_POOL)
    assert "$" not in out and "KES" not in out
    sw = rt._comment_public_reply("", dm_sent=False, name_tag=" Pro", seed="s",
                                  product_known=False, ask_which=True, swahili=True)
    assert any(sw == line.replace("{name}", " Pro") for line in rt._SW_LIVE_WHICH_POOL)


def test_the_engine_sells_only_on_a_trusted_identity_that_was_asked_for():
    src = inspect.getsource(rt._run_comment_engage)
    assert "_trusted = identity_trusted(_known_product)" in src
    assert "if thumb and not is_live and not _trusted else None" in src
    assert "free_ask = _trusted and is_bare_price_ask(prompt_text)" in src
    assert "asks_it = is_bare_price_ask(prompt_text) or _names_product(prompt_text, product_name)" in src
    assert "ask_which = is_bare_price_ask(prompt_text)" in src
    assert 'price_text = "from " + price_text' in src
    assert "comment_text=comment_text, saw_image=bool(media)" in src
    assert "ask_which=ask_which, set_items=set_items," in src


def test_names_product_reads_the_comment():
    assert rt._names_product("How much is the tallit?", "Tallit (Prayer Shawl) - Medium") is True
    assert rt._names_product("Share more designs for ladies, interested.", "BELL") is False
    assert rt._names_product("what is an apostolic ring", "Apostolic Ring") is True


# ── 6. the vision rung: see the photo, compare it to the catalogue photo ─────

class _Resp:
    def __init__(self, text):
        self.text = text


class _LLM:
    def __init__(self, answers):
        self.answers = list(answers)
        self.calls = []

    async def complete(self, *, system, messages, tools):
        self.calls.append(messages)
        return _Resp(self.answers.pop(0))


def _vision_env(monkeypatch, answers):
    llm = _LLM(answers)
    monkeypatch.setattr("app.agent.runtime.build_llm", lambda model=None: llm)
    monkeypatch.setattr("app.agent.media.load_image_block",
                        lambda url: {"type": "image", "source": {"type": "url", "url": url}})
    return llm


def test_vision_pick_confirmed_against_the_catalogue_photo_is_trusted(monkeypatch):
    llm = _vision_env(monkeypatch, ["NAME=Tallit (Prayer Shawl) - Medium | CONF=high", "SAME"])
    r = _Redis()
    hit = asyncio.run(pc.product_from_vision(r, "https://fb/thumb.jpg", CATALOG, caption=TALLIT_CAPTION))
    assert hit is not None and hit["name"] == "Tallit (Prayer Shawl) - Medium"
    assert hit["_identity_source"] == "vision" and hit["_identity_confidence"] == 0.9
    assert pc.identity_trusted({"name": hit["name"], "source": hit["_identity_source"],
                               "confidence": hit["_identity_confidence"]})
    # the first read saw only tallits (the caption narrows the shelf) and the photo
    first = llm.calls[0][0]["content"]
    listing = next(b["text"] for b in first if b.get("type") == "text")
    assert "Tallit" in listing and "Anointing" not in listing and "BELL" not in listing
    assert len(llm.calls) == 2                                  # the compare ran


def test_vision_that_disagrees_with_the_catalogue_photo_is_not_an_identity(monkeypatch):
    _vision_env(monkeypatch, ["NAME=Eliad Anointing Oil | CONF=high", "DIFFERENT"])
    r = _Redis()
    assert asyncio.run(pc.product_from_vision(r, "https://fb/thumb2.jpg", CATALOG)) is None
    assert any(k.startswith("postcat:vision-none:") for k in r.kv)   # remembered for a day
    # NONE, an unlisted name, and a medium confidence all identify nothing
    for ans in (["NONE"], ["NAME=Purple Velvet Cope | CONF=high"], ["NAME=BELL | CONF=medium"]):
        _vision_env(monkeypatch, ans)
        assert asyncio.run(pc.product_from_vision(_Redis(), "https://fb/t3.jpg", CATALOG)) is None


def test_a_pick_without_a_catalogue_photo_steers_but_never_prices(monkeypatch):
    _vision_env(monkeypatch, ["NAME=BELL | CONF=high"])          # BELL has no image to compare
    hit = asyncio.run(pc.product_from_vision(_Redis(), "https://fb/t4.jpg", CATALOG))
    assert hit is not None and hit["_identity_source"] == "vision-name"
    assert not pc.identity_trusted({"name": "BELL", "source": "vision-name", "confidence": 0.7})


def test_the_ladder_stamps_every_rung(monkeypatch):
    async def no_image(redis_, thumb, catalog):
        return None
    monkeypatch.setattr(pc, "product_from_image", no_image)
    hit = asyncio.run(pc.resolve_post(None, {"title": "Our Silver Communion Tray, back in stock"}, CATALOG))
    assert hit["_identity_source"] == "caption"
    link = asyncio.run(pc.resolve_post(
        None, {"title": "Order here https://bethanyhouse.co.ke/product/tallit-medium"}, CATALOG))
    assert link["_identity_source"] == "link" and link["_identity_confidence"] == 1.0


# ── 7. the model is told the difference between a record and a lead ──────────

def test_run_turn_trusts_only_a_trusted_record():
    src = inspect.getsource(rt.run_turn)
    assert "if _trusted_id(_known):" in src
    assert "a lead, not a record" in src


def test_the_rules_say_never_price_a_guess():
    for currency in ("USD", "KES"):
        p = build_system_prompt(country_iso="KE" if currency == "KES" else "", currency=currency)
        assert "NEVER PRICE A GUESS (owner rule, 2026-09-21)" in p
        assert 'match: "partial"' in p
        assert "What is an apostolic ring?" in p
    add = rt._public_comment_addendum("USD")
    assert "NEVER PRICE A GUESS (owner, 2026-09-21" in add
    assert "quote NOTHING" in add


def test_the_team_override_is_the_strongest_rung(monkeypatch):
    import types
    from app.routers import admin

    async def _catalog(db, redis):
        return CATALOG
    monkeypatch.setattr("app.services.n8n_bridge.catalog_items", _catalog)
    stored = {}

    async def _remember(redis, channel, pid, product, thumb=""):
        stored[pid] = (product.get("slug"), product.get("_identity_source"), product.get("_identity_confidence"))
    monkeypatch.setattr("app.agent.runtime._remember_post_product", _remember)
    req = types.SimpleNamespace(app=types.SimpleNamespace(state=types.SimpleNamespace(redis=None)))
    out = asyncio.run(admin.set_post_product("post9", req, {"product": "tallit-medium"}, None,
                                             types.SimpleNamespace(id="a1")))
    assert out["ok"] and stored["post9"] == ("tallit-medium", "team", 1.0)
