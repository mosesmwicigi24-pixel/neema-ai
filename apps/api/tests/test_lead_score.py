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
    # Cynthia: name known (10) + verified phone (10), no orders/spend/multi-channel
    assert with_phone == 20


def test_email_no_longer_scores():
    """An email is not asked for and must not move the score either way."""
    plain = User(wa_id="254700000001", name="A")
    with_email = User(wa_id="254700000001", name="A", email="a@example.com")
    assert (_compute_lead_score(plain, 1, 5000, 2, phone_verified=True)
            == _compute_lead_score(with_email, 1, 5000, 2, phone_verified=True))


def test_the_rest_of_the_scale_is_unchanged():
    u = User(wa_id="254700000001", name="A", location="Nairobi")
    # orders cap at 45, spend >10k = 30, name 10, location 5, multi-channel 15,
    # verified phone 10 → capped at 100
    assert _compute_lead_score(u, 10, 50000, 3, phone_verified=True) == 100
    assert _compute_lead_score(User(wa_id="web_x"), 0, 0, 1) == 0     # nothing known
    # spend tiers still step
    bare = User(wa_id="web_x")
    assert _compute_lead_score(bare, 0, 5000, 1) == 15
    assert _compute_lead_score(bare, 0, 20000, 1) == 30
