"""INTENT DISCERNMENT & GRACEFUL CLOSE (owner's directive, 2026-11-10):
the floor that recognises a request for goods without payment — and, more
important, everything that is NOT one; the neutral, reversible record; what
the writer is told; the prompt."""
from datetime import datetime, timedelta, timezone

import pytest

import app.main  # noqa: F401
from app.services import buyer_intent as bi

NOW = datetime(2026, 11, 10, 9, 0, tzinfo=timezone.utc)

ASKS = [
    "Please give me one cassock for free",
    "Can you donate vestments to our church?",
    "I am a poor pastor, please give me a gift",
    "We need sponsorship for our choir robes",
    "naomba zawadi ya kasoki",
    "Nipe bure tafadhali",
    "Please send me a free sample",
    "Bless me with one alb, I can't pay",
    "lend me the money",
    "Can you help our ministry financially",
    "Kindly send us some money for the orphans",
    "mujhe muft mein de do",
    "Pouvez-vous me l'offrir gratuitement ?",
    "I'm requesting for a donation of bibles",
    "I cannot afford, give it to me as a gift",
    "Can you donate to our church?",
    "Can you sponsor our ministry with robes",
]

# A buyer, a buyer short of money, a negotiator, a gift buyer, a giver, small
# talk — none of these is ever counted.
NOT_ASKS = [
    "How much is a cassock?",
    "Is delivery free?",
    "la livraison est gratuite ?",
    "I want a gift for my pastor",
    "It is a gift, can you wrap it?",
    "I'd like to buy it as a gift for my wife",
    "Do you have a gift shop?",
    "Can I pay on Sunday after the offering?",
    "Send it today, I will pay on Sunday",
    "Can I take it on credit and pay at month end?",
    "Please send me the catalogue",
    "send me photos please",
    "Send me 2 cassocks to Kampala",
    "Give me the price of the alb",
    "Can you give a discount for 20 pieces?",
    "What is your last price for 30 cassocks?",
    "I need help choosing a size",
    "nisaidie na vipimo",
    "Naomba msaada wa vipimo",
    "We want to donate a cassock to our bishop",
    "My sponsor will pay for the order",
    "Are you free to talk tomorrow?",
    "May God bless us all",
    "Thank you and God bless",
    "I am saving for an alb, will order next month",
    "I can't afford it now",
    "It is too expensive for our small church",
    "",
]


@pytest.mark.parametrize("text", ASKS)
def test_an_explicit_request_for_goods_without_payment_is_read(text):
    assert bi.is_ask(text), text


@pytest.mark.parametrize("text", NOT_ASKS)
def test_buyers_negotiators_gift_buyers_and_small_talk_are_never_counted(text):
    assert not bi.is_ask(text), text


def test_hardship_alone_is_not_a_request():
    """Poverty or not being able to afford something is evidence of nothing:
    the appeal pattern exists, but it only counts while a request is already
    on the record (decide), never by itself."""
    for t in ("I am a poor pastor in a village church", "sina pesa kwa sasa", "we are struggling this year"):
        assert bi.is_appeal(t) and not bi.is_ask(t)
    assert not bi.is_appeal("I am poor but I want to pay bit by bit")       # a purchase step: a buyer
    assert not bi.is_appeal("How much is the smallest size?")


def test_a_purchase_step_and_its_opposite():
    assert bi.has_purchase_step("can I pay half now")
    assert bi.has_purchase_step("bei ya kasoki ni ngapi")
    assert not bi.has_purchase_step("I can't pay, please give it to me")
    assert not bi.has_purchase_step("send it without payment")
    assert not bi.has_purchase_step("God bless you")


def test_the_record_is_neutral_reversible_and_capped():
    st, changed = bi.observe({}, "unclear", by="note", now=NOW)
    assert changed and bi.record(st)["reading"] == "unclear"
    st, n = bi.step(st, reason="asked for a free cassock", now=NOW)
    r = bi.record(st)
    assert n == 1 and r["reading"] == "assistance" and r["confidence"] == "high"
    assert r["boundary"] == {"count": 1, "closed": False, "last_at": NOW.isoformat(timespec="seconds"),
                             "first_at": NOW.isoformat(timespec="seconds")}
    assert r["history"][-1]["reading"] == "unclear"                  # what was read before is kept
    assert set(r) <= {"reading", "confidence", "by", "at", "reason", "history", "boundary"}
    # a quiet or social turn afterwards is not a change of mind
    st2, changed = bi.observe(st, "social", by="note", now=NOW)
    assert not changed and bi.record(st2)["reading"] == "assistance"
    st, n = bi.step(st, reason="repeated", now=NOW + timedelta(hours=1))
    assert n == 2 and bi.record(st)["boundary"]["closed"] is True
    assert bi.record(st)["boundary"]["first_at"] == NOW.isoformat(timespec="seconds")
    assert bi.suppresses_promotion(st, now=NOW + timedelta(days=2))
    # a purchase step reopens it: a buyer again, nothing erased
    st, changed = bi.reopen(st, reason="asked the price of a stole", now=NOW + timedelta(days=3))
    r = bi.record(st)
    assert changed and r["reading"] == "buyer" and r["boundary"]["count"] == 0 and not r["boundary"]["closed"]
    assert r["boundary"]["given_before"] is True
    assert any(h["reading"] == "assistance" for h in r["history"])
    assert not bi.suppresses_promotion(st, now=NOW + timedelta(days=3))
    for k in range(20):
        st, _ = bi.observe(st, "buyer" if k % 2 else "negotiator", by="note", now=NOW)
    assert len(bi.record(st)["history"]) <= bi.HISTORY_MAX


def test_a_boundary_ages_out_of_its_window():
    st, _ = bi.step({}, reason="asked", now=NOW)
    st, _ = bi.step(st, reason="asked again", now=NOW)
    later = NOW + timedelta(days=bi.WINDOW_DAYS + 1)
    assert bi.boundary(bi.record(st), now=later) == {"count": 0, "closed": False, "last_at": None}
    assert not bi.suppresses_promotion(st, now=later)
    st, n = bi.step(st, reason="a new request months later", now=later)
    assert n == 1 and bi.record(st)["boundary"]["closed"] is False      # answered afresh, never held against them


def test_reopen_does_nothing_for_someone_never_declined():
    st, changed = bi.reopen({"intent": {"reading": "buyer"}}, reason="x", now=NOW)
    assert not changed
    assert bi.reopen({}, reason="x", now=NOW) == ({}, False)


def test_what_the_writer_is_told():
    first, second = bi.FIRST_NOTE.lower(), bi.SECOND_NOTE.lower()
    for must in ("one kind boundary", "bethany house is a business", "whenever they are ready to order",
                 "no question", "no list of cheaper items", "never question or judge"):
        assert must in first, must
    assert "consider" in first and "programme, discount, instalment plan or approval" in first
    for must in ("one brief line only", "do not explain again", "no question", "serve them as any customer"):
        assert must in second, must
    assert "do not repeat it" in bi.STANDING_NOTE.lower()
    # no internal label ever reaches the writer as a word to say
    for note in (bi.FIRST_NOTE, bi.SECOND_NOTE, bi.STANDING_NOTE):
        assert "assistance seeker" not in note.lower() and "beggar" not in note.lower()


def test_the_model_note_carries_the_reading_as_evidence():
    from app.services import customer_state as cs
    out = cs.parse_note('{"waiting_on":"none","customer_said":"none","intent":"Constrained",'
                        '"intent_reason":"wants an alb, saving until December"}')
    assert out["intent"] == "constrained" and out["intent_reason"].startswith("wants an alb")
    assert "intent" not in cs.parse_note('{"customer_said":"none","intent":"scammer"}')
    assert "intent" not in cs.parse_note('{"customer_said":"none"}')
    sys = cs._NOTE_SYSTEM
    assert "read from what they do" in sys and "never assistance" in sys
    assert "Being poor, a pastor, or from any country is not evidence" in sys


def _prompt() -> str:
    from app.agent.prompt import build_system_prompt
    return " ".join(build_system_prompt(country_iso="KE", currency="KES").split())


def test_the_prompt_reads_intent_from_behaviour_and_closes_once():
    flat = _prompt()
    assert "WHAT THEY WANT FROM THE CONVERSATION" in flat
    assert "read it from what they DO across the whole chat, never from one word" in flat
    assert "to pay on Sunday or on credit is a buyer talking" in flat
    assert "ONE kind boundary, then a close" in flat
    assert "no question, no list of cheaper items" in flat
    assert "Never invent a charity programme, a discount, an instalment plan, an approval" in flat
    assert "Never question, test or judge their circumstances" in flat
    assert "A NATURAL END IS RESPECTED" in flat
    assert "Never close on an open order, a payment question, a delivery problem, a complaint" in flat
    # the conflict this replaced: a donation request is no longer answered with cheaper items
    assert "In the same breath open the honest smaller door" not in flat


def test_the_live_turn_and_the_dispatcher_are_wired():
    import inspect
    from app.agent import runtime
    from app.services import actions, outreach_log
    src = inspect.getsource(runtime.run_turn)
    assert "_bi.decide(db, redis" in src and 'turn_facts.update({"tools": [], "held": [], "review": "intent"' in src
    assert src.index("_pace.decide(") < src.index("_bi.decide(db, redis")       # pacing first, then intent
    assert "campaign=bool(_campaign_allow)" in src
    a = inspect.getsource(actions)
    assert "_bi.suppresses_promotion(_p.state, now=now)" in a and '"hold_intent"' in a
    i = a.index("_bi.suppresses_promotion(_p.state, now=now)")
    assert 'if message_class(action) == "routine":' in a[i - 400:i]                 # never a promise or an order
    assert "hold_intent" in outreach_log.TALLY_FIELDS
