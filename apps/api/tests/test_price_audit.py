"""The hub's two currencies must agree, and a per-piece price must never
become a pack.

2026-09-02: "How much for the cups only, plastic ones?" → "$10 for a pack of
50" → "Kshs pls" → "KES 10 per pack of 50". Both numbers came straight from
the hub row (KES 10, USD 10 — the per-cup price, and a hand-set dollar), and
the pack size came from a prompt example. 39 of 95 products had a USD row
that did not match their KES row, and nothing had looked.
"""
import pytest

from app.services import price_audit as pa

RATE = 100


def _p(name, kes, usd=None, category="Communion Items", desc="", variants=None):
    prices = {"KES": kes}
    if usd is not None:
        prices["USD"] = usd
    return {"name": name, "category": category, "description": desc,
            "price": kes, "price_kes": kes, "price_usd": usd, "prices": prices,
            "variants": variants or []}


# ── the currency gap ─────────────────────────────────────────────────────────

def test_the_cups_row_from_the_incident_is_flagged():
    g = pa.currency_gap(_p("Plastic Communion Cups", 10, 10), RATE)
    assert g and g["usd_expected"] == 0.1 and g["factor"] == 100.0


@pytest.mark.parametrize("name,kes,usd", [
    ("Straight Collar", 400, 10),                 # $10 floor on a $4 item
    ("Double Stacked Silver Tray Set", 36000, 600),   # $600 where 360 was right
    ("Red Apostolic Cassock", 21000, 170),        # UNDER-priced: leaves $40
])
def test_real_rows_from_the_audit_are_flagged(name, kes, usd):
    assert pa.currency_gap(_p(name, kes, usd), RATE) is not None


@pytest.mark.parametrize("kes,usd", [
    (500, 5), (19500, 200), (4500, 45), (2500, 25), (150, 1.5), (99, 1),
])
def test_rounding_drift_is_not_a_finding(kes, usd):
    # A round rate and whole-unit prices leave a shilling or two of noise.
    assert pa.currency_gap(_p("x", kes, usd), RATE) is None


def test_a_row_with_no_usd_is_consistent_by_construction():
    # The converter derives USD from KES when the hub carries none.
    assert pa.currency_gap(_p("x", 500), RATE) is None


def test_an_unpriced_row_is_someone_elses_problem():
    assert pa.currency_gap(_p("x", 0, 10), RATE) is None
    assert pa.currency_gap(_p("x", None, 10), RATE) is None


# ── per-piece pricing masquerading as a product price ────────────────────────

@pytest.mark.parametrize("name,kes", [
    ("Plastic Communion Cups", 10),
    ("Pre-Packed Communion Cups", 30),
    ("Host", 20),
])
def test_the_three_per_piece_rows_from_the_audit(name, kes):
    assert pa.looks_per_piece(_p(name, kes))


@pytest.mark.parametrize("name,kes", [
    ("Disposable Communion Cups (250 pcs)", 2500),      # quantity in the name = a pack
    ("Communion Hosts — 1,000 pieces", 1500),
    ("Aluminium 4-Stack Communion Set — 160 Cups", 28000),
    ("Plastic Communion Cups", 500),                     # a real pack price
    ("Brass Chalice Cup", 40000),                        # a cup, but not a pack good price
    ("Straight Collar", 10),                             # cheap, but not a pack good
])
def test_packs_and_non_pack_goods_are_left_alone(name, kes):
    assert not pa.looks_per_piece(_p(name, kes))


# ── the report ───────────────────────────────────────────────────────────────

def test_the_report_names_the_worst_row_first_and_counts_the_rest():
    cat = [_p("Plastic Communion Cups", 10, 10),
           _p("Double Stacked Silver Tray Set", 36000, 600),
           _p("Cassock Set", 19500, 200), _p("Host", 20, 0.2)]
    r = pa.audit(cat, RATE)
    assert r["checked"] == 4
    assert [g["name"] for g in r["currency_gaps"]] == ["Double Stacked Silver Tray Set",
                                                        "Plastic Communion Cups"]
    assert [x["name"] for x in r["per_piece"]] == ["Plastic Communion Cups", "Host"]


def test_variants_are_audited_like_products():
    v = {"name": "L", "sku": "C-L", "price_kes": 5000, "prices": {"KES": 5000, "USD": 120}}
    r = pa.audit([_p("Cassock", 5000, 50, variants=[v])], RATE)
    assert any("— L" in g["name"] for g in r["currency_gaps"])


def test_a_clean_catalogue_says_nothing():
    r = pa.audit([_p("Cassock Set", 19500, 195), _p("Cups (50 pcs)", 500, 5)], RATE)
    assert r["currency_gaps"] == [] and r["per_piece"] == []
    assert pa.summary_line(r) == ""


def test_the_standup_line_is_actionable():
    line = pa.summary_line(pa.audit([_p("Plastic Communion Cups", 10, 10)], RATE))
    assert line.startswith("PRICES —")
    assert "Plastic Communion Cups" in line and "$10" in line and "$0.1" in line
    assert "per single piece" in line
    assert "Fix the hub rows" in line


# ── the guard in the catalogue search ────────────────────────────────────────

def test_search_catalog_labels_a_per_piece_row_and_forbids_inventing_a_pack():
    import inspect
    from app.agent import tools
    src = inspect.getsource(tools._search_catalog)
    assert "looks_per_piece" in src
    assert 'row["unit"] = "per piece"' in src
    # Adjacent string literals wrap across lines in the source; assert within one.
    assert "state a pack size or a pack price" in src


def test_the_prompt_no_longer_hardcodes_a_pack_price():
    from app.agent import prompt
    src = open(prompt.__file__, encoding="utf-8").read()
    assert "a 50-cup pack at" not in src
    assert "50-cup pack of plastic cups is" not in src
    # The rule wraps mid-sentence in the source; assert on a span within one line.
    assert "per-piece price into a pack" in src


def test_the_probe_is_in_the_daily_selfcheck():
    from app.services import selfcheck
    assert any(n == "price_consistency" for n, _ in selfcheck.PROBES)
