"""Slice 11 — Commercial Emotional Intelligence: the come-back turn.

The Johana case (owner, 2026-11-07): after a quote for a clergy collar the
customer wrote "Waiting I will come back you Asap." and Neema answered
"Thank you, Johana, take all the time you need. Is there a day you'd like me
to check back with you?" — polite, disengaged, and a question the customer
had just answered. The cause was the prompt's own rule (step 2 asked for a
day) and a scorer that never penalised the first such ask. These tests pin
the corrected behaviour at every deterministic layer: the floor's reading,
the prompt's instruction, the length and pressure gates on the owner's
preferred reply, and the evaluation scorer's verdict on both replies."""
from __future__ import annotations

import pytest

JOHANA = "Waiting I will come back you Asap."
OWNER_REPLY = ("Sure, Johana. I'd be happy to help you get the right collar. Just send me "
               "your preferred size when you're back, and we'll get your order sorted.")
PRODUCTION_REPLY = ("Thank you, Johana, take all the time you need. Is there a day you'd "
                    "like me to check back with you?")


def _case():
    return {"id": "x", "categories": [], "lang": "en"}


def _turn(user, nxt="hold_ack"):
    return {"user": user, "expect": {"next": nxt}}


def test_the_floor_reads_the_johana_message_as_a_request_for_time():
    from app.services.customer_state import floor, HOLD_STATES
    r = floor(JOHANA) or {}
    assert r.get("customer_said") == "needs_time" and "needs_time" in HOLD_STATES


@pytest.mark.parametrize("text,state", [
    ("I'll confirm later", "needs_time"), ("I'll confirm tomorrow", "needs_time"),
    ("I'll update you next week", "needs_time"),
    ("Let me consult.", "consulting"), ("ok let me consult first", "consulting"),
    ("I have to consult", "consulting"),
])
def test_the_stage_nine_phrasings_the_floor_missed_are_now_read(text, state):
    from app.services.customer_state import floor
    assert (floor(text) or {}).get("customer_said") == state, text


@pytest.mark.parametrize("text", [
    "I'll confirm the size now", "Let me consult the size chart you sent",
    "I'll confirm", "ok let me consult the bishop",
])
def test_a_confirmation_now_or_a_named_consultee_is_not_misread(text):
    from app.services.customer_state import floor
    said = (floor(text) or {}).get("customer_said")
    if text.endswith("bishop"):
        assert said == "consulting"
    else:
        assert said != "needs_time", text


@pytest.mark.parametrize("text", ["Give me a moment", "Please wait", "hold on, sending the photo"])
def test_a_moment_is_not_a_hold(text):
    """Cautious by design: 'give me a moment' usually precedes a photo or a
    detail, not a decision. No hold, no outreach block, the prompt reads
    the room instead."""
    from app.services.customer_state import floor
    assert (floor(text) or {}).get("customer_said") not in ("needs_time", "consulting", "comparing")


def test_the_prompt_no_longer_asks_for_a_check_in_day_and_keeps_the_item():
    from app.agent.prompt import build_system_prompt
    p = build_system_prompt(country_iso="KE", currency="KES")
    assert "Is there a day we should check back with you?" not in p
    assert "Shall I remind you at the end of the month?\"" not in p.replace("habit here, \"Shall", "")
    assert "NEVER ask when to remind them" in p
    assert "KEEP THE ITEM" in p and "NAME THE ONE STEP" in p
    assert "A FIRM DECLINE" in p
    # the check-in tool is still booked on a named time — the promise is kept
    assert "call `schedule_check_in` with it IN THE SAME TURN" in p


def test_the_owners_reply_passes_the_brevity_and_pressure_gates():
    from app.agent import reply_length as rl, review as rv
    from app.agent.runtime import length_target_for
    tgt = length_target_for(JOHANA)
    assert rl.is_long(OWNER_REPLY, tgt) is None
    assert rv.manufactured_pressure(OWNER_REPLY, None) is None


def test_the_scorer_fails_the_production_reply_and_passes_the_owners():
    from app.jobs import eval_run
    facts = {"tools": []}
    v = eval_run.check_turn(_case(), 0, _turn(JOHANA), PRODUCTION_REPLY, facts,
                            opted_out=False, intercept_mode="ai", after_hold=False)
    assert "asked for a check-in date the customer did not offer" in v["failures"]
    v = eval_run.check_turn(_case(), 0, _turn(JOHANA), OWNER_REPLY, facts,
                            opted_out=False, intercept_mode="ai", after_hold=False)
    assert v["passed"], v["failures"]


@pytest.mark.parametrize("reply", [
    "Thank you, we'll be here when you're ready. Is there a day you'd like us to check back with you?",
    "Of course. Which day suits you?",
    "Sure. Shall I remind you at the end of the month?",
    "Take your time. When would you like me to follow up with you?",
])
def test_every_shape_of_the_unprompted_reminder_is_caught(reply):
    from app.jobs.eval_run import asks_for_a_check_in
    assert asks_for_a_check_in(reply)


@pytest.mark.parametrize("reply", [
    "Noted — I'll check back with you on Friday as you asked.",        # a statement on THEIR day
    "Happy to help with the collar; just send your size when you're back.",
    "Sure. Would you like the 10-inch or the 8-inch?",                # a product question is not a reminder ask
])
def test_a_statement_on_their_day_or_a_product_question_is_not_a_reminder_ask(reply):
    from app.jobs.eval_run import asks_for_a_check_in
    assert not asks_for_a_check_in(reply)


def test_the_experience_flag_names_the_unprompted_ask():
    from app.jobs.agent_eval import experience_checks
    flags = experience_checks(PRODUCTION_REPLY, JOHANA, after_hold=False)
    assert "ASKED FOR A CHECK-IN DATE THEY DID NOT OFFER" in flags
    assert not [f for f in experience_checks(OWNER_REPLY, JOHANA, after_hold=False) if "DATE" in f]


def test_the_live_turn_note_on_an_open_hold_still_forbids_the_re_ask():
    """Stage 3B's note to the next live turn is the runtime half of the same
    rule: an open hold says do NOT ask again when they will decide."""
    from datetime import datetime, timedelta, timezone
    from types import SimpleNamespace
    from app.services.customer_state import turn_note
    until = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat(timespec="seconds")
    deal = SimpleNamespace(next_action={"hold": {"until": until, "said": "needs_time",
                                                 "since": datetime.now(timezone.utc).isoformat()}},
                           blocking="Asked for time — until x")
    note = turn_note(deal, None) or ""
    assert "do NOT ask again when they will decide" in note
