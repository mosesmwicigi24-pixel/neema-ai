"""The post ladder against the live catalogue, systematically (owner, 2026-10-21:
"widen the look … be super intelligent and intentional").

The cope post sold as the Bib was one instance of a family of faults in how a
caption names a product. These tests sweep the whole catalogue snapshot and a
battery of the captions Bethany House actually posts, so a change that brings
any of the family back fails here:
  - a generic brand or range caption names NO product (the photo decides);
  - a caption naming one product names THAT product;
  - an outfit caption names the hub's set;
  - "Our <name> is now available" never names a DIFFERENT product (the owner's
    synonym table aside: "pendant" IS the Pectoral Cross);
  - a product's own hub description, posted as a caption, names a different
    product only in the known catalogue-data cases listed below.
"""
import json

import pytest

import app.main  # noqa: F401 — registers all SQLAlchemy models
from app.agent import runtime as rt
from app.services import post_catalog as pc

CATALOG = json.load(open(__file__.rsplit("/", 1)[0] + "/fixtures/catalog_snapshot_2026_10_05.json",
                         encoding="utf-8"))


def _name(caption):
    hit, _src = pc.caption_identity(caption, CATALOG)
    return hit.get("name") if hit else None


GENERIC = [
    "There is something beautiful about a well-dressed minister of God! We make handcrafted clergy vestments.",
    "Bethany House — clergy wear, church supplies and Bibles. Visit us in Nairobi or order online.",
    "Dress for your calling. Clergy robes, cassocks and stoles made to measure.",
    "We have restocked! Clergy shirts, collars, stoles and cassocks now available.",
    "Ordination season is here. Book your ordination vestments early!",
    "Happy Sunday from all of us at Bethany House. God bless you.",
    "New arrivals in store this week. Come and see!",
    "Quality church regalia for bishops, pastors and reverends. Order today.",
    "Mavazi ya wachungaji na maaskofu yanapatikana. Agiza leo!",
    "GIVEAWAY! Comment and share to win a clergy gift from Bethany House.",
    "Bishops cape in purple for ordinations.",        # the single cope or the set: the photo says
]


@pytest.mark.parametrize("caption", GENERIC)
def test_a_generic_caption_names_no_product(caption):
    assert _name(caption) is None


@pytest.mark.parametrize("caption,name", [
    ("Our Purple Red Cope — made to order for bishops.", "Purple Red Cope"),
    ("Double sided stole in two colours, reversible.", "Double sided stole"),
    ("Clergy bib (rabat) now available in black.", "Bib"),
    ("The NIV Application Bible — a pastor's companion.", "NIV APPLICATION BIBLE"),
    ("Silver Communion Tray, holds 40 cups.", "Silver Communion Tray"),
    ("Cincture rope with tassels for altar servers.", "Cincture Rope"),
    ("Surplice, white, made to measure.", "Surplice"),
])
def test_a_caption_naming_one_product_names_that_product(caption, name):
    assert _name(caption) == name


@pytest.mark.parametrize("caption,name", [
    ("Complete cope set: cope, cassock, stole and cincture belt. Ordination ready.", "Cope — Complete Set"),
    ("Complete cassock set: cassock, shirt, collar, cincture belt and stole.", "Cassock Set"),
    ("Congratulations Bishop Mary, robed in her Classic Princes Cassock Set!", "Classic Princes Cassock Set"),
    ("Complete five-piece ladies' cassock set — cassock, shirt, collar, stole and cincture belt.",
     "Classic Princes Cassock Set"),
])
def test_an_outfit_caption_names_the_hub_set(caption, name):
    assert _name(caption) == name


# The owner's synonym table makes these the same item (core/synonyms).
_SYNONYMS = {("Pendant", "Pectoral Cross")}


def _same(hit_name, hit, row):
    if hit_name == row["name"]:
        return True
    fam = (hit or {}).get("family") or []
    return row.get("slug") in fam or row["name"] in fam


def test_no_product_named_in_a_caption_is_sold_as_another():
    wrong = []
    for row in CATALOG:
        if not row.get("name"):
            continue
        hit, _ = pc.caption_identity(f"Our {row['name']} is now available. Order today!", CATALOG)
        if hit and not _same(hit.get("name"), hit, row) and (row["name"], hit["name"]) not in _SYNONYMS:
            wrong.append((row["name"], hit["name"]))
    assert wrong == []


# Hub descriptions that name ANOTHER product in their own words — catalogue
# data, not the ladder ("Large bell … the large altar bell"). A new entry here
# is a regression; fix the ladder, or the hub's description.
_KNOWN_DESCRIPTION_CASES = {
    "Small bread tray containers(SIZE 10)", "Pendant", "Episcopal Cross",
    "Aluminium 4-Stack Communion Set — 160 Cups", "Ring", "NKJV Giant Print",
    "Round Collar Shirt", "Anointing horn",
}


def test_a_product_description_as_a_caption_never_names_a_new_wrong_product():
    wrong = set()
    for row in CATALOG:
        desc = (row.get("description") or "").strip()
        if not row.get("name") or not desc:
            continue
        hit, _ = pc.caption_identity(desc, CATALOG)
        if hit and not _same(hit.get("name"), hit, row) and not (hit.get("bundle")):
            wrong.add(row["name"])
    assert wrong <= _KNOWN_DESCRIPTION_CASES, sorted(wrong - _KNOWN_DESCRIPTION_CASES)


def test_an_alias_never_claims_another_product_s_name():
    distinct = pc.distinctive_aliases(CATALOG)
    by_name = {p["name"]: p for p in CATALOG if p.get("name")}
    assert "altar wine" not in distinct[id(by_name["Devai"])]
    assert "bishopric ring" not in distinct[id(by_name["Ring"])]
    assert "biblia" not in distinct[id(by_name["NIV BIBLE"])]
    assert "rabat" in distinct[id(by_name["Bib"])]


def test_the_more_specific_name_wins_when_the_caption_covers_it():
    assert rt._hub_caption_match(
        CATALOG, "Bishop's pectoral cross in a bright gold finish")["name"] == "Pectoral Cross — Gold Finish"
