"""The cost-governor must never short-circuit a sales confirmation.

`_ACK_RE` suppresses the expensive AI turn for trivial closers. A bare "yes" is
how a customer CONFIRMS an order, so affirmatives must NOT match (else the AI
never runs, the order is never placed, and nothing reaches the hub). Only pure
gratitude/closers may be suppressed.
"""
from app.services.n8n_bridge import _ACK_RE, _GREETING_RE


def _is_ack(text: str) -> bool:
    t = text.strip()
    return bool(_ACK_RE.match(t)) and not _GREETING_RE.match(t)


def test_affirmatives_are_not_acks():
    # These must reach the AI — they answer/confirm in a sales flow.
    for t in ["yes", "Yes", "yes please", "no", "ok", "okay", "sure", "sawa",
              "poa", "fine", "alright", "confirm", "yeah", "yep"]:
        assert not _is_ack(t), f"{t!r} should NOT be suppressed"


def test_pure_closers_are_still_acks():
    for t in ["thanks", "Thank you", "asante", "asante sana", "thx", "ty", "amen",
              "👍", "🙏", "😊"]:
        assert _is_ack(t), f"{t!r} should be suppressed as a closer"


def test_greetings_are_not_acks():
    # Greetings route via their own cheap path, not the ack path.
    assert not _is_ack("hi")
    assert not _is_ack("habari")
