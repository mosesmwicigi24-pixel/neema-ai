"""THE PRICES IN NEEMA'S INSTRUCTIONS COME FROM THE HUB (owner, 2026-11-16).
No price is typed into the instructions unnoticed, and the examples carry the
hub's own figures once the catalogue has been read."""
import inspect

import pytest

import app.main  # noqa: F401
from app.agent import prompt_prices as pp
from app.agent.prompt import build_system_prompt

# The hub's rows on 2026-11-16 (slug → KES, per-currency map).
HUB = [
    {"slug": "cassock-set", "price": 19500, "prices": {"KES": 19500, "ZMW": 3900}},
    {"slug": "cassock", "price": 13000, "prices": {"KES": 13000, "ZMW": 2400}},
    {"slug": "silver-communion-tray", "price": 18000, "prices": {"KES": 18000}},
    {"slug": "golden-communion-tray", "price": 22000, "prices": {"KES": 22000}},
    {"slug": "aluminium-tray", "price": 7000, "prices": {"KES": 7000}},
    {"slug": "wooden-tray", "price": 5000, "prices": {"KES": 5000}},
    {"slug": "aluminium-double-stacked-communion-set", "price": 28000, "prices": {"KES": 28000}},
    {"slug": "mitre", "price": 5500, "prices": {"KES": 5500}},
    {"slug": "cincture-rope", "price": 2000, "prices": {"KES": 2000}},
    {"slug": "skull-cap", "price": 1500, "prices": {"KES": 1500}},
    {"slug": "plastic-cups", "price": 10, "prices": {"KES": 10}},
    {"slug": "glass-cups", "price": 100, "prices": {"KES": 100}},
    {"slug": "communion-wafer-bread-200pcs", "price": 400, "prices": {"KES": 400}},
    {"slug": "communion-wafer-bread-500pcs", "price": 1000, "prices": {"KES": 1000}},
    {"slug": "round-collar-shirt", "price": 4500, "prices": {"KES": 4500, "ZMW": 900}},
    {"slug": "ornate-chasuble", "price": 14000, "prices": {"KES": 14000}},
    {"slug": "incense-burner", "price": 15000, "prices": {"KES": 15000}},
    {"slug": "gold-bread-tray", "price": 14000, "prices": {"KES": 14000}},
    {"slug": "eliad-anointing-oil", "price": 5000, "prices": {"KES": 5000}},
]


@pytest.fixture
def seen(monkeypatch):
    monkeypatch.setattr(pp, "_PRICES", {"by_slug": {}, "mark": None})
    pp.remember(HUB)


@pytest.mark.parametrize("ccy", ["KES", "USD", "ZMW"])
def test_no_price_is_typed_into_the_instructions_unnoticed(ccy):
    # Every money figure is either a listed example (fed from the hub) or a
    # named non-price. To add a product price to the instructions, add its
    # row to prompt_prices.ROWS with the hub product it belongs to.
    text = build_system_prompt(currency=ccy)
    assert pp.unlisted(text) == []
    assert pp.unlisted(text + ' "The Bishop Ring is KES 9,000."') == ["KES 9,000"]
    missing = [f for f, _ in pp.ROWS if not pp._rx(f).search(text) and "Eliad" not in f and f != "$50 to $45"]
    assert missing == []                                  # a row that matches nothing is dead weight


def test_without_a_catalogue_the_instructions_are_exactly_as_written(monkeypatch):
    monkeypatch.setattr(pp, "_PRICES", {"by_slug": {}, "mark": None})
    text = build_system_prompt(currency="USD")
    assert pp.fill(text) is text or pp.fill(text) == text
    assert pp.status()["catalogue_seen"] is False


def test_the_examples_carry_the_hubs_figures(seen):
    out = pp.fill(build_system_prompt(currency="USD"), 100)
    assert "Our Cassock Set is $195" in out and "Our Cassock Set is $210" not in out
    assert "$90: the Mitre at $55, the Cincture Rope at $20 and the Skull Cap at" in " ".join(out.split())
    assert "the Skull Cap at $15" in " ".join(out.split())
    assert "200pcs at KES 400, or 500pcs at KES 1,000" in " ".join(out.split())
    assert "the glass ones KES 100" in " ".join(out.split())
    assert "gold piping — is KES 14,000" in out
    assert "That's our Cassock Set — 19,500." in out
    assert "6 trays, $1,080" in out and "2 Silver Trays, $360 total" in out
    assert "is ZMW 900" in out
    # what is not a product price is untouched
    assert "that is $250, not $25,000" in out
    assert "mostly KES 350 within Kenya" in pp.fill(build_system_prompt(currency="KES"), 100)


def test_a_price_change_on_the_hub_reaches_every_example(seen):
    changed = [dict(r, price=20000, prices={"KES": 20000}) if r["slug"] == "silver-communion-tray" else r
               for r in HUB]
    pp.remember(changed)
    out = " ".join(pp.fill(build_system_prompt(currency="USD"), 100).split())
    assert "Silver Communion Tray is $200" in out and "6 trays, $1,200" in out
    assert "2 Silver Trays, $400 total" in out and "Silver Communion Tray ni KES 20,000" in out
    assert "$180" not in out


def test_a_product_the_hub_does_not_carry_leaves_its_sentence_whole(monkeypatch):
    monkeypatch.setattr(pp, "_PRICES", {"by_slug": {}, "mark": None})
    pp.remember([r for r in HUB if r["slug"] != "skull-cap"])
    out = " ".join(pp.fill(build_system_prompt(currency="USD"), 100).split())
    # the three-piece sum is not half-updated
    assert "$100: the Mitre at $60, the Cincture Rope at $20 and the Skull Cap at $20" in out
    st = pp.status()
    assert st["as_written"] >= 1 and st["from_hub"] + st["as_written"] == st["examples"]


def test_the_turn_and_the_catalogue_reader_are_wired():
    from app.agent import runtime
    from app.services import messaging
    assert "_pp.fill(system, settings.usd_kes_rate)" in inspect.getsource(runtime.run_turn)
    assert "_pp_hub.remember(_hub_cat)" in inspect.getsource(messaging.catalog_items)
