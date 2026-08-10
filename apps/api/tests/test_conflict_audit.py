"""Fixes from the 2026-08-10 client-handling audit: the country-hedge that
outlived its prompt ban, the rapid-echo stall, the over-cap line that stopped
selling, and the instruction conflicts named and resolved."""
import asyncio

import app.main  # noqa: F401
from app.agent import runtime as rt
from app.agent.prompt import build_system_prompt
from app.services import meta_send


# ── the country hedge dies at the send boundary, like links ──────────────────

def test_country_hedge_is_stripped_from_public_replies():
    """Live: '…are you in Kenya? I can quote you in KES' kept appearing AFTER
    the prompt ban — the model mirrors its own earlier replies in history, so
    the habit outlives the rule. Enforced at the sanitizer now."""
    out, removed = meta_send.sanitize_public_comment(
        "The Refiller is $20 — the handy squeeze bottle. Cups are sold "
        "separately - how many would you like, and are you in Kenya? I can "
        "quote you in KES.")
    assert "are you in Kenya" not in out
    assert "The Refiller is $20" in out
    assert any("are you" in r.lower() for r in removed)


def test_stating_our_own_location_is_untouched():
    good = ("We're based in Nairobi, Kenya — that's our workshop and shop — "
            "but we ship worldwide via DHL, so wherever you are, we deliver.")
    out, removed = meta_send.sanitize_public_comment(good)
    assert out == good and removed == []


def test_hedge_and_link_are_both_removed():
    out, removed = meta_send.sanitize_public_comment(
        "It is $70. Which country are you writing from?\n"
        "Order here 👉 https://bethanyhouse.co.ke/product/x")
    assert "country" not in out.lower() and "http" not in out
    assert "It is $70." in out
    assert len(removed) == 2


# ── the rapid echo guard ─────────────────────────────────────────────────────

def _db_with_last_outbound(text):
    class _R:
        def scalar_one_or_none(self): return text

    class _DB:
        async def execute(self, q): return _R()
    return _DB()


def test_identical_reply_within_minutes_is_an_echo():
    """José got 'One moment — let me check on that for you.' three times in
    58 seconds. Identical text minutes apart is robotic; suppress it."""
    stall = "One moment — let me check on that for you."
    db = _db_with_last_outbound(stall)
    assert asyncio.run(rt._is_echo(db, "whatsapp", "254700", stall)) is True
    # Case/whitespace variants are still the same sentence.
    assert asyncio.run(rt._is_echo(db, "whatsapp", "254700",
                                   "  one MOMENT — let me check on that for you. ")) is True


def test_fresh_replies_and_empty_history_pass():
    db = _db_with_last_outbound("One moment — let me check on that for you.")
    assert asyncio.run(rt._is_echo(db, "messenger", "PSID",
                                   "The Aluminium Tray is $70 — how many?")) is False
    assert asyncio.run(rt._is_echo(_db_with_last_outbound(None),
                                   "whatsapp", "254700", "Karibu!")) is False
    # An empty composed reply must never be sent at all.
    assert asyncio.run(rt._is_echo(_db_with_last_outbound(None),
                                   "whatsapp", "254700", "  ")) is True


# ── the over-cap line sells when the post identity carries a price ───────────

def test_over_cap_line_quotes_the_price_and_pulls():
    out = rt._comment_public_reply("", dm_sent=False, name_tag=" Grace", seed="g",
                                   product_known=True, product_name="Refiller",
                                   price_text="$20")
    assert "$20" in out and "the Refiller" in out
    assert "?" in out                              # a pull question, not a signpost
    assert "send us a message" not in out.lower()
    assert "dm us" not in out.lower()


def test_over_cap_without_a_price_keeps_the_old_warm_line():
    out = rt._comment_public_reply("", dm_sent=False, name_tag=" Grace", seed="g",
                                   product_known=True, product_name="Refiller")
    assert "Refiller" in out                       # named, warm, still link-free


# ── the instruction conflicts, resolved and pinned ───────────────────────────

def test_upsell_rule_names_its_two_exceptions():
    p = " ".join(build_system_prompt(currency="KES").split())
    assert "Exactly two named exceptions" in p
    assert "visible in THEIR OWN photo" in p
    assert "availability check runs" in p


def test_ambiguous_photo_quotes_both_never_asks_which():
    p = " ".join(build_system_prompt(currency="KES").split())
    assert "quote BOTH prices in one line" in p
    assert 'never "which item did you mean?"' in p


def test_distance_is_framed_as_reach():
    p = " ".join(build_system_prompt(currency="KES").split())
    assert "FRAME DISTANCE AS REACH" in p
    assert "never open with what we lack" in p
