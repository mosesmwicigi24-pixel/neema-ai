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
    assert "ONE warm question that is a gift, not a hook" in a


def test_comment_rules_answer_where_are_you_in_my_country_as_an_invitation():
    a = rt._public_comment_addendum("USD")
    assert "'WHERE ARE YOU IN MY COUNTRY?' is a person asking us to come" in a
    assert "answer as an invitation, never as a correction" in a
    assert "Never open with what we don't have" in a
    # the promise comes from the owner's own line in the rules, with its year
    assert "WHERE WE ARE GOING, in your rules" in a
    assert "say it with its year, never as if it were already open" in a
    # honesty guard: nothing beyond the rules or the post's own words
    assert "a hashtag is not a branch" in a
    assert "Never invent a branch, a city or a year" in a


# ── 5. where we are going — the owner's promise, in the prompt ───────────────

def test_the_prompt_carries_the_owners_promise_with_its_year():
    from app.agent.prompt import build_system_prompt
    for p in (build_system_prompt(country_iso="", currency="USD"),
              build_system_prompt(country_iso="MW", currency="USD"),
              build_system_prompt(country_iso="KE", currency="KES")):
        assert "WHERE WE ARE GOING (the owner's words)" in p
        assert "Zambia in 2027" in p
        assert "South Africa" in p and "Malawi" in p and "Zimbabwe" in p
        assert "WITH ITS YEAR" in p and "never as if it were already open" in p
        assert "no other city, no other date" in p
    # today's facts are still today's facts
    p = build_system_prompt(country_iso="", currency="USD")
    assert "TODAY our only physical presence is Nairobi" in p


def test_an_empty_expansion_note_says_nothing(monkeypatch):
    from app.agent import prompt as pr
    from app.agent.prompt import build_system_prompt
    monkeypatch.setattr(pr.settings, "expansion_note", "", raising=False)
    p = build_system_prompt(country_iso="", currency="USD")
    assert "WHERE WE ARE GOING (the owner's words)" not in p
    assert "2027" not in p


# ── 6. the host's language, and the launch list ──────────────────────────────

def test_comment_rules_teach_the_hosts_language():
    a = rt._public_comment_addendum("USD")
    assert "THE HOST'S LANGUAGE" in a
    assert "mirror their energy in your first five words" in a
    assert "use their title as they wear it (Apostle, Bishop, Reverend, Pastor" in a
    assert "one promise and one open door, never two pitches" in a
    for chilling in ("'reach out'", "'a member of our team'", "'unfortunately'",
                     "'no branch'", "'your patience'"):
        assert chilling in a, chilling
    assert "THE LAUNCH LIST" in a and "capture_contact" in a


def test_the_complaint_line_is_human_and_uncheerful():
    line = rt._PUBLIC_EMPATHY.replace("{name}", " Sydney")
    for corporate in ("reach out", "member of our team", "patience", "💛"):
        assert corporate not in line, corporate
    assert "🙏" in line and "Sydney" in line
    assert "put it right" in line


# ── 7. over the cap, goodwill still gets warmth — never a form, never a pitch ─

def test_goodwill_over_the_cap_gets_a_warm_line_not_a_neutral_ack():
    out = rt._comment_public_reply("", dm_sent=False, name_tag=" Sydney", seed="s",
                                   goodwill=True)
    assert out in [p.replace("{name}", " Sydney") for p in rt._GOODWILL_POOL]
    assert out not in [p.replace("{name}", " Sydney") for p in rt._NEUTRAL_ACK_POOL]


def test_goodwill_over_the_cap_never_sells_even_on_a_product_post():
    out = rt._comment_public_reply("", dm_sent=False, name_tag=" Sydney", seed="s",
                                   product_known=True, product_name="Preaching Gown",
                                   price_text="$130", goodwill=True)
    assert "$130" not in out and "Gown" not in out
    assert out in [p.replace("{name}", " Sydney") for p in rt._GOODWILL_POOL]


def test_goodwill_pool_makes_no_promise_it_cannot_keep():
    # No year, no city, no branch, no link — those need the post in hand.
    for line in rt._GOODWILL_POOL:
        low = line.lower()
        for word in ("2027", "branch", "lusaka", "zambia", "http", "order"):
            assert word not in low, (line, word)
        assert "{name}" in line


def test_the_engine_hands_goodwill_to_the_fallback():
    src = inspect.getsource(rt._run_comment_engage)
    assert 'goodwill=(intent == "goodwill")' in src
