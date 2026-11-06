"""Workstream 1/4 (intelligence programme, 2026-11-06): a payment
acknowledgement needs the hub's word, manufactured urgency never passes, a
promised offer that cannot be read is surfaced, and the Meta door does not
ack a message it lost."""
from __future__ import annotations

import inspect

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


def test_manufactured_urgency_or_scarcity_is_a_hard_finding():
    for answer in ("Only 2 left — today only at KES 4,500!", "Hurry, this offer ends tonight.",
                   "Last piece in stock, don't miss out."):
        f = _f({"pressure"}, answer=answer, tool_results=[], mode="dm")
        assert "pressure" in f and f["pressure"]["hard"], answer


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
