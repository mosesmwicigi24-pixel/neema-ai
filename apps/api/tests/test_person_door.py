"""THE PERSON DOOR (owner's decision, 2026-11-07): an explicit request for a
human is routed before any model turn — human mode, the team flagged and
rung, one honest line in their language; out of hours or with nobody
available, the truth and the time the team is back. The detector is held to
ZERO matches on the readable case set's non-hand-over turns."""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

import app.main  # noqa: F401

POSITIVE = [
    "Can I talk to a real person please?", "I want to speak with a human", "Put me through to someone",
    "can someone call me", "I'd like to speak to an agent", "Please let me talk to the manager",
    "Nataka kuongea na mtu", "Je veux parler à quelqu'un", "Quero falar com uma pessoa", "No more bots please",
    "Am I talking to a robot? I want a real person",
]
NEGATIVE = [
    "How much is a cassock for one person?", "Does the tray serve 40 persons?", "Can I come in person to the shop?",
    "I want a personalised stole", "How much per person for the choir gowns?", "What's a person's size for a size 44?",
    "I want a cassock", "Talk to me about the chasuble prices", "Someone told me you sell trays",
    "Can I speak to you about a bulk order?", "Hi, I need a stole for my pastor",
    # a QUESTION about the bot gets an honest answer, not a hand-over (safe-039)
    "Is this a bot?", "Am I talking to a robot?", "Je wewe ni roboti?", "Est-ce un robot?",
]


@pytest.mark.parametrize("text", POSITIVE)
def test_explicit_requests_are_read(text):
    from app.services.intent import wants_a_person
    assert wants_a_person(text), text


@pytest.mark.parametrize("text", NEGATIVE)
def test_a_product_question_with_the_word_is_not_a_request(text):
    from app.services.intent import wants_a_person
    assert not wants_a_person(text), text


def test_zero_false_positives_on_the_readable_case_set():
    """Every turn of every readable file whose expected next action is NOT a
    hand-over must stay with Neema. (The blind file is left out: aggregates
    only, never read per case.)"""
    from app.jobs import eval_cases
    from app.services.intent import wants_a_person
    fired, total, caught, escalate_total = [], 0, 0, 0
    for c in eval_cases.load():
        for t in c["turns"]:
            nxt = (t.get("expect") or {}).get("next")
            if nxt == "escalate":
                escalate_total += 1
                caught += int(bool(wants_a_person(t["user"])))
            else:
                total += 1
                if wants_a_person(t["user"]):
                    fired.append((c["id"], t["user"]))
    assert not fired, fired
    assert total > 1000 and caught >= 1        # it reads the explicit ones, and only those


# ── the door ────────────────────────────────────────────────────────────────

class _Db:
    def __init__(self, available=1):
        self.added, self.commits, self.available = [], 0, available

    def add(self, row):
        self.added.append(row)

    async def commit(self):
        self.commits += 1

    async def execute(self, q):
        n = self.available

        class _R:
            def scalar(self):
                return n
        return _R()


class _Redis:
    def __init__(self):
        self.published = []

    async def publish(self, channel, message):
        self.published.append((channel, json.loads(message)))


def _conv(mode=None):
    from app.models.conversation import InterceptMode
    return SimpleNamespace(id="c1", wa_id="254700000009", external_id=None,
                           intercept_mode=InterceptMode(mode) if mode else None)


def _route(text, *, db=None, conv=None, now=None, hours="00-24"):
    from app.services import commitments as cm, person_door as pd
    cm.settings.commitment_staffed_hours = hours
    db, redis = db or _Db(), _Redis()
    conv = conv or _conv()
    ack = asyncio.run(pd.route(db, redis, conv, text, channel="whatsapp", key="254700000009",
                               now=now or datetime(2026, 11, 7, 9, 0, tzinfo=timezone.utc)))
    return ack, db, redis, conv


def test_the_door_sets_human_mode_flags_rings_and_acknowledges_in_their_language():
    from app.models.conversation import InterceptMode
    ack, db, redis, conv = _route("Can I talk to a real person please?")
    assert conv.intercept_mode == InterceptMode.human and db.commits == 1
    assert len(db.added) == 1 and "ASKED FOR A PERSON" in db.added[0].note
    assert [m["type"] for _, m in redis.published] == ["human_transfer"]
    assert ack == "Of course — a colleague will take over this chat shortly."
    ack, *_ = _route("Nataka kuongea na mtu")
    assert ack.startswith("Sawa — mwenzangu")
    ack, *_ = _route("Je veux parler à quelqu'un")
    assert ack.startswith("Bien sûr — un collègue")
    ack, *_ = _route("Quero falar com uma pessoa")
    assert ack.startswith("Claro — um colega")


def test_out_of_hours_or_nobody_available_is_said_plainly_with_the_time_back():
    night = datetime(2026, 11, 7, 20, 30, tzinfo=timezone.utc)                # 23:30 Nairobi
    ack, db, redis, _ = _route("I want to speak with a human", now=night, hours="07-21")
    assert "back at 07:00" in ack and "already with them" in ack
    assert "back at 07:00" in db.added[0].note and "back at 07:00" in redis.published[0][1]["body"]
    ack, *_ = _route("I want to speak with a human", db=_Db(available=0))     # staffed, nobody available
    assert "back at" in ack


def test_asking_again_while_waiting_re_rings_rather_than_being_ignored():
    ack, db, redis, conv = _route("Is this a bot? I want a person", conv=_conv("human"))
    assert "again" in redis.published[0][1]["title"] and "They asked again" in db.added[0].note
    assert ack


def test_the_door_runs_before_the_model_on_both_inbound_paths_and_in_the_runner():
    import inspect
    from app.agent import runtime as rt
    from app.jobs import eval_run
    for fn in (rt.schedule_reply, rt.schedule_meta_reply):
        if fn is None:
            continue
        src = inspect.getsource(fn)
        assert src.index("_intent.wants_a_person(text)") < src.index("closer_gate(")
    src = inspect.getsource(eval_run.run_cases)
    assert '"door": "person"' in src and src.index("wants_a_person") < src.index('"door": "closer"')
