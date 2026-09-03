"""The instructions must agree with the truth of the conversation.

The prompt is shared by every channel, so an unconditional claim in it becomes a
lie on the channels where it doesn't hold. The clearest case: "You ALREADY know
their country from their phone number — never ask it." True on WhatsApp; false
on the website and on Messenger/Instagram, where there is no phone. On those
channels Neema was told she both knew their country AND must never ask for it —
so she could never place a visitor, and quoted a default currency to someone she
had no country for.

These tests pin the rule to what is actually known, and pin the mood/interest
guidance the sales flow depends on.
"""
from app.agent.prompt import build_system_prompt


def _known() -> str:                     # a WhatsApp customer: phone → country
    return build_system_prompt(country_iso="KE", currency="KES")


def _unknown() -> str:                   # a website visitor: no phone, no country
    return build_system_prompt(currency="USD")


# ── location: claim it only when we actually know it ─────────────────────────

def test_known_country_keeps_the_never_ask_rule():
    p = _known()
    assert "ALREADY know their country from their phone number" in p
    assert "never ask it" in p
    # The opener no longer asks a location at all (owner, 2026-08-10) — the
    # city surfaces when delivery is being arranged, not as small talk.
    assert "which town are you in" not in p


def test_unknown_country_reads_cues_instead_of_asking():
    """Owner rule (2026-08-10, from the live 'are you in Kenya?' miss): a
    location question up front makes the shop feel far away. Sell first,
    read cues, never interrogate."""
    p = _unknown()
    assert "do NOT know where this customer is" in p
    assert "never ASK" in p and "SELL FIRST" in p
    assert "CUES" in p
    assert 'NEVER ask "are you in Kenya?"' in p
    assert "quote USD confidently" in p
    # the old opener interrogation is gone, and the false claim stays absent
    assert "which city and country are you in" not in p
    assert "ALREADY know their country" not in p


def test_unknown_country_reprices_once_they_say_kenya():
    """A Kenyan on the website must end up on real KES prices, not a conversion."""
    p = _unknown()
    assert 'currency="KES"' in p
    assert "never a conversion" in p


def test_no_unrendered_placeholders_in_either_branch():
    for p in (_known(), _unknown()):
        assert "{location_rule}" not in p and "{place_ask}" not in p
        assert "{place_ask}" not in p


# ── currency: the gate stays coherent per market ─────────────────────────────

def test_kenya_never_converts():
    p = _known()
    assert "convert from the USD amount" not in p     # KES is native, never derived
    assert "Kenyan Shillings (KES)" in p


def test_non_kenya_converts_from_usd_without_rounding():
    # Owner rule (2026-09-03): the price is what the hub holds — a converted
    # figure is the arithmetic's, never rounded up to a tidy ten.
    p = _unknown()
    assert "convert from the USD amount (never from KES)" in p
    assert "nearest 10" not in p
    assert "never rounded up, down or to a tidy number" in p
    assert "US Dollars (USD)" in p


def test_country_is_only_asserted_when_known():
    """The 'They appear to be in …' line lives in the per-customer block now
    (customer_context — the prompt-cache split), so the rules block itself must
    never claim a place; the tail asserts it only when we actually have one."""
    from app.agent.prompt import customer_context
    assert "They appear to be in Kenya." in customer_context("", "Kenya")
    assert "They appear to be in" not in customer_context("", "")
    for p in (_known(), _unknown()):
        assert "They appear to be in" not in p


# ── mood + interest: the intelligence the sale depends on ────────────────────

def test_mood_rules_cover_the_states_that_change_the_move():
    p = _known()
    assert "READ THE MOOD, THEN CHOOSE THE MOVE" in p
    for state in ("IN A HURRY", "PRICE-SENSITIVE", "UNSURE / BROWSING",
                  "FRUSTRATED or COMPLAINING", "GRIEF", "SUSPICIOUS"):
        assert state in p, state


def test_a_complaint_stops_the_selling():
    p = _known()
    assert "STOP SELLING ENTIRELY" in p
    assert "a product, a price, or an emoji" in p
    assert "WHEN SOMETHING HAS GONE WRONG" in p


def test_price_sensitivity_never_invents_a_discount():
    p = _known()
    assert "never discount on your own authority" in p
    assert "never apologise\n    for the price" in p or "never apologise" in p


def test_interest_is_read_as_a_signal():
    p = _known()
    assert "INTEREST IS A SIGNAL, NOT A PROMISE" in p
    assert "Going quiet after a price" in p
