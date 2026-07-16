"""The missed-reply sweep decides what an unanswered last-inbound message needs.
Pure logic — no DB — so the answerable/skip rules can't silently regress."""
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
