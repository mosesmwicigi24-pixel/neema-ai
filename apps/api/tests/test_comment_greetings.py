"""A hello is a door opening, not praise.

The Sylvia miss (2026-08-08): she commented "How are you" under a Bible post
and got the canned praise reply — "Thank you Sylvia! Your kind words mean the
world to us 💛" — because the classifier filed a greeting under 'low'
(generic positivity). A greeting is a person opening a conversation: it now
routes to the model deterministically, gets a real greeting back tied to the
post, and every comment answer ends with the pull that starts the sale.
"""
import asyncio

import pytest

import app.main  # noqa: F401 — registers all SQLAlchemy models
from app.agent import runtime


# ── the deterministic guard ──────────────────────────────────────────────────

@pytest.mark.parametrize("text", [
    "How are you", "how are you doing?", "Hi", "hello!!", "Habari",
    "habari yako 🙏", "Bonjour", "Good morning", "mambo", "Greetings",
])
def test_greetings_are_recognised(text):
    assert runtime.looks_greeting(text) is True


@pytest.mark.parametrize("text", [
    "How much", "how are you still not delivering my order",   # not a bare hello
    "Amen 🙏", "this is wrong", "I want this",
])
def test_non_greetings_are_not(text):
    assert runtime.looks_greeting(text) is False


def test_greeting_comments_route_to_engagement_without_the_model(monkeypatch):
    def _no_llm(*a, **k):
        raise AssertionError("greeting classification must not need the model")
    monkeypatch.setattr(runtime, "build_llm", _no_llm)
    assert asyncio.run(runtime.classify_comment_intent("How are you")) == "high"
    assert asyncio.run(runtime.classify_comment_intent("Habari yako")) == "high"
    # Displeasure still wins over everything.
    assert asyncio.run(runtime.classify_comment_intent("this is wrong")) == "negative"


# ── the addenda teach the behaviour ──────────────────────────────────────────

def test_comment_addendum_greets_back_and_pulls():
    a = " ".join(runtime._public_comment_addendum("KES").split())
    assert "A GREETING comment" in a
    assert "never 'kind words'" in a.replace("’", "'")
    assert "Never answer a greeting with a canned thanks" in a
    assert "END WITH THE PULL" in a
    assert "a comment that answers AND asks is what starts the sale" in a


def test_meta_dm_suggests_whatsapp_once_a_number_lands():
    a = " ".join(runtime._meta_addendum("USD").split())
    assert "DO suggest it, politely and exactly once" in a
    assert "we can finish everything right here" in a
    assert "Never repeat the invitation" in a
