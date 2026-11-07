"""Owner's rules on a customer who says "I'll get back to you".

2026-08-12: thank them, say we'll be waiting, and ask whether there's a time
to remind them. 2026-11-07 (the collar case, slice 11) supersedes the asking
half: keep the item, name the one step as a statement, and NEVER ask when to
remind them — "take all the time you need, is there a day I should check
back?" disengages and takes back the move they just claimed. The booking
half stands: a time THEY name is booked with `schedule_check_in` in the same
turn, one per matter. The instalment offer joins only when money is the
reason they gave (owner, 2026-10-30: for when price or budget comes up, never
a tail).
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
    assert "never a bare \"okay\", never a chase" in flat
    assert "ACCEPT in one warm clause and KEEP THE ITEM" in flat
    assert "NAME THE ONE STEP that completes it, as a STATEMENT, not a question" in flat


def test_a_named_time_is_kept_and_a_reminder_is_never_asked_for():
    flat = _flat()
    assert "Is there a day we should check back with you?" not in flat.replace(
        'no "Is there a day we should check back', "")          # only as the banned example
    assert "NEVER ask when to remind them" in flat
    assert "no question of any kind" in flat                    # brevity contract holds
    assert "call `schedule_check_in` with it IN THE SAME TURN" in flat
    assert "a named time is a promise the system keeps" in flat


def test_after_the_deferral_she_stops():
    """A chase is how a polite 'later' becomes a lost customer."""
    flat = _flat()
    assert "Then STOP. No fresh pitch" in flat
    assert "the scheduled check-in is how we return" in flat


def test_the_instalment_line_comes_only_when_money_is_the_reason():
    """Owner, 2026-10-30: the offer is for when price or budget comes up —
    a plain "I'll come back" gets thanks and the reminder question only."""
    flat = _flat()
    assert "ONLY IF money is the reason they gave" in flat
    assert "TELL them, as a statement, that they may pay little by little" in flat
    assert 'A plain "I\'ll come back" gets no instalment line' in flat


def test_the_payment_rule_offers_instalments_only_on_price_or_budget():
    for iso, ccy in (("KE", "KES"), ("", "USD"), ("ZM", "ZMW")):
        flat = _flat(country_iso=iso, currency=ccy)
        assert "they say they'll come back later" not in flat, ccy
        assert "ONLY when price or budget comes up" in flat, ccy
        assert "never as a tail" in flat.lower(), ccy


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
