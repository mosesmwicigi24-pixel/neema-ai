"""The cope-set post answered as the $15 Bib (owner, 2026-10-21).

A Facebook post showed a bishop's cope over a purple cassock with a stole and
a cincture belt. Its caption opened "There is something beautiful about a
well-dressed minister of God! … handcrafted clergy vestments …" and only
after its first 200 characters listed "Copes, Cassocks, Stoles, and complete
Ordination Vestments". Every comment reply for days called the piece "our
Bib — the clergy bib with a collar insert slot … at $15".

Three faults, each pinned here against the live catalogue snapshot:
  1. identification read the post's 200-char inbox TITLE, never the whole
     caption the context already carried — the product words came later;
  2. a name/alias was "in" the caption by plain substring: the Bib's alias
     "clergy vest" matched inside "clergy vestments", stamped "caption" at
     0.95 — trusted to price a reply — and kept for thirty days;
  3. the hub's "Cope — Complete Set" does not list its contents ("supplied as
     a complete coordinated set"), so the set rule could not see that a
     caption listing copes, cassocks and stoles as complete vestments is it.
And a record made by the old rules is now stale: the next comment re-reads
the post and the cope set replaces the Bib.
"""
import asyncio
import inspect
import json

import app.main  # noqa: F401 — registers all SQLAlchemy models
from app.agent import runtime as rt
from app.services import post_catalog as pc

CATALOG = json.load(open(__file__.rsplit("/", 1)[0] + "/fixtures/catalog_snapshot_2026_10_05.json",
                         encoding="utf-8"))

CAPTION = (
    "There is something beautiful about a well-dressed minister of God!\n"
    "At Bethany House, we make beautiful, handcrafted clergy vestments that bring out "
    "dignity, elegance, and excellence in ministry.\n"
    "From our beautifully designed Copes, Cassocks, Stoles, and complete Ordination "
    "Vestments, we make every piece with great attention to detail.\n"
    "We custom-make and deliver to ALL PARTS OF KENYA AND WORLDWIDE! \U0001F30D\n"
    "\U0001F4DE Order today: 0785 490805 / +254 727 891989\n"
    "#BethanyHouse #ClergyVestments #bishopvestments #fyp #foryoupage")
# What fetch_post_context hands the reply engine: the title cut at 200
# characters, the caption whole.
PCTX = {"post_id": "p1", "title": CAPTION[:200], "caption": CAPTION, "thumb": ""}


def _resolve(pctx):
    return asyncio.run(pc.resolve_post(None, pctx, CATALOG))


def test_the_title_stops_before_the_product_words():
    assert "Copes" not in PCTX["title"] and "clergy vestments" in PCTX["title"]


def test_a_name_inside_a_longer_word_is_not_a_match():
    assert not pc.words_in("clergy vest", "handcrafted clergy vestments")
    assert not pc.words_in("cope", "copenhagen")
    assert pc.words_in("cope set", "our cope sets are ready")
    assert pc.words_in("rabat", "a white clergy rabat.")
    assert pc.words_in("clergy vest", "a black clergy vest, made to measure")


def test_the_opening_line_alone_names_no_product():
    # The Bib's alias "clergy vest" no longer hides inside "clergy vestments".
    assert pc.product_from_caption(PCTX["title"], CATALOG) is None
    assert rt._hub_caption_match(CATALOG, PCTX["title"]) is None
    assert _resolve({"title": PCTX["title"], "thumb": ""}) is None


def test_the_cope_post_is_the_cope_set_never_the_bib():
    hit = _resolve(PCTX)
    assert hit is not None
    assert hit["name"] == "Cope — Complete Set"
    assert hit["price"] == 45000.0
    assert hit.get("set") is True
    assert hit["_identity_source"] == "caption"


def test_a_set_that_does_not_list_its_contents_is_its_garment_s_set():
    cope_set = next(p for p in CATALOG if p["name"] == "Cope — Complete Set")
    assert pc.set_components(cope_set, CATALOG) == []
    assert pc.set_head_kind(cope_set) == "cope"
    assert pc.set_head_kind(next(p for p in CATALOG if p["name"] == "Cassock Set")) == "cassock"
    assert pc.set_head_kind(next(p for p in CATALOG if p["name"] == "Bib")) == ""


def test_a_listed_cassock_outfit_stays_the_cassock_set():
    cap = "Complete cassock set: cassock, stole, belt, straight collar shirt and a 12 inch clergy collar."
    hit = pc.product_set_from_caption(cap, CATALOG)
    assert hit is not None and hit["name"] == "Cassock Set"


def test_a_plain_range_listing_names_no_set():
    # No set cue: a listing of what the shop makes is not one outfit.
    assert pc.product_set_from_caption("We have copes, cassocks and stoles in stock.", CATALOG) is None


def test_the_old_bib_record_is_stale_and_the_cope_set_record_is_not():
    bib = {"name": "Bib", "slug": "bib", "source": "caption", "confidence": 0.95}
    cope = {"name": "Cope — Complete Set", "slug": "cope-complete-set",
            "source": "caption", "confidence": 0.95}
    assert pc.caption_record_stale(bib, CAPTION, CATALOG)
    assert not pc.caption_record_stale(cope, CAPTION, CATALOG)


def test_identification_reads_the_whole_caption_everywhere():
    assert pc.post_text(PCTX) == CAPTION
    assert pc.post_text({"title": "Cassock Set"}) == "Cassock Set"
    assert "post_text(pctx)" in inspect.getsource(pc.resolve_post)
    ident = inspect.getsource(rt._post_identity)
    assert "caption_record_stale(known, post_caption(pctx), _cat)" in ident
    assert 'pctx.get("title")' not in ident
    resolver = inspect.getsource(rt._resolve_post_product)
    assert "title = post_caption(post_ctx)" in resolver


def test_the_reply_model_is_shown_the_whole_caption_not_the_title():
    src = inspect.getsource(rt.run_turn)
    assert "_post_words = post_caption(pctx)" in src
    assert "line += f' \"{pctx[\"title\"]}\"'" not in src


def test_the_post_photo_is_read_by_the_main_model_and_knows_sets():
    from app.core.config import settings
    src = inspect.getsource(pc.product_from_vision)
    assert "settings.tier2_model_vision or settings.tier2_model" in src
    assert "tier2_model_light" not in src
    assert "is ONE item when the list has that set" in src
    assert settings.tier2_model_vision == "" or isinstance(settings.tier2_model_vision, str)
