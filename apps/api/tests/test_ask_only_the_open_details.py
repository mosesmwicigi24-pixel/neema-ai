"""ASK ONLY WHAT THE HUB CANNOT ANSWER (owner, 2026-09-15): "Every product that
is not in production or marked for production means we have specific details
of it — the colour, the items, the capacity — which we do not need to ask.
Only items that go to production, which can be produced in varying colours,
sizes and attributes, get that question. Others we must be very specific,
and ask the relevant question."

The live miss: a Silver Communion Tray (stock; "for 40 cups, complete with
lid, holder and basin") was closed with "tuambie rangi na idadi unayohitaji"
and described with an invented "mfuko wa kumshika".

Repo fake style (no DB fixture). Requires Python 3.11 (SQLAlchemy models).
"""
import asyncio
import inspect

import app.main  # noqa: F401 — registers all SQLAlchemy models
from app.agent import runtime as rt
from app.agent import tools
from app.agent.prompt import build_system_prompt
from app.agent.tools import ToolContext, _search_catalog


STOCK_TRAY = {"hub_product_id": 1, "name": "Silver Communion Tray", "sku": "SCT", "slug": "silver-tray",
              "price": 18000, "price_usd": 180, "category": "Communion Items",
              "product_type": "simple", "is_producible": False,
              "description": "Silver-tone communion tray for 40 cups, complete with lid, holder and basin."}
TALLIT = {"hub_product_id": 2, "name": "Tallit (Prayer Shawl) - Medium", "sku": "TAL-M", "slug": "tallit-m",
          "price": 3500, "price_usd": 35, "category": "Prayer", "product_type": "variable",
          "is_producible": False,
          "description": "Medium tallit in royal blue, navy or purple.",
          "variants": [{"name": "Royal blue", "sku": "TAL-M-RB", "price_kes": 3500, "price_usd": 35},
                       {"name": "Navy", "sku": "TAL-M-NV", "price_kes": 3500, "price_usd": 35}]}
CASSOCK = {"hub_product_id": 3, "name": "Cassock", "sku": "CAS", "slug": "cassock",
           "price": 12000, "price_usd": 120, "category": "Vestments", "product_type": "variable",
           "is_producible": True, "description": "Made-to-measure cassock in every liturgical colour.",
           "measurements": [{"name": "chest", "required": True, "unit": "in"}]}


def _ctx(monkeypatch):
    async def fake_catalog(db, redis):
        return [STOCK_TRAY, TALLIT, CASSOCK]
    monkeypatch.setattr(tools.svc, "catalog_items", fake_catalog)
    return ToolContext(db=None, redis=None, wa_id="254700", currency="KES")


# ── 1. every search row says which questions the order still needs ──────────

def test_a_stock_item_is_never_asked_its_colour(monkeypatch):
    out = asyncio.run(_search_catalog({"query": "silver communion tray"}, _ctx(monkeypatch)))
    row = out["results"][0]
    assert row["made_to_order"] is False
    assert row["ask_next"].startswith("stock item — every detail is fixed")
    assert "never ask colour or size" in row["ask_next"]
    assert "how many, how soon and the delivery city" in row["ask_next"]
    assert "lid, holder and basin" in row["details"]                 # the specifics to STATE


def test_a_stock_item_with_fixed_options_offers_those_by_name(monkeypatch):
    out = asyncio.run(_search_catalog({"query": "tallit"}, _ctx(monkeypatch)))
    row = out["results"][0]
    assert row["made_to_order"] is False and row.get("variants")
    assert row["ask_next"].startswith("stock item with a FIXED set of options")
    assert "never an open 'which colour?'" in row["ask_next"]


def test_a_made_to_order_item_is_asked_colour_then_size(monkeypatch):
    out = asyncio.run(_search_catalog({"query": "cassock"}, _ctx(monkeypatch)))
    row = out["results"][0]
    assert row["made_to_order"] is True
    assert row["ask_next"].startswith("made to order")
    assert "ask the colour first, then the size or measurements" in row["ask_next"]
    assert row["measurements_needed"].startswith("chest")


# ── 2. the canned lines split the same way ───────────────────────────────────

def test_stock_pools_ask_how_many_where_and_when_never_colour():
    for line in (rt._STOCK_SELL_POOL + rt._STOCK_FIRST_SELL_POOL
                 + rt._SW_STOCK_SELL_POOL + rt._SW_STOCK_FIRST_SELL_POOL):
        low = line.lower()
        assert "colour" not in low and "rangi" not in low and "size" not in low, line
        assert "how many" in low or "idadi" in low, line
        assert "city" in low or "deliver" in low or "mji" in low, line
        assert line.count("?") == 1 and "{product}" in line and "{price}" in line, line


def test_made_to_order_pools_still_ask_the_colour():
    for line in rt._OVER_CAP_SELL_POOL + rt._FIRST_SELL_POOL:
        assert "colour" in line.lower(), line
    for line in rt._SW_OVER_CAP_SELL_POOL + rt._SW_FIRST_SELL_POOL:
        assert "rangi" in line.lower(), line


def test_the_composer_picks_by_the_hubs_flag():
    kw = dict(dm_sent=False, name_tag=" Joshua", seed="j", product_known=True,
              product_name="Silver Communion Tray", price_text="KES 18,000")
    stock = rt._comment_public_reply("", **kw)                              # default: stock
    assert "colour" not in stock.lower() and "how many you need" in stock
    mto = rt._comment_public_reply("", made_to_order=True, **kw)
    assert "colour" in mto.lower()
    sw_stock = rt._comment_public_reply("", swahili=True, **kw)
    assert "rangi" not in sw_stock and "idadi unayohitaji na mji wako" in sw_stock
    assert "Silver Communion Tray ni KES 18,000" in sw_stock
    sw_mto = rt._comment_public_reply("", swahili=True, made_to_order=True, **kw)
    assert "rangi" in sw_mto
    first = rt._comment_public_reply("", first_contact=True, **kw)
    assert first.startswith("Welcome to Bethany House Joshua") and "colour" not in first.lower()


def test_the_engine_reads_the_flag_from_the_hub_row():
    src = inspect.getsource(rt._run_comment_engage)
    assert 'made_to_order = bool(matched) and matched.get("product_type") == "variable"' in src
    assert "made_to_order=made_to_order" in src


# ── 3. the rule itself, in the prompt and under a comment ────────────────────

def test_the_prompt_asks_only_what_the_hub_cannot_answer():
    p = " ".join(build_system_prompt(country_iso="KE", currency="KES").split())
    assert "ASK ONLY WHAT THE HUB CANNOT ANSWER (owner rule, 2026-09-15)" in p
    assert "NEVER ask a stock item's colour or size" in p
    assert '"gold or silver?" — never an open "which colour?"' in p
    assert "THERE the colour and the size or measurements are the open details" in p
    assert "Every search result says which it is (`ask_next`)" in p
    assert ("The Silver Communion Tray is KES 18,000 — it holds 40 cups and comes with its lid, "
            "holder and basin. Kindly place your order — tell us how many you need and your city. "
            "How soon do you want it?") in p
    # the Swahili specifics and the Swahili stock close
    assert '"inabeba vikombe 40", "inakuja na kifuniko, kishikilio na beseni"' in p
    assert '("mfuko wa kumshika" was invented)' in p
    assert "Tafadhali weka oda yako — tuambie idadi unayohitaji na mji wako. Unaihitaji lini?" in p


def test_comment_rules_carry_the_same_split():
    a = " ".join(rt._public_comment_addendum("KES").split())
    assert "colour or size ONLY for a made-to-order item" in a
    assert "`ask_next` on every search result says which" in a
    assert "state them, never ask them" in a
    assert "never an invention like 'mfuko wa kumshika'" in a
    assert "Tafadhali weka oda yako — tuambie idadi unayohitaji na mji wako. Unaihitaji lini?" in a
