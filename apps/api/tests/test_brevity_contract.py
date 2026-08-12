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
    assert "it belongs in the LEAD-IN line that introduces them" in flat
    assert "so the lines below carry only name and price" in flat
    assert "never re-attach it to later quotes, cart lines or totals" in flat
    # the trade facts themselves survive — free cups, extras charged, stacking
    assert "40 plastic cups included, FREE" in flat
    assert "We have several trays, each with 40 cups included:" in flat
    assert "Charge only for EXTRA cups" in flat


def test_shared_facts_are_said_once_everywhere():
    flat = _flat()
    assert "A SHARED FACT IS SAID ONCE" in flat
    assert "say it once for the whole group" in flat


# ── 2: lists and cart updates have a lean shape ──────────────────────────────

def test_lists_lead_with_the_shared_fact_then_name_and_price_only():
    """Owner's dictated shape (2026-08-12): 'we have several trays that come
    with forty cups. Aluminium tray, seventy dollars. Silver tray, one hundred
    and eighty…' — the shared fact introduces the list, the lines carry name +
    price and nothing else."""
    flat = _flat()
    assert "LISTS — THE LEAN SHAPE (owner's rule)" in flat
    assert "goes in the ONE short line that introduces them" in flat
    assert "each line is then NAME + PRICE and nothing else" in flat
    assert "Aluminium Tray – $70" in flat            # the worked example
    assert "When in doubt, leave it out" in flat
    # and the trays rule agrees — lead-in, not a trailing line
    assert "it belongs in the LEAD-IN line that introduces them" in flat


def test_the_same_fact_reworded_is_still_the_same_fact():
    """The Spanish thread leaked because capacity ('para 40 copas') and the
    free cups ('40 copas incluidas') were treated as two facts — so 40
    appeared four times in one message."""
    flat = _flat()
    assert "once means once in ANY wording" in flat
    assert "never a second time dressed as a different fact" in flat
    assert 'a capacity ("holds 40 cups") IS the included-cups fact in other words' in flat


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


# ── 5: the Messenger morning (2026-08-11) — the contract binds on EVERY
# platform. A Messenger DM opened with "Perfect! The Communion Full Set…
# Here's how to order: 1… 2… 3… 4…" — an ~85-word numbered manual where one
# question belonged. The lecture shape gets banned by name, and each channel
# addendum points at the contract so no channel can claim local custom. ──────

def test_ordering_process_is_walked_not_lectured():
    flat = _flat()
    assert "NEVER EXPLAIN HOW ORDERING WORKS" in flat
    assert 'No "Here\'s how to order:"' in flat
    assert "gets the first question, not the manual" in flat


def test_meta_and_web_addenda_bind_the_contract_by_name():
    import app.main  # noqa: F401 — registers models before runtime import
    from app.agent.runtime import _meta_addendum, _web_addendum
    for addendum in (_meta_addendum("USD"), _meta_addendum("KES"), _web_addendum()):
        assert "THE BREVITY CONTRACT (STYLE)" in addendum
        assert "no how-to-order lectures" in addendum
    # the old weak closer is gone — "short, precise and friendly" was losing
    assert "Keep replies short, precise" not in _meta_addendum("USD")


def test_comment_dm_continue_lines_stay_short():
    """The comment-DM is answer + order link + continue line stacked together —
    a long continue line turns every DM into an essay. Keep each under 50
    characters so the composite reads like a note, not a letter."""
    import app.main  # noqa: F401
    from app.agent.runtime import _DM_CONTINUE_POOL
    assert _DM_CONTINUE_POOL, "pool must not be empty"
    for line in _DM_CONTINUE_POOL:
        assert len(line) <= 50, f"DM continue line too long ({len(line)}): {line!r}"


# ── 6: deploys are verifiable — /health names the running commit ─────────────

def test_health_reports_the_built_git_sha(monkeypatch):
    """The box pulls :latest on a timer; before this field there was no way to
    ask WHICH commit it runs, so 'did the deploy land?' was guesswork."""
    import asyncio
    monkeypatch.setenv("GIT_SHA", "abc1234def")
    from app.routers.health import health
    out = asyncio.run(health())
    assert out == {"status": "ok", "version": "abc1234def"}
