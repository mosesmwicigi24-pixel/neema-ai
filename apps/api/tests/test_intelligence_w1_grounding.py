"""Workstream 1/4 (intelligence programme, 2026-11-06): a payment
acknowledgement needs the hub's word, manufactured urgency never passes, a
promised offer that cannot be read is surfaced, and the Meta door does not
ack a message it lost."""
from __future__ import annotations

import inspect

import pytest

from app.agent import review as rv


def _f(kinds, **kw):
    out = rv.rule_findings("", kw.pop("answer"), [], **kw)
    return {o["kind"]: o for o in out if o["kind"] in kinds}


PAID = [{"tool": "check_order_status", "input": {}, "out": {"order_number": "1187", "payment_status": "paid"}}]
UNPAID = [{"tool": "check_order_status", "input": {}, "out": {"order_number": "1187", "payment_status": "unpaid"}}]


def test_thanking_for_a_payment_without_a_paid_state_is_a_hard_finding():
    for answer in ("Thank you for your payment! We'll start the work.",
                   "Payment received, asante. Your cassock goes into production.",
                   "Asante kwa malipo, tutaanza kazi."):
        f = _f({"paid_ack"}, answer=answer, tool_results=UNPAID, mode="dm")
        assert "paid_ack" in f and f["paid_ack"]["hard"], answer
        f = _f({"paid_ack"}, answer=answer, tool_results=[], mode="dm")
        assert "paid_ack" in f, answer


def test_a_paid_state_from_the_hub_in_this_turn_allows_the_thanks():
    f = _f({"paid_ack"}, answer="Thank you for your payment — order 1187 is confirmed.", tool_results=PAID, mode="dm")
    assert "paid_ack" not in f


def test_saying_the_team_will_match_the_payment_is_not_an_acknowledgement():
    f = _f({"paid_ack"}, answer="Noted — the team will match your M-Pesa to order 1187 and confirm here.",
           tool_results=[], mode="dm")
    assert "paid_ack" not in f


def test_manufactured_urgency_or_scarcity_is_a_finding():
    for answer in ("Only 2 left — today only at KES 4,500!", "Hurry, this offer ends tonight.",
                   "Last piece in stock, don't miss out."):
        f = _f({"pressure"}, answer=answer, tool_results=[], mode="dm")
        assert "pressure" in f and f["pressure"]["hard"] is False, answer     # soft until the live tally is clean


def test_a_recorded_offer_from_a_promotion_tool_may_be_named():
    tools = [{"tool": "apply_offer", "input": {}, "out": {"ok": True, "offer": "Easter 10% off", "until": "2026-04-05"}}]
    f = _f({"pressure"}, answer="The Easter offer gives 10% off until 5 April.", tool_results=tools, mode="dm")
    assert "pressure" not in f


def test_a_recorded_campaign_discount_figure_is_the_figure_rules_business_not_this_rules():
    # "10% off" with the list and the discounted figures is judged by the figure rule
    # (every money figure from a hub row or a recorded promotion); the pressure rule
    # only reads the urgency words around it
    f = _f({"pressure"}, answer="Today's offer: 10% off — KES 22,000, now KES 19,800.", tool_results=[], mode="dm")
    assert "pressure" not in f


def test_an_honest_no_discount_is_not_pressure():
    f = _f({"pressure"}, answer="We don't offer discounts, but the price includes the cincture and collar.",
           tool_results=[], mode="dm")
    assert "pressure" not in f


def test_the_order_tool_surfaces_an_unread_promised_offer():
    from app.agent import tools as t
    src = inspect.getsource(t._create_order)
    assert "PROMISED OFFER UNVERIFIED" in src and 'result["offer_unverified"] = True' in src
    assert "no offer recorded beats no order created" in src     # the business rule stands


def test_the_meta_door_answers_502_when_capture_fails():
    from app.routers import meta_webhook as mw
    src = inspect.getsource(mw.receive_webhook)
    assert "acking anyway" not in src.split("_capture_comment_events")[0]
    assert "return Response(status_code=502)" in src


# ── verification pass 1: correct replies are not held ───────────────────────

@pytest.mark.parametrize("answer", [
    "We have not received your payment yet — could you share the M-Pesa code?",
    "Once your payment is confirmed, we start production.",
    "Your order ships as soon as the payment has been received.",
    "We received your M-Pesa? Not yet — the team checks and confirms here.",
])
def test_a_negated_or_conditional_payment_mention_is_not_an_acknowledgement(answer):
    assert not rv.paid_ack_without_source(answer, []), answer


def test_the_paid_acknowledgement_rule_runs_in_comment_mode_too():
    f = _f({"paid_ack"}, answer="Thank you for your payment, we start the work!", tool_results=[], mode="comment")
    assert "paid_ack" in f


@pytest.mark.parametrize("answer", [
    "No hurry, take your time.", "Please do not hurry, the offer is open all month.",
    "The last one we sent you was purple, same again?", "In the last few days we restocked the gold cope.",
    "The last unit of the previous batch was sold; a new batch arrives Monday.",
])
def test_kindness_and_plain_facts_are_not_pressure(answer):
    assert rv.manufactured_pressure(answer, []) is None, answer


def test_a_stock_figure_a_tool_returned_is_a_fact_not_pressure():
    rows = [{"tool": "search_catalog", "input": {}, "out": {"results": [{"name": "Cassock", "stock": 2}]}}]
    assert rv.manufactured_pressure("Only 2 left in stock in size 46.", rows) is None
    assert rv.manufactured_pressure("Only 2 left in stock in size 46.", []) == "Only 2 left"


def test_pressure_is_soft_for_now_and_the_exemption_list_names_real_tools():
    f = _f({"pressure"}, answer="Hurry, only 3 left!", tool_results=[], mode="dm")
    assert "pressure" in f and f["pressure"]["hard"] is False
    from app.agent import tools as t
    assert rv._PROMO_TOOLS <= set(t._HANDLERS)
