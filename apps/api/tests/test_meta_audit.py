"""The prompt meta-audit's fixes, pinned so the contradictions never grow back.

A deep-tissue consistency audit of the prompt + tool descriptions found the
remaining risk was DRIFT: rules added in different rounds pointing at different
tools (refunds), promising speed an async tool doesn't have (ready-made
confirms), or saying the same thing twice with different verdicts (two mood
taxonomies). Each test pins the exact collision its fix removed.
"""
import asyncio

import app.main  # noqa: F401 — registers all SQLAlchemy models
from app.agent.prompt import build_system_prompt


def _p() -> str:
    return build_system_prompt(country_iso="KE", currency="KES")


def _flat() -> str:
    return " ".join(_p().split())


# ── F1: refunds have exactly one door ────────────────────────────────────────

def test_refunds_route_through_raise_complaint_only():
    flat = _flat()
    assert "A REFUND" in flat and "`raise_complaint`" in flat
    # The old line sent refunds to handoff_to_human — both rules could fire.
    assert "a refund, or something you cannot do, `handoff_to_human`" not in flat


def test_handoff_tool_no_longer_claims_refunds():
    from app.agent.tools import TOOLS
    desc = next(t["description"] for t in TOOLS if t["name"] == "handoff_to_human")
    assert "OUTSIDE any complaint" in desc
    assert "REFUND" in desc and "raise_complaint" in desc
    assert "(a refund, a discount" not in desc      # refund out of the handoff list


# ── F2: ready-made never stalls the sale on the team ─────────────────────────

def test_ready_made_continues_the_sale_while_the_team_checks():
    flat = _flat()
    assert "CONTINUE the sale meanwhile" in flat
    assert "never idles waiting" in flat
    assert "never promise same-day collection before the team has confirmed" in flat
    # The misleading promise of a synchronous confirm is gone.
    assert "quickly confirms a ready piece" not in flat


# ── F3: one mood taxonomy, not two ───────────────────────────────────────────

def test_single_merged_mood_section():
    p = _p()
    assert "READ THE ROOM — READ THE MOOD, THEN CHOOSE THE MOVE" in p
    assert p.count("THEN CHOOSE THE MOVE") == 1
    flat = _flat()
    # The merged verdict for anger is the complaint protocol, not a freelance
    # "fix or escalate".
    assert "UPSET or DISAPPOINTED" in flat and "STOP SELLING ENTIRELY" in flat
    assert "apologise once sincerely, fix or escalate" not in flat


# ── F4: the question-count exception matches the examples ────────────────────

def test_first_contact_no_longer_pairs_a_location_question():
    """The two-question first-contact exception existed to pair colour with
    city/country. Owner rule (2026-08-10): no location questions up front at
    all — so the exception is gone, ONE question stands everywhere."""
    flat = _flat()
    assert "First contact is the ONLY exception" not in flat
    assert "item or colour question with their city/country" not in flat
    assert "ask EXACTLY ONE question" in flat


# ── F7/F8: speed rules have explicit winners ─────────────────────────────────

def test_hurried_customers_get_price_before_cards():
    flat = _flat()
    assert "the price in TEXT first; product cards can follow" in flat
    assert "IN A HURRY gets the price in text first" in flat   # show-then-tell side


def test_close_immediately_means_the_two_step_ask():
    assert ("move to the payment ask of the two-step close in that SAME message"
            in _flat())


# ── F9/F10: precedence exists; the redundant bullet is gone ──────────────────

def test_precedence_hierarchy_is_stated():
    p = _p()
    assert "WHEN RULES COLLIDE — precedence, top wins" in p
    flat = _flat()
    assert flat.index("Money & truth safety") < flat.index("A complaint or grief")


def test_redundant_reask_bullet_removed_but_discipline_kept():
    flat = _flat()
    assert "Never re-ask something they've already answered" not in flat
    assert "SLOT CHECK" in flat                          # the mechanism remains
    assert "NEVER ask for something already said" in flat   # CONTINUITY remains


# ── F5: quotations render per channel ────────────────────────────────────────

def test_quotation_is_plain_text_off_whatsapp(monkeypatch):
    from app.agent import tools

    async def _cart(db, key, channel):
        return {"items": [{"name": "Clergy Cassock", "qty": 1, "unit_price": 7000}]}

    async def _display(cart, ctx):
        return cart["items"], 7000
    monkeypatch.setattr(tools.cartmod, "get_cart", _cart)
    monkeypatch.setattr(tools, "_cart_display", _display)

    wa = asyncio.run(tools._prepare_quotation({}, tools.ToolContext(
        db=None, redis=None, wa_id="254712345678", channel="whatsapp")))
    assert "*QUOTATION" in wa["quotation"] and "*TOTAL" in wa["quotation"]

    ms = asyncio.run(tools._prepare_quotation({}, tools.ToolContext(
        db=None, redis=None, wa_id="psid1", channel="messenger")))
    assert "*" not in ms["quotation"]               # Messenger shows literal stars


# ── F6: the stale Messenger-names claim is gone ──────────────────────────────

def test_capture_contact_no_longer_denies_profile_names():
    from app.agent.tools import TOOLS
    desc = next(t["description"] for t in TOOLS if t["name"] == "capture_contact")
    assert "CANNOT read Messenger names" not in desc
    assert "NEVER re-ask a name you can see" in desc


# ── F9 (comments) + F11: public square manners ───────────────────────────────

def test_public_comments_skip_the_greeting_ritual():
    from app.agent.runtime import _public_comment_addendum
    a = _public_comment_addendum("KES")
    assert "No greeting ritual" in a
    assert "first line is the ANSWER" in a


def test_neutral_ack_pool_carries_no_cheerful_emoji():
    from app.agent.runtime import _NEUTRAL_ACK_POOL
    for line in _NEUTRAL_ACK_POOL:
        assert "💛" not in line                     # may land on a complaint
