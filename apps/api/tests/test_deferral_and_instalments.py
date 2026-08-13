"""Owner's rules (2026-08-12): a customer who says "I'll get back to you".

Three moves, warmly, in one short message: thank them and say we'll be waiting;
ask whether there's a time to remind them (booking it as a real promise); and
tell them they may pay little by little until the purchase is complete.

"Later" is usually money, said politely. The instalment offer removes that
reason without discounting a shilling — and the scheduled check-in means the
sale returns to us instead of relying on the customer to remember.
"""
import app.main  # noqa: F401 — registers models before agent imports
from app.agent.prompt import build_system_prompt


def _flat(**kw) -> str:
    kw.setdefault("country_iso", "KE")
    kw.setdefault("currency", "KES")
    return " ".join(build_system_prompt(**kw).split())


# ── the deferral itself ──────────────────────────────────────────────────────

def test_a_deferral_is_answered_with_thanks_and_an_open_door():
    flat = _flat()
    assert "WHEN THEY SAY THEY WILL COME BACK" in flat
    assert "nitakujulisha" in flat                      # Swahili deferral too
    assert "never a bare \"okay\" and never a chase" in flat
    assert "THANK them and say plainly we'll be waiting" in flat


def test_the_reminder_time_is_asked_and_kept():
    flat = _flat()
    assert "Is there a day we should check back with you?" in flat
    assert "This is your ONE question" in flat          # brevity contract holds
    assert "call `schedule_check_in` with it" in flat
    assert "a named time is a promise the system keeps" in flat


def test_after_the_deferral_she_stops():
    """A chase is how a polite 'later' becomes a lost customer."""
    flat = _flat()
    assert "Then STOP. No fresh pitch" in flat
    assert "the scheduled check-in is how we return" in flat


def test_the_instalment_line_is_a_statement_not_a_second_question():
    flat = _flat()
    assert "TELL them, as a statement (not a second question)" in flat


# ── the instalment offer, in both payment worlds ─────────────────────────────

def test_instalments_are_offered_in_kenya_and_internationally():
    for iso, ccy in (("KE", "KES"), ("", "USD"), ("ZM", "ZMW")):
        flat = _flat(country_iso=iso, currency=ccy)
        assert "THEY MAY PAY LITTLE BY LITTLE (owner's standing offer)" in flat, ccy
        assert "until the purchase is complete" in flat, ccy
        assert "You're welcome to pay bit by bit until it's complete" in flat, ccy


def test_instalments_never_become_a_discount_or_a_pity_offer():
    """The money-safety rule still wins: the total never moves, and a customer
    paying in parts is a customer, not a charity case."""
    for iso, ccy in (("KE", "KES"), ("", "USD")):
        flat = _flat(country_iso=iso, currency=ccy)
        assert "It is NOT a discount and never changes the total" in flat, ccy
        assert "never present it as charity" in flat, ccy
        assert "Offer it plainly and without pity" in flat, ccy


def test_part_paid_dispatch_timing_is_never_promised():
    """The hub flags a partial payment for a human to reconcile, so when we
    start making or ship a part-paid order is the team's word, not Neema's."""
    flat_ke = _flat()
    assert ("If they ask when we begin making or dispatch a part-paid order, say "
            "warmly that the team will confirm that — never promise it yourself"
            ) in flat_ke
    flat_intl = _flat(country_iso="", currency="USD")
    assert ("question about when a part-paid order is made or shipped goes to the "
            "team — never promise it yourself") in flat_intl


# ── the tool the promise rides on ────────────────────────────────────────────

def test_schedule_check_in_advertises_the_deferral_case():
    """A tool description is an instruction too: scoped to replenishment only,
    the model would not reach for it when someone says 'I'll get back to you'."""
    from app.agent.tools import TOOLS
    spec = next(t for t in TOOLS if t["name"] == "schedule_check_in")
    d = " ".join(spec["description"].split())
    assert "GET BACK TO US on a purchase they're still deciding" in d
    assert "when to have the delivery ready" in d
    assert spec["input_schema"]["required"] == ["days_from_now", "reason"]
