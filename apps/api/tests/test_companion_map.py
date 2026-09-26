"""THE COMPANION MAP, grounded (owner, 2026-09-26: "upselling naturally").
A suggestion is a fact only with a hub row and a price behind it: search rows
carry the humblest companion of each kind, a piece names the set it is also
sold in, and a set prices each piece as sold alone."""
import asyncio

import app.main  # noqa: F401 — registers all SQLAlchemy models
import app.services.promotions as promotions
from app.core import companions as cm


def _row(i, name, kes, usd, *, desc="", mto=False, ptype="simple"):
    return {"hub_product_id": i, "sku": f"S{i}", "name": name, "slug": name.lower().replace(" ", "-"),
            "price": kes, "price_kes": kes, "price_usd": usd, "prices": {"KES": kes, "USD": usd},
            "description": desc, "is_producible": mto, "product_type": ptype, "variants": [],
            "category": "", "images": []}


CATALOG = [
    _row(1, "Cassock Set", 19500, 200,
         desc="Complete cassock outfit in one order — cassock, stole, belt, straight "
              "collar shirt and a 12 inch clergy collar."),
    _row(2, "Classic Princes Cassock Set", 19000, 190, mto=True,
         desc="Complete five-piece ladies' cassock set — cassock, shirt, collar, stole "
              "and cincture belt — ordination-ready in one order."),
    _row(3, "Cassock", 13000, 120, mto=True),
    _row(4, "White Cassock", 13000, 130, mto=True),
    _row(5, "Straight Collar Shirt", 2500, 30, mto=True),
    _row(6, "Round Collar Clergy Shirt", 3000, 30, mto=True),
    _row(7, "Straight Collar", 400, 10),
    _row(8, "CINCTURE BELT", 2200, 30, mto=True),
    _row(9, "Usher Belt", 650, 10),
    _row(10, "Single Sided Stole", 2500, 30),
    _row(11, "Double sided stole", 4000, 40),
    _row(12, "Mitre", 5500, 60, mto=True),
    _row(13, "Cincture Rope", 2000, 20),
    _row(14, "Skull Cap", 1500, 20),
    _row(15, "Silver Communion Tray", 18000, 180, desc="Holds 40 cups; comes with lid, holder and basin."),
    _row(16, "Silver Communion Cups", 100, 1),
    _row(17, "Plastic Communion Cups", 10, 0.1),
    _row(18, "Communion Wafer Bread 500PCS", 1000, 10),
    _row(19, "Altar Wine", 1500, 15),
    _row(20, "Brass Thurible", 9000, 90),
    _row(21, "Pectoral Cross", 6000, 60),
    _row(22, "Bishop's Ring", 4500, 45),
    _row(23, "Eliad Oil", 5000, 50),
]
_BY = {r["name"]: r for r in CATALOG}


def test_a_cassock_goes_with_its_stole_cincture_and_shirt():
    names = [r["name"] for r in cm.goes_with(_BY["Cassock"], CATALOG)]
    # the humblest stole; the CINCTURE belt, never the usher belt; the cheapest shirt
    assert names == ["Single Sided Stole", "CINCTURE BELT", "Straight Collar Shirt"]


def test_a_tray_goes_with_cups_bread_and_wine_cheapest_first():
    names = [r["name"] for r in cm.goes_with(_BY["Silver Communion Tray"], CATALOG)]
    assert names == ["Plastic Communion Cups", "Communion Wafer Bread 500PCS", "Altar Wine"]


def test_sets_and_unknown_kinds_have_no_companions():
    assert cm.goes_with(_BY["Cassock Set"], CATALOG) == []
    assert cm.goes_with(_BY["Eliad Oil"], CATALOG) == []
    assert cm.goes_with(None, CATALOG) == [] and cm.goes_with(_BY["Cassock"], []) == []


def test_a_piece_names_the_plain_set_it_is_sold_in():
    assert cm.part_of_set(_BY["Cassock"], CATALOG)["name"] == "Cassock Set"
    assert cm.part_of_set(_BY["Straight Collar Shirt"], CATALOG)["name"] == "Cassock Set"
    assert cm.part_of_set(_BY["Silver Communion Tray"], CATALOG) is None   # no tray set here
    assert cm.part_of_set(_BY["Cassock Set"], CATALOG) is None            # a set is not in a set


def test_a_set_prices_each_piece_as_sold_alone():
    got = {e["piece"]: e["row"]["name"] for e in cm.pieces_priced(_BY["Cassock Set"], CATALOG)}
    assert got["cassock"] == "Cassock"                       # the plain name over White Cassock
    assert got["stole"] == "Single Sided Stole"
    assert got["belt"] == "CINCTURE BELT"                    # a cassock's belt is the cincture
    assert got["straight collar shirt"] == "Straight Collar Shirt"
    assert got["12 inch clergy collar"] == "Straight Collar"


def test_search_rows_carry_the_map(monkeypatch):
    from app.agent.tools import _search_catalog, ToolContext
    import app.agent.tools as tools

    async def _cat(db, redis):
        return CATALOG
    monkeypatch.setattr(tools.svc, "catalog_items", _cat, raising=False)

    async def _no_campaign(*a, **kw):
        return None
    monkeypatch.setattr(promotions, "campaign_now", _no_campaign)
    ctx = ToolContext(db=None, redis=None, wa_id="254700000001", channel="whatsapp",
                      currency="USD", usd_rate=100, seen_products=[], read_only=True)
    out = asyncio.run(_search_catalog({"query": "cassock"}, ctx))
    rows = {r["name"]: r for r in out["results"]}
    piece = rows["Cassock"]
    assert [g["name"] for g in piece["goes_with"]][:2] == ["Single Sided Stole", "CINCTURE BELT"]
    assert all(isinstance(g["price"], (int, float)) for g in piece["goes_with"])
    assert piece["part_of_set"]["name"] == "Cassock Set" and piece["part_of_set"]["price"] == 200
    assert "AND the set's total" in piece["part_of_set"]["note"]
    sset = rows["Cassock Set"]
    priced = {e["piece"]: e for e in sset["set"]["pieces_priced"]}
    assert priced["cassock"]["row"] == "Cassock" and priced["cassock"]["price"] == 120
    assert "goes_with" not in sset                            # a set is complete
    # companions only on the first rows — the ones that get quoted
    assert sum(1 for r in out["results"] if r.get("goes_with")) <= 3
    # made-to-order rows take the order in the owner's pull
    assert "Kindly place your order" in piece["ask_next"] and "measurements after the yes" in piece["ask_next"]


def test_the_offer_on_a_varied_product_names_the_variant(monkeypatch):
    from app.agent.tools import _search_catalog, ToolContext
    import app.agent.tools as tools
    collar = dict(_row(30, "Clergy Collar", 350, 3.5, ptype="variable"))
    collar["variants"] = [{"label": "Clergy Collar — 8 inch", "sku": "C8", "price_kes": 350, "price_usd": 3.5,
                           "prices": {"KES": 350, "USD": 3.5}, "attributes": {"Size": "8"}},
                          {"label": "Clergy Collar — 10 inch", "sku": "C10", "price_kes": 400, "price_usd": 4,
                           "prices": {"KES": 400, "USD": 4}, "attributes": {"Size": "10"}}]

    async def _cat(db, redis):
        return [collar]
    camp = {"name": "Harvest Offer", "percent": 10, "scope": "all", "categories": [], "skus": [],
            "starts_on": None, "ends_on": "2099-12-31"}

    async def _campaign(*a, **kw):
        return camp
    monkeypatch.setattr(tools.svc, "catalog_items", _cat, raising=False)
    monkeypatch.setattr(promotions, "campaign_now", _campaign)
    ctx = ToolContext(db=None, redis=None, wa_id="254700000001", channel="whatsapp",
                      currency="USD", usd_rate=100, seen_products=[], read_only=True)
    out = asyncio.run(_search_catalog({"query": "clergy collar"}, ctx))
    row = out["results"][0]
    say = row["offer_available"]["say_when_played"]
    assert "chosen variant" in say and "$3.50" in say and "$3.15" in say
    assert [v.get("offer_price") for v in row["variants"]] == [3.15, 3.6]
