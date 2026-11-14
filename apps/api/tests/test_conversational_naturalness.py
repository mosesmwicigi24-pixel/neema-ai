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
    # a question the reader could not classify (the model was down) is still a
    # question: never liked into silence (found by the giveaway dry run, 2026-11-14)
    for q in ("When will you choose the pastor?", "when will the pastor be chosen"):
        out = _engage(monkeypatch, q, reading=LOW, identity=SHOE, over_cap=True)
        assert len(out["public"]) == 1, q
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


# ── the owner's Facebook screenshots (2026-11-10): the cassock giveaway ──────
CASSOCK = ("Would You Love Us to Gift Your Pastor a Beautiful Cassock? Bethany House is giving away a "
           "beautifully custom-made cassock to one deserving pastor! We want to hear from you. Tell us why "
           "your pastor deserves this special gift. Your story could be the reason we choose them! Who can "
           "participate? - Open to everyone, both in Kenya and abroad. - Tell us why your pastor should be "
           "selected. - Bethany House will choose the recipient. - The cassock is completely FREE! The "
           "selected recipient will only cover delivery costs within Kenya or international shipping costs "
           "outside Kenya. Nominate your pastor in the comments! We can't wait to read your stories.")
SAID_1 = ("Hello Siyethemba, welcome to Bethany House, and thank you for nominating Rev TP. Our team will "
          "select one recipient for this gift. The cassock is free, and the recipient covers only the "
          "shipping to South Africa. Follow us for the details. May we have his church and town?")


def test_the_cassock_post_is_read_as_a_gifting_campaign():
    assert rt.is_campaign_post(CASSOCK) and not rt.campaign_is_draw(CASSOCK)


def test_the_page_tag_in_front_of_a_thread_reply_is_not_part_of_what_they_said():
    said = "Bethany House Pentecostal Holiness Church ( Potters House) around Nongoma KZN"
    assert rt._strip_page_tag(said, "c0") == "Pentecostal Holiness Church ( Potters House) around Nongoma KZN"
    assert rt._strip_page_tag("@bethanyhouse.ke Thokozani Ndwandwe", "c0") == "Thokozani Ndwandwe"
    assert rt._strip_page_tag("Bethany House, thank you", "c0") == "thank you"
    # a sentence about us, a top-level comment, a bare tag: left as written
    assert rt._strip_page_tag("Bethany House is the best", "c0") == "Bethany House is the best"
    assert rt._strip_page_tag(said, "") == said
    assert rt._strip_page_tag("Bethany House", "c0") == "Bethany House"


def test_the_church_reply_reaches_the_model_without_our_name_and_as_a_continuation(monkeypatch):
    _prior(monkeypatch, [SAID_1])
    from tests import test_campaign_posts as tc

    def engage_reply(text):
        real = rt._run_comment_engage

        async def run(redis, channel, comment, own):
            await real(redis, channel, dict(comment, parent_id="c0"), own)
        monkeypatch.setattr(rt, "_run_comment_engage", run)
        try:
            return tc._engage(monkeypatch, text, reading=HIGH, caption=CASSOCK,
                              answer="Pentecostal Holiness Church, Nongoma — with us.", name="Siyethemba Khumasta")
        finally:
            monkeypatch.setattr(rt, "_run_comment_engage", real)
    out = engage_reply("Bethany House Pentecostal Holiness Church ( Potters House) around Nongoma KZN")
    assert out["turn"]["user_text"].startswith("Pentecostal Holiness Church")
    r = out["turn"]["comment_reading"]
    assert r["returning"] == 1 and r["explained"] is True
    brief = rt._reading_context(r)
    assert "CONTINUING AN EXCHANGE" in brief and "welcome to Bethany House!" not in brief
    assert "the exchange is complete" in brief and "no further question" in brief
    assert "a church, a town or a full name the caption never asked for is not requested" in brief


def test_the_first_brief_asks_only_what_this_caption_asks():
    first = rt._reading_context({"kind": "other", "campaign": CASSOCK})
    assert "ASK ONLY FOR WHAT THIS CAPTION ASKS FOR" in first
    assert "do not invent a request for a church, a town or a full name the caption never made" in first


def test_asking_to_receive_the_gift_oneself_is_participation_never_a_sale():
    for ctx in (rt._reading_context({"kind": "other", "campaign": CASSOCK}),
                rt._reading_context({"kind": "other", "campaign": CASSOCK, "returning": 1}),
                rt._campaign_turn_context(CASSOCK, "pls gift me the one")):
        assert "IS TAKING PART" in ctx and "'I nominate myself'" in ctx
        assert "Never answer it with an offer to buy one" in ctx
        assert "a price is given only when THEY ask to buy" in ctx
    # the Swahili self-nomination in the screenshot is no buying ask
    irene = ("Hii labda nijiongee Mimi mwenyewe pls gift me the one I had the bishop who gave it alikujia "
             "the whole. Cussock sinanga na sijafanikiwa kupata pesa ya kushona")
    assert not rt._CAMPAIGN_BUY_RE.search(irene)


# ── a note to self is not a message (the real-model pass of 2026-11-14) ──────
def test_a_reply_that_only_says_no_reply_is_needed_is_sent_as_nothing():
    from app.agent.voice import stage_direction
    for t in ("_(No further reply is needed.)_", "(No reply needed)", "[silence]", "*(no response)*",
              "No further reply is needed.", "(Silence.)", "Nothing more to add.", "_(No reply.)_"):
        assert stage_direction(t), t
    for t in ("The set (cassock and stole) is $210.", "Thank you — I'll have everything ready.",
              "(Kindly note) we ship worldwide by DHL.", "No.", "", None,
              "No reply came from the team yet; I have referred it again."):
        assert not stage_direction(t), t
    src = inspect.getsource(rt.run_turn)
    assert "if _stage(reply):" in src and 'reply = ""' in src


# ── the gift never travels as "Order here" (the giveaway run of 2026-11-14) ──
def test_the_gifts_own_item_gets_no_order_link_in_the_inbox(monkeypatch):
    assert rt._is_the_gift(CASSOCK, "Cassock") and rt._is_the_gift(CASSOCK, "cassock")
    assert not rt._is_the_gift(CASSOCK, "Clergy Collar") and not rt._is_the_gift(CASSOCK, "Cassock Set")
    assert not rt._is_the_gift("", "Cassock") and not rt._is_the_gift(CASSOCK, "")
    cassock = {"name": "Cassock", "slug": "cassock", "price": 13000, "source": "caption"}
    _prior(monkeypatch, [])

    async def allowed(redis, channel, ext):
        return True
    monkeypatch.setattr(rt, "_comment_dm_allowed", allowed)
    out = _engage(monkeypatch, "How much is this cassock?", caption=CASSOCK, identity=cassock,
                  reading={"intent": "high", "kind": "question", "severity": 0, "ask": "the price"},
                  answer="This cassock is a gift, not for sale — one pastor our team selects receives it free.",
                  turn_rows=[cassock])
    assert out["public"] and out["dm"] == []
    # another item they bring up still gets its link
    collar = {"name": "Clergy Collar", "slug": "clergy-collar", "price": 500, "source": "caption"}
    out = _engage(monkeypatch, "And how much is a clergy collar?", caption=CASSOCK, identity=collar,
                  reading={"intent": "high", "kind": "question", "severity": 0, "ask": "the collar's price"},
                  answer="The cassock here is a gift. Our Clergy Collar is KES 500 — message us to order.",
                  turn_rows=[collar])
    assert len(out["dm"]) == 1 and "clergy-collar" in out["dm"][0]


# ── the three left open by the giveaway run (owner, 2026-11-14: "fix them") ──
def test_a_continuing_reply_loses_the_reflex_thanks():
    t = rt._trim_continuing
    assert t("Thank you, we have noted your church and Nongoma.", "Potters House, Nongoma", explained=False) \
        == "We have noted your church and Nongoma."
    assert t("Thank you, Siyethemba. Your nomination of Rev TP is with our team.", "Thokozani Ndwandwe",
             explained=False) == "Your nomination of Rev TP is with our team."
    assert t("Asante sana, Irene 🙏 Ombi lako limepokelewa.", "sawa", explained=False) == "Ombi lako limepokelewa."
    # a thanks FOR something is a sentence and stays; so does a reply that is only the thanks
    assert t("Thank you for the correction — Nongoma it is.", "It is Nongoma", explained=False) \
        == "Thank you for the correction — Nongoma it is."
    assert t("Thank you, Siyethemba.", "ok then", explained=False) == "Thank you, Siyethemba."
    assert t("Thank you. Noted.", "ok", explained=False) == "Thank you. Noted."      # nothing left worth keeping
    assert t("", "x", explained=True) == ""


def test_terms_they_have_heard_are_not_said_again_unless_they_ask():
    t = rt._trim_continuing
    said = ("We have noted your church and Nongoma. The gift is shipped from our Nairobi workshop by DHL, "
            "and the recipient covers only that shipping, as the post says.")
    assert t(said, "Pentecostal Holiness Church around Nongoma KZN", explained=True) \
        == "We have noted your church and Nongoma."
    # not yet explained, or they asked about it: the terms stay
    assert t(said, "Pentecostal Holiness Church", explained=False) == said
    assert t(said, "Who pays for the shipping?", explained=True) == said
    assert t(said, "when will you choose", explained=True) == said
    # a reply that is ONLY terms is never emptied
    only = "Our team will be selecting one recipient. Follow us for the details."
    assert t(only, "Rev John", explained=True) == only


def test_the_engine_trims_only_a_continuing_reply(monkeypatch):
    _prior(monkeypatch, [SAID_1])
    out = _engage(monkeypatch, "Pentecostal Holiness Church around Nongoma KZN", reading=HIGH, caption=CASSOCK,
                  answer="Thank you, we have noted your church. The recipient covers only the shipping.")
    assert out["public"] == ["We have noted your church."]
    assert out["turn"]["comment_reading"]["commenter"] == "John"
    _prior(monkeypatch, [])
    first = "Thank you, John. Our team will be selecting one recipient — completely free."
    out = _engage(monkeypatch, "I nominate Rev Peter", reading=HIGH, caption=CASSOCK, answer=first)
    assert out["public"] == [first]                      # a first reply is left as written


def test_a_name_sent_after_a_nomination_is_the_nominees():
    cont = rt._reading_context({"kind": "other", "campaign": CASSOCK, "returning": 2, "explained": True,
                                "commenter": "Siyethemba"})
    assert "The person writing is Siyethemba (the name on the comment)." in cont
    assert "is the NOMINEE'S name" in cont and "never greet or thank the commenter by it" in cont
    assert "never save it as the commenter's own name" in cont
    assert "The person writing is" not in rt._reading_context(
        {"kind": "other", "campaign": CASSOCK, "returning": 1})
