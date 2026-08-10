"""The brevity contract — lessons from the Tally communion-tray thread.

A live Messenger thread (2026-08-10) read like a brochure answering a text
message. Tally typed one-line requests; Neema replied in 60–120 words:
 1. Three trays listed, "40 cups free" repeated on EVERY line — the prompt
    itself mandated it ("say it each time you quote a tray").
 2. Every cart update re-described every item, features re-attached
    ("(stackable, each with 40 cups free)"), then a two-clause question
    ("Would you like extra cups beyond those 160, or is this set enough for
    your congregation?").
 3. A one-word correction ("I mean 2 alluminum tray with lid") was echoed
    back as the full order plus "Shall I update your cart to that — …?".
 4. "What is your recommendation?" earned a paragraph weighing both options
    instead of a pick.
Long replies read as machine, bury the answer, and bill output tokens — the
dearest tokens — for padding. These tests pin the contract that ends it.
"""
from app.agent.prompt import build_system_prompt


def _flat(**kw) -> str:
    kw.setdefault("country_iso", "KE")
    kw.setdefault("currency", "KES")
    return " ".join(build_system_prompt(**kw).split())


# ── the contract exists, and it outranks habit on every channel ──────────────

def test_style_is_a_named_brevity_contract():
    flat = _flat()
    assert "STYLE — THE BREVITY CONTRACT" in flat
    assert "1–3 short sentences, roughly 40 words" in flat
    # and the precedence ladder points at it, so channel habits can't bury it
    assert "BREVITY CONTRACT (STYLE)" in flat


def test_contract_is_fleet_wide_not_a_kenya_special():
    """The contract lives in the shared rules block — every market bucket
    (web USD, Zambia ZMW, WhatsApp KES) must carry the same words."""
    for p in (_flat(), _flat(country_iso="", currency="USD"),
              _flat(country_iso="ZM", currency="ZMW")):
        assert "STYLE — THE BREVITY CONTRACT" in p
        assert "A SHARED FACT IS SAID ONCE" in p


# ── 1: the per-line repetition mandate is dead ───────────────────────────────

def test_tray_cups_fact_is_said_once_not_each_time():
    flat = _flat()
    assert "say it each time" not in flat                 # the old mandate
    assert "Sell with that fact ONCE" in flat
    assert "ONE shared line after the list covers them all" in flat
    assert "never repeated per line" in flat
    assert "never re-attach it to later quotes, cart lines or totals" in flat
    # the trade facts themselves survive — free cups, extras charged, stacking
    assert "40 plastic cups included, FREE" in flat
    assert "each tray comes with its 40 cups free" in flat
    assert "Charge only for EXTRA cups" in flat


def test_shared_facts_are_said_once_everywhere():
    flat = _flat()
    assert "A SHARED FACT IS SAID ONCE" in flat
    assert "say it once for the whole group" in flat


# ── 2: lists and cart updates have a lean shape ──────────────────────────────

def test_lists_are_one_line_per_item():
    flat = _flat()
    assert "LISTS: one line per item — name, price, at most ONE differentiator" in flat
    assert "Whatever the lines share goes in one line after the list" in flat


def test_cart_changes_show_the_change_not_the_catalogue():
    flat = _flat()
    assert "CART CHANGES: the line(s) that changed + the new total" in flat
    assert "Re-describe nothing" in flat
    # and the update_cart working rule points at the same shape
    assert "the CART CHANGES shape" in flat


def test_the_one_question_has_no_either_or_tail():
    flat = _flat()
    assert "never an either/or tail" in flat
    assert "TWO questions wearing one question mark" in flat
    assert "end the message at the first one" in flat


# ── 3: a correction is applied in a sentence, not echoed as the order ────────

def test_corrections_are_applied_not_echoed():
    flat = _flat()
    assert "A CUSTOMER CORRECTION" in flat
    assert "never echo the whole order back" in flat
    assert "never ask permission to update the cart" in flat
    # ambiguity still earns one brief confirm — dropping items on a guess is worse
    assert "only when their words truly allow two readings" in flat


# ── 4: a recommendation question gets a pick, not an essay ───────────────────

def test_recommendation_is_a_pick_plus_one_reason():
    flat = _flat()
    assert "ASKED TO RECOMMEND, RECOMMEND: your pick + ONE reason" in flat
    assert "Never a paragraph weighing every option" in flat
