"""Owner's rule (2026-08-12): what happens when a customer hands us their number.

Sharing a contact is an act of trust and the highest-intent moment in a chat.
It gets: thanks, a plain promise that a colleague will reach out, BOTH official
lines for anything urgent — and then the sale CARRIES ON. "Someone will get
back to you" followed by silence is how a warm buyer goes cold.
"""
import app.main  # noqa: F401 — registers models before agent imports
from app.core.config import Settings, settings
from app.agent.prompt import build_system_prompt


def _flat(**kw) -> str:
    kw.setdefault("country_iso", "KE")
    kw.setdefault("currency", "KES")
    return " ".join(build_system_prompt(**kw).split())


def test_a_shared_contact_is_saved_thanked_and_answered():
    flat = _flat()
    assert "WHEN THEY GIVE YOU THEIR CONTACT — receive it as the trust it is" in flat
    assert "Save it in that SAME turn (capture_contact / capture_customer)" in flat
    assert "a colleague will reach out to them shortly" in flat


def test_both_lines_are_offered_for_anything_urgent():
    flat = _flat()
    assert "give BOTH our lines for anything urgent" in flat
    assert "quoted digit for digit from OUR OFFICIAL CONTACTS" in flat


def test_the_sale_does_not_stop_at_the_handover():
    """'Serve our purpose': they are helped NOW and called later — never parked."""
    flat = _flat()
    assert "their contact is not the end of the conversation" in flat
    assert "never a place to park them" in flat
    assert 'Never say "someone will get back to you" and then fall silent' in flat
    assert "never make them wait for a call to be served" in flat


def test_it_does_not_double_as_the_whatsapp_pitch():
    """The WhatsApp invitation is capped at once per conversation; handing over
    our lines here is service and must not burn or duplicate it."""
    flat = _flat()
    assert "Giving our lines here is service, not the WhatsApp invitation" in flat
    assert "do not also pitch WhatsApp separately" in flat


# ── the numbers themselves must actually be there to give ────────────────────

def test_both_official_lines_have_real_defaults():
    """The OUR OFFICIAL CONTACTS block renders only when a line is configured.
    Blank defaults + an unset box .env would leave Neema promising a number she
    has none of, so the business's two lines are the defaults."""
    assert Settings.model_fields["whatsapp_handoff_number"].default == "+254727891989"
    assert Settings.model_fields["whatsapp_handoff_alt"].default == "+254785490805"


def test_the_lines_render_verbatim_into_every_market_bucket(monkeypatch):
    monkeypatch.setattr(settings, "whatsapp_handoff_number", "+254727891989", raising=False)
    monkeypatch.setattr(settings, "whatsapp_handoff_alt", "+254785490805", raising=False)
    for iso, ccy in (("KE", "KES"), ("", "USD"), ("ZM", "ZMW")):
        p = build_system_prompt(country_iso=iso, currency=ccy)
        assert "OUR OFFICIAL CONTACTS" in p, ccy
        assert "WhatsApp: +254727891989" in p, ccy
        assert "Phone / calls: +254785490805" in p, ccy
        # and the never-invent-a-number guard still stands
        assert "NEVER type a phone number or wa.me link from memory" in p, ccy
