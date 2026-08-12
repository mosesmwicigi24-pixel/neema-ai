"""Cost routing without quality loss (owner, 2026-08-12): 97% of tokens ran on
the main model, driven by comment replies. Comments default to the light model;
money, risk, vision and nuance stay on the main one."""
import asyncio
import inspect

import app.main  # noqa: F401
from app.agent import runtime as rt
from app.core.config import settings


LIGHT = settings.tier2_model_light
MAIN = settings.tier2_model


def test_plain_price_comments_ride_the_light_model():
    for text in ("How much po with cups", "Bei gani?", "Location?",
                 "how much please", "Ni ya ngapi hii"):
        assert rt.route_comment_model(text) == LIGHT, text


def test_money_and_risk_stay_on_the_main_model():
    for text in ("I want to order 5 trays",            # digits + order = cart math
                 "how do I pay",
                 "this is wrong, you never replied",   # negativity → mood ladder
                 "do you do wholesale prices",
                 "can you deliver to Abuja"):
        assert rt.route_comment_model(text) == MAIN, text


def test_long_comments_get_the_main_model():
    long = " ".join(["word"] * 30)
    assert rt.route_comment_model(long) == MAIN


def test_routing_flag_off_means_main_model_everywhere():
    old = settings.tier2_model_routing
    try:
        settings.tier2_model_routing = False
        assert rt.route_comment_model("how much?") == MAIN
    finally:
        settings.tier2_model_routing = old


def test_comment_pipeline_pins_vision_to_the_main_model():
    src = inspect.getsource(rt._engage_comment) if hasattr(rt, "_engage_comment") else \
        open("app/agent/runtime.py").read()
    assert "settings.tier2_model if media else route_comment_model" in src


def test_history_window_is_channel_tuned():
    src = inspect.getsource(rt.run_turn)
    assert "14 if public_comment else 40" in src   # comments trimmed, DMs full


# ── the politeness ping-pong ends (owner, 2026-08-12) ────────────────────────
# "thank you" → "you're welcome" → "I'll get back to you" → "I'll be waiting"
# → "ok" → … — every round a model call, each more robotic than the last.

def test_closers_are_recognised():
    for t in ("Thanks!", "asante sana 🙏", "🙏🙏", "ok", "Amen",
              "I'll get back to you", "I will let you know", "nitakujulisha",
              "God bless you", "Goodnight", "You're welcome"):
        assert rt.is_closer(t), t


def test_real_messages_are_never_closers():
    for t in ("Thanks — and how much is the silver tray?",
              "I'll get back to you tomorrow after the committee meets to "
              "decide on the full set of vestments we discussed",   # >8 words
              "ok send me the payment link",
              "How much?"):
        assert not rt.is_closer(t), t


class _Redis:
    def __init__(self): self.store = {}

    async def get(self, k): return self.store.get(k)

    async def set(self, k, v, ex=None): self.store[k] = v

    async def delete(self, k): self.store.pop(k, None)

    async def expire(self, k, ex): ...


def test_first_closer_replies_then_silence_until_substance():
    r = _Redis()
    # First "thanks": gate open (model replies once), then armed post-send.
    assert asyncio.run(rt.closer_gate(r, "whatsapp", "254700", "Thanks!")) is False
    asyncio.run(rt.mark_closer_answered(r, "whatsapp", "254700", "Thanks!"))
    # The ping-pong: every further closer is silence, not a model call.
    assert asyncio.run(rt.closer_gate(r, "whatsapp", "254700", "🙏")) is True
    assert asyncio.run(rt.closer_gate(r, "whatsapp", "254700", "I'll get back to you")) is True
    # Substance clears the flag — the conversation is alive again.
    assert asyncio.run(rt.closer_gate(r, "whatsapp", "254700", "How much is the tray?")) is False
    assert "closer:whatsapp:254700" not in r.store
    assert asyncio.run(rt.closer_gate(r, "whatsapp", "254700", "Thanks!")) is False


def test_gate_never_arms_after_a_substantive_reply():
    r = _Redis()
    asyncio.run(rt.mark_closer_answered(r, "whatsapp", "254700", "I want 5 trays"))
    assert r.store == {}


def test_sweeper_never_rescues_a_closer():
    from app.services.reply_sweeper import _answerable_turn
    assert _answerable_turn("Thanks 🙏", None, None) == (None, None)
    assert _answerable_turn("I'll get back to you", None, None) == (None, None)
    text, _ = _answerable_turn("How much for the tray?", None, None)
    assert text == "How much for the tray?"
