"""CHEAPEST FIRST, THEN CLIMB — and say it like a person (owner, 2026-09-16).

"How much is that Holy communion set?" was answered with three dear sets and
a chalice ($280, $600, $650) and "Which one did you have in mind?" — nothing
under $280 when the range starts at a $50 wooden tray, and a chalice is not a
communion set. The owner: "start with the aluminium tray or wooden tray …
silver communion tray at $180 … golden communion tray at $220 … after that
the Aluminium 4-Stack set … you don't quote the Chalice Cup here."

And the photo reply: "The photo shows our Silver Communion Tray, $180 — comes
with lid, holder, basin and 40 cups included free … Tell me a little more and
I'll sort you out" must become "This is our Silver Communion Tray, and it goes
for $180. It comes with a lid, a holder and a basin, and 40 cups are included
in the package for free. Kindly place your order now and let us know how many
trays you may need and how soon you want them delivered." — and nothing after
the order link.

Repo fake style (no DB fixture). Requires Python 3.11 (SQLAlchemy models).
"""
import asyncio
import inspect

import app.main  # noqa: F401 — registers all SQLAlchemy models
from app.agent import runtime as rt
from app.agent import tools
from app.agent.prompt import build_system_prompt
from app.agent.tools import ToolContext, _search_catalog
from app.core.synonyms import range_for, range_members


def _row(pid, name, kes, usd, **extra):
    d = {"hub_product_id": pid, "name": name, "sku": f"S{pid}", "slug": name.lower().replace(" ", "-"),
         "price": kes, "price_usd": usd, "category": "Communion Items",
         "product_type": "simple", "is_producible": False, "description": ""}
    d.update(extra)
    return d


# The live hub's communion shelf, deliberately out of price order.
CATALOG = [
    _row(1, "Golden Chalice Cup with Paten Set", 65000, 650),
    _row(2, "Double Stacked Silver Tray Set", 36000, 600),
    _row(3, "Aluminium 4-Stack Communion Set — 160 Cups", 28000, 280),
    _row(4, "Silver Communion Tray", 18000, 180,
         description="Silver-tone communion tray for 40 cups, complete with lid, holder and basin."),
    _row(5, "Silver Communion Cups", 100, 10),
    _row(6, "Golden Communion Tray", 22000, 220),
    _row(7, "Communion Wafer Bread 500PCS", 1000, 10),
    _row(8, "Wooden tray", 5000, 50),
    _row(9, "Aluminium Tray", 7000, 70),
    _row(10, "Silver Bread Tray", 13000, 130),
    _row(11, "EFRAT COMMUNION WINE", 3500, 40),
    _row(12, "Brass Chalice Cup", 40000, 400),
]


def _ctx(monkeypatch, currency="USD"):
    async def fake_catalog(db, redis):
        return CATALOG
    monkeypatch.setattr(tools.svc, "catalog_items", fake_catalog)

    async def no_campaign(redis):
        return None
    from app.services import promotions
    monkeypatch.setattr(promotions, "campaign_now", no_campaign)
    return ToolContext(db=None, redis=None, wa_id="PSID1", currency=currency, channel="messenger")


# ── 1. the range table knows a KIND from ONE item ────────────────────────────

def test_a_kind_of_thing_is_a_range_and_one_item_is_not():
    assert range_for("how much is that holy communion set")["name"] == "communion trays and sets"
    assert range_for("communion trays")["name"] == "communion trays and sets"
    assert range_for("trays for communion")["name"] == "communion trays and sets"
    assert range_for("bei ya meza ya bwana")["name"] == "communion trays and sets"
    # one member → the ordinary search answers
    assert range_for("silver communion tray") is None
    assert range_for("golden communion tray") is None
    assert range_for("aluminium 4-stack communion set") is None
    # a neighbour is not the range
    assert range_for("chalice") is None
    assert range_for("communion wafers") is None


def test_the_range_is_the_trays_and_sets_cheapest_first_and_no_chalice():
    rng = range_for("holy communion set")
    names = [p["name"] for p in range_members(rng, CATALOG)]
    assert names == [
        "Wooden tray",
        "Aluminium Tray",
        "Silver Communion Tray",
        "Golden Communion Tray",
        "Aluminium 4-Stack Communion Set — 160 Cups",
        "Double Stacked Silver Tray Set",
    ]
    for wrong in ("Golden Chalice Cup with Paten Set", "Brass Chalice Cup", "Silver Communion Cups",
                  "Communion Wafer Bread 500PCS", "EFRAT COMMUNION WINE", "Silver Bread Tray"):
        assert wrong not in names, wrong


# ── 2. search_catalog answers the range in that order, and says so ───────────

def test_search_catalog_lists_the_range_cheapest_first_with_the_note(monkeypatch):
    out = asyncio.run(_search_catalog({"query": "how much is that Holy communion set"},
                                      _ctx(monkeypatch)))
    prices = [r["price"] for r in out["results"]]
    assert prices == sorted(prices) and prices[0] == 50 and prices[-1] == 600
    assert [r["name"] for r in out["results"]][:2] == ["Wooden tray", "Aluminium Tray"]
    assert out["range"]["range"] == "communion trays and sets"
    assert "CHEAPEST FIRST" in out["range"]["order"]
    assert "chalice" in out["range"]["stay_in_range"].lower()
    names = " ".join(r["name"] for r in out["results"])
    assert "Chalice" not in names and "Wafer" not in names and "Cups" not in names.replace("160 Cups", "")


def test_one_named_item_leads_its_own_search(monkeypatch):
    # The category word "Communion" lets the Silver Bread Tray and the Double
    # Stacked Silver Tray Set match "silver communion tray" too — the row whose
    # NAME carries the words must still come first, whatever it costs.
    out = asyncio.run(_search_catalog({"query": "silver communion tray"}, _ctx(monkeypatch)))
    assert out["results"][0]["name"] == "Silver Communion Tray"
    assert "range" not in out


def test_ordinary_matches_come_cheapest_first_too(monkeypatch):
    out = asyncio.run(_search_catalog({"query": "chalice"}, _ctx(monkeypatch)))
    prices = [r["price"] for r in out["results"]]
    assert prices == sorted(prices) and prices[0] == 400


# ── 3. the DM is the answer and the link — nothing after ─────────────────────

def test_the_dm_ends_on_the_order_link():
    link = "https://bethanyhouse.co.ke/product/silver-communion-tray?ref=F4F6A7"
    answer = ("This is our Silver Communion Tray, and it goes for $180. It comes with a lid, "
              "a holder and a basin, and 40 cups are included in the package for free. Kindly "
              "place your order now and let us know how many trays you may need and how soon "
              "you want them delivered.")
    dm = rt._dm_text(answer, link, "seed")
    assert dm == f"{answer}\n\nOrder here 👉 {link}"
    assert not hasattr(rt, "_DM_CONTINUE_POOL") and not hasattr(rt, "_SW_DM_CONTINUE_POOL")


# ── 4. the rules carry the owner's words ─────────────────────────────────────

def test_the_rules_say_cheapest_first_and_the_human_shape():
    for currency in ("USD", "KES"):
        p = build_system_prompt(country_iso="KE" if currency == "KES" else "", currency=currency)
        assert "CHEAPEST FIRST, THEN CLIMB (owner rule, 2026-09-16)" in p
        assert "never open with\n  the three dearest" in p
        assert "STAY IN THE RANGE" in p
        assert "This is our\n  Silver Communion Tray, and it goes for $180." in p
        assert 'never "The photo shows our…"' in p
    add = rt._public_comment_addendum("USD")
    assert "SAY IT LIKE A PERSON WHO KNOWS THE STOCK (owner, 2026-09-16)" in add
    assert "This is our Silver Communion Tray, and it goes for $180." in add
    assert "Never 'The photo shows our…'" in add


# ── 5. the ad they tapped is carried into the conversation ───────────────────

def test_the_engine_carries_the_ad_headline_into_the_context():
    src = inspect.getsource(rt.run_turn)
    assert "ad_headline = (await _ad_headline(db, channel, key)) if is_meta else \"\"" in src
    assert "elif ad_headline:" in src
    assert "this customer reached us from our ad" in src


def test_the_ad_headline_comes_from_the_person_state():
    class _Ident:
        person_id = 7

    class _Person:
        state = {"lead_source": "facebook_ad", "ad_ref": {"headline": "Silver Communion Tray — 40 cups"}}

    class _Res:
        def __init__(self, v):
            self._v = v

        def scalar_one_or_none(self):
            return self._v

    class _DB:
        async def execute(self, stmt):
            return _Res(_Ident())

        async def get(self, model, pk):
            return _Person()

    assert asyncio.run(rt._ad_headline(_DB(), "messenger", "PSID")) == "Silver Communion Tray — 40 cups"

    class _NoIdent(_DB):
        async def execute(self, stmt):
            return _Res(None)

    assert asyncio.run(rt._ad_headline(_NoIdent(), "messenger", "PSID")) == ""
