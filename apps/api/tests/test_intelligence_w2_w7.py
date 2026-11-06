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
    """Behaviour: the live turn's own target function. A complaint the
    comment detector misses but the customer-state floor reads still lands
    on the care-first length; a plain price ask does not."""
    text = "The cassock you sent me is torn at the seam and I paid in full. This is not acceptable."
    assert cs.floor(text)["customer_said"] == "complaint"
    target = rt.length_target_for(text)
    assert target["kind"] == "complaint" and target["words"] == 60
    assert rt.length_target_for("How much is the stole?")["kind"] != "complaint"
    assert rt.length_target_for(None)["kind"] != "complaint"              # no text, no crash
    # the evaluation harness scores the same function, not a mirror of it
    from app.jobs.eval_floors import _runtime_target
    assert _runtime_target(text) == target


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


@pytest.mark.asyncio
async def test_state_writes_take_the_row_lock(monkeypatch):
    """Behaviour: both writers of persons.state hand the person to the lock
    and write to the row the lock hands back (locked AND re-read)."""
    import types
    from app.services import intent, state_lock

    locked, fresh = [], types.SimpleNamespace(id="p", state={"contact_preferences": {"language": "en"}})
    stale = types.SimpleNamespace(id="p", state={"contact_preferences": {"language": "en"}})

    async def fake_lock(db, row):
        locked.append(row)
        return fresh
    monkeypatch.setattr(state_lock, "lock_for_write", fake_lock)

    class _DB:
        def __init__(self): self.added = []
        async def get(self, model, pk): return stale
        async def commit(self): pass
        async def rollback(self): pass
        def add(self, o): self.added.append(o)

    conv = types.SimpleNamespace(id="c", person_id="p", channel="whatsapp", wa_id="254700000001")
    await cs.apply(_DB(), conv, None, {"customer_said": "needs_time"}, source="floor",
                   inbound_text="Nitakujulisha Jumatatu")
    assert locked == [stale]
    assert fresh.state["customer_state"]["said"] == "needs_time"       # written to the re-read row
    assert "customer_state" not in stale.state                            # not to the stale copy

    locked.clear()
    await intent.record_opt_out(_DB(), None, conv, "stop messaging me", channel="whatsapp", key="254700000001")
    assert locked == [stale]
    assert fresh.state["contact_preferences"]["opt_out"]["said"] == "stop messaging me"
    assert "opt_out" not in stale.state["contact_preferences"]


@pytest.mark.asyncio
async def test_an_opt_out_still_lands_when_the_lock_cannot_be_taken(monkeypatch):
    """Recorded trade-off (W7-6): a lock failure is logged and the write goes
    ahead unlocked — a lost opt-out would be the worse failure."""
    import types
    from app.services import intent, state_lock

    async def broken_lock(db, row):
        raise RuntimeError("lock unavailable")
    monkeypatch.setattr(state_lock, "lock_for_write", broken_lock)
    person = types.SimpleNamespace(id="p", state={})

    class _DB:
        async def get(self, model, pk): return person
        async def commit(self): pass
        async def rollback(self): pass
        def add(self, o): pass

    conv = types.SimpleNamespace(id="c", person_id="p", channel="whatsapp", wa_id="254700000001")
    await intent.record_opt_out(_DB(), None, conv, "stop", channel="whatsapp", key="254700000001")
    assert person.state["contact_preferences"]["opt_out"]["said"] == "stop"


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


def test_the_scribe_keeps_the_team_check_when_the_customer_names_a_day(monkeypatch):
    """Behaviour (W2-4 wiring): scribe_update itself, with a deal that holds an
    open team check, filing a customer promise — the team check stays the
    next action and the promise is tucked under it."""
    import asyncio
    import types
    from app.agent import cart as cartmod
    from app.services import customer_state

    conv = types.SimpleNamespace(id="conv1", person_id="p1")
    deal = types.SimpleNamespace(next_action={"kind": "team_check", "item": "gold cope",
                                              "since": "2026-11-06T10:00:00"},
                                 blocking="Checking with the team: gold cope",
                                 items_snapshot=None, title=None, stage="new")
    queued = []

    class _DB:
        def add(self, o): pass
        async def flush(self): pass
        async def commit(self): pass
        async def rollback(self): pass

    async def fake_conv(db, key, channel): return conv
    async def fake_open(db, conversation_id=None, person_id=None): return deal
    async def fake_cart(db, key, channel="whatsapp"): return {"items": []}
    async def fake_upsert(db, d, *, due_at, kind, reason): queued.append(kind)
    async def fake_after_turn(*a, **k): return {}
    monkeypatch.setattr(deals, "_conversation_of", fake_conv)
    monkeypatch.setattr(deals, "open_deal_for", fake_open)
    monkeypatch.setattr(cartmod, "get_cart", fake_cart)
    monkeypatch.setattr("app.services.actions.upsert_follow_up", fake_upsert)
    monkeypatch.setattr(customer_state, "after_turn", fake_after_turn)

    asyncio.run(deals.scribe_update(_DB(), "254700000001", "whatsapp", "Sawa, tutaongea Jumatatu.",
                                    inbound_text="I will confirm on Monday", tools=[]))
    assert queued == ["customer_promise"]
    assert deal.next_action["kind"] == "team_check" and deal.next_action["item"] == "gold cope"
    assert deal.next_action["then"]["kind"] == "customer_promise"
    assert deal.blocking.startswith("Waiting on the customer")


def test_usage_logs_the_model_that_actually_served():
    """Behaviour (W10-3): after a fallback the client's last_model differs
    from its configured _model, and that is the one that gets logged."""
    import types
    assert rt.served_model(types.SimpleNamespace(_model="claude-a", last_model="claude-b")) == "claude-b"
    assert rt.served_model(types.SimpleNamespace(_model="claude-a", last_model=None)) == "claude-a"
    assert rt.served_model(types.SimpleNamespace()) == ""
