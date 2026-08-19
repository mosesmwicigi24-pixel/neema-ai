"""Neema learns the house voice from the team's OWN replies (owner, 2026-08-19).

The owner's observation, reviewing the humans' intercepts: "human responses
are not as big, not too much depth, but accurate" — 'The roman collar shirt
goes for 2500' closes a question that Neema, rules and all, answers in three
sentences. Rules describe the voice; the team's messages ARE the voice.

app.tools.stylebook reads the human replies, pairs each with the customer
message it answered, measures the honest length target, picks a spread of
real exchanges by question kind, and stores the block; the prompt injects it
beside the brevity contract. Deterministic, zero model cost, rerunnable.
"""
import asyncio
import types
from datetime import datetime, timedelta, timezone

import app.main  # noqa: F401 — registers models
import app.tools.stylebook as stylebook
from app.tools.stylebook import (bucket_of, choose_exemplars, render_block,
                                 usable_answer, usable_question)


# ── what counts as a learnable answer ────────────────────────────────────────

def test_the_hallmark_reply_is_learnable():
    assert usable_answer("The roman collar shirt goes for 2500")


def test_notes_media_links_and_letters_are_not():
    assert not usable_answer("🤝 Handoff briefing\n\n- the sale stands…")
    assert not usable_answer("[image]")
    assert not usable_answer("see https://bethanyhouse.co.ke/catalog")
    assert not usable_answer("")
    assert not usable_answer("word " * 61)          # a letter, not a reply


def test_questions_need_text_too():
    assert usable_question("How much is the cassock?")
    assert not usable_question("[image]") and not usable_question("  ")


# ── the questions customers actually ask, bucketed ───────────────────────────

def test_buckets_speak_both_languages():
    assert bucket_of("How much is the cassock?") == "price"
    assert bucket_of("Cassock ni bei gani? pesa ngapi") == "price"
    assert bucket_of("Do you have ropes") == "availability"
    assert bucket_of("Can you deliver to Ghana?") == "delivery"
    assert bucket_of("Nimelipa na mpesa") == "payment"
    assert bucket_of("What size should I take?") == "measurements"
    assert bucket_of("Asante sana, God bless") == "thanks"
    assert bucket_of("Habari yako") == "greeting"
    assert bucket_of("hello") == "greeting"          # short + no other cue


# ── selection: a SPREAD, newest first, no duplicates ─────────────────────────

def _pair(q, a, kind, days_ago=0):
    return {"q": q, "a": a, "kind": kind,
            "at": datetime.now(timezone.utc) - timedelta(days=days_ago)}


def test_one_busy_bucket_cannot_crowd_out_the_rest():
    pairs = [_pair(f"price q{i}", f"price a{i}", "price", i) for i in range(20)]
    pairs += [_pair("do you have it", "Yes, available", "availability", 1),
              _pair("deliver to Kisumu?", "We deliver countrywide", "delivery", 2)]
    chosen = choose_exemplars(pairs, cap=6)
    kinds = [p["kind"] for p in chosen]
    assert "availability" in kinds and "delivery" in kinds
    assert kinds.count("price") <= 4


def test_duplicate_answers_collapse():
    pairs = [_pair("q1", "Karibu sana!", "greeting", 0),
             _pair("q2", "karibu   sana", "greeting", 1),
             _pair("q3", "Karibu sana.", "greeting", 2)]
    assert len(choose_exemplars(pairs)) == 1


# ── the stored block ─────────────────────────────────────────────────────────

def test_the_block_targets_the_teams_length_and_names_the_gap():
    ex = [_pair("How much?", "The roman collar shirt goes for 2500", "price")]
    block = render_block(ex, human_wc=[10, 14, 14, 18, 20], ai_wc=[38, 40, 44])
    assert "median of 14 words" in block
    assert "recent AI replies ran 40" in block
    assert 'They asked: "How much?"' in block
    assert 'the team answered: "The roman collar shirt goes for 2500"' in block


def test_no_exemplars_means_no_block_and_no_gap_line_when_ai_is_already_lean():
    assert render_block([], [10], [40]) == ""
    ex = [_pair("q", "a b c", "other")]
    assert "close that gap" not in render_block(ex, [20, 20, 20, 20], [12, 14])


def test_the_block_never_outgrows_its_cap():
    ex = [_pair(f"question {i} " * 8, f"answer {i} " * 20, "other", i)
          for i in range(40)]
    block = render_block(ex, [10] * 10, [])
    assert len(block) <= stylebook.MAX_BLOCK_CHARS


# ── pairing: the reply learns which question it answered ─────────────────────

def test_collect_pairs_matches_the_question_and_skips_notes(monkeypatch):
    from app.models.message import MsgDirection, MsgSender
    now = datetime.now(timezone.utc)
    conv = "c1"

    def _msg(text, sender, direction, minutes_ago, media_type=None):
        return types.SimpleNamespace(
            text=text, sender=sender, direction=direction, media_type=media_type,
            conversation_id=conv, created_at=now - timedelta(minutes=minutes_ago))

    human = [
        _msg("The roman collar shirt goes for 2500", MsgSender.human_agent,
             MsgDirection.outbound, 5),
        _msg("🤝 Handoff briefing\n\n- …", MsgSender.human_agent,
             MsgDirection.outbound, 4, media_type="note"),
    ]
    inbound = [
        _msg("[image]", MsgSender.user, MsgDirection.inbound, 20),
        _msg("How much is the roman collar shirt?", MsgSender.user,
             MsgDirection.inbound, 10),
    ]
    ai = []

    class _Res:
        def __init__(self, rows):
            self._rows = rows

        def scalars(self):
            return types.SimpleNamespace(all=lambda: list(self._rows))

    class _DB:
        def __init__(self):
            self.calls = 0

        async def execute(self, *a, **k):
            self.calls += 1
            return _Res([human[0], human[1]] if self.calls == 1
                        else ai if self.calls == 2 else inbound)

    pairs, human_wc, ai_wc = asyncio.run(stylebook.collect_pairs(_DB()))
    assert len(pairs) == 1
    assert pairs[0]["q"].startswith("How much is the roman collar")
    assert pairs[0]["a"] == "The roman collar shirt goes for 2500"
    assert pairs[0]["kind"] == "price"
    assert human_wc == [7], "the note leaked into the length statistics"


# ── the prompt carries the voice ─────────────────────────────────────────────

def test_the_prompt_injects_the_house_voice_beside_the_style_rules():
    from app.agent.prompt import build_system_prompt
    block = ('- The team\'s replies run a median of 14 words…\n'
             '- They asked: "How much?" — the team answered: "KES 2,500."')
    p = build_system_prompt(currency="KES", house_voice=block)
    assert "THE HOUSE VOICE — REAL ANSWERS FROM OUR TEAM" in p
    assert 'the team answered: "KES 2,500."' in p
    # the examples teach form, never facts
    assert "never from these examples" in p
    # placed with the style rules, before the brevity contract
    assert p.index("THE HOUSE VOICE") < p.index("STYLE — THE BREVITY CONTRACT")


def test_an_empty_voice_leaves_the_prompt_untouched():
    from app.agent.prompt import build_system_prompt
    assert "HOUSE VOICE" not in build_system_prompt(currency="KES")


def test_the_shared_cache_invariant_holds():
    """Same block for every customer in a market bucket — byte-identical, so
    the fleet still reads ONE shared cache entry."""
    from app.agent.prompt import build_system_prompt
    a = build_system_prompt(currency="KES", house_voice="- exemplars here")
    b = build_system_prompt(currency="KES", house_voice="- exemplars here")
    assert a == b


def test_runtime_fetches_it_best_effort():
    import inspect
    import app.agent.runtime as runtime
    src = inspect.getsource(runtime)
    assert "get_house_voice" in src and "house_voice=_house" in src


def test_the_settings_read_is_cached_like_the_directives(monkeypatch):
    from app.services import app_settings as aps

    class _R:
        def __init__(self):
            self.kv = {}

        async def get(self, k):
            return self.kv.get(k)

        async def set(self, k, v, ex=None):
            self.kv[k] = v

    class _DB:
        def __init__(self):
            self.reads = 0

    async def _gv(db, key):
        db.reads += 1
        assert key == "house_voice"
        return "- the block"
    monkeypatch.setattr(aps, "get_value", _gv)

    r, db = _R(), _DB()
    assert asyncio.run(aps.get_house_voice(db, r)) == "- the block"
    assert asyncio.run(aps.get_house_voice(db, r)) == "- the block"
    assert db.reads == 1, "the second read should come from cache"


def test_the_tools_queries_compile_outside_the_app_process():
    """The first live run died compiling its very first query: Message's
    relationship to 'Conversation' resolves only once the model registry is
    imported, and the in-process tests (which import app.main globally) could
    never see it missing. A fresh interpreter that imports ONLY the stylebook
    module must be able to compile a select over Message — no database needed:
    mapper configuration happens at compile time, which is exactly where the
    box fell over."""
    import os
    import subprocess
    import sys
    api_dir = os.path.join(os.path.dirname(__file__), "..")
    code = (
        "import app.tools.stylebook\n"
        "from sqlalchemy import select\n"
        "from sqlalchemy.dialects import postgresql\n"
        "from app.models.message import Message\n"
        "select(Message).compile(dialect=postgresql.dialect())\n"
        "print('compiled')\n"
    )
    out = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True, text=True, timeout=120,
        cwd=api_dir, env={**os.environ, "PYTHONPATH": api_dir})
    assert out.returncode == 0, f"query would not compile:\n{out.stderr[-2000:]}"
    assert "compiled" in out.stdout


# ── the owner's own coaching, written into the standing rules ─────────────────
# 2026-08-19, the Malakhi Benya comment thread: he asked "How can I order it"
# and Neema answered "$40 — which colours would you like?" — brief, accurate,
# and deaf to the question. The owner wrote the reply he WOULD have sent and
# asked for the memory update; that reply is now the canonical first-contact
# example, and answer-what-they-asked is a named rule.

def test_the_owners_first_contact_welcome_is_the_standard():
    from app.agent.prompt import build_system_prompt
    p = build_system_prompt(currency="USD")
    assert "FIRST CONTACT — THE WELCOME" in p
    assert "Welcome to Bethany House, Malakhi" in p
    assert "excited to have you" in p                 # (spelling corrected)
    assert "ship to you via DHL" in p
    assert "FIRST touch only" in p and "never a re-welcome" in p


def test_answer_the_question_they_actually_asked_is_a_named_rule():
    from app.agent.prompt import build_system_prompt
    p = build_system_prompt(currency="USD")
    assert "ANSWER THE QUESTION THEY ACTUALLY ASKED" in p
    flat = " ".join(p.split())              # the rule wraps across lines
    assert '"How can I order it?" is an ORDERING question' in flat
    assert "not a price recital" in flat


def test_deflecting_replies_never_become_teaching_examples():
    """First live report (2026-08-19): 'can I pay in Ethiopian currency?' was
    answered with 'i will be calling you using our other whatsapp number' —
    and the curator chose it as an exemplar. The standing rules forbid
    deflection; the textbook must never teach it."""
    assert not usable_answer(
        "Hello, i will be calling you using our other whatsapp number to "
        "finalize with your order")
    assert not usable_answer("Kindly DM us for the price list")
    assert not usable_answer("Please check your inbox, we texted you")
    # …while real in-channel answers keep teaching
    assert usable_answer("We are located in Nairobi CBD, Sonalux House 7th floor Room 18.")
    assert usable_answer("this aluminium tray goes for 70$")
