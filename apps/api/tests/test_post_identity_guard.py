"""A post's recorded product identity must be RIGHT and must stay right.

The live Arman thread: a Silver Communion Tray post ("…Each tray is KES 18000
and holds 40 cups…") tied Tray vs Cups in the bag-of-words ladder, the ladder
refused to pick, the model free-styled 'Gold Bread Tray' — and that guess was
about to be RECORDED as the post's identity for every future commenter.
"""
from app.agent.runtime import (_hub_caption_match, _post_identity_compatible,
                               _public_comment_addendum)

_ARMAN_CAPTION = ("We have Silver Communion Trays at Bethany House! Each tray is "
                  "KES 18000 and holds 40 cups. Make your order today by calling / "
                  "WhatsApp. We ship across the world.")

_CATALOG = [
    {"name": "Silver Communion Tray", "aliases": []},
    {"name": "Silver Communion Cups", "aliases": []},
    {"name": "Gold Bread Tray", "aliases": []},
    {"name": "Silver Bread Tray", "aliases": []},
]


def test_caption_naming_the_product_verbatim_is_decisive():
    """'Silver Communion Trays' appears as a contiguous phrase; 'cups' only as a
    stray word ('holds 40 cups') — the phrase breaks the tie the way a human
    reads the caption. This exact caption used to return None (ambiguous)."""
    hit = _hub_caption_match(_CATALOG, _ARMAN_CAPTION)
    assert hit is not None and hit["name"] == "Silver Communion Tray"


def test_genuinely_ambiguous_captions_still_refuse_to_guess():
    # Neither sibling named as a phrase → the honest tie is preserved.
    hit = _hub_caption_match(_CATALOG, "Silver items for communion: cup and tray available")
    assert hit is None


def test_model_guess_contradicting_the_caption_is_never_recorded():
    guess = {"name": "Gold Bread Tray"}
    assert _post_identity_compatible({}, _ARMAN_CAPTION, guess) is False
    # a caption-supported sibling MAY be recorded (the model could see the frame)
    assert _post_identity_compatible({}, _ARMAN_CAPTION, {"name": "Silver Communion Tray"}) is True
    assert _post_identity_compatible({}, _ARMAN_CAPTION, {"name": "Silver Communion Cups"}) is True


def test_recorded_identity_is_never_overwritten_by_a_different_product():
    known = {"name": "Silver Communion Tray"}
    # a customer asking about ANOTHER item must not rewrite what the post is
    assert _post_identity_compatible(known, _ARMAN_CAPTION, {"name": "Gold Bread Tray"}) is False
    # refreshing the SAME product (plural/case drift) is fine
    assert _post_identity_compatible(known, _ARMAN_CAPTION, {"name": "silver communion trays"}) is True


def test_captionless_reel_trusts_the_identification():
    assert _post_identity_compatible({}, "", {"name": "Chasuble"}) is True
    assert _post_identity_compatible({}, None, {"name": "Chasuble"}) is True
    assert _post_identity_compatible({}, "", {}) is False          # no name → nothing to record


def test_comment_addendum_pins_thread_product_continuity():
    p = _public_comment_addendum()
    assert "STAY ON THE POST'S PRODUCT" in p
    assert "silver is not gold" in p
    assert "Gold Bread Tray" in p          # the live failure, named as the counter-example


def test_hub_descriptions_arrive_as_plain_text():
    """'<p>The Bishop staff</p>' leaked raw into both catalogs AND the agent's
    context — hub rich text is stripped to plain text at the mapping."""
    from app.core.hub_client import _strip_html, _map_product
    assert _strip_html("<p>The Bishop staff. The shepherd staff</p>") == \
        "The Bishop staff. The shepherd staff"
    assert _strip_html("<ul><li>CINCTURE &amp; belt</li></ul>") == "CINCTURE & belt"
    assert _strip_html(None) == "" and _strip_html("plain") == "plain"
    prod = _map_product({"id": 1, "translations": [
        {"language_code": "en", "name": "Crozier",
         "short_description": "<p>The Bishop staff</p>"}], "prices": []})
    assert prod["description"] == "The Bishop staff"
