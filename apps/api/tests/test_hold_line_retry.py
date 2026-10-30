"""One hold line per failure the customer saw, never one per retry.

The live turn that fails sends the welcome-and-contacts line. The sweeper's
retry of that same message (now that it can see past the hold line —
test_hold_line_sweep_db.py) must not send it again when it fails too: a
customer waiting through an outage would be welcomed afresh every pass.
"""
import asyncio

import pytest

from app.agent import runtime as rt


@pytest.fixture
def failing_turn(monkeypatch):
    held = []

    async def boom(*a, **k):
        raise RuntimeError("Your credit balance is too low to access the Anthropic API.")

    async def hold(redis, channel, key):
        held.append((channel, key))

    async def noop(*a, **k):
        return None
    monkeypatch.setattr(rt, "run_turn", boom)
    monkeypatch.setattr(rt, "build_llm", lambda **k: object())
    monkeypatch.setattr(rt, "_send_hold_line", hold)
    import app.services.meta_send as meta_send
    monkeypatch.setattr(meta_send, "send_typing_on", noop)
    return held


@pytest.mark.parametrize("retry", [False, True])
def test_whatsapp(failing_turn, retry):
    went = asyncio.run(rt._run_and_send(None, "254700000099", "How much?",
                                        **({"hold_line": False} if retry else {})))
    assert went is False
    assert failing_turn == ([] if retry else [("whatsapp", "254700000099")])


@pytest.mark.parametrize("retry", [False, True])
def test_messenger(failing_turn, retry):
    went = asyncio.run(rt._run_and_send_meta(None, "messenger", "psid-99", "How much?",
                                             **({"hold_line": False} if retry else {})))
    assert went is False
    assert failing_turn == ([] if retry else [("messenger", "psid-99")])
