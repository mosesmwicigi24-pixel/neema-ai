"""The missed-reply sweep decides what an unanswered last-inbound message needs.
Pure logic — no DB — so the answerable/skip rules can't silently regress."""
import asyncio

from app.services import reply_sweeper
from app.services.reply_sweeper import _answerable_turn
from app.agent.runtime import is_outside_window


def test_detects_metas_closed_window_only():
    """Meta refuses a send >24h after the customer's last message. That's a policy
    wall (a human must reply), not a bug to retry — so it must be told apart from
    ordinary send failures."""
    assert is_outside_window(
        'Meta send message failed (400): {"error":{"message":"(#10) This message is '
        'sent outside of allowed window","code":10,"error_subcode":2018278}}') is True
    assert is_outside_window(RuntimeError("... error_subcode\":2018278 ...")) is True
    # ordinary failures must NOT be mistaken for a closed window
    assert is_outside_window("Meta send message failed (500): server error") is False
    assert is_outside_window("connection timeout") is False
    assert is_outside_window(None) is False


def test_plain_text_is_answered():
    text, media = _answerable_turn("Munakaa wapi", None, None)
    assert text == "Munakaa wapi" and media is None


def test_image_with_caption_carries_both():
    text, media = _answerable_turn("how much?", "image", "https://cdn/x.jpg")
    assert text == "how much?"
    assert media == {"type": "image", "url": "https://cdn/x.jpg", "caption": "how much?"}


def test_image_placeholder_becomes_captionless_image():
    # a photo with no caption is stored as "[image]" — answer the photo, no fake caption
    text, media = _answerable_turn("[image]", "image", "https://cdn/x.jpg")
    assert text == "" and media["url"] == "https://cdn/x.jpg" and media["caption"] == ""


def test_bare_attachment_placeholder_is_skipped():
    # a video/file/audio with no words and no image → nothing to answer
    assert _answerable_turn("[video]", "video", "https://cdn/v.mp4") == (None, None)
    assert _answerable_turn("[file]", "file", "https://cdn/f.pdf") == (None, None)
    assert _answerable_turn("", None, None) == (None, None)
    assert _answerable_turn(None, None, None) == (None, None)


def test_escalation_claim_is_once_per_message_and_falls_back_to_the_flags(monkeypatch):
    class _Redis:
        def __init__(self):
            self.kv = {}

        async def set(self, k, v, nx=False, ex=None):
            if nx and k in self.kv:
                return None
            self.kv[k] = v
            return True

        async def delete(self, k):
            self.kv.pop(k, None)

    class _Down:
        async def set(self, *a, **k):
            raise ConnectionError("redis down")

    import types
    r = _Redis()
    claim = reply_sweeper._claim_escalation
    c1, c2 = types.SimpleNamespace(id="c1"), types.SimpleNamespace(id="c2")

    def m(i):
        return types.SimpleNamespace(id=i, created_at=None)
    assert asyncio.run(claim(r, m("m1"), c1)) is True
    assert asyncio.run(claim(r, m("m1"), c1)) is False     # same message: never again
    assert asyncio.run(claim(r, m("m2"), c1)) is True      # a new message earns one
    asyncio.run(reply_sweeper._unclaim_escalation(r, "m2"))  # the escalation did not land
    assert asyncio.run(claim(r, m("m2"), c1)) is True      # …so the next pass retries it
    flagged = {"c1": True, "c2": False}

    async def already(conv_id, inbound_at):
        return flagged[conv_id]
    monkeypatch.setattr(reply_sweeper, "_already_escalated_since", already)
    assert asyncio.run(claim(_Down(), m("m3"), c1)) is False
    assert asyncio.run(claim(_Down(), m("m4"), c2)) is True
