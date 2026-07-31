"""Opening the links customers share (services/link_preview.py).

The live failure: a customer pasted facebook.com/share/p/1Bp5DJdS3j/ — a link to
OUR OWN aluminium-tray post — and Neema replied that she couldn't open it.
"""
import asyncio

import app.models.agent, app.models.conversation  # noqa: F401 — register mappers
from app.services import link_preview as lp


def test_finds_every_facebook_link_shape():
    f = lp.find_facebook_link
    assert f("look at this https://www.facebook.com/share/p/1Bp5DJdS3j/") \
        == "https://www.facebook.com/share/p/1Bp5DJdS3j/"
    assert f("https://fb.watch/abc123/") == "https://fb.watch/abc123/"
    assert f("see m.facebook.com? no") is None          # bare host, no path
    # Trailing sentence punctuation must not become part of the URL.
    assert f("(https://www.facebook.com/share/p/XY/).") \
        == "https://www.facebook.com/share/p/XY/"
    assert f("no link here") is None
    assert f(None) is None


def test_post_id_is_composed_from_the_resolved_story_url():
    """share/p/… redirects to story.php?story_fbid=<post>&id=<page>; Graph wants
    them joined the other way round."""
    url = ("https://www.facebook.com/story.php?story_fbid=1678395280959617"
           "&id=100063674845161&rdid=qD0Z4OC2ax7jbeAw")
    assert lp._post_id_from_url(url) == "100063674845161_1678395280959617"
    # A pfbid permalink carries no numeric pair — must not guess one.
    assert lp._post_id_from_url("https://www.facebook.com/permalink.php?pfbid=abc") is None
    assert lp._post_id_from_url("https://www.facebook.com/share/p/1Bp5DJdS3j/") is None


def test_title_and_caption_fallbacks():
    html = "<title>Bethany House - Welcome to Bethany House. We have Aluminum...</title>"
    assert lp._title_from_html(html).startswith("Welcome to Bethany House")
    assert lp._og('<meta property="og:image" content="https://x/y.jpg">', "image") \
        == "https://x/y.jpg"
    slug = ("https://www.facebook.com/houseofbethany/posts/"
            "welcome-to-bethany-house-we-have-aluminum-trays-in-stocks/")
    assert lp._caption_from_permalink(slug).startswith("Welcome to bethany house")


def _fake_client(final_url: str, html: str, monkeypatch):
    class _Resp:
        url = final_url
        text = html

    class _Client:
        def __init__(self, *a, **k): ...
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, url, headers=None):
            # Facebook 400s a browser UA on share slugs — the crawler UA is the
            # whole reason this works, so pin it.
            assert headers["User-Agent"] == "facebookexternalhit/1.1"
            return _Resp()
    monkeypatch.setattr(lp.httpx, "AsyncClient", _Client)


def test_resolves_our_own_post_through_graph(monkeypatch):
    _fake_client("https://www.facebook.com/story.php?story_fbid=999&id=111", "", monkeypatch)

    async def fake_ctx(post_id, channel="facebook"):
        assert post_id == "111_999"
        return {"title": "We have Aluminum trays in stocks. Each holds 40 cups",
                "permalink": "https://fb.com/p/999", "thumb": "https://img/t.jpg"}
    monkeypatch.setattr("app.services.meta_send.fetch_post_context", fake_ctx)

    got = asyncio.run(lp.resolve_facebook_link("https://www.facebook.com/share/p/X/"))
    assert got["source"] == "graph"
    assert "Aluminum trays" in got["title"]
    assert got["post_id"] == "111_999"


def test_falls_back_to_open_graph_when_graph_is_closed(monkeypatch):
    html = ('<title>Someone Else - A cassock for sale...</title>'
            '<meta property="og:url" content="https://www.facebook.com/x/posts/1/">'
            '<meta property="og:image" content="https://img/og.jpg">')
    _fake_client("https://www.facebook.com/x/posts/1/", html, monkeypatch)
    got = asyncio.run(lp.resolve_facebook_link("https://fb.me/abc"))
    assert got["source"] == "opengraph"
    assert got["title"].startswith("A cassock for sale")


def test_unopenable_link_returns_none_and_never_raises(monkeypatch):
    class _Boom:
        def __init__(self, *a, **k): ...
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, url, headers=None): raise RuntimeError("blocked")
    monkeypatch.setattr(lp.httpx, "AsyncClient", _Boom)
    assert asyncio.run(lp.resolve_facebook_link("https://fb.me/x")) is None
    assert asyncio.run(lp.shared_link_context("https://fb.me/x")) == ""


def test_context_block_only_claims_ownership_when_graph_confirmed(monkeypatch):
    _fake_client("https://www.facebook.com/story.php?story_fbid=9&id=1", "", monkeypatch)

    async def fake_ctx(post_id, channel="facebook"):
        return {"title": "Aluminium trays in stock", "permalink": "", "thumb": ""}
    monkeypatch.setattr("app.services.meta_send.fetch_post_context", fake_ctx)
    block = asyncio.run(lp.shared_link_context("see https://www.facebook.com/share/p/Z/"))
    assert "OUR OWN Facebook post" in block
    assert "NEVER say you cannot open a link" in block
    # No link in the message → no block at all.
    assert asyncio.run(lp.shared_link_context("just a hello")) == ""


# ── The login wall (found only by running this in production) ─────────────────
# From a datacenter IP Facebook bounces the crawler to /login/?next=<escaped
# story.php…>. The ids survive, one encoding level down.


def test_post_id_survives_the_login_redirect():
    login = ("https://www.facebook.com/login/?next=https%3A%2F%2Fwww.facebook.com"
             "%2Fstory.php%3Fstory_fbid%3D1678395280959617%26id%3D100063674845161"
             "%26rdid%3DS0PsE4dD5JAgV8Iq&rdid=S0PsE4dD5JAgV8Iq")
    assert lp._post_id_from_url(login) == "100063674845161_1678395280959617"


def test_rdid_and_fbid_never_masquerade_as_the_page_id():
    assert lp._post_id_from_url(
        "https://www.facebook.com/x?story_fbid=5&rdid=99&fbid=77") is None


def test_reel_share_resolves_through_the_video_node(monkeypatch):
    """/share/r/... is the commonest share of all — it lands on /reel/<id>/,
    whose page title is always just 'Facebook'."""
    _fake_client("https://www.facebook.com/reel/1863405804324326/?rdid=x", "<title>Facebook</title>", monkeypatch)

    async def fake_video(vid):
        assert vid == "1863405804324326"
        return {"title": "Welcome to Bethany House. The No.1 Shop for your Vestment needs.",
                "permalink": "https://www.facebook.com/reel/1863405804324326/",
                "thumb": "", "post_id": vid, "source": "graph"}
    monkeypatch.setattr(lp, "_fetch_video_context", fake_video)

    got = asyncio.run(lp.resolve_facebook_link("https://www.facebook.com/share/r/1PKQHxPJuK/"))
    assert got["source"] == "graph" and "Vestment needs" in got["title"]


def test_video_id_is_read_from_every_url_shape():
    f = lp._video_id_from_url
    assert f("https://www.facebook.com/reel/1863405804324326/?rdid=x") == "1863405804324326"
    assert f("https://www.facebook.com/houseofbethany/videos/874257912350591/") == "874257912350591"
    assert f("https://www.facebook.com/watch/?v=1019752660712465") == "1019752660712465"
    assert f("https://www.facebook.com/share/r/1PKQHxPJuK/") is None   # slug, not an id


def test_caption_slug_covers_videos_not_just_posts():
    c = lp._caption_from_permalink
    assert c("https://www.facebook.com/houseofbethany/videos/"
             "welcome-to-bethany-house-the-no1-shop-for-your-vestment-needs/") \
        .startswith("Welcome to bethany house")
    # A numeric permalink is an id, never a caption.
    assert c("https://www.facebook.com/houseofbethany/videos/874257912350591/") == ""


def test_generic_titles_are_always_discarded():
    for t in ("Facebook", "facebook", "Watch", "Log in to Facebook", "", "  ", "Video"):
        assert lp._is_generic_title(t), t
    assert not lp._is_generic_title("Welcome to Bethany House. We have Aluminum trays")


def test_a_login_wall_is_never_described_as_the_post(monkeypatch):
    """Better to say nothing than to have Neema confidently describe a post she
    never saw — the login page's og:title is just 'Facebook'."""
    html = ('<title>Facebook</title>'
            '<meta property="og:title" content="Facebook">'
            '<meta property="og:url" content="https://www.facebook.com/login/">')
    _fake_client("https://www.facebook.com/login/?next=https%3A%2F%2Fx", html, monkeypatch)
    assert asyncio.run(lp.resolve_facebook_link("https://fb.me/blocked")) is None
    assert asyncio.run(lp.shared_link_context("https://fb.me/blocked")) == ""


def test_login_wall_still_reaches_graph_when_ids_are_present(monkeypatch):
    """The wall blocks the HTML, not the Page token — the post id is enough."""
    final = ("https://www.facebook.com/login/?next=https%3A%2F%2Fwww.facebook.com"
             "%2Fstory.php%3Fstory_fbid%3D999%26id%3D111")
    _fake_client(final, "<title>Facebook</title>", monkeypatch)

    async def fake_ctx(post_id, channel="facebook"):
        assert post_id == "111_999"
        return {"title": "Aluminium trays in stock", "permalink": "", "thumb": ""}
    monkeypatch.setattr("app.services.meta_send.fetch_post_context", fake_ctx)

    got = asyncio.run(lp.resolve_facebook_link("https://www.facebook.com/share/p/X/"))
    assert got["source"] == "graph" and got["title"] == "Aluminium trays in stock"
