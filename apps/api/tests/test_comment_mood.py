"""Read the mood before selling — the Florence case.

A customer commented "this is wrong" under a post about cassock colours, and
Neema replied, publicly: "We'd love to help Florence! 🙏 Continue on WhatsApp to
get yours 💛". A complaint answered with a sales pitch, in front of everyone.

Two independent defects produced that one reply:

  1. `classify_comment_intent` labelled a plain complaint `high` (buying
     interest). The classifier leaned toward "engage" on uncertainty, and every
     error path defaulted to `high` too.
  2. When no answer could be composed (over the per-post cap, or the agent turn
     failed), `_comment_public_reply` fell back to a WhatsApp SALES PITCH —
     chosen without any reference to what the customer had actually said.

These tests pin both shut: displeasure is never `high`, and a reply we could not
compose never becomes a pitch.
"""
import asyncio

import app.agent.runtime as rt


# ── 1. displeasure is recognised deterministically, before any model call ────

def test_the_florence_comment_is_negative():
    assert rt.looks_negative("this is wrong")
    # …and the classifier returns it without consulting the model at all
    assert asyncio.run(rt.classify_comment_intent("this is wrong")) == "negative"


def test_short_complaints_are_caught():
    for text in ("This is wrong", "that's wrong", "not true", "incorrect",
                 "wrong price", "poor quality", "still waiting",
                 "you never replied", "this is a scam", "I want a refund",
                 "very disappointed", "misleading"):
        assert rt.looks_negative(text), text
        assert asyncio.run(rt.classify_comment_intent(text)) == "negative", text


def test_genuine_interest_is_not_mislabelled():
    """The guard must be precise — buying questions still reach the model path."""
    for text in ("how much?", "where are you located?", "do you ship to Uganda?",
                 "I want this", "is it available in purple?", "Amen 🙏",
                 "beautiful work", "what sizes do you have?"):
        assert not rt.looks_negative(text), text


def test_negative_plan_never_sells():
    plan = rt.plan_comment_actions("negative")
    assert plan["dm"] is False          # no sales DM to someone who is unhappy
    assert plan["human"] is True        # a person picks it up
    assert plan["style"] == "empathy"


# ── 2. no answer → never a pitch ─────────────────────────────────────────────

def test_no_answer_and_no_product_gives_a_neutral_line_not_a_pitch():
    """The exact path that produced the Florence reply."""
    out = rt._comment_public_reply("", dm_sent=False, link="", name_tag=" Florence",
                                   seed="florence", product_link="")
    assert "WhatsApp" not in out
    assert "get yours" not in out            # the offending line, gone
    assert "Florence" in out                 # still warm and personal
    assert out in [p.replace("{name}", " Florence") for p in rt._NEUTRAL_ACK_POOL]


def test_no_answer_but_identified_product_may_still_offer_the_order_link():
    """When we DID work out what they want, a buyer is never stranded."""
    out = rt._comment_public_reply("", dm_sent=False,
                                   link="https://neema.example/api/o/ABC",
                                   name_tag=" Grace", seed="grace", product_link="")
    assert "WhatsApp" in out                 # the tap-to-order invite is legitimate here


def test_neutral_lines_are_safe_for_anyone():
    """These go out when we do not know what was said — so they must sell
    nothing at all: safe for a buyer, a critic, or someone grieving."""
    for line in rt._NEUTRAL_ACK_POOL:
        low = line.lower()
        assert "whatsapp" not in low
        assert "order" not in low
        assert "get yours" not in low
        assert "price" not in low


# ── 3. the public-comment instructions carry the mood rule ───────────────────

def test_public_comment_addendum_reads_the_mood_first():
    a = rt._public_comment_addendum("KES")
    assert "READ THE MOOD BEFORE YOU SELL" in a
    assert "do NOT quote a price and do NOT pitch" in a
    assert "grief" in a.lower()              # not every commenter is a customer
