"""Per-turn model routing (roadmap #2) — pure unit tests, no DB, no network.

Verifies route_model() sends trivial turns (greetings, thanks/acks, bare
affirmations) to the light model and everything else — anything that could
plausibly need a tool call — to the main model, and that the routing switch
in settings disables it entirely.
"""
from app.agent.runtime import route_model
from app.core.config import settings


def test_route_model_light_for_greetings_and_acks():
    assert route_model("hi") == settings.tier2_model_light
    assert route_model("thanks") == settings.tier2_model_light
    assert route_model("sawa") == settings.tier2_model_light
    assert route_model("👍") == settings.tier2_model_light


def test_route_model_main_for_substantive_turns():
    assert route_model("I want 3 cassocks") == settings.tier2_model
    assert route_model("how much is anointing oil?") == settings.tier2_model
    assert route_model("yes place the order") == settings.tier2_model
    assert route_model("deliver to Nakuru") == settings.tier2_model


def test_route_model_more_greeting_and_ack_variants():
    assert route_model("Hello!") == settings.tier2_model_light
    assert route_model("Habari") == settings.tier2_model_light
    assert route_model("good morning") == settings.tier2_model_light
    assert route_model("asante sana") == settings.tier2_model_light
    assert route_model("ok") == settings.tier2_model_light
    assert route_model("poa") == settings.tier2_model_light
    assert route_model("got it") == settings.tier2_model_light
    assert route_model("🙏🙏") == settings.tier2_model_light


def test_route_model_defaults_to_main_on_empty_or_ambiguous_text():
    assert route_model("") == settings.tier2_model
    assert route_model("   ") == settings.tier2_model
    # A greeting plus a real question is NOT trivial — must not short-circuit.
    assert route_model("hi, how much is anointing oil?") == settings.tier2_model


def test_route_model_routing_disabled_always_returns_main(monkeypatch):
    monkeypatch.setattr(settings, "tier2_model_routing", False)
    assert route_model("hi") == settings.tier2_model
    assert route_model("thanks") == settings.tier2_model
    assert route_model("sawa") == settings.tier2_model
    assert route_model("I want 3 cassocks") == settings.tier2_model
