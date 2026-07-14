"""The missed-reply sweep decides what an unanswered last-inbound message needs.
Pure logic — no DB — so the answerable/skip rules can't silently regress."""
from app.services.reply_sweeper import _answerable_turn


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
