"""When we cannot answer, welcome the customer — don't confess an outage.

Reported from a live Messenger thread: a customer who had already been quoted a
price got, as the next message,

    "Samahani for the wait — I'm having a small technical hitch on my side. A
     colleague has been alerted, and we'll be right back to you."

Two things wrong with it. It hands the customer OUR problem, which is not
theirs to carry. And when the tokens are out, no colleague is coming back to
them soon — so the promise is empty, and the customer sits waiting on it.

The line they get now welcomes them and gives them the ways to reach us: true
whether the outage lasts a minute or the rest of the evening, and useful either
way. It is built from config alone — no LLM, no catalogue, no DB, because this
runs precisely when those are what broke.
"""
import pytest

from app.agent import runtime as rt
from app.core.config import settings


ALL_CHANNELS = ["whatsapp", "messenger", "instagram", "facebook", "tiktok", "web"]


@pytest.mark.parametrize("channel", ALL_CHANNELS)
def test_the_outage_is_never_the_customers_problem(channel):
    low = rt._hold_line(channel).lower()
    for confession in ("technical", "hitch", "colleague", "samahani",
                       "snag", "error", "sorry for the"):
        assert confession not in low, f"{confession!r} still leaks our outage"


@pytest.mark.parametrize("channel", ALL_CHANNELS)
def test_every_channel_gets_a_welcome(channel):
    assert "welcome to Bethany House" in rt._hold_line(channel)


@pytest.mark.parametrize("channel", ["messenger", "instagram", "facebook", "tiktok", "web"])
def test_a_customer_off_whatsapp_is_given_the_whatsapp_number(channel):
    # The screenshot's thread was Messenger: the number is the whole point of
    # the message there — it is how they reach a human while we are down.
    assert settings.whatsapp_handoff_number.strip() in rt._hold_line(channel)
    assert "place your order" in rt._hold_line(channel)


def test_on_whatsapp_we_do_not_quote_the_number_they_are_already_texting():
    line = rt._hold_line("whatsapp")
    assert settings.whatsapp_handoff_number.strip() not in line
    assert "right here" in line


@pytest.mark.parametrize("channel", ALL_CHANNELS)
def test_it_names_no_product_and_no_price(channel):
    # There is no model and no catalogue to ask when this fires. A guess here
    # would repeat the live-broadcast bug on the one message that must be safe.
    line = rt._hold_line(channel)
    assert "$" not in line
    for token in ("ksh", "kes", "usd", "price"):
        assert token not in line.lower()


@pytest.mark.parametrize("channel", ALL_CHANNELS)
def test_it_survives_a_config_with_no_contacts_at_all(channel, monkeypatch):
    # A blank .env must still produce a sendable line, never a crash inside the
    # failure handler or a dangling "reach us at ".
    monkeypatch.setattr(settings, "whatsapp_handoff_number", "")
    monkeypatch.setattr(settings, "whatsapp_handoff_alt", "")
    line = rt._hold_line(channel)
    assert "welcome to Bethany House" in line
    assert line.strip().endswith("💛")
    assert "  " not in line and " ." not in line


def test_the_old_hold_line_constant_is_gone():
    # It was a module constant three surfaces imported and sent verbatim. The
    # docstring on its replacement still quotes it, on purpose, so the reason
    # it went survives longer than this commit — so assert on the symbol, not
    # on the source text.
    assert not hasattr(rt, "_HOLD_LINE")

    import inspect
    from app.routers import manychat, web_chat
    for mod in (manychat, web_chat):
        assert "_HOLD_LINE" not in inspect.getsource(mod)
