"""The comment thread IS the shop (owner, 2026-08-10): onboard, sell and close
in the comments — the same on Messenger, WhatsApp and the storefront. Pins the
tool kit, the addendum's selling+privacy contract, and the raised cap."""
from app.agent import runtime as rt
from app.core.config import settings


def test_comment_path_carries_the_full_selling_kit():
    names = {t["name"] for t in rt.PUBLIC_COMMENT_TOOLS}
    # Selling: quote, build, close.
    assert {"search_catalog", "get_cart", "update_cart", "create_order"} <= names
    # Onboarding: capture what they volunteer.
    assert {"capture_contact", "save_parish", "save_measurements",
            "remember"} <= names
    # Service: availability, seasons, orders, a human when they want one.
    assert {"check_availability", "church_calendar", "check_order_status",
            "handoff_to_human"} <= names


def test_comment_path_still_excludes_what_public_cannot_have():
    names = {t["name"] for t in rt.PUBLIC_COMMENT_TOOLS}
    # Link-bearing tools tax the post's reach; cards are a DM-only send API;
    # pausing a public thread makes no sense.
    assert "whatsapp_checkout_link" not in names
    assert "share_catalog" not in names
    assert "send_product_cards" not in names
    assert "pause_conversation" not in names


def test_addendum_sells_here_and_keeps_the_privacy_line():
    a = " ".join(rt._public_comment_addendum("KES").split())
    assert "THE THREAD IS THE SHOP" in a
    assert "is a lost sale" in a                      # deflection named as failure
    assert "PUBLIC PRIVACY" in a
    assert "never ask for a phone number" in a.lower()
    assert "capture_contact" in a                     # a volunteered number is used
    assert "never scold" in a
    assert "update_cart" in a and "create_order" in a
    # The two standing laws survive the rewrite.
    assert "NEVER WRITE A LINK" in a and "reach" in a
    assert "READ THE MOOD BEFORE YOU SELL" in a


def test_cap_is_a_backstop_not_a_budget():
    """30 full replies per post starved boosted posts into 'DM us for the
    price' (the Allan case)."""
    assert settings.meta_comment_agent_cap >= 300


def test_swahili_defaults_to_kes_unless_another_country_is_stated():
    """Owner rule (2026-08-10, from the live test): 'Hii Refiller … $20' quoted
    a Swahili speaker in dollars — a Kenyan treated as a foreigner in their own
    shop. Swahili → KES on both public comments and Meta DMs; a stated other
    country (Tanzania, DRC…) still wins."""
    pub = " ".join(rt._public_comment_addendum("USD").split())
    assert "SWAHILI MEANS KENYA" in pub
    assert 'currency="KES"' in pub
    assert "Tanzania" in pub                     # the override is spelled out
    # Present even when the default is already KES (harmless no-op there).
    assert "SWAHILI MEANS KENYA" in " ".join(rt._public_comment_addendum("KES").split())

    dm = " ".join(rt._meta_addendum("USD").split())
    assert "SWAHILI MEANS KENYA" in dm and "without waiting to be asked" in dm


def test_currency_is_never_a_question():
    """'…are you in Kenya? I can quote you in KES' went to a Filipino customer
    live. Both Meta surfaces now ban the ask outright."""
    pub = " ".join(rt._public_comment_addendum("USD").split())
    assert "NEVER ASK WHERE THEY ARE" in pub
    assert "are you in Kenya?" in pub            # named so the model can't rephrase it
    dm = " ".join(rt._meta_addendum("USD").split())
    assert "NEVER ask 'are you in Kenya?'" in dm
    assert "switch seamlessly" in dm.lower() or "switch seamlessly" in dm
