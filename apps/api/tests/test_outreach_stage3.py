"""OUTBOUND COMMUNICATION, STAGE 3 — customer intelligence without a database:
the deterministic floor in three languages, the model note's parsing, what a
reading writes on the deal and the person, the live-turn note, the widened
customer-promise verbs, and the prompt's precedence for what THEY said."""
import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.services import customer_state as cs


def run(coro):
    return asyncio.run(coro)


# ── the floor ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("text,said", [
    ("Let me get back to you after I've thought about it", "needs_time"),
    ("Not now, give me some time", "needs_time"),
    ("Nitakujulisha baadaye", "needs_time"),
    ("Je reviens vers vous la semaine prochaine", "needs_time"),
    ("I am comparing prices with other suppliers in Arusha", "comparing"),
    ("Let me check other prices first", "comparing"),
    ("Nalinganisha bei na maduka mengine", "comparing"),
    ("Je dois comparer avec d'autres fournisseurs", "comparing"),
    ("I need to consult the bishop before I decide", "consulting"),
    ("Let me discuss it with my wife", "consulting"),
    ("Nitamuuliza mchungaji kwanza", "consulting"),
    ("Je dois en parler à l'évêque", "consulting"),
    ("I have already paid, check your Mpesa", "paid_claim"),
    ("Nimeshalipa", "paid_claim"),
    ("The chasuble arrived torn and I want a refund", "complaint"),
    ("Go ahead and place the order", "ready"),
    ("Please stop messaging me", "stop"),
    ("Usinitumie ujumbe tena", "stop"),
    ("Asante sana 🙏", "closing"),
])
def test_the_floor_reads_what_the_schedulers_must_never_miss(text, said):
    r = cs.floor(text)
    assert r and r["customer_said"] == said, (text, r)


@pytest.mark.parametrize("text", [
    "How much is the cassock set?", "Do you have it in purple?", "Bei ya stola?", "",
    "What about the price if I compare two sizes?",      # a question, not a state
])
def test_the_floor_stays_silent_on_ordinary_messages(text):
    assert cs.floor(text) is None


def test_the_floor_keeps_the_day_they_named():
    now = datetime(2026, 11, 5, 9, 0, tzinfo=timezone.utc)          # a Thursday
    r = cs.floor("I will consult the committee and contact you on Monday", now=now)
    assert r["customer_said"] == "consulting"
    assert r["hold_until"] and r["hold_until"].startswith("2026-11-09")


def test_a_named_time_alone_is_a_request_for_time():
    now = datetime(2026, 11, 5, 9, 0, tzinfo=timezone.utc)
    r = cs.floor("I will call you tomorrow about it", now=now)
    assert r["customer_said"] == "needs_time" and r["hold_until"].startswith("2026-11-06")


# ── language ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("text,lang", [
    ("How much is the stole please?", "en"),
    ("Habari, bei ya kanzu ni ngapi?", "sw"),
    ("Bonjour, combien coûte la chasuble?", "fr"),
    ("नमस्ते, कृपया मुझे कीमत बताएं", "hi"),
    ("السلام عليكم كم السعر", "ar"),
    ("ok", None),
])
def test_language_is_read_from_their_own_words(text, lang):
    assert cs.guess_language(text) == lang


def test_only_three_languages_are_automated():
    assert cs.automated_ok(None) and cs.automated_ok("en") and cs.automated_ok("sw") and cs.automated_ok("fr")
    assert not cs.automated_ok("hi") and not cs.automated_ok("ar")


# ── the model's note ─────────────────────────────────────────────────────────

def test_the_note_is_parsed_defensively():
    good = cs.parse_note('Sure: {"waiting_on":"customer","customer_said":"comparing",'
                         '"hold_until":"2026-11-10","language":"sw","open_item_check":"purple chasuble"}')
    assert good == {"waiting_on": "customer", "customer_said": "comparing", "hold_until": "2026-11-10",
                    "language": "sw", "open_item_check": "purple chasuble"}
    odd = cs.parse_note('{"customer_said":"buying now!!","hold_until":"next week","language":"swahili"}')
    assert odd["customer_said"] == "none" and odd["hold_until"] is None and odd["language"] is None
    assert cs.parse_note("no json here") is None and cs.parse_note("[1,2]") is None


def test_the_note_asks_a_light_model_with_no_tools_and_uses_the_floor_first(monkeypatch):
    calls = []

    class _LLM:
        async def complete(self, *, system, messages, tools):
            calls.append((system, messages, tools))
            return SimpleNamespace(text='{"waiting_on":"customer","customer_said":"comparing","language":"en"}')

    class _DB:
        async def get(self, model, pk): return None
        async def commit(self): pass
        async def execute(self, q): raise AssertionError("no transcript needed when one is given")

    conv = SimpleNamespace(id="c1", person_id=None)
    deal = SimpleNamespace(next_action=None, blocking=None)
    out = run(cs.after_turn(_DB(), conv, deal, inbound_text="Hmm, I saw cheaper ones in town",
                            reply="Understood.", transcript=[("customer", "hi")], llm=_LLM()))
    assert out["said"] == "comparing" and out["source"] == "note"
    assert calls and calls[0][2] == [] and "JSON" in calls[0][0]
    assert deal.next_action["hold"]["said"] == "comparing"
    # the floor answers first — no model call when the words are plain
    calls.clear()
    deal2 = SimpleNamespace(next_action=None, blocking=None)
    out = run(cs.after_turn(_DB(), conv, deal2, inbound_text="nitakujulisha", reply="Sawa.", llm=_LLM()))
    assert out["source"] == "floor" and not calls


def test_a_lone_sawa_never_flips_the_stored_language():
    # slice 7: the live floor stores guess_language(inbound) when the note has none;
    # a neutral "Sawa" from an English-speaking customer must leave "en" alone
    from types import SimpleNamespace
    person = SimpleNamespace(state={"contact_preferences": {"language": "en"}}, id="p1")

    class _DB:
        async def get(self, model, pk): return person
        async def commit(self): pass
        async def execute(self, q): raise AssertionError("no transcript needed")

    conv = SimpleNamespace(id="c1", person_id="p1")
    deal = SimpleNamespace(next_action=None, blocking=None)
    out = run(cs.after_turn(_DB(), conv, deal, inbound_text="Sawa", reply="Noted.", llm=None))
    assert person.state["contact_preferences"]["language"] == "en", out
    out = run(cs.after_turn(_DB(), conv, deal, inbound_text="Naweza kulipa kwa kadi?", reply="Ndiyo.", llm=None))
    assert person.state["contact_preferences"]["language"] == "sw", out


def test_no_note_without_a_key(monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "anthropic_api_key", "", raising=False)
    assert cs.note_llm() is None


# ── what a reading writes ────────────────────────────────────────────────────

class _DB:
    def __init__(self, person=None):
        self.person, self.commits = person, 0
    async def get(self, model, pk):
        return self.person
    async def commit(self):
        self.commits += 1


def test_a_hold_lands_on_the_deal_and_the_language_on_the_person():
    now = datetime(2026, 11, 5, 9, 0, tzinfo=timezone.utc)
    person = SimpleNamespace(state={"contact_preferences": {"language": "en"}})
    conv = SimpleNamespace(id="c", person_id="p")
    deal = SimpleNamespace(next_action={"kind": "customer_promise", "note": "x"}, blocking="Waiting on the customer")
    out = run(cs.apply(_DB(person), conv, deal, {"customer_said": "consulting", "hold_until": "2026-11-09"},
                       source="floor", inbound_text="Nitamuuliza askofu, nitakujulisha Jumatatu", now=now))
    assert out["hold_until"].startswith("2026-11-09T07:00")          # 10:00 Nairobi on their day
    assert deal.next_action["kind"] == "customer_promise"              # the scribe's row survives
    assert deal.next_action["hold"]["said"] == "consulting"
    assert deal.blocking.startswith("Consulting someone — until 09 Nov")
    assert person.state["contact_preferences"]["language"] == "sw" and out["language"] == "sw"
    assert person.state["customer_state"]["said"] == "consulting"
    assert cs.hold_open(deal, now=now) == (datetime(2026, 11, 9, 7, 0, tzinfo=timezone.utc), "consulting")
    assert cs.hold_open(deal, now=now + timedelta(days=5)) is None     # over once the day has passed


def test_a_bare_request_for_time_holds_a_week_and_a_real_message_clears_it():
    now = datetime(2026, 11, 5, 9, 0, tzinfo=timezone.utc)
    deal = SimpleNamespace(next_action=None, blocking=None)
    conv = SimpleNamespace(id="c", person_id=None)
    run(cs.apply(_DB(), conv, deal, {"customer_said": "needs_time"}, source="floor",
                 inbound_text="give me some time", now=now))
    until, _ = cs.hold_open(deal, now=now)
    assert until == datetime(2026, 11, 12, 7, 0, tzinfo=timezone.utc)
    assert deal.blocking.startswith("Asked for time")
    run(cs.apply(_DB(), conv, deal, {"customer_said": "quoting"}, source="note",
                 inbound_text="Actually, how much is the stole?", now=now + timedelta(days=1)))
    assert cs.hold_open(deal, now=now + timedelta(days=1)) is None and deal.blocking is None


def test_a_payment_claim_is_noted_never_believed_and_a_team_check_survives():
    now = datetime(2026, 11, 5, 9, 0, tzinfo=timezone.utc)
    deal = SimpleNamespace(next_action={"kind": "team_check", "item": "purple chasuble",
                                        "until": (now + timedelta(days=7)).isoformat()}, blocking="x")
    conv = SimpleNamespace(id="c", person_id=None)
    out = run(cs.apply(_DB(), conv, deal, {"customer_said": "paid_claim"}, source="floor",
                       inbound_text="I have already paid", now=now))
    assert out["paid_claim"] and deal.blocking.startswith("Says they have paid")
    assert deal.next_action["kind"] == "team_check"
    assert not hasattr(deal, "paid") and "paid" not in (deal.next_action or {})


def test_the_live_turn_note_says_what_stands():
    now = datetime(2026, 11, 5, 9, 0, tzinfo=timezone.utc)
    deal = SimpleNamespace(next_action={"hold": {"until": "2026-11-09T07:00:00+00:00", "said": "comparing"}},
                           blocking=None)
    note = cs.turn_note(deal, None, now=now)
    assert note.startswith("(CUSTOMER STATE:") and "comparing prices" in note and "Monday 09 Nov" in note
    assert "do NOT ask again when they will decide" in note
    assert cs.turn_note(SimpleNamespace(next_action=None, blocking=None), None, now=now) is None
    paid = SimpleNamespace(next_action=None, blocking="Says they have paid — awaiting the hub")
    assert "never announce it as received" in cs.turn_note(paid, None, now=now)


# ── the widened customer promise ─────────────────────────────────────────────

@pytest.mark.parametrize("text", [
    "I will contact you on Thursday", "I'll call you tomorrow", "We will message you next week",
    "I will remind you on Monday", "I'll be in touch on Friday", "I will come back to you after the meeting",
])
def test_contact_verbs_are_customer_promises(text):
    from app.services.deals import detect_customer_promise
    assert detect_customer_promise(text, now=datetime(2026, 11, 5, 9, 0, tzinfo=timezone.utc)) is not None


# ── the prompt ───────────────────────────────────────────────────────────────

def test_what_they_said_outranks_discovery_and_the_close():
    import app.main  # noqa: F401
    from app.agent.prompt import build_system_prompt
    p = build_system_prompt(country_iso="KE", currency="KES")
    i = p.index("WHEN RULES COLLIDE")
    block = " ".join(p[i:i + 1600].split())
    assert block.index("4. Answer what they actually asked") < block.index("5. What THEY said about buying") \
        < block.index("6. Discovery and the close") < block.index("7. Extras last")
    assert "The system returns on the day they named; you never chase" in block


# ── the scribe hook ──────────────────────────────────────────────────────────

def test_the_scribe_files_the_state_after_its_own_commit():
    import inspect
    from app.services import deals
    src = inspect.getsource(deals.scribe_update)
    assert "customer_state.after_turn" in src
    assert src.index("await db.commit()") < src.index("customer_state.after_turn(db, conv, deal")
    assert "not holding" in src                                        # a request for time opens the deal


def test_the_dispatcher_holds_before_it_decides_and_parks_other_languages():
    import inspect
    from app.services import actions
    src = inspect.getsource(actions.process_due)
    assert src.index("_cs.hold_for(") < src.index("await decide(db, conv, action, now=now)")
    assert "a person should write this" in src


def test_the_live_turn_reads_the_state():
    import inspect
    from app.agent import runtime
    assert "_cs.live_note(db, key, channel)" in inspect.getsource(runtime.run_turn)


def test_the_inbox_row_shows_it():
    import inspect
    from app.routers import admin
    src = inspect.getsource(admin)
    assert '"customer_state":' in src and '"language":' in src
