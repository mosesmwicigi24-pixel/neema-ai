"""One item, many names (owner, 2026-09-06): "Cross and chain, Pendant, Pectoral
Cross, Pastors / Bishops cross are all the same item. When someone enquires,
you should guide the person to the product which is in the hub."

The table in core/synonyms rewrites the customer's words to the hub's term at
every seam that turns words into a hub row, so a "pendant" is never an empty
search, a "let me confirm", or a "we don't sell chains".

Repo fake style (no DB fixture). Requires Python 3.11 (SQLAlchemy models).
"""
import asyncio

import pytest

import app.main  # noqa: F401 — registers all SQLAlchemy models
from app.agent import runtime as rt
from app.agent import tools
from app.agent.prompt import build_system_prompt
from app.agent.tools import ToolContext, _match_product, _search_catalog
from app.core import hub_client
from app.core.synonyms import canonical, hub_terms
from app.services import post_catalog as pc


# The hub as it stands (2026-09-06): the Pectoral Cross listed twice at one
# price, a Premium sibling, a Small cross, and a thurible that swings on a chain.
CATALOG = [
    {"hub_product_id": 11, "name": "Pectoral Cross — Gold Finish", "sku": "PC-1",
     "slug": "pectoral-cross", "price": 4000, "price_usd": 40, "category": "Vestments",
     "aliases": [], "thumbnail_url": "https://img/pc.jpg"},
    {"hub_product_id": 12, "name": "Pectoral Cross", "sku": "PC-2",
     "slug": "pectoral-cross-gold", "price": 4000, "price_usd": 40, "category": "Vestments",
     "aliases": [], "thumbnail_url": "https://img/pc2.jpg"},
    {"hub_product_id": 13, "name": "Premium Pectoral Cross", "sku": "PC-3",
     "slug": "premium-pectoral-cross", "price": 10000, "price_usd": 100,
     "category": "Clergy Accessories", "aliases": []},
    {"hub_product_id": 14, "name": "Small cross", "sku": "SC-1", "slug": "small-cross-1",
     "price": 2500, "price_usd": 25, "category": "Clergy Accessories", "aliases": []},
    {"hub_product_id": 15, "name": "Incense Burner / Thurible", "sku": "TH-1",
     "slug": "incense-burner", "price": 15000, "price_usd": 150,
     "category": "Clergy Accessories", "aliases": ["chain-swung censer"]},
]
PECTORAL = {"pectoral-cross", "pectoral-cross-gold", "premium-pectoral-cross"}


# ── the table itself ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("said, hub", [
    ("Do you have cross and chain?", "Do you have pectoral cross?"),
    ("How much is the pendant?", "How much is the pectoral cross?"),
    ("Pendants available?", "pectoral cross available?"),
    ("Pastor's cross price", "pectoral cross price"),
    ("bishops cross", "pectoral cross"),
    ("Bishop’s Cross", "pectoral cross"),
    ("cross with chain", "pectoral cross"),
    ("cross & chain", "pectoral cross"),
    ("chain cross", "pectoral cross"),
    ("cross pendant", "pectoral cross"),
    ("cross for bishops", "pectoral cross"),
    ("clergy cross", "pectoral cross"),
    ("pedant", "pectoral cross"),                    # the phone-keyboard spelling
])
def test_the_owners_words_become_the_hubs_term(said, hub):
    assert canonical(said) == hub


@pytest.mark.parametrize("text", [
    "Incense burner with chain",                     # a chain alone is no cross
    "across the road",
    "the small cross",
    "pectoral cross",
    "chain",
    "",
])
def test_everything_else_is_left_alone(text):
    assert canonical(text) == text


def test_none_is_empty():
    assert canonical(None) == ""


# ── the catalogue search: never an empty result for a pendant ────────────────

def _ctx(monkeypatch):
    async def fake_catalog(db, redis):
        return CATALOG
    monkeypatch.setattr(tools.svc, "catalog_items", fake_catalog)
    return ToolContext(db=None, redis=None, wa_id="254700", currency="KES")


@pytest.mark.parametrize("query", [
    "pendant", "cross and chain", "bishop's cross", "pastors cross", "Pendant cross",
])
def test_search_guides_the_customer_to_the_pectoral_cross(monkeypatch, query):
    ctx = _ctx(monkeypatch)
    out = asyncio.run(_search_catalog({"query": query}, ctx))
    names = [r["name"] for r in out["results"]]
    assert names, query
    assert all("Pectoral Cross" in n for n in names), names   # not the thurible, not the Small cross
    assert out["results"][0]["price"] == 4000                  # the hub's own KES figure


def test_search_still_finds_the_thurible_by_its_own_name(monkeypatch):
    ctx = _ctx(monkeypatch)
    out = asyncio.run(_search_catalog({"query": "thurible"}, ctx))
    assert [r["name"] for r in out["results"]] == ["Incense Burner / Thurible"]


# ── product cards and order lines land on the hub row ────────────────────────

def test_a_product_card_for_a_pendant_is_the_pectoral_cross():
    assert _match_product("pendant", CATALOG)["slug"] in PECTORAL
    assert _match_product("cross and chain", CATALOG)["slug"] in PECTORAL
    assert _match_product("Bishop's cross", CATALOG)["slug"] in PECTORAL


def test_an_order_line_in_the_customers_words_resolves_to_the_hub_product():
    line = hub_client.resolve_hub_line({"name": "cross and chain", "qty": 1}, CATALOG)
    assert line and line["product_id"] in {11, 12}
    assert line["unit_price"] == 4000.0                        # the hub's price, not the model's
    line = hub_client.resolve_hub_line({"name": "pendant", "quantity": 2}, CATALOG)
    assert line and line["product_id"] in {11, 12} and line["quantity"] == 2


# ── the comment funnel: a live comment and a post caption ────────────────────

def test_a_live_comment_asking_for_a_pendant_names_an_item():
    assert rt._mentions_catalogue_item("How much is the pendant?")
    assert rt._mentions_catalogue_item("Do you have cross and chain?")
    assert not rt._mentions_catalogue_item("Watching from Liberia 🇱🇷")


def test_a_post_captioned_cross_and_chain_is_a_pectoral_cross_post():
    hit = rt._hub_caption_match(CATALOG, "Cross and chain available today ✨")
    assert hit and "Pectoral Cross" in hit["name"]
    hit = pc.product_from_caption("Pendant for bishops, gold finish", CATALOG)
    assert hit and "Pectoral Cross" in hit["name"]


# ── the prompt says the same thing, and names every family in the table ──────

def test_the_prompt_teaches_the_rule():
    p = " ".join(build_system_prompt(currency="KES").split())
    for phrase in ('"cross and chain"', '"pendant"', "pastor's cross", "bishop's cross"):
        assert phrase in p, phrase
    assert "ALL our Pectoral Cross" in p
    assert "ONE item in the hub" in p
    assert "never send it to \"let me confirm\"" in p
    assert "presented once" in p                                # the hub's duplicate row
    for term in hub_terms():                                    # the table and the prompt agree
        assert term in p.lower(), term
