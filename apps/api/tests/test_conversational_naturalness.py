"""CONVERSATIONAL NATURALNESS & SOCIAL INTELLIGENCE (owner's directive,
2026-11-10): one conversation per person per post — a nomination and the
details that follow it are one exchange; a bare acknowledgement after our
reply gets the Page's Like and no more words; the welcome and the selection
procedure are said once; giveaway participation is not assistance-seeking;
thanks are for something, never an opening reflex."""
import inspect

import pytest

import app.main  # noqa: F401
from app.agent import prompt as pr
from app.agent import runtime as rt
from app.services import buyer_intent as bi
from tests.test_campaign_posts import LOW, OWNER_CAPTION, SHOE, _engage

HIGH = {"intent": "high", "kind": "other", "severity": 0, "ask": ""}
FIRST = ("Hello Pastor Stephen, welcome to Bethany House! Our team will be selecting one recipient "
         "for this gift — completely free, you'd only cover the shipping. May we have your church and town?")


def _prior(monkeypatch, replies):
    async def prior(channel, ext, post_id):
        return list(replies)
    monkeypatch.setattr(rt, "_thread_prior", prior)


# ── the thread: one conversation per person per post ─────────────────────────
@pytest.mark.parametrize("text", ["Amen", "Thank you", "Ok", "🙏", "Asante sana", "God bless you", "Noted"])
def test_an_acknowledgement_after_our_reply_is_liked_not_answered(monkeypatch, text):
    _prior(monkeypatch, [FIRST])
    out = _engage(monkeypatch, text, reading=LOW, identity=SHOE)
    assert out["public"] == [] and out["dm"] == [] and out["human"] == []
    assert out["turn"] is None                       # no model call, no tokens
    assert len(out["noted"]) == 1 and "nothing to add" in out["noted"][0]


def test_the_like_follows_when_likes_are_on_and_never_on_instagram(monkeypatch):
    _prior(monkeypatch, [FIRST])
    out = _engage(monkeypatch, "Amen", reading=LOW, identity=SHOE)
    assert out["liked"] == []                        # the harness turns likes off
    src = inspect.getsource(rt._run_comment_engage)
    assert 'if settings.meta_comment_like and channel != "instagram":' in src


@pytest.mark.parametrize("text", [
    "Thank you — when will the selection be made?",      # a question rides the thanks
    "Ok, how much is the cassock?",                      # a buying word
    "Thanks, size 42",                                   # a detail to save
    "My pastor is Rev. John of AIC Eldoret",             # a nomination's details
])
def test_anything_that_needs_an_answer_still_gets_its_turn(monkeypatch, text):
    _prior(monkeypatch, [FIRST])
    out = _engage(monkeypatch, text, reading=HIGH, identity=SHOE, answer="Saved — AIC Eldoret.")
    assert out["turn"] is not None and out["public"] == ["Saved — AIC Eldoret."]
    r = out["turn"]["comment_reading"]
    assert r["returning"] == 1 and r["explained"] is True and r["campaign"]


def test_a_first_acknowledgement_is_still_answered_once(monkeypatch):
    _prior(monkeypatch, [])
    out = _engage(monkeypatch, "Amen", reading=LOW, identity=SHOE)
    assert len(out["public"]) == 1                   # the host's one light line
    assert out["noted"] == []


def test_nothing_to_add_never_swallows_a_question_a_figure_or_a_photo():
    for t in ("Amen", "Thank you", "ok", "👍", "Asante"):
        assert rt._nothing_to_add({"text": t}), t
    for t in ("Thank you?", "Amen, how much", "size 41", "0712 345 678", "I nominate Rev John", ""):
        assert not rt._nothing_to_add({"text": t}), t
    assert not rt._nothing_to_add({"text": "Amen", "photo": "http://x/p.jpg"})


def test_a_returning_entrant_over_the_cap_is_not_thanked_for_joining_twice(monkeypatch):
    _prior(monkeypatch, [FIRST])
    out = _engage(monkeypatch, "We are following you now", reading=LOW, identity=SHOE, over_cap=True)
    assert out["public"] == [] and len(out["noted"]) == 1
    # details, a question or a first comment keep their line
    out = _engage(monkeypatch, "Rev Alice from Nakuru, size 39", reading=LOW, identity=SHOE, over_cap=True)
    assert len(out["public"]) == 1
    _prior(monkeypatch, [])
    out = _engage(monkeypatch, "We are following you now", reading=LOW, identity=SHOE, over_cap=True)
    assert len(out["public"]) == 1


# ── the host's brief: said once ──────────────────────────────────────────────
def test_the_continuing_brief_drops_the_welcome_and_the_procedure():
    first = rt._reading_context({"kind": "other", "campaign": OWNER_CAPTION})
    cont = rt._reading_context({"kind": "other", "campaign": OWNER_CAPTION, "returning": 2, "explained": True})
    assert "THE SHAPE OF YOUR REPLY" in first and "THE SHAPE OF YOUR REPLY" not in cont
    assert "Hello Pastor, welcome to Bethany House!" not in cont
    assert "CONTINUING AN EXCHANGE" in cont and "replied to them 2 time(s)" in cont
    assert "ONE conversation" in cont and "no fresh welcome" in cont
    assert "do NOT say any of it again unless they ask" in cont
    assert "never recited back in full" in cont and "STILL missing" in cont
    assert "Never suggest they have been or will be the one chosen" in cont
    assert "Never ask for a phone number, an address or an email in public" in cont
    assert "never a pivot from the gift" in cont           # no redirect into a sale
    assert "A GIFT AND ONLY A GIFT" in cont                # the campaign's facts stand
    # not yet explained (the first reply was a canned line): the gift's line once
    cont2 = rt._reading_context({"kind": "other", "campaign": OWNER_CAPTION, "returning": 1})
    assert "say it once, briefly" in cont2
    # a question keeps its reading on top of the continuing brief
    q = rt._reading_context({"kind": "question", "ask": "the size", "campaign": OWNER_CAPTION, "returning": 1})
    assert "CONTINUING AN EXCHANGE" in q and "this comment is a QUESTION — the size" in q


def test_the_first_brief_is_substance_not_a_script():
    first = rt._reading_context({"kind": "other", "campaign": OWNER_CAPTION})
    assert "the SUBSTANCE of a FIRST answer, not a script to recite" in first
    assert "Never ask for a phone number, an address or an email in public" in first


def test_explained_is_read_from_what_we_actually_said():
    assert rt._EXPLAINED_RE.search(FIRST)
    assert rt._EXPLAINED_RE.search("Timu yetu itamchagua mpokeaji mmoja")
    assert not rt._EXPLAINED_RE.search("Thank you for joining in Stephen 🙏 We've received your comment")


def test_an_ordinary_thread_carries_the_returning_note_too():
    note = rt._returning_note(3)
    assert "already replied to this person 3 time(s)" in note and "CONTINUES that exchange" in note
    assert "no thanks or 'noted' out of habit" in note
    src = inspect.getsource(rt.run_turn)
    assert 'comment_reading.get("returning") and not comment_reading.get("campaign")' in src


def test_the_dm_from_a_campaign_says_it_once():
    line = rt._campaign_turn_context(OWNER_CAPTION, "I nominate my pastor")
    assert "SAID ONCE IS ENOUGH" in line and "one exchange" in line
    assert "never suggest they have been chosen" in line


# ── giveaway participation is not assistance-seeking (slice 19 intact) ───────
@pytest.mark.parametrize("text", [
    "I nominate my pastor, Rev. John Mwangi of AIC Eldoret",
    "My nomination is Bishop Peter",
    "I saw your giveaway, how do I take part?",
    "Is the free cassock in your post still open?",
    "Yes I would love you to gift my pastor a cassock",
    "Nampendekeza mchungaji wangu",
])
def test_participation_is_protected_from_the_request_ladder(text):
    assert bi.campaign_participation(text), text
    assert bi.protected(text) == "campaign participation"


@pytest.mark.parametrize("text", [
    "Please give me one cassock for free",
    "I am a poor pastor, please give me a gift",
    "We need sponsorship for our choir robes",
    "Nipe bure tafadhali",
    "How much is the cassock?",
])
def test_an_ordinary_request_or_enquiry_is_not_read_as_participation(text):
    assert not bi.campaign_participation(text), text


def test_the_note_writer_is_told_participation_is_not_assistance():
    from app.services import customer_state as cs
    assert "taking part in our campaign — never assistance" in " ".join(cs._NOTE_SYSTEM.split())


# ── the prompt: thanks are for something ─────────────────────────────────────
def _flat():
    return " ".join(inspect.getsource(pr).split())


def test_the_prompt_reads_the_message_before_answering():
    flat = _flat()
    assert "READ WHAT THE MESSAGE IS BEFORE YOU ANSWER IT (owner, 2026-11-10" in flat
    assert "THANKS ARE FOR SOMETHING" in flat and "never as the opening reflex of a reply" in flat
    assert 'Do not swap one habit for another ("Got it", "Sure", "Alright")' in flat
    assert "A DETAIL THEY SUPPLY IS TAKEN, NOT RECITED" in flat
    assert "Never ask a question only to keep the chat going" in flat
    # silence is checked, never a default
    assert "silence is a decision, checked first" in flat
    assert "no question of theirs unanswered, no promise of ours pending" in flat
    # the two lines that prescribed a fixed shape are gone
    assert "Every reply moves acknowledge → answer → advance" not in flat
    assert "an acknowledgement in front only when there is something to acknowledge" in flat
    # participation, in the intent section
    assert "is campaign participation" in flat and "never by the gift-request boundary" in flat


def test_what_was_established_still_stands():
    flat = _flat()
    assert "THE REGISTER IS CALM AND HONORABLE" in flat and "quiet courtesy" in flat
    assert "A bare \"thanks\"/\"ok\"/\"amen\"/a thumbs-up gets NOTHING back" in flat
    assert "GIFT REQUESTS AND HARDSHIP APPEALS" in flat and "A NATURAL END IS RESPECTED" in flat
