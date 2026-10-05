"""Voice note → sale: the catalogue search finds what customers SAY (2026-10-05).

The owner: "Make sure that you can sell when the transcribing have valuable
information that points to our products." Measured before this change on
the live catalogue snapshot, the REAL search_catalog found the right stocked
product for only 57.6% of the items customers named in their own words
(45.7% as a confident, non-partial row): "kasoki", "stola", "shati ya kola",
"mishumaa", "plateau de communion", "bandeja dorada", "étole", "vasitos",
"tots" and "a train for the sacrament" all came back empty. After: 100%
found, ≥ 95% confident, and nothing we do not sell is force-matched.

The set (tests/voice_to_sale_cases.py) is real production voice notes and
typed asks, paraphrased and anonymised. The thresholds below are the
measured after-state; a change that lowers them is a lost sale.

Repo fake style (no DB): the real tools._search_catalog over the snapshot.
"""
import asyncio
import json
import os
import re

import pytest

import app.main  # noqa: F401 — registers all SQLAlchemy models
from app.agent import tools
from app.agent.tools import ToolContext, _search_catalog
from app.core import vernacular
from app.services import promotions

import voice_to_sale_cases as V

SNAPSHOT = os.path.join(os.path.dirname(__file__), "fixtures", "catalog_snapshot_2026_10_05.json")
CATALOG = json.load(open(SNAPSHOT, encoding="utf-8"))

# The measured after-state (2026-10-05); before: said 57.6% / 45.7%.
MIN_SAID_FOUND = 1.00
MIN_SAID_CONFIDENT = 0.95
MIN_ALL_FOUND = 0.99
MIN_QUERY_CONFIDENT = 1.00


@pytest.fixture
def shelf(monkeypatch):
    async def fake_catalog(db, redis):
        return CATALOG

    async def no_campaign(redis):
        return None
    monkeypatch.setattr(tools.svc, "catalog_items", fake_catalog)
    monkeypatch.setattr(promotions, "campaign_now", no_campaign)


def _search(q: str, currency: str = "KES") -> dict:
    ctx = ToolContext(db=None, redis=None, wa_id="EVAL", currency=currency, read_only=True)
    return asyncio.run(_search_catalog({"query": q}, ctx))


def test_the_set_is_big_enough_and_anonymised():
    assert len(V.CASES) >= 40
    langs = {c[1] for c in V.CASES}
    assert {"en", "sw", "fr"} <= langs and ({"es", "pt"} & langs)
    assert sum(len(c[3]) > 1 for c in V.CASES) >= 15          # multi-item notes
    text = " ".join(c[2] for c in V.CASES)
    assert not re.search(r"\+?\d{9,}", text)                   # no phone numbers


def test_recall_over_the_labelled_voice_notes(shelf):
    tally: dict = {}
    misses = []
    for cid, i, form, words, expect in V.items():
        rows = _search(words)["results"]
        hit = [r for r in rows if re.search(expect, r["name"] or "")]
        confident = [r for r in hit if r.get("match") != "partial"]
        n, h, c = tally.get(form, (0, 0, 0))
        tally[form] = (n + 1, h + bool(hit), c + bool(confident))
        if not hit:
            misses.append((form, cid, words, [r["name"] for r in rows][:4]))
    said_n, said_h, said_c = tally["said"]
    q_n, _q_h, q_c = tally["query"]
    all_n = sum(v[0] for v in tally.values())
    all_h = sum(v[1] for v in tally.values())
    report = f"{tally} misses={misses}"
    assert said_h / said_n >= MIN_SAID_FOUND, report
    assert said_c / said_n >= MIN_SAID_CONFIDENT, report
    assert q_c / q_n >= MIN_QUERY_CONFIDENT, report
    assert all_h / all_n >= MIN_ALL_FOUND, report


@pytest.mark.parametrize("said,why", V.NOT_STOCKED)
def test_what_we_do_not_sell_is_never_force_matched(shelf, said, why):
    out = _search(said)
    confident = [r["name"] for r in out["results"] if r.get("match") != "partial"]
    assert confident == [], f"{said!r} ({why}) was matched to {confident}"


# ── the words, one by one ────────────────────────────────────────────────────

@pytest.mark.parametrize("said, first", [
    ("kasoki", "Cassock"),
    ("stola", "Stole"),
    ("shati ya kola", "Collar Shirt"),
    ("mishumaa", "Candles"),
    ("plateau de pain", "Bread"),
    ("bandeja dorada", "Golden Communion Tray"),
    ("étole", "Stole"),
    ("calice", "Chalice"),
    ("vasitos de plástico", "Plastic Communion Cups"),
    ("kisinia cha kubebea vikombe", "tray"),
    ("siniya ya kubebea mikate", "bread tray"),
    ("kikombe kubwa ya mchungaji", "Chalice"),
    ("cheni ya msalaba", "Pectoral Cross"),
    ("train for a sacrament", "tray"),
])
def test_a_customers_word_finds_the_kind_we_stock(shelf, said, first):
    rows = _search(said)["results"]
    assert rows, said
    assert any(first.lower() in (r["name"] or "").lower() for r in rows[:3]), \
        (said, [r["name"] for r in rows])
    assert all(r.get("match") != "partial" for r in rows), said


def test_the_carrier_is_not_the_cups(shelf):
    """'I don't want cups — the thing that CARRIES the cups': the trays,
    never the cups themselves (the live 2026-09-29 Swahili note)."""
    rows = _search("kisinia cha kubebea vikombe")["results"]
    assert rows and not any(re.search(V.SMALL_CUPS, r["name"]) for r in rows)


def test_the_small_cup_and_the_chalice_stay_apart(shelf):
    """vikombe (the small cups) never lead with a chalice; the pastor's big
    cup is a chalice and never a pack of small cups."""
    small = _search("vikombe")["results"]
    assert small and all(re.search(V.SMALL_CUPS, r["name"]) for r in small)
    big = _search("kikombe kubwa")["results"]
    assert big and all("Chalice" in r["name"] for r in big)


def test_a_misheard_word_is_named_back_not_presumed(shelf):
    out = _search("sprinkle")
    assert out["results"] and out["results"][0]["name"].startswith("Sprinkler")
    assert "spelling" in out and "sprinkle" in out["spelling"]


def test_ordinary_words_are_not_bent_onto_goods(shelf):
    """The near-miss reader only corrects towards words in hub product
    NAMES: an ordinary word close to an alias stays itself."""
    cat = CATALOG
    toks = tools._search_tokens(vernacular.to_hub("professional wristband super embroidery"))
    assert tools._closest_words(toks, cat) == {}


# ── the vernacular table itself ──────────────────────────────────────────────

@pytest.mark.parametrize("said, hub", [
    ("nataka kasoki na stola", "nataka cassock na stole"),
    ("plateau de communion", "communion tray"),
    ("Le plateau de pain", "le bread tray"),
    ("bandeja de las copas", "communion tray"),
    ("chemise pastorale", "clergy shirt"),
    ("croix pectorale", "pectoral cross"),
    ("a train for the sacrament", "a communion tray"),
    ("suti ya kanisa", "suti ya kanisa"),            # we sell no suits: untouched
    ("a train to Mombasa", "a train to mombasa"),    # a train alone is never a tray
    ("tree", "tree"),
])
def test_to_hub(said, hub):
    assert vernacular.to_hub(said) == hub


def test_every_vernacular_target_is_a_kind_we_stock():
    """No entry may point at a word the catalogue does not carry — the table
    guides to goods, it never invents them."""
    words = set()
    for p in CATALOG:
        words |= tools._search_words(" ".join([p.get("name", ""), p.get("category", ""),
                                               " ".join(p.get("aliases") or [])]))
    for _pat, hub in (*vernacular.PHRASES, *vernacular.WORDS):
        toks = tools._search_words(hub)
        assert toks and toks <= words, (hub, toks - words)


def test_the_spoken_words_all_find_goods(shelf):
    """Every Swahili / French word taught to the transcriber finds a row."""
    for w in (*vernacular.SPOKEN_SWAHILI, *vernacular.SPOKEN_FRENCH):
        assert _search(w)["results"], w
