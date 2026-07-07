"""Country-aware phone canonicalization — the shared WhatsApp↔hub identity key.

The load-bearing property: matching is on the FULL E.164 (country code included),
so numbers that merely share trailing digits across countries never merge.
"""
from app.core.phone import to_e164, same_number, national_digits


def test_e164_resolves_the_formats_the_hub_stores():
    assert to_e164("0712345678") == "+254712345678"        # local KE
    assert to_e164("254712345678") == "+254712345678"      # wa_id (intl, no +)
    assert to_e164("+254 712 345 678") == "+254712345678"  # pretty e164
    assert to_e164("0110000000") == "+254110000000"        # 01xx range


def test_e164_keeps_international_country_codes():
    assert to_e164("+256712345678") == "+256712345678"     # Uganda, explicit +
    assert to_e164("256712345678") == "+256712345678"      # Uganda, no +
    # A *local* number read for a non-default region gets that region's code.
    assert to_e164("0712345678", region="UG") == "+256712345678"


def test_e164_rejects_junk():
    assert to_e164(None) is None
    assert to_e164("") is None
    assert to_e164("12345") is None


def test_same_number_matches_across_formats_same_country():
    # The real fix: a hub customer stored as 0712… vs a wa_id of 254712….
    assert same_number("0712345678", "254712345678") is True
    assert same_number("+254712345678", "0712345678") is True


def test_same_number_does_not_collide_across_countries():
    # Kenya +254 712345678 vs Uganda +256 712345678 share the last 9 digits but
    # are different people — must NOT match.
    assert same_number("254712345678", "+256712345678") is False
    assert same_number("0712345679", "0712345678") is False


def test_national_digits_for_hub_search():
    # Used as the ILIKE query so every stored format is a substring hit.
    assert national_digits("254712345678") == "712345678"
    assert national_digits("0712345678") == "712345678"
    assert national_digits("bad") is None
