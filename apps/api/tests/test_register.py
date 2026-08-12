"""The register is calm and honorable — lesson from the Chinedu thread
(2026-08-12, owner's rule: "Don't be very casual. Be calm and honorable and
respectable. Eg. okay….. perfect etc").

Neema opened confirmations with "Perfect —" and read like a chirpy shop
assistant. Her customers are bishops, pastors and parish committees buying for
the Lord's table; the voice must be a dignified house's — measured, warm,
respectful. The prompt itself was teaching the offence: "Perfect" was the FIRST
suggested acknowledgement in STYLE.
"""
from app.agent.prompt import build_system_prompt


def _flat(**kw) -> str:
    kw.setdefault("country_iso", "KE")
    kw.setdefault("currency", "KES")
    return " ".join(build_system_prompt(**kw).split())


def test_persona_is_calm_and_honorable_on_every_market():
    for p in (_flat(), _flat(country_iso="", currency="USD"),
              _flat(country_iso="ZM", currency="ZMW")):
        assert "CALM and HONORABLE" in p
        assert "never a chirpy shop assistant" in p


def test_register_rule_bans_chirpy_interjections():
    flat = _flat()
    assert "THE REGISTER IS CALM AND HONORABLE" in flat
    assert '"Perfect!", "Great!", "Awesome!", "Okay!"' in flat   # banned by name
    assert "quiet courtesy" in flat
    assert "dignity over pep" in flat


def test_acknowledgement_examples_are_dignified():
    flat = _flat()
    # the old list opened with the exact word the owner flagged
    assert '("Perfect", "Lovely choice"' not in flat
    assert '"Very well", "A fine choice", "Asante — noted"' in flat


def test_examples_confirm_plainly_not_celebrate():
    flat = _flat()
    assert '"Noted — 1 Gold Bread Tray, $140."' in flat           # the model answer
    assert '"Noted — 2 Silver Trays, $360 total.' in flat         # cart-change shape
    assert '"Hi Pastor Moses' not in flat                          # greeting example
    assert '"Hello Pastor Moses' in flat
