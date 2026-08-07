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
    return build_system_prompt(country="Kenya", country_iso="KE", currency="KES")


def _unknown() -> str:                   # a website visitor: no phone, no country
    return build_system_prompt(currency="USD")


# ── location: claim it only when we actually know it ─────────────────────────

def test_known_country_keeps_the_never_ask_rule():
    p = _known()
    assert "ALREADY know their country from their phone number" in p
    assert "never ask it" in p
    assert "which town are you in" in p            # city only


def test_unknown_country_asks_instead_of_assuming():
    p = _unknown()
    assert "do NOT know where this customer is" in p
    assert "which city and country are you in" in p
    # the false claim must be absent, not merely contradicted
    assert "ALREADY know their country" not in p
    assert "never assume a country, a currency or a shipping cost" in p


def test_unknown_country_reprices_once_they_say_kenya():
    """A Kenyan on the website must end up on real KES prices, not a conversion."""
    p = _unknown()
    assert 'currency="KES"' in p
    assert "never a converted figure" in p


def test_no_unrendered_placeholders_in_either_branch():
    for p in (_known(), _unknown()):
        assert "{location_rule}" not in p and "{place_ask}" not in p
        assert "{place_ask}" not in p


# ── currency: the gate stays coherent per market ─────────────────────────────

def test_kenya_never_converts():
    p = _known()
    assert "convert from the USD amount" not in p     # KES is native, never derived
    assert "Kenyan Shillings (KES)" in p


def test_non_kenya_converts_from_usd_and_rounds_up():
    p = _unknown()
    assert "convert from the USD amount (never from KES)" in p
    assert "nearest 10" in p
    assert "US Dollars (USD)" in p


def test_country_is_only_asserted_when_known():
    assert "They appear to be in Kenya." in _known()
    assert "They appear to be in" not in _unknown()


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
    assert "Never answer a complaint with" in p
    assert "handoff_to_human" in p


def test_price_sensitivity_never_invents_a_discount():
    p = _known()
    assert "never discount on your own authority" in p
    assert "never apologise\n    for the price" in p or "never apologise" in p


def test_interest_is_read_as_a_signal():
    p = _known()
    assert "INTEREST IS A SIGNAL, NOT A PROMISE" in p
    assert "Going quiet after a price" in p
