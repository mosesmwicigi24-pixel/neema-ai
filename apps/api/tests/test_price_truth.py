"""THE KES PRICE IS THE TRUTH (owner, 2026-10-02).

Facebook, under a post of bishop's rings: "Are they consecrated? na ni pesa
ngapi?" was answered "Hii ni Ring yetu… bei ni USD 20". Three faults in one
reply: the post's item is the Bishopric Ring (KES 4,500 — "45 USD"), not the
plain Ring (KES 1,500 — "the normal rings are 15 usd"); the hub's own USD row
for the Ring said 20, and Neema repeated it; and a Swahili price ask was
quoted in dollars. The owner: "The prices should be accurate on Facebook."
"""
import asyncio
import inspect

import pytest

import app.main  # noqa: F401
import app.agent.runtime as rt
from app.agent import review as rv
from app.agent.tools import ToolContext, _to_display
from app.core.synonyms import canonical
from app.routers import health as health_router
from app.routers import public as pub
from app.services import post_catalog as pc
from app.services import price_audit as pa

RING = {"name": "Ring", "slug": "bishops-ring", "price": 1500, "price_kes": 1500, "price_usd": 20,
        "prices": {"KES": 1500, "USD": 20}, "category": "Clergy Accessories", "product_type": "simple",
        "description": "Gold ring with a coloured stone."}
BISHOPRIC = {"name": "Bishopric Ring", "slug": "apostolic-ring", "price": 4500, "price_kes": 4500,
             "price_usd": 45, "prices": {"KES": 4500, "USD": 45}, "category": "Clergy Accessories",
             "product_type": "simple", "description": "A bishop's ring with a large stone."}
CROSS = {"name": "Pectoral Cross", "slug": "pectoral-cross", "price": 3500, "price_kes": 3500, "price_usd": 35,
         "prices": {"KES": 3500, "USD": 35}, "category": "Clergy Accessories", "product_type": "simple"}
COLLAR = {"name": "Straight Collar", "slug": "straight-collar", "price": 400, "price_kes": 400, "price_usd": 10,
          "prices": {"KES": 400, "USD": 10}, "category": "Clergy Accessories", "product_type": "simple"}
CATALOG = [RING, BISHOPRIC, CROSS]


def _ctx(ccy="USD"):
    return ToolContext(db=None, redis=None, wa_id="u1", currency=ccy, usd_rate=100)


# ── cycle 1: the quote policy ────────────────────────────────────────────────
@pytest.mark.parametrize("kes,usd,quoted", [
    (1500, 20, 15),        # the ring: the hub's $20 is a stale number — KES / 100
    (4500, 45, 45),        # the bishopric ring: the hub agrees
    (10000, 95, 95),       # within 5%: the hub's own figure stands
    (1300, 12.75, 12.75),  # a deliberate exact price stands
    (400, 10, 4),          # the $10 floor on a $4 collar
    (36000, 600, 360),     # the tray set rounded to 600
    (4500, 50, 45),        # the shirt quoted at $50 on Facebook (2026-09-06)
    (1500, None, 15),      # no hub USD: KES / rate
    (None, 20, 20),        # no KES: the hub's USD is all there is
    (None, None, None),
])
def test_the_usd_quote_follows_the_kes_price(kes, usd, quoted):
    assert pa.usd_quote(kes, usd, 100) == quoted


def test_the_tools_quote_fifteen_and_forty_five():
    assert _to_display(1500, _ctx("USD"), 20, prices=RING["prices"]) == 15
    assert _to_display(4500, _ctx("USD"), 45, prices=BISHOPRIC["prices"]) == 45
    assert _to_display(1500, _ctx("KES"), 20, prices=RING["prices"]) == 1500
    assert _to_display(10000, _ctx("USD"), price_usd=95) == 95        # within 5%, the hub's own
    assert _to_display(1300, _ctx("USD"), prices={"USD": 12.75}) == 12.75
    assert _to_display(400, _ctx("USD"), price_usd=10) == 4
    assert _to_display(None, _ctx("USD"), price_usd=0.5) == 0.5


def test_the_canned_line_and_the_storefront_card_say_the_same_figure():
    assert rt._public_price_text(1500, 20, "USD") == "$15"
    assert rt._public_price_text(4500, 45, "USD") == "$45"
    assert rt._public_price_text(1500, 20, "KES") == "KES 1,500"
    assert rt._public_price_text(None, 20, "USD") == "$20"
    price, cur = pub._resolve_price({"KES": 1500, "USD": 20}, "USD")
    assert float(price) == 15 and cur == "USD"
    price, cur = pub._resolve_price({"KES": 4500, "USD": 45}, "USD")
    assert float(price) == 45
    price, cur = pub._resolve_price({"KES": 1500, "USD": 20}, "KES")
    assert float(price) == 1500 and cur == "KES"


# ── cycle 2: the reviewer enforces it ────────────────────────────────────────
def test_the_reviewer_holds_the_stale_hub_dollar_and_passes_the_true_one():
    figs = rv._row_figures(RING, "USD")
    assert 15.0 in figs and 1500.0 in figs and 20.0 not in figs
    assert rv._usd_of(set(), [RING]) == {15.0}
    bad = rv.rule_findings("How much is the ring?", "The Ring is $20.", [RING])
    assert any(f["kind"] == "figure" and f["hard"] for f in bad)
    good = rv.rule_findings("How much is the ring?", "The Ring is $15.", [RING])
    assert not any(f["kind"] == "figure" for f in good)
    good_b = rv.rule_findings("How much is the bishopric ring?", "The Bishopric Ring is $45.", [BISHOPRIC])
    assert not any(f["kind"] == "figure" for f in good_b)
    text = rv.rows_text([RING, BISHOPRIC], "USD")
    assert "Ring — USD 15" in text and "Bishopric Ring — USD 45" in text and "20" not in text
    assert "KES 1500" in rv.rows_text([RING], "KES")


# ── cycles 3-4: the post's item is the specific one ──────────────────────────
def test_the_bishops_ring_is_the_bishopric_ring():
    assert "bishopric ring" in canonical("Bishop's rings in red, blue and gold")
    for cap in ("Bishop's rings in red, blue and gold 💍", "Bishopric rings available",
                "Episcopal ring for your consecration", "Pete za maaskofu zimefika",
                "Apostolic rings in three stones", "Rings for bishops — red, blue and gold"):
        hit = rt._hub_caption_match(CATALOG, cap)
        assert hit is not None and hit["name"] == "Bishopric Ring", cap
    # the caption says only "rings": the caption has not said which — the photo decides
    assert rt._hub_caption_match(CATALOG, "Rings available in three stones") is None
    assert rt._hub_caption_match(CATALOG, "New rings in stock, which stone is yours?") is None
    # a one-word name with no longer sibling still matches on its own
    assert rt._hub_caption_match([RING, CROSS], "Rings available in three stones")["name"] == "Ring"
    # the rest of the shelf is untouched
    assert rt._hub_caption_match(CATALOG, "Our Pectoral Cross is back in stock")["name"] == "Pectoral Cross"
    assert rt._hub_caption_match(CATALOG, "Blessed Sunday to all our friends") is None


def test_the_ladder_trusts_the_specific_caption_and_leaves_the_generic_one_to_the_photo():
    hit = asyncio.run(pc.resolve_post(None, {"title": "Bishop's rings in red, blue and gold", "thumb": ""}, CATALOG))
    assert hit is not None and hit["name"] == "Bishopric Ring" and hit.get("_identity_source") == "caption"
    assert asyncio.run(pc.resolve_post(None, {"title": "Rings available in three stones", "thumb": ""}, CATALOG)) is None
    names = {p["name"] for p in pc.vision_candidates(CATALOG, "Rings available in three stones")}
    assert {"Ring", "Bishopric Ring"} <= names
    # a recorded generic "Ring" (caption-stamped) is stale beside the Bishopric Ring: re-read, not kept
    rec = {"name": "Ring", "slug": "bishops-ring", "source": "caption", "confidence": 1.0}
    assert pc.caption_record_stale(rec, "Bishop's rings in red, blue and gold", CATALOG)
    assert pc.caption_record_stale(rec, "Rings available", CATALOG)
    assert not pc.caption_record_stale(rec, "Rings available", [RING, CROSS])            # no longer sibling
    assert not pc.caption_record_stale(dict(rec, name="Bishopric Ring", slug="apostolic-ring"),
                                       "Bishop's rings", CATALOG)
    assert not pc.caption_record_stale(dict(rec, source="vision"), "Rings available", CATALOG)


# ── cycles 5-6: Swahili means Kenya, by construction ─────────────────────────
class _FakeRedis:
    def __init__(self):
        self.kv: dict = {}

    async def get(self, k):
        return self.kv.get(k)

    async def set(self, k, v, ex=None, nx=False):
        self.kv[k] = v
        return True


def test_a_swahili_ask_is_quoted_in_kes_and_the_thread_stays_kes():
    r = _FakeRedis()
    kes = lambda text, ccy="USD", key="u1": asyncio.run(rt._kes_for_swahili(r, "facebook", key, text, ccy))
    assert kes("Are they consecrated? na ni pesa ngapi?") == "KES"      # the live comment
    assert kes("Thank you, and the blue one?") == "KES"                 # the thread stays KES
    assert kes("How much is the blue one?", key="u2") == "USD"           # another, English, thread
    assert kes("Habari, bei ya pete ni ngapi?", key="u3") == "KES"
    assert kes("Niko Tanzania, bei gani?", key="u4") == "USD"           # a stated other country keeps the market
    assert kes("Niko Nakuru, nataka hii", key="u5") == "KES"
    assert kes("Bei gani?", "ZMW", key="u6") == "ZMW"                   # evidence already decided
    src = inspect.getsource(rt.run_turn)
    assert 'currency = await _kes_for_swahili(redis, channel, key, user_text or "", currency)' in src


# ── cycles 7-8: the health block names the rows to fix ───────────────────────
def test_health_names_the_hub_rows_whose_dollar_disagrees():
    out = pa.health_summary_from(CATALOG + [COLLAR], 100)
    assert out["rate"] == 100 and out["checked"] == 4
    assert out["hub_usd_gaps"] == 2 and out["quoted_from_kes"] == 2
    assert out["worst"][0]["name"] == "Straight Collar" and out["worst"][0]["quoted_usd"] == 4
    assert {"name": "Ring", "kes": 1500, "hub_usd": 20, "quoted_usd": 15} in out["worst"]
    assert "else KES/100" in out["policy"]
    assert 'out["prices"]' in inspect.getsource(health_router.health)
    clean = pa.health_summary_from([BISHOPRIC, CROSS], 100)
    assert clean["hub_usd_gaps"] == 0 and clean["worst"] == []
