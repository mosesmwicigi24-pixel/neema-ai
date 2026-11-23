"""Repairs and alterations: the 14-day house rule (management, 2026-11-19).

"Effective immediately, Bethany House will no longer accept repair or
alteration work for products purchased or manufactured outside Bethany House.
For products purchased from Bethany House, repairs or alterations may only be
considered within 14 days of the customer receiving and accepting the item,
subject to assessment. … There are no exceptions to this policy."

Neema's instructions said nothing about repairs, so nothing stopped her
agreeing to one. The rule is now part of every system prompt.
"""
from app.agent.prompt import build_system_prompt


def _prompt() -> str:
    return build_system_prompt()


def test_the_rule_is_in_the_prompt():
    p = _prompt()
    assert "REPAIRS AND ALTERATIONS" in p
    assert "ONLY items bought from Bethany House" in p
    assert "ONLY within 14 days of the customer receiving the item" in " ".join(p.split())
    assert "subject to our assessment" in p


def test_items_from_elsewhere_and_late_requests_are_declined_without_an_exception():
    flat = " ".join(_prompt().split())
    assert "An item bought or made elsewhere: we do not repair or alter it." in flat
    # owner, 2026-11-20 (decision D5): the window is said plainly; an exception
    # is a colleague's decision — never promised, never hinted at
    assert "more than 14 days after they received it: say plainly, once, that our repair and alteration window is 14 days from delivery" in flat
    assert "Never promise an exception and never hint that one is likely" in flat
    assert "a colleague decides exceptions" in flat


def test_within_the_window_she_does_not_promise_and_brings_in_a_colleague():
    flat = " ".join(_prompt().split())
    assert "within the 14 days: never promise the repair yourself" in flat
    assert "bring in a colleague" in flat
    assert 'maintained "for life"' in flat


def test_a_faulty_delivery_is_still_a_complaint_not_a_repair_request():
    flat = " ".join(_prompt().split())
    assert "ARRIVED faulty, damaged or wrong is a complaint, not a repair request" in flat
