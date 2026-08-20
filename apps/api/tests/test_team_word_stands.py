"""A colleague's reply is settled fact in every later turn (owner, 2026-08-19).

The Mestowt Negash thread: Moses answered the shipping question BY HAND —
"1-2 days to ship via Ethiopian Airline from Nairobi or via DHL. Allow me to
confirm the shipping cost tomorrow" — and ten hours later the scheduled
check-in told the customer we were "still following up ... on the shipping
cost" with no trace of what Moses had said. His reply WAS in the history the
composer read; it was just indistinguishable from Neema's own past turns, so
the stale promise outranked it.

Three fixes pinned here: human turns carry a marker in the transcript, the
standing rules make a marked line settled fact (and forbid echoing the
marker), and the scheduled follow-up instruction orders a re-read before any
re-promise.
"""
import asyncio
import types
from datetime import datetime, timedelta, timezone

import app.main  # noqa: F401 — registers models
import app.agent.runtime as runtime
from app.models.message import MsgDirection, MsgSender


def _msg(text, direction, sender, minutes_ago=0, media_type=None):
    return types.SimpleNamespace(
        text=text, direction=direction, sender=sender, media_type=media_type,
        created_at=datetime.now(timezone.utc) - timedelta(minutes=minutes_ago))


def _fake_db(rows):
    class _Res:
        def scalars(self):
            # _history reverses a DESC fetch — hand rows back newest-first
            return types.SimpleNamespace(all=lambda: list(reversed(rows)))

    class _DB:
        async def execute(self, *a, **k):
            return _Res()
    return _DB()


def test_a_human_colleagues_turn_is_marked_in_the_transcript():
    rows = [
        _msg("Do you have an authorized agent in Ethiopia?",
             MsgDirection.inbound, MsgSender.user, 60),
        _msg("Greetings Mestowt. It will take 1-2 days to ship via Ethiopian "
             "Airline from Nairobi or via DHL.",
             MsgDirection.outbound, MsgSender.human_agent, 50),
        _msg("ok Thanks", MsgDirection.inbound, MsgSender.user, 40),
        _msg("You're welcome, Mestowt.", MsgDirection.outbound, MsgSender.ai, 30),
    ]
    h = asyncio.run(runtime._history(_fake_db(rows), "psid1", channel="messenger"))
    colleague = h[1]["content"]
    assert colleague.startswith("[TEAM — a human colleague sent this]: Greetings Mestowt")
    # Neema's own turn stays unmarked
    assert h[3]["content"] == "You're welcome, Mestowt."
    # roles still alternate cleanly and start with the customer
    assert [t["role"] for t in h] == ["user", "assistant", "user", "assistant"]


def test_the_marker_survives_a_collapse_with_an_ai_turn():
    """A human reply immediately after an AI reply merges into one assistant
    turn — the marker must still separate whose words are whose."""
    rows = [
        _msg("How much?", MsgDirection.inbound, MsgSender.user, 60),
        _msg("One moment.", MsgDirection.outbound, MsgSender.ai, 50),
        _msg("The tray is $70.", MsgDirection.outbound, MsgSender.human_agent, 40),
    ]
    h = asyncio.run(runtime._history(_fake_db(rows), "psid1", channel="messenger"))
    assert len(h) == 2
    assert "One moment.\n[TEAM — a human colleague sent this]: The tray is $70." \
        in h[1]["content"]


def test_internal_notes_never_reach_the_model_even_from_humans():
    import inspect
    src = inspect.getsource(runtime._history)
    assert 'media_type != "note"' in src


def test_the_standing_rules_make_a_colleagues_word_settled_fact():
    from app.agent.prompt import build_system_prompt
    p = build_system_prompt(currency="USD")
    assert "WHAT A COLLEAGUE SAID STANDS" in p
    assert "[TEAM — a human colleague sent this]:" in p
    assert "NEVER" in p and "write it in your own replies" in p


def test_the_scheduled_follow_up_re_reads_before_re_promising():
    import inspect
    from app.services import actions
    src = inspect.getsource(actions._compose_follow_up)
    assert "FIRST re-read the conversation" in src
    assert "their answer" in src and "STANDS" in src
