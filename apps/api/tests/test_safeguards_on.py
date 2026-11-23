"""THE SAFEGUARDS, SWITCHED ON (owner, 2026-11-23). The rest of the suite runs
with them off (tests/conftest.py); here each is turned on and its behaviour
seen."""
import asyncio

import pytest

from app.agent import policy as pol
from app.agent import runtime as rt
from app.core.config import settings


class _Redis:
    def __init__(self):
        self.kv = {}

    async def get(self, k):
        return self.kv.get(k)

    async def set(self, k, v, nx=False, ex=None):
        if nx and k in self.kv:
            return None
        self.kv[k] = v
        return True

    async def delete(self, *ks):
        for k in ks:
            self.kv.pop(k, None)

    async def expire(self, *a):
        return True


@pytest.fixture
def on(monkeypatch):
    monkeypatch.setattr(settings, "policy_mode", "enforce", raising=False)
    monkeypatch.setattr(settings, "policy_enforce", "FIN-02,FIN-03,FIN-04,FIN-05,ORD-01,ORD-02", raising=False)
    for name in ("policy_guards_active", "official_numbers_by_code", "offer_price_after_grant",
                 "second_deferral_line"):
        monkeypatch.setattr(settings, name, True, raising=False)


@pytest.mark.parametrize("text,policy", [
    ("We will refund you today.", "FIN-03"),
    ("I can take 10% off for you.", "FIN-02"),
    ("Yes, you can pay on delivery.", "FIN-04"),
    ("Please send the payment to 0712 345 678.", "FIN-05"),
    ("Your order has been placed.", "ORD-02"),
])
def test_each_critical_policy_holds_a_message(on, text, policy):
    f = pol.evaluate(text, route=pol.LIVE)
    assert policy in [x["policy"] for x in pol.enforced(f)]


@pytest.mark.parametrize("text", [
    "The Silver Communion Tray is $180. How many do you need?",
    "I have passed this to a colleague who decides refunds, and they will come back to you here.",
    "Payment is completed before delivery in every country.",
    "Our official numbers are +254727891989 and +254785490805. Any other number is not from Bethany House.",
    "Shall I place the order for you?",
])
def test_ordinary_replies_are_not_held(on, monkeypatch, text):
    monkeypatch.setattr(settings, "whatsapp_handoff_number", "+254727891989", raising=False)
    monkeypatch.setattr(settings, "whatsapp_handoff_alt", "+254785490805", raising=False)
    assert pol.enforced(pol.evaluate(text, route=pol.LIVE)) == []


def test_a_recorded_only_policy_does_not_hold(on):
    f = pol.evaluate("It will be ready in 9 days.", route=pol.LIVE)
    assert [x["policy"] for x in f] == ["FUL-01"] and pol.enforced(f) == []


def test_the_order_step_refuses_without_the_customers_yes(on):
    f = [pol.finding("ORD-01", "order step called with no yes in the customer's recent words")]
    assert pol.enforced(f) == f
    assert pol.customer_agreed(["Yes, go ahead and send the link"])


def test_a_second_deferral_gets_one_line_then_silence(on):
    r = _Redis()
    text = "I'll get back to you"
    # the first closer is answered by the turn; the gate is armed after the reply
    assert asyncio.run(rt.closer_gate(r, "whatsapp", "254700", text)) is False
    asyncio.run(rt.mark_closer_answered(r, "whatsapp", "254700", text, "Of course."))
    # the second gets a turn (one short line) …
    assert asyncio.run(rt.closer_gate(r, "whatsapp", "254700", text)) is False
    asyncio.run(rt.mark_closer_answered(r, "whatsapp", "254700", text, "Take your time."))
    # … and the third is silence
    assert asyncio.run(rt.closer_gate(r, "whatsapp", "254700", text)) is True


def test_with_the_switch_off_the_second_deferral_is_silence(monkeypatch):
    monkeypatch.setattr(settings, "second_deferral_line", False, raising=False)
    r = _Redis()
    text = "I'll get back to you"
    assert asyncio.run(rt.closer_gate(r, "whatsapp", "254700", text)) is False
    asyncio.run(rt.mark_closer_answered(r, "whatsapp", "254700", text, "Of course."))
    assert asyncio.run(rt.closer_gate(r, "whatsapp", "254700", text)) is True


def test_shadow_brings_everything_back_to_record_only(on, monkeypatch):
    monkeypatch.setattr(settings, "policy_mode", "shadow", raising=False)
    assert pol.enforced(pol.evaluate("We will refund you today.", route=pol.LIVE)) == []
