"""Intelligence programme, 2026-11-06 — the small corrections from the
investigation report: silence is honoured, a hold lifts when the customer
comes back, the scribe never erases a team check, a handoff rings the team,
a photo stays in history, a complaint earns the care-first length, language
continuity has a deterministic check, state writes take the lock."""
from __future__ import annotations

import pytest

import inspect

from app.agent import review as rv
from app.agent import runtime as rt
from app.services import customer_state as cs
from app.services import deals


def test_the_turn_honours_an_empty_reply_on_an_overlap_or_a_closer():
    src = inspect.getsource(rt.run_turn)
    assert "_overlap_noted = True" in src and "if not reply and (_overlap_noted or is_closer(user_text or \"\")):" in src
    # the stall line is still the last resort for a real question, never for silence
    assert src.index("empty reply honoured as silence") < src.index('"One moment — let me check on that for you."')


def test_a_question_or_a_buying_signal_lifts_a_hold():
    assert cs._buying_message("How much is the stole?")
    assert cs._buying_message("I want to order the cassock set now")
    assert not cs._buying_message("")
    src = inspect.getsource(cs.apply)
    assert "_buying_message(inbound_text)" in src


def test_the_scribe_keeps_a_team_check_and_a_hold_when_it_files_a_promise():
    cur = {"kind": "team_check", "item": "gold cope", "since": "2026-11-06T10:00:00",
           "hold": {"until": "2026-11-13T07:00:00", "said": "needs_time"}}
    new = {"kind": "follow_up", "owner": "ai", "due_at": "2026-11-06T13:00:00", "note": "I'll check"}
    out = deals._merge_next_action(cur, new)
    assert out["kind"] == "team_check" and out["item"] == "gold cope"
    assert out["then"] == new and out["hold"]["said"] == "needs_time"
    # no team check: the new intent leads, the hold survives
    out2 = deals._merge_next_action({"hold": cur["hold"], "kind": "follow_up"}, new)
    assert out2["kind"] == "follow_up" and out2["hold"] == cur["hold"]
    assert deals._merge_next_action(None, new) == new


def test_the_handoff_tool_rings_the_team():
    from app.agent import tools as t
    src = inspect.getsource(t._handoff_to_human)
    assert "_team_note(" in src and '"team_told": told' in src and "if not ctx.read_only" in src


def test_a_caption_less_photo_is_a_turn_in_history():
    src = inspect.getsource(rt._history)
    assert "[the customer sent a photo]" in src and "MsgDirection.inbound" in src


def test_a_complaint_read_by_the_floor_earns_the_care_first_length():
    src = inspect.getsource(rt.run_turn)
    assert '(_cs_floor(user_text) or {}).get("customer_said") == "complaint"' in src


def test_language_continuity_is_checked_without_the_model_reviewer():
    assert rv.language_mismatch("नमस्ते, कोप सेट की कीमत क्या है?", "The cope set is KES 45,000.") == "hi"
    assert rv.language_mismatch("नमस्ते, कीमत क्या है?", "नमस्ते! कोप सेट की कीमत KES 45,000 है।") is None
    assert rv.language_mismatch("Habari, bei ya stola ni ngapi? Nataka mbili za zambarau.",
                                "The stole is KES 2,500 each, so two would be KES 5,000. Shall I add them?") == "sw"
    assert rv.language_mismatch("Habari, bei ya stola?", "Stola ni KES 2,500, karibu sana.") is None
    assert rv.language_mismatch("Bonjour, le prix de la chasuble violette, s'il vous plaît ?",
                                "The purple chasuble is USD 120 and ships by DHL in a week.") == "fr"
    assert rv.language_mismatch("Thanks, how much?", "Bei ni KES 2,500.") is None     # English left alone
    out = rv.rule_findings("Habari, bei ya stola ni ngapi? Nataka mbili za zambarau.",
                           "The stole is KES 2,500 each, so two would be KES 5,000. Shall I add them?",
                           [], tool_results=[], mode="dm")
    kinds = {o["kind"]: o for o in out}
    assert "language" in kinds and not kinds["language"]["hard"]


def test_state_writes_take_the_row_lock():
    from app.services import intent
    assert "lock_for_write(db, person)" in inspect.getsource(intent.record_opt_out)
    assert "lock_for_write(db, person)" in inspect.getsource(cs.apply)


def test_the_standing_orders_cap_keeps_the_newest_learned_rules():
    from app.agent.prompt import _cap_standing_orders, _LEARNED_HEADER
    orders = "Push copes this week. " * 25                      # ~550 chars
    rules = "\n".join(f"- rule {i}: " + "x" * 40 for i in range(40))   # ~2,000 chars
    text = orders + _LEARNED_HEADER + " (approved from experience — follow them):\n" + rules
    out = _cap_standing_orders(text, 1800)
    assert len(out) <= 1800
    assert out.startswith(orders)                       # the standing orders are whole
    assert "- rule 39:" in out and "- rule 0:" not in out   # newest kept, oldest dropped
    assert _cap_standing_orders("short", 1800) == "short"


@pytest.mark.asyncio
async def test_apply_lifts_a_hold_when_the_customer_asks_a_question():
    """Behaviour, not source: a deal on hold, a real question, the hold is gone."""
    import types

    class _DB:
        async def commit(self):
            pass
    deal = types.SimpleNamespace(next_action={"kind": "follow_up", "hold": {"until": "2026-11-13T07:00:00", "said": "needs_time"}},
                                 blocking="Asked for time — until 13 Nov")
    conv = types.SimpleNamespace(person_id=None)
    changed = await cs.apply(_DB(), conv, deal, {"customer_said": "none"}, source="floor",
                             inbound_text="How much is the stole?")
    assert changed.get("hold_cleared") is True
    assert "hold" not in (deal.next_action or {}) and deal.blocking is None
