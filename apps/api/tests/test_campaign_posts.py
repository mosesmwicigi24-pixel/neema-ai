"""CAMPAIGN POSTS and the grievance the words do not carry (owner, 2026-09-26).

Live, Facebook, a shoe giveaway for clergy ("one person will get the shoe
for free; the only cost is shipping"): Bishop John Tela wrote "I am bishop
John Tela. I love the shoe. That shoe can serve me well with the bishops
cassock that I am planning to buy at Bethany house. My size is no 41." and
was told "we're sorry about the part that went wrong. One of us will speak
with you personally to put it right." Pastor Stephen's "I'm Pastor Stephen
Tanui From Eldoret" got the canned "Bless you… so glad this speaks to…"."""
import asyncio
import inspect

import app.main  # noqa: F401
import app.agent.runtime as rt

BISHOP = ("I am bishop John Tela.I love the shoe.That shoe can serve me well with the bishops "
          "cassock that I am planning to buy at Bethany house.My size is no 41.")
PASTOR = "I'm Pastor Stephen Tanui From Eldoret"
CAPTION = ("Clergy shoe giveaway! One pastor, reverend or bishop will win this shoe for free — "
           "the only cost is shipping. Comment with your name and shoe size to enter.")


def test_a_grievance_the_words_do_not_carry_is_not_a_grievance():
    # the light model's misread, exactly as it must have come back
    for model_says in ({"intent": "negative", "kind": "mixed", "severity": 1, "ask": ""},
                       {"intent": "negative", "kind": "complaint", "severity": 2, "ask": ""},
                       {"intent": "high", "kind": "mixed", "severity": 1, "ask": ""}):
        r = rt._settle_reading(BISHOP, dict(model_says))
        assert (r["intent"], r["kind"], r["severity"]) == ("high", "other", 0), model_says
        r = rt._settle_reading(PASTOR, dict(model_says))
        assert (r["intent"], r["kind"]) == ("high", "other"), model_says
    # a real grievance keeps its reading — cue words, plain displeasure, "but"
    for text in ("Beautiful work but my order never came", "I am not happy with this",
                 "Still waiting since May", "Nilituma pesa zangu, sijapata kitu", "this is wrong"):
        r = rt._settle_reading(text, {"intent": "negative", "kind": "complaint", "severity": 1, "ask": ""})
        assert r["intent"] == "negative", text
    r = rt._settle_reading("Beautiful work but my order never came",
                           {"intent": "negative", "kind": "mixed", "severity": 1, "ask": ""})
    assert r["kind"] == "mixed"


def test_the_bishops_entry_never_reaches_the_complaint_line(monkeypatch):
    """Whatever the model says, the reading that reaches the plan is 'high':
    the host answers, no empathy line, no colleague."""
    class _LLM:
        async def complete(self, **kw):
            import types
            return types.SimpleNamespace(text="intent=negative | kind=mixed | severity=1 | ask=-")
    monkeypatch.setattr(rt, "build_llm", lambda model=None, **kw: _LLM())
    r = asyncio.run(rt.read_comment(BISHOP))
    assert r["intent"] == "high" and r["kind"] == "other"
    plan = rt.plan_comment_actions(r["intent"])
    assert plan["style"] == "answer" and plan["human"] is False


def test_a_campaign_post_is_read_from_its_caption():
    assert rt.is_campaign_post(CAPTION)
    for c in ("GIVEAWAY: stand a chance to win a Bible", "Shinda viatu hivi — andika jina lako",
              "Lucky draw this Sunday for one pastor", "Win a stole for your ordination"):
        assert rt.is_campaign_post(c), c
    for c in ("Silver Communion Tray in stock — 40 cups included free", "New cassocks for the season",
              "Gift set for your pastor: stole and collar", "", None):
        assert not rt.is_campaign_post(c), c


def test_the_host_context_carries_the_rule_and_saves_the_entry():
    ctx = rt._reading_context({"intent": "high", "kind": "other", "severity": 0, "ask": "", "campaign": CAPTION})
    assert ctx.startswith("(THIS POST IS A CAMPAIGN / GIVEAWAY")
    assert "the only cost is shipping" in ctx                     # the caption, verbatim
    assert "HOST of the campaign, not a shopkeeper" in ctx
    assert "capture_contact" in ctx and "save_measurements" in ctx
    assert "never a date, a count, a winner or a rule the caption does not" in ctx
    assert "never priced and never sold" in ctx
    assert "item they plan to buy" in ctx and 'never "something went wrong"' in ctx
    # the ordinary reading still follows the campaign block
    ctx2 = rt._reading_context({"kind": "question", "ask": "the size", "campaign": CAPTION})
    assert "CAMPAIGN" in ctx2 and "this comment is a QUESTION — the size" in ctx2
    assert rt._reading_context({"kind": "other"}) == ""


def test_the_engine_hands_entries_to_the_host():
    src = inspect.getsource(rt._run_comment_engage)
    assert "is_campaign_post(_caption)" in src
    assert 'reading = dict(reading, campaign=_caption)' in src
    assert 'reading["intent"] in ("low", "goodwill")' in src and '"high", "other"' in src
    add = " ".join(rt._public_comment_addendum("USD").split())
    assert "CAMPAIGN / GIVEAWAY POSTS (owner, 2026-09-26)" in add
    assert "hosted, not sold" in add and "Never a complaint line or an apology at an entry" in add
