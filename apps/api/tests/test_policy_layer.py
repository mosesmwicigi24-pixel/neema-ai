"""THE POLICY LAYER (agent/policy.py; owner's directive, 2026-11-20).

Each company rule is tested four ways: the plain violation, a paraphrase, the
legitimate sentence that must NOT be flagged, and the record that makes the
claim true (a granted offer, a successful order step, a colleague's own
words). The wording finds the claim; the record decides.
"""
import asyncio
import json

import pytest

from app.agent import policy as pol
from app.core.config import settings


def ids(text, **kw):
    kw.setdefault("route", pol.LIVE)
    return [f["policy"] for f in pol.evaluate(text, **kw)]


# ── FIN-03 refunds, remakes, replacements ────────────────────────────────────

@pytest.mark.parametrize("text", [
    "We will refund you today.",
    "I'll make sure you get your money back by Friday.",
    "Your refund has been approved.",
    "We can replace it for you at no cost.",
    "I will reship the cassock tomorrow.",
    "Tutakurudishia pesa zako leo.",
    "Unfortunately we do not give refunds.",
])
def test_a_refund_or_replacement_is_not_neemas_to_promise_or_refuse(text):
    assert "FIN-03" in ids(text)


@pytest.mark.parametrize("text", [
    "I have passed this to a colleague who decides refunds, and they will come back to you here.",
    "I'm sorry about the torn seam. A colleague will review this and confirm what we can do.",
    "We will not refund without a colleague looking at it first — they will reply here.",
    "Thank you for the photo of the cassock.",
])
def test_handing_a_refund_to_the_person_who_decides_is_allowed(text):
    assert "FIN-03" not in ids(text)


def test_a_colleagues_own_decision_may_be_delivered():
    text = "Good news — we will replace the stole and send it this week."
    assert "FIN-03" not in ids(text, route=pol.TEAM_ANSWER,
                               source_text="yes replace the stole, send this week")


# ── FIN-02 a discount in words ───────────────────────────────────────────────

@pytest.mark.parametrize("text", [
    "I can take 10% off for you.",
    "I can give you a discount if you order today.",
    "Special price for you: $180.",
    "We could reduce it a little.",
    "Punguzo ya 5% kwako.",
])
def test_a_discount_needs_a_recorded_offer(text):
    assert "FIN-02" in ids(text)


def test_a_granted_offer_may_be_spoken():
    log = [{"tool": "apply_offer", "input": {}, "out": {"ok": True, "percent": 10}}]
    assert "FIN-02" not in ids("Advent offer: 10% off — $200, now $180.", tool_log=log)
    # a failed grant is not a grant
    bad = [{"tool": "apply_offer", "input": {}, "out": {"error": "no offer running"}}]
    assert "FIN-02" in ids("Advent offer: 10% off — $200, now $180.", tool_log=bad)


@pytest.mark.parametrize("text", [
    "We don't offer a discount on single pieces, but the set saves you the belt.",
    "The Silver Communion Tray is $180.",
    "Our price is the same for every size.",
])
def test_holding_the_price_is_not_a_discount(text):
    assert "FIN-02" not in ids(text)


# ── FIN-04 payment before delivery ───────────────────────────────────────────

@pytest.mark.parametrize("text", [
    "Yes, you can pay on delivery.",
    "No problem, pay when it arrives.",
    "Cash on delivery is fine.",
    "Unaweza lipa ukipokea.",
])
def test_pay_on_delivery_is_never_agreed(text):
    assert "FIN-04" in ids(text)


@pytest.mark.parametrize("text", [
    "Payment is completed before delivery in every country.",
    "We do not do pay on delivery — payment comes first, then DHL collects.",
])
def test_the_rule_stated_is_fine(text):
    assert "FIN-04" not in ids(text)


def test_payment_at_collection_needs_an_approved_policy(monkeypatch):
    text = "You are welcome to pay at our shop when you collect it."
    monkeypatch.setattr(settings, "policy_pay_at_collection", False, raising=False)
    assert "FIN-04" in ids(text)
    monkeypatch.setattr(settings, "policy_pay_at_collection", True, raising=False)
    assert "FIN-04" not in ids(text)
    assert "FIN-04" in ids("Pay when it arrives by DHL.")       # delivery is never covered


# ── FIN-05 numbers ───────────────────────────────────────────────────────────

def test_only_our_official_numbers(monkeypatch):
    monkeypatch.setattr(settings, "whatsapp_handoff_number", "+254727891989", raising=False)
    monkeypatch.setattr(settings, "whatsapp_handoff_alt", "+254785490805", raising=False)
    ok = "Our official numbers are +254727891989 and +254785490805."
    assert "FIN-05" not in ids(ok)
    assert "FIN-05" not in ids("Send M-Pesa to 0727 891 989.")          # the same line, written locally
    assert "FIN-05" in ids("Our official numbers are +254727891998 and +254785490805.")   # two digits swapped
    assert "FIN-05" in ids("Please send the payment to 0712 345 678.")


def test_the_customers_own_number_and_prices_are_not_findings():
    said = ["my number is 0712345678, call me"]
    assert "FIN-05" not in ids("Thank you — I have 0712345678 for the delivery.", said=said)
    assert "FIN-05" not in ids("That is KES 1,250,000 for the full parish order.")
    assert "FIN-05" not in ids("The total is $1,080 for 6 trays.")


# ── ORD-02 an order is placed only when it is ────────────────────────────────

def test_placed_needs_the_order_step():
    text = "Your order has been placed — here is your payment link."
    assert "ORD-02" in ids(text)
    assert "ORD-02" in ids(text, tool_log=[{"tool": "create_order", "out": {"error": "phone missing"}}])
    assert "ORD-02" not in ids(text, tool_log=[{"tool": "create_order", "out": {"ok": True, "order_url": "u"}}])
    assert "ORD-02" not in ids("Your order has been placed.", route=pol.HUB_EVENT, status_known=True)
    assert "ORD-02" not in ids("Shall I place the order for you?")


# ── FUL-02 repairs ───────────────────────────────────────────────────────────

def test_repairs_are_never_for_life():
    assert "FUL-02" in ids("We repair our cassocks for life.")
    assert "FUL-02" in ids("It comes with a lifetime guarantee.")
    assert "FUL-02" not in ids("We repair items bought from us within 14 days of delivery.")


# ── FUL-01 times need a source ───────────────────────────────────────────────

def test_a_time_needs_a_source():
    assert "FUL-01" in ids("It will be ready in 5 days.")
    assert "FUL-01" in ids("DHL will deliver by Friday.")
    # the customer named the day; a tool gave the duration; a colleague said it
    assert "FUL-01" not in ids("We will have it ready by Friday.", said=["I need it by Friday please"])
    assert "FUL-01" not in ids("It will be ready in 5 days.",
                               tool_log=[{"tool": "check_availability", "out": {"note": "about 5 days"}}])
    assert "FUL-01" not in ids("It will be ready in 5 days.", route=pol.TEAM_ANSWER,
                               source_text="yes we make it, 5 days")
    assert "FUL-01" not in ids("We deliver worldwide with DHL.")


# ── ACT-01 the team was asked ────────────────────────────────────────────────

def test_a_promise_to_ask_needs_the_asking():
    text = "Let me confirm with my colleague and come right back."
    assert "ACT-01" in ids(text)
    assert "ACT-01" not in ids(text, tool_log=[{"tool": "check_availability", "out": {"ok": True}}])
    assert "ACT-01" not in ids("Which colour would you like?")


# ── ORD-01 the customer's yes ────────────────────────────────────────────────

def test_the_customers_yes_is_read_from_their_words():
    assert pol.customer_agreed(["Yes please, send the link"])
    assert pol.customer_agreed(["sawa endelea"])
    assert pol.customer_agreed(["how do I pay?"])
    assert not pol.customer_agreed(["How much is the purple one?"])
    assert not pol.customer_agreed(["let me think about it", "how much?", "is it cotton?"])
    assert not pol.customer_agreed([])
    # only the recent words count
    assert not pol.customer_agreed(["how much?", "and the stole?", "is it lined?", "yes please"])


# ── clean replies stay clean ─────────────────────────────────────────────────

@pytest.mark.parametrize("text", [
    "Hello Pastor Moses, welcome to Bethany House. We make cassocks to your measurements. Which colour would you like?",
    "The Silver Communion Tray is $180 and the Golden Communion Tray $220. Which would you like?",
    "6 trays, $1,080. Shall I prepare the order?",
    "We ship worldwide from Nairobi with DHL. Which city should we deliver to?",
    "Karibu Bethany House. Ungependa rangi gani?",
    "Thank you — a colleague is confirming the price of the purple cassock and will complete the order with you here.",
])
def test_ordinary_selling_is_not_flagged(text):
    log = [{"tool": "update_cart", "out": {"ok": True}}] if "colleague" in text else []
    assert ids(text, tool_log=log) == []


# ── modes and the record ─────────────────────────────────────────────────────

class _Redis:
    def __init__(self):
        self.h, self.l = {}, []

    async def hincrby(self, k, f, n):
        self.h.setdefault(k, {})[f] = self.h.get(k, {}).get(f, 0) + n

    async def lpush(self, k, v):
        self.l.insert(0, v)

    async def expire(self, *a):
        return True

    async def ltrim(self, *a):
        return True

    async def hgetall(self, k):
        return self.h.get(k, {})

    async def lrange(self, k, a, b):
        return self.l[a:b + 1]


def test_shadow_records_and_holds_nothing(monkeypatch):
    monkeypatch.setattr(settings, "policy_mode", "shadow", raising=False)
    f = pol.evaluate("We will refund you today.", route=pol.LIVE)
    assert pol.enforced(f) == []
    r = _Redis()
    assert asyncio.run(pol.record(r, f, route=pol.LIVE, channel="whatsapp", key="254700000001")) == "detected"
    row = json.loads(r.l[0])
    assert row["policy"] == "FIN-03" and row["version"] == pol.RULES_VERSION
    assert row["route"] == pol.LIVE and row["outcome"] == "detected" and row["to"] == "…0001"
    assert "254700000001" not in r.l[0]                      # the number is never stored whole
    rep = asyncio.run(pol.report(r))
    assert rep["mode"] == "shadow" and rep["days"][0]["rows"][0]["policy"] == "FIN-03"


def test_enforce_holds_only_the_listed_policies(monkeypatch):
    monkeypatch.setattr(settings, "policy_mode", "enforce", raising=False)
    monkeypatch.setattr(settings, "policy_enforce", "FIN-03", raising=False)
    f = pol.evaluate("We will refund you today, and it will be ready in 5 days.", route=pol.LIVE)
    assert {x["policy"] for x in f} == {"FIN-03", "FUL-01"}
    assert [x["policy"] for x in pol.enforced(f)] == ["FIN-03"]
    monkeypatch.setattr(settings, "policy_enforce", "*", raising=False)
    assert [x["policy"] for x in pol.enforced(f)] == ["FIN-03"]      # "*" = the critical ones
    assert asyncio.run(pol.record(_Redis(), f, route=pol.LIVE)) == "prevented"


def test_no_findings_no_record():
    r = _Redis()
    assert asyncio.run(pol.record(r, [], route=pol.LIVE)) == "clear" and r.l == []


# ── every route calls the layer ──────────────────────────────────────────────

def test_every_route_is_wired():
    import inspect
    from app.agent import runtime, tools
    from app.routers import admin
    from app.services import actions, hub_events
    assert "_pol.evaluate(reply, route=_pol.LIVE" in inspect.getsource(runtime.run_turn)
    assert "_pol.INITIATED" in inspect.getsource(actions._send)
    assert "_pol.HUB_EVENT" in inspect.getsource(hub_events)
    src = inspect.getsource(admin.answer_through_neema)
    assert "_pol.TEAM_ANSWER" in src and "teamanswer:once" in src and "opted_out" in src
    assert "_pol.ORDER_TOOL" in inspect.getsource(tools._create_order)
    # a second "stop" is marked as deliberate silence on both channels
    assert "audit H1" in inspect.getsource(runtime.schedule_reply)
    assert "audit H1" in inspect.getsource(runtime.schedule_meta_reply)


def test_the_default_is_shadow():
    from app.core.config import Settings
    assert Settings.model_fields["policy_mode"].default == "shadow"
    assert Settings.model_fields["policy_enforce"].default == ""
    assert Settings.model_fields["policy_guards_active"].default is False
    assert Settings.model_fields["policy_pay_at_collection"].default is False


def test_a_given_outcome_is_recorded_as_given(monkeypatch):
    monkeypatch.setattr(settings, "policy_mode", "enforce", raising=False)
    monkeypatch.setattr(settings, "policy_enforce", "*", raising=False)
    r = _Redis()
    out = asyncio.run(pol.record(r, [pol.finding("GATE", "sent after one rewrite")], route=pol.LIVE,
                                 outcome="detected"))
    assert out == "detected" and json.loads(r.l[0])["policy"] == "GATE"


def test_the_instructions_own_shipping_times_have_a_source():
    assert pol.stated_times()                                   # read from the instructions themselves
    assert "FUL-01" not in ids("It ships via DHL in 1–2 days.")
    assert "FUL-01" in ids("It ships via DHL in 8–9 days.")     # a duration nobody stated
    assert "ORD-02" not in ids("Give them their order number and a colleague will follow up.",
                               tool_log=[{"tool": "handoff_to_human", "out": {"ok": True}}])
    assert "ORD-02" in ids("Your order number is BH-10432.")
    assert "ORD-02" not in ids("Your order is placed once you confirm the total.")
    assert "FIN-02" not in ids("The final price is $630 for the three garments.")
