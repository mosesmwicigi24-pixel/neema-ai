"""Lead score, tuned for a WhatsApp-first business.

The 10 points that used to require an EMAIL now require a REACHABLE, PROVEN phone.
We sell on WhatsApp and rarely ask for an email, so every good customer was quietly
losing those 10 points for something we never wanted.
"""
import types

import app.main  # noqa: F401 — registers models
from app.models.user import User
from app.routers.crm import _compute_lead_score, _phone_verified


def _ident(channel, ext, confidence="deterministic"):
    return types.SimpleNamespace(channel=channel, external_id=ext,
                                 confidence=confidence, display_name=None, source="x")


# ── what counts as a reachable phone ─────────────────────────────────────────

def test_whatsapp_wa_id_is_proof():
    """A wa_id is the number Meta verified when they messaged us — it can't be a typo."""
    assert _phone_verified(User(wa_id="254727808176")) is True


def test_messenger_only_contact_is_not_phone_verified():
    """A PSID is 16-17 digits — reachable on Messenger, but NOT by phone."""
    u = User(wa_id="web_abc")
    assert _phone_verified(u, [_ident("messenger", "26414904614761138")]) is False
    assert _phone_verified(u, []) is False
    assert _phone_verified(u) is False


def test_captured_phone_counts_when_deterministic():
    u = User(wa_id="web_abc")
    assert _phone_verified(u, [_ident("whatsapp", "254712345678")]) is True
    # they told us on Messenger and we stored it deterministically
    assert _phone_verified(u, [_ident("messenger", "254712345678")]) is True
    # a guessed/probabilistic non-whatsapp number is not proof
    assert _phone_verified(u, [_ident("messenger", "254712345678", "probabilistic")]) is False


# ── the score itself ─────────────────────────────────────────────────────────

def test_verified_phone_earns_the_ten_points_email_used_to():
    u = User(wa_id="254727808176", name="Cynthia Kaffi")
    with_phone = _compute_lead_score(u, 0, 0, 1, phone_verified=True)
    without = _compute_lead_score(u, 0, 0, 1, phone_verified=False)
    assert with_phone - without == 10


def test_email_no_longer_scores():
    """An email is not asked for and must not move the score either way."""
    plain = User(wa_id="254700000001", name="A")
    with_email = User(wa_id="254700000001", name="A", email="a@example.com")
    assert (_compute_lead_score(plain, 1, 5000, 2, phone_verified=True)
            == _compute_lead_score(with_email, 1, 5000, 2, phone_verified=True))


# ── "who should I call TODAY?" — live intent outranks a dormant buyer ────────

def test_a_hot_lead_with_a_cart_outranks_a_dormant_past_buyer():
    """The whole point of the retune: someone actively shopping, who has never
    bought, must rank ABOVE a big spender who went quiet months ago."""
    hot = _compute_lead_score(
        User(wa_id="254700000001", name="Hot", location="Nairobi"),
        order_count=0, total_spent=0, channel_count=2,
        phone_verified=True, cart_items=3, days_since_contact=1)
    dormant = _compute_lead_score(
        User(wa_id="254700000002", name="Dormant", location="Nairobi"),
        order_count=5, total_spent=50000, channel_count=1,
        phone_verified=True, cart_items=0, days_since_contact=200)
    assert hot > dormant


def test_an_active_cart_is_the_single_biggest_signal():
    u = User(wa_id="254700000001")
    assert (_compute_lead_score(u, 0, 0, 1, cart_items=1)
            - _compute_lead_score(u, 0, 0, 1, cart_items=0)) == 25


def test_recency_decays():
    u = User(wa_id="254700000001")
    warm = _compute_lead_score(u, 0, 0, 1, days_since_contact=2)
    fading = _compute_lead_score(u, 0, 0, 1, days_since_contact=20)
    cold = _compute_lead_score(u, 0, 0, 1, days_since_contact=90)
    never = _compute_lead_score(u, 0, 0, 1, days_since_contact=None)
    assert warm == 15 and fading == 7 and cold == 0 and never == 0


def test_scale_bounds_and_breakdown_matches_the_score():
    from app.routers.crm import _lead_score_parts
    u = User(wa_id="254700000001", name="A", location="Nairobi")
    # everything at once still caps at 100
    assert _compute_lead_score(u, 10, 50000, 3, phone_verified=True,
                               cart_items=2, days_since_contact=0) == 100
    assert _compute_lead_score(User(wa_id="web_x"), 0, 0, 1) == 0   # nothing known
    # the itemised breakdown IS the score (the panel renders this list)
    parts = _lead_score_parts(u, 1, 5000, 2, phone_verified=True,
                              cart_items=1, days_since_contact=3)
    assert min(sum(p["pts"] for p in parts), 100) == _compute_lead_score(
        u, 1, 5000, 2, phone_verified=True, cart_items=1, days_since_contact=3)
    assert all(0 <= p["pts"] <= p["max"] for p in parts)
    assert {"Active cart", "Recent contact", "Phone verified"} <= {p["label"] for p in parts}


def test_cart_size_reads_whichever_store_holds_it():
    from app.routers.crm import _cart_size
    person = {"agent_cart": {"items": [{"name": "Chasuble"}, {"name": "Mitre"}]}}
    assert _cart_size(person, None) == 2
    assert _cart_size(None, {"agent_cart": {"items": [{"name": "Alb"}]}}) == 1
    assert _cart_size(None, {}) == 0
    assert _cart_size({"agent_cart": {"items": []}}, None) == 0
