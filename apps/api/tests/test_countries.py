"""Unit tests for server-side country resolution (pure, no DB)."""
from app.core.countries import resolve_country, flag_url_for


def test_kenya_from_wa_id():
    r = resolve_country("254717905405")
    assert r == {
        "country": "Kenya",
        "country_iso": "KE",
        "flag_url": "https://flagcdn.com/ke.svg",
        "code": "254",
    }


def test_longest_prefix_wins():
    # American Samoa is +1-684; must beat the bare +1 (USA/Canada).
    assert resolve_country("16845551234")["country"] == "American Samoa"
    assert resolve_country("15551234567")["country"] in {"United States", "Canada"}


def test_handles_plus_prefix_and_spaces():
    assert resolve_country("+254 717 905 405")["country_iso"] == "KE"


def test_unknown_and_empty_are_safe():
    assert resolve_country("")["country"] is None
    assert resolve_country(None)["country"] is None
    assert resolve_country("000000")["country"] is None  # no such prefix


def test_flag_url_for():
    assert flag_url_for("KE") == "https://flagcdn.com/ke.svg"
    assert flag_url_for(None) is None
