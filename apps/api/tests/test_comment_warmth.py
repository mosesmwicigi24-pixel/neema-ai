"""Warm, kind and welcoming under a momentum post — the Zambia case.

Under "#Zambia see you in 2027!" (a travel photo, no product), two replies went
out cold (2026-09-03):

  · "We can't wait to have you Bethany in Zambia" → "So sorry to hear this
    Sydney 🙏 A member of our team will reach out to you personally to make it
    right" — and a complaint ticket. The light classifier is told to lean
    negative on anything wait-shaped, and this had "wait" in it.
  · "Where is Bethany house in Malawi?" → "This post isn't about a product,
    Apostle Duncan — just a travel celebration photo, no branch in Malawi to
    point you to." The comment rules gave the model only one role, the
    shopkeeper, and a post with nothing to sell left it with nothing kind to
    say.

These tests pin the fix: goodwill is read before the model and never as a
complaint; a goodwill comment gets a real, personal public reply and no sales
DM; and the comment rules give the model a second role — the host.
"""
import asyncio
import inspect
import types

import app.main  # noqa: F401 — registers models
import app.agent.runtime as rt


# ── 1. cheering us on is recognised deterministically ────────────────────────

def test_the_sydney_comment_is_goodwill_not_a_complaint():
    text = "We can't wait to have you Bethany in Zambia"
    assert rt.looks_goodwill(text)
    assert not rt.looks_negative(text)


def test_goodwill_cues_are_caught():
    for text in ("We can't wait to have you Bethany in Zambia",
                 "Welcome to Zambia! 🇿🇲",
                 "Karibu Zambia",
                 "Congratulations 🎉🎉",
                 "Hongera Bethany House",
                 "See you in Lusaka!",
                 "We are waiting for you in Malawi",
                 "God bless you Bethany House",
                 "Safe travels 🙏",
                 "Looking forward to 2027",
                 "So proud of you"):
        assert rt.looks_goodwill(text), text


def test_a_grievance_wearing_goodwill_words_is_not_goodwill():
    for text in ("We can't wait any longer, where is our order?",
                 "Still waiting for my order",
                 "Still waiting for your reply",
                 "God bless but this is wrong",
                 "welcome to the scam"):
        assert not rt.looks_goodwill(text), text
    # …and the complaints among them are still complaints
    assert rt.looks_negative("Still waiting for my order")
    assert rt.looks_negative("God bless but this is wrong")


def test_questions_and_buying_interest_are_not_goodwill():
    for text in ("Where is Bethany house in Malawi?", "how much?",
                 "do you ship to Zambia?", "I want this"):
        assert not rt.looks_goodwill(text), text


# ── 2. the classifier returns goodwill without consulting the model ──────────

def _never_called(model=None):
    raise AssertionError("the model must not be consulted for plain goodwill")


def test_goodwill_short_circuits_the_model(monkeypatch):
    monkeypatch.setattr(rt, "build_llm", _never_called)
    out = asyncio.run(rt.classify_comment_intent("We can't wait to have you Bethany in Zambia"))
    assert out == "goodwill"


def test_goodwill_is_read_before_the_negative_guard(monkeypatch):
    # "waiting for you in Malawi" carries a negative-guard cue ("waiting");
    # read as goodwill first, it never becomes an apology.
    monkeypatch.setattr(rt, "build_llm", _never_called)
    assert asyncio.run(rt.classify_comment_intent("We are still waiting for you in Malawi 🇲🇼")) == "goodwill"
    # …while a real wait is still a real wait
    assert asyncio.run(rt.classify_comment_intent("Still waiting for my order")) == "negative"


class _CapturingLLM:
    def __init__(self, label="high"):
        self.label, self.prompt = label, ""

    async def complete(self, *, system, messages, tools):
        self.prompt = messages[0]["content"]
        return types.SimpleNamespace(text=self.label, tool_calls=[],
                                     assistant_content=[], usage={})


def test_the_model_is_told_goodwill_is_not_negative(monkeypatch):
    llm = _CapturingLLM("goodwill")
    monkeypatch.setattr(rt, "build_llm", lambda model=None: llm)
    # a goodwill phrasing the regex does not know (French) reaches the model…
    out = asyncio.run(rt.classify_comment_intent("On vous attend avec impatience en Zambie"))
    assert out == "goodwill"                       # …and the label passes through
    assert "- goodwill:" in llm.prompt
    assert "NOT negative even when it contains the word 'wait'" in llm.prompt
    assert "high, low, negative, goodwill, or spam" in llm.prompt
    assert "goodwill" in rt._INTENTS


# ── 3. goodwill gets a real public reply and no sales DM ─────────────────────

def test_goodwill_plan_answers_publicly_without_a_dm_or_a_ticket():
    plan = rt.plan_comment_actions("goodwill")
    assert plan == {"public": True, "style": "answer", "dm": False, "human": False}
    # the other plans are untouched
    assert rt.plan_comment_actions("high")["dm"] is True
    assert rt.plan_comment_actions("negative")["human"] is True


def test_the_engine_routes_goodwill_to_the_model_and_gates_the_dm():
    src = inspect.getsource(rt._run_comment_engage)
    # the canned branch is keyed on the style, so goodwill (style "answer",
    # dm False) reaches the model instead of a canned line…
    assert 'if plan["style"] != "answer":' in src
    assert 'if not plan["dm"]:' not in src
    # …and the DM opens only for high intent, or when the post sells a product
    assert 'if answer and (plan["dm"] or product_link):' in src


# ── 4. the comment rules give the model the host's role ──────────────────────

def test_comment_rules_have_a_host_mode_for_non_product_posts():
    a = rt._public_comment_addendum("USD")
    assert "WHEN THE POST IS NOT A PRODUCT" in a
    assert "you are the HOST, not the shopkeeper" in a
    assert "NEVER tell anyone the post 'isn't about a product'" in a
    assert "Sell nothing unless they ask for an item" in a
    # the identification ladder starts by recognising there may be nothing to identify
    assert "(0) a post that plainly is not about a product has nothing to identify" in a
    assert "IDENTIFY THE PRODUCT in this order" in a        # the old pin still holds


def test_comment_rules_say_goodwill_is_never_a_complaint():
    a = rt._public_comment_addendum("USD")
    assert "GOODWILL IS NEVER A COMPLAINT" in a
    assert "the word 'wait' in it is anticipation, not a grievance" in a
    assert "end with ONE warm question that is not a sales question" in a


def test_comment_rules_answer_where_are_you_in_my_country_as_an_invitation():
    a = rt._public_comment_addendum("USD")
    assert "'WHERE ARE YOU IN MY COUNTRY?' is a person asking us to come" in a
    assert "answer as an invitation, never as a correction" in a
    assert "never open with what we don't have" in a
    # honesty guard: the model repeats only what the post itself promises
    assert "Say back ONLY what the post's own words state" in a
    assert "a hashtag is not a branch" in a
    assert "Never invent a branch, a city or a year" in a
