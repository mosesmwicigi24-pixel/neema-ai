"""A SET IS PRICED AS ITS TOTAL (owner, 2026-09-21).

"This explanation of the pricing for this cassock should include all the
items listed there — the shirt and the collar, the cassock, the signature belt
and the stole — so that you give the accurate figure from the hub. If the
description describes a product that has different combinations of items, we
should always do the total and give that. Because if we give just one item,
people will misunderstand it to mean that that is the total amount of the
entire set."

Live, a caption enumerating the five-piece outfit went down the ladder's
name-containment rung and came back as ONE piece — "Cassock" ($120), or the
CINCTURE BELT ($30) when its two-word name was the longest match — stamped
"caption" and trusted, so the canned line and the model both sold a piece as
the set. Closed here: an enumerating caption is a SET (the hub's own set row
that covers the list, else the listed rows totalled) or nothing; the canned
line says the set's one price and what it comes with; the model is told the
rule and the listed items.

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
from app.core.synonyms import canonical
from app.services import post_catalog as pc


def _row(pid, name, kes, usd, slug=None, desc="", mto=False, image=None):
    return {"hub_product_id": pid, "name": name, "sku": f"S{pid}",
            "slug": slug or name.lower().replace(" ", "-").replace("(", "").replace(")", ""),
            "price": kes, "price_usd": usd, "category": "Vestments", "aliases": [],
            "product_type": "variable" if mto else "simple", "is_producible": mto,
            "description": desc, "images": ([{"url": image}] if image else [])}


# The live shelf as it stood on 2026-09-21 (names, prices and the hub's own
# descriptions of its set rows).
CATALOG = [
    _row(1, "Cassock Set", 19500, 200, slug="cassock-set",
         desc="Complete cassock outfit in one order — cassock, stole, belt, straight "
              "collar shirt and a 12 inch clergy collar.",
         image="https://hub/img/cassock-set.jpg"),
    _row(2, "Classic Princes Cassock Set", 19000, 190, slug="clergy-cassock", mto=True,
         desc="Complete five-piece ladies' cassock set — cassock, shirt, collar, stole "
              "and cincture belt — ordination-ready in one order."),
    _row(3, "Cassock", 13000, 120, mto=True,
         desc="Our signature made-to-measure cassock — breathable premium fabrics."),
    _row(4, "White Cassock", 13000, 130, mto=True),
    _row(5, "Straight Collar Shirt", 2500, 30, mto=True),
    _row(6, "Round Collar Clergy Shirt", 3000, 30, slug="clergy-shirt", mto=True),
    _row(7, "Straight Collar", 400, 10),
    _row(8, "CINCTURE BELT", 2200, 30, slug="cincture-belt", mto=True),
    _row(9, "Usher Belt", 650, 10),
    _row(10, "Single Sided Stole", 2500, 30),
    _row(11, "Double sided stole", 4000, 40),
    _row(12, "Mitre", 5500, 60, mto=True),
    _row(13, "Cincture Rope", 2000, 20),
    _row(14, "Skull Cap", 1500, 20),
    _row(15, "Silver Communion Tray", 18000, 180,
         desc="Holds 40 cups; comes with lid, holder and basin."),
    _row(16, "Silver Communion Cups", 100, 1),
    _row(17, "Cope — Complete Set", 45000, 450, slug="cope-complete-set", mto=True,
         desc="A bishop's ceremonial cope supplied as a complete coordinated set — made "
              "to order in Nairobi for ordinations and solemn rites."),
    _row(18, "Aluminium 4-Stack Communion Set — 160 Cups", 28000, 280,
         slug="aluminium-double-stacked-communion-set",
         desc="Four stackable trays in one set, light and dignified carry."),
    _row(19, "Purple Red Cope", 15000, 150, mto=True),
    _row(20, "Ring", 1500, 20),
    _row(21, "Apostolic Ring", 3500, 40),
]

OWNER_CAPTION = ("Complete cassock set: cassock, shirt, collar, signature belt and stole. "
                 "Order yours today.")
CONGRATS_CAPTION = ("Congratulations Rev. Grace. Cassock, shirt, collar, belt and stole by "
                    "Bethany House.")
LISTING_CAPTION = "New stock: cassocks, stoles and shirts available"
BISHOP_CAPTION = "Full bishop's set: mitre, cincture rope and skull cap"


def _by(name):
    return next(r for r in CATALOG if r["name"] == name)


class _Redis:
    def __init__(self):
        self.kv = {}

    async def get(self, k):
        return self.kv.get(k)

    async def set(self, k, v, nx=None, ex=None):
        self.kv[k] = v
        return True

    async def delete(self, k):
        self.kv.pop(k, None)
        return 1


def _no_image_rungs(monkeypatch):
    async def none(*a, **k):
        return None
    monkeypatch.setattr(pc, "product_from_image", none)
    monkeypatch.setattr(pc, "product_from_vision", none)


def _resolve(monkeypatch, caption):
    _no_image_rungs(monkeypatch)
    return asyncio.run(pc.resolve_post(None, {"title": caption, "thumb": "https://fb/t.jpg"}, CATALOG))


# ── 1. what kind of thing each hub row is, and what a set comes with ─────────

def test_kinds_are_the_head_noun_and_a_set_is_a_set():
    assert pc.product_kind(_by("Straight Collar Shirt")) == "shirt"
    assert pc.product_kind(_by("Straight Collar")) == "collar"
    assert pc.product_kind(_by("CINCTURE BELT")) == "belt"
    assert pc.product_kind(_by("Round Collar Clergy Shirt")) == "shirt"
    assert pc.product_kind(_by("Single Sided Stole")) == "stole"
    assert pc.product_kind(_by("Silver Communion Cups")) == "cup"
    for name in ("Cassock Set", "Classic Princes Cassock Set", "Cope — Complete Set",
                 "Aluminium 4-Stack Communion Set — 160 Cups"):
        assert pc.is_set_row(_by(name)) and pc.product_kind(_by(name)) == "set", name
    assert not pc.is_set_row(_by("Cassock"))


def test_set_components_come_from_the_hubs_own_description():
    assert pc.set_components(_by("Cassock Set"), CATALOG) == \
        ["cassock", "stole", "belt", "straight collar shirt", "12 inch clergy collar"]
    assert pc.set_components(_by("Classic Princes Cassock Set"), CATALOG) == \
        ["cassock", "shirt", "collar", "stole", "cincture belt"]
    # a description that enumerates nothing lists nothing — never a flourish
    assert pc.set_components(_by("Cope — Complete Set"), CATALOG) == []
    assert pc.set_components(_by("Aluminium 4-Stack Communion Set — 160 Cups"), CATALOG) == []
    assert pc.set_components(_by("Cassock"), CATALOG) == []          # not a set


# ── 2. a caption that LISTS several items ────────────────────────────────────

def test_the_owner_caption_lists_five_items():
    assert pc.caption_item_kinds(OWNER_CAPTION, CATALOG) == ["cassock", "shirt", "collar", "belt", "stole"]
    assert pc.caption_item_kinds(CONGRATS_CAPTION, CATALOG) == ["cassock", "shirt", "collar", "belt", "stole"]
    assert pc.caption_item_kinds(LISTING_CAPTION, CATALOG) == ["cassock", "stole", "shirt"]
    # one item, with a capacity in passing, is not a list of two
    assert pc.caption_item_kinds("We have Silver Communion Trays in stock. Each holds 40 cups", CATALOG) == []
    assert pc.caption_item_kinds("Silver Communion Tray, with 40 cups included", CATALOG) == []
    assert pc.caption_item_kinds("Our Silver Communion Tray, made to serve", CATALOG) == []
    assert pc.caption_item_kinds("", CATALOG) == []


# ── 3. the ladder: the set row, never one of its pieces ──────────────────────

def test_the_owner_caption_is_the_cassock_set_not_the_cassock(monkeypatch):
    # the old rung, on its own, picked ONE piece by longest name containment
    old = pc.product_from_caption(OWNER_CAPTION, CATALOG)
    assert old is not None and old["name"] in ("Cassock", "CINCTURE BELT")
    hit = _resolve(monkeypatch, OWNER_CAPTION)
    assert hit is not None and hit["name"] == "Cassock Set"
    assert hit["_identity_source"] == "caption" and pc.identity_trusted(
        {"name": hit["name"], "source": "caption", "confidence": hit["_identity_confidence"]})
    assert hit["set"] is True and hit["price_usd"] == 200
    assert hit["components"] == ["cassock", "stole", "belt", "straight collar shirt", "12 inch clergy collar"]


def test_a_person_robed_in_the_outfit_is_the_set_too(monkeypatch):
    hit = _resolve(monkeypatch, CONGRATS_CAPTION)
    assert hit is not None and hit["name"] == "Cassock Set"
    hit2 = _resolve(monkeypatch, "Congratulations to Bishop Mary, robed in her Classic Princes "
                                 "Cassock Set — cassock, shirt, collar, stole and cincture belt")
    assert hit2 is not None and hit2["name"] == "Classic Princes Cassock Set"


def test_a_listing_is_not_a_set_and_never_one_piece(monkeypatch):
    assert _resolve(monkeypatch, LISTING_CAPTION) is None
    # "complete set: cassock and stole" is two of the five — not the Cassock Set
    assert _resolve(monkeypatch, "Complete set: cassock and stole") is None
    # a list with no set cue names nothing by itself (the model gets the list)
    assert _resolve(monkeypatch, "Shirt, collar, cassock, cincture belt and stole. Order now.") is None


def test_a_combination_with_no_set_row_is_totalled(monkeypatch):
    hit = _resolve(monkeypatch, BISHOP_CAPTION)
    assert hit is not None and hit["name"] == "Mitre + Cincture Rope + Skull Cap"
    assert hit["price"] == 9000 and hit["price_usd"] == 100 and hit["slug"] == "mitre"
    assert [i["name"] for i in hit["bundle"]] == ["Mitre", "Cincture Rope", "Skull Cap"]
    assert hit["_identity_source"] == "caption"
    # a kind the hub sells in several rows, with nothing in the caption to pick one, is no total
    assert pc.bundle_from_caption("Full set: cassock and stole", CATALOG) is None
    # an unpriced piece leaves no total to give
    assert pc.bundle_row([dict(_by("Mitre")), {**_by("Skull Cap"), "price": 0}]) is None
    assert pc.bundle_row([_by("Mitre")]) is None


def test_the_single_name_rungs_still_answer(monkeypatch):
    assert _resolve(monkeypatch, "Silver Communion Tray, with 40 cups included")["name"] == "Silver Communion Tray"
    assert _resolve(monkeypatch, "Cassock Set now available")["name"] == "Cassock Set"
    link = _resolve(monkeypatch, "Order here https://bethanyhouse.co.ke/product/cassock-set")
    assert link["name"] == "Cassock Set" and link["_identity_source"] == "link"
    # a spelled-out set row whose description enumerates nothing is still the set
    hit = _resolve(monkeypatch, "Cope — Complete Set for your consecration: cope, mitre and ring")
    assert hit is not None and hit["name"] == "Cope — Complete Set" and hit["components"] == []


# ── 4. the resolver: the recorded row leads the sink, a bundle is re-totalled ─

def _resolver_env(monkeypatch):
    async def fake_catalog(db, redis_):
        return CATALOG
    monkeypatch.setattr("app.services.n8n_bridge.catalog_items", fake_catalog)

    class _DB:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
    monkeypatch.setattr("app.database.AsyncSessionLocal", lambda: _DB())
    _no_image_rungs(monkeypatch)

    async def no_describe(thumb):
        return ""
    monkeypatch.setattr(rt, "_describe_post_image", no_describe)
    queries = []

    async def fake_run_tool(name, args, ctx):
        # the real search: every row carrying all the query's words, CHEAPEST first
        queries.append(args["query"])
        toks = tools._search_tokens(args["query"])
        rows = [dict(p) for p in CATALOG if toks and toks <= tools._search_words(p["name"])]
        rows.sort(key=lambda p: p["price"])
        ctx.seen_products.extend(rows)
        return {}
    monkeypatch.setattr(rt, "run_tool", fake_run_tool)
    return queries


def test_the_set_post_leads_with_the_recorded_row_not_the_cheaper_sibling(monkeypatch):
    r = _Redis()
    queries = _resolver_env(monkeypatch)
    sink: list = []
    asyncio.run(rt._resolve_post_product(r, "facebook", "PSID1",
                                         {"post_id": "P-set", "title": OWNER_CAPTION}, sink))
    rec = json.loads(r.kv[rt._post_product_key("facebook", "P-set")])
    assert rec["name"] == "Cassock Set" and rec["source"] == "caption" and pc.identity_trusted(rec)
    assert queries == ["Cassock Set"]
    # the search returned the ladies' set first (cheaper); the record's row leads
    assert sink[0]["name"] == "Cassock Set" and sink[0]["price_usd"] == 200
    assert sink[0]["components"] == ["cassock", "stole", "belt", "straight collar shirt", "12 inch clergy collar"]
    assert any(p["name"] == "Classic Princes Cassock Set" for p in sink[1:])


def test_a_bundle_post_is_re_totalled_from_fresh_rows(monkeypatch):
    r = _Redis()
    queries = _resolver_env(monkeypatch)
    sink: list = []
    asyncio.run(rt._resolve_post_product(r, "facebook", "PSID1",
                                         {"post_id": "P-bishop", "title": BISHOP_CAPTION}, sink))
    rec = json.loads(r.kv[rt._post_product_key("facebook", "P-bishop")])
    assert rec["name"] == "Mitre + Cincture Rope + Skull Cap" and rec["source"] == "caption"
    assert [i["slug"] for i in rec["bundle"]] == ["mitre", "cincture-rope", "skull-cap"]
    assert queries == ["Mitre", "Cincture Rope", "Skull Cap"]
    assert sink[0]["bundle"] and sink[0]["price"] == 9000 and sink[0]["price_usd"] == 100
    assert [p["name"] for p in sink[0]["bundle_rows"]] == ["Mitre", "Cincture Rope", "Skull Cap"]
    # a second comment recalls the record and re-totals it without the caption
    sink2: list = []
    asyncio.run(rt._resolve_post_product(r, "facebook", "PSID2",
                                         {"post_id": "P-bishop", "title": ""}, sink2))
    assert sink2 and sink2[0]["name"] == "Mitre + Cincture Rope + Skull Cap" and sink2[0]["price"] == 9000


def test_a_listing_caption_is_never_scored_down_to_one_row(monkeypatch):
    r = _Redis()
    queries = _resolver_env(monkeypatch)
    called = []
    real = rt._hub_caption_match
    monkeypatch.setattr(rt, "_hub_caption_match", lambda cat, title: called.append(title) or real(cat, title))
    sink: list = []
    asyncio.run(rt._resolve_post_product(r, "facebook", "PSID1",
                                         {"post_id": "P-list", "title": LISTING_CAPTION}, sink))
    assert called == [] and queries == [] and sink == []
    assert r.kv.get(rt._post_product_key("facebook", "P-list")) is None


def test_a_stale_one_piece_record_under_a_set_caption_is_re_read(monkeypatch):
    """The live post: 'Cassock' recorded from the caption, trusted, under the
    five-piece outfit. The ladder re-reads it into the Cassock Set."""
    r = _Redis()
    _resolver_env(monkeypatch)
    key = rt._post_product_key("facebook", "P-live")
    r.kv[key] = json.dumps({"name": "Cassock", "slug": "cassock", "source": "caption", "confidence": 0.95})
    assert pc.caption_record_stale(json.loads(r.kv[key]), OWNER_CAPTION, CATALOG) is True
    known = asyncio.run(rt._post_identity(r, "facebook", {"post_id": "P-live", "title": OWNER_CAPTION}))
    assert known["name"] == "Cassock Set" and known["source"] == "caption"
    assert json.loads(r.kv[key])["name"] == "Cassock Set"
    # a one-piece record under a plain LISTING is dropped: nothing to trust
    r.kv[rt._post_product_key("facebook", "P-list")] = json.dumps(
        {"name": "Cassock", "slug": "cassock", "source": "caption", "confidence": 0.95})
    known2 = asyncio.run(rt._post_identity(r, "facebook", {"post_id": "P-list", "title": LISTING_CAPTION}))
    assert known2 == {} and rt._post_product_key("facebook", "P-list") not in r.kv
    # a set record, a bundle record, the team's word and a one-item caption are never stale
    assert pc.caption_record_stale({"name": "Cassock Set", "slug": "cassock-set", "source": "caption"},
                                   OWNER_CAPTION, CATALOG) is False
    assert pc.caption_record_stale({"name": "Mitre + Skull Cap", "source": "caption", "bundle": [{"name": "Mitre"}]},
                                   BISHOP_CAPTION, CATALOG) is False
    assert pc.caption_record_stale({"name": "Cassock", "slug": "cassock", "source": "team"},
                                   OWNER_CAPTION, CATALOG) is False
    assert pc.caption_record_stale({"name": "Cassock", "slug": "cassock", "source": "caption"},
                                   "Our Cassock, made to measure", CATALOG) is False
    src = inspect.getsource(rt._post_identity)
    assert "caption_record_stale" in src and "stale caption identity" in src


def test_a_bundle_record_survives_a_refresh(monkeypatch):
    async def no_describe(thumb):
        return ""
    monkeypatch.setattr(rt, "_describe_post_image", no_describe)
    r = _Redis()
    total = pc.with_provenance(pc.bundle_row([_by("Mitre"), _by("Skull Cap")]), "caption")
    asyncio.run(rt._remember_post_product(r, "facebook", "P1", total))
    asyncio.run(rt._remember_post_product(r, "facebook", "P1", {"name": total["name"], "slug": "mitre"}))
    rec = json.loads(r.kv[rt._post_product_key("facebook", "P1")])
    assert rec["source"] == "caption" and [i["name"] for i in rec["bundle"]] == ["Mitre", "Skull Cap"]


# ── 5. the canned line: the set's one price and what it comes with ───────────

def test_the_set_line_is_said_the_owners_way():
    items = rt._components_text(pc.set_components(_by("Cassock Set"), CATALOG))
    assert items == "a cassock, a stole, a belt, a straight collar shirt and a 12 inch clergy collar"
    out = rt._comment_public_reply("", dm_sent=False, name_tag=" Grace", seed="g", product_known=True,
                                   product_name="Cassock Set", price_text="$200", set_items=items)
    assert "This is our Cassock Set, and it goes for $200" in out
    assert f"It comes with {items}" in out
    assert out.count("$200") == 1 and "$120" not in out
    assert "place your order now" in out and "how many you need, your city" in out   # stock: no colour
    mto = rt._comment_public_reply("", dm_sent=False, name_tag=" Grace", seed="g", product_known=True,
                                   product_name="Cassock Set", price_text="$200", set_items=items,
                                   made_to_order=True)
    assert "the colour you need" in mto and "how many" not in mto
    first = rt._comment_public_reply("", dm_sent=False, name_tag=" Grace", seed="g", product_known=True,
                                     product_name="Cassock Set", price_text="$200", set_items=items,
                                     first_contact=True)
    assert first.startswith("Welcome to Bethany House Grace") and "It comes with" in first


def test_the_set_line_in_swahili_keeps_the_hubs_name():
    items = rt._components_text(pc.set_components(_by("Cassock Set"), CATALOG), swahili=True)
    assert items == "cassock, stole, belt, straight collar shirt na 12 inch clergy collar"
    out = rt._comment_public_reply("", dm_sent=False, name_tag=" Amina", seed="a", product_known=True,
                                   product_name="Cassock Set", price_text="KES 19,500", set_items=items,
                                   swahili=True, made_to_order=True)
    assert "Hii ni Cassock Set yetu, na ni KES 19,500 kwa seti kamili" in out
    assert f"Inakuja na {items}" in out and "rangi unayohitaji" in out


def test_the_bundle_line_accounts_for_every_item():
    total = pc.bundle_row([_by("Mitre"), _by("Cincture Rope"), _by("Skull Cap")])
    items = rt._bundle_items_text(total["bundle_rows"], "USD")
    assert items == "the Mitre at $60, the Cincture Rope at $20 and the Skull Cap at $20"
    out = rt._comment_public_reply("", dm_sent=False, name_tag=" Sam", seed="s", product_known=True,
                                   product_name=total["name"], price_text="$100", set_items=items,
                                   bundle=True)
    assert items in out and "$100" in out and "all together" in out.lower()
    sw = rt._comment_public_reply("", dm_sent=False, name_tag="", seed="s", product_known=True,
                                  product_name=total["name"], price_text="KES 9,000",
                                  set_items=rt._bundle_items_text(total["bundle_rows"], "KES", swahili=True),
                                  bundle=True, swahili=True)
    assert "Seti nzima — Mitre KES 5,500, Cincture Rope KES 2,000 na Skull Cap KES 1,500 — ni KES 9,000 kwa jumla" in sw


def test_without_items_the_ordinary_line_is_unchanged():
    out = rt._comment_public_reply("", dm_sent=False, name_tag=" Joy", seed="j", product_known=True,
                                   product_name="Silver Communion Tray", price_text="$180")
    assert "the Silver Communion Tray is $180" in out and "It comes with" not in out


def test_the_engine_hands_the_set_line_its_items():
    src = inspect.getsource(rt._run_comment_engage)
    assert 'set_items = _bundle_items_text(matched["bundle_rows"], _ccy, swahili)' in src
    assert 'set_items = _components_text(matched["components"], swahili)' in src
    assert "ask_which=ask_which, set_items=set_items," in src and "bundle=is_bundle)" in src
    assert 'and not (matched.get("components") or matched.get("bundle"))' in src


# ── 6. the model is told the rule, the set's contents, or the listed items ───

def test_run_turn_tells_the_model_what_the_post_sells():
    src = inspect.getsource(rt.run_turn)
    assert "line += _set_context(_known, _catalog)" in src
    assert 'line += _listed_items_context(pctx["title"], _catalog)' in src
    ctx = rt._set_context({"name": "Cassock Set", "slug": "cassock-set"}, CATALOG)
    assert "It is a SET the hub prices as ONE row" in ctx
    assert "it comes with cassock, stole, belt, straight collar shirt, 12 inch clergy collar" in ctx
    assert "never one piece's price as the set's" in ctx
    assert rt._set_context({"name": "Cassock", "slug": "cassock"}, CATALOG) == ""
    bundle = rt._set_context({"name": "Mitre + Skull Cap", "bundle": [{"name": "Mitre"}, {"name": "Skull Cap"}]}, CATALOG)
    assert "ONE outfit made of several hub items: Mitre, Skull Cap" in bundle and "TOTAL" in bundle
    listed = rt._listed_items_context("Shirt, collar, cassock, cincture belt and stole. Order now.", CATALOG)
    assert "lists several items (shirt, collar, cassock, belt, stole)" in listed and "TOTAL" in listed
    assert rt._listed_items_context("Our Silver Communion Tray, made to serve", CATALOG) == ""


def test_the_rules_say_a_set_is_its_total():
    for currency in ("USD", "KES"):
        p = build_system_prompt(country_iso="KE" if currency == "KES" else "", currency=currency)
        assert "A SET IS PRICED AS ITS TOTAL (owner rule, 2026-09-21)" in p
        assert "It comes with a cassock, a stole, a belt" in p
        assert "Separate items merely listed together" in p
    add = rt._public_comment_addendum("USD")
    assert "A SET IS PRICED AS ITS TOTAL (owner, 2026-09-21" in add
    assert "Never one piece's price alone under a set post" in add


# ── 7. the search tool marks a set row, and the owner's word for the belt ────

def _ctx(monkeypatch, currency="USD"):
    async def fake_catalog(db, redis):
        return CATALOG
    monkeypatch.setattr(tools.svc, "catalog_items", fake_catalog)

    async def no_campaign(redis):
        return None
    from app.services import promotions
    monkeypatch.setattr(promotions, "campaign_now", no_campaign)
    return ToolContext(db=None, redis=None, wa_id="PSID1", currency=currency, channel="facebook")


def test_search_marks_a_set_row_with_what_it_comes_with(monkeypatch):
    out = asyncio.run(_search_catalog({"query": "cassock set"}, _ctx(monkeypatch)))
    rows = {r["name"]: r for r in out["results"]}
    assert rows["Cassock Set"]["set"]["comes_with"] == \
        ["cassock", "stole", "belt", "straight collar shirt", "12 inch clergy collar"]
    assert "whole set" in rows["Cassock Set"]["set"]["note"]
    plain = asyncio.run(_search_catalog({"query": "cassock"}, _ctx(monkeypatch)))
    assert "set" not in next(r for r in plain["results"] if r["name"] == "Cassock")


def test_the_signature_belt_is_the_cincture_belt(monkeypatch):
    assert canonical("the signature belt and the stole") == "the cincture belt and the stole"
    out = asyncio.run(_search_catalog({"query": "signature belt"}, _ctx(monkeypatch)))
    assert out["results"] and out["results"][0]["name"] == "CINCTURE BELT"
