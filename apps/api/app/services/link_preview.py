"""Open the links customers share.

A customer who pastes `facebook.com/share/p/1Bp5DJdS3j/` is pointing at a
product — usually one of OUR posts — and asking about it without words. Neema
used to answer "I'm not able to open that link, could you tell me in words what
caught your eye?", which is honest and useless: the answer was one hop away and
the customer had already done the pointing.

Resolution is two steps, because a share slug carries nothing on its own:

  1. Fetch it as `facebookexternalhit/1.1`. That UA matters — Facebook serves a
     bot-check 400 to a browser UA on these slugs, but redirects the crawler
     straight to the canonical `story.php?story_fbid=<post>&id=<page>`.
  2. Compose the Graph post id as `<page>_<post>` and read it with the Page
     token, which gives the real caption and the post photo.

When the id can't be composed (a `pfbid…` permalink, someone else's page), we
fall back to the Open Graph tags already in the crawler's HTML — less detail,
but still enough to know what they are looking at.

Everything is best-effort and cached: a post's content doesn't change, and a
link Neema can't open must never cost the customer their reply.
"""
from __future__ import annotations

import html as _html
import json
import logging
import re
from urllib.parse import unquote

import httpx

_log = logging.getLogger("neema.meta")

# Any Facebook link shape a customer might paste — share slugs, permalinks,
# story/photo pages, mobile hosts and the fb.watch / fb.me shorteners.
FB_LINK_RE = re.compile(
    r"https?://(?:www\.|m\.|web\.|mbasic\.)?"
    r"(?:facebook\.com|fb\.watch|fb\.me)/[^\s<>\"']+",
    re.I,
)

_CRAWLER_UA = "facebookexternalhit/1.1"
_CACHE_PREFIX = "linkprev:"
_CACHE_TTL = 7 * 24 * 3600


# A share URL ends at its token: /share/p/<tok>/ (or /r/, /v/, or no letter).
# Customers routinely type the next word straight onto a pasted link — the live
# data had ".../1D6dUaMrsm/bleu" and ".../1JajDZBQ55/I" — and the glued word
# turns a good link into a 404.
_SHARE_URL_RE = re.compile(
    r"^(https?://(?:www\.|m\.|web\.|mbasic\.)?facebook\.com/share/"
    r"(?:[prv]/)?[A-Za-z0-9]+/?)", re.I)


def find_facebook_link(text: str | None) -> str | None:
    """The first Facebook URL in a message, trimmed of trailing punctuation and
    of any word the customer ran straight into it."""
    m = FB_LINK_RE.search(text or "")
    if not m:
        return None
    url = m.group(0).rstrip(").,;!”\"'")
    share = _SHARE_URL_RE.match(url)
    return share.group(1) if share else url


def _post_id_from_url(url: str) -> str | None:
    """Graph's `<page>_<post>` id, when the resolved URL carries both halves.

    Read from the WHOLE unescaped URL, not just its top-level query: from a
    datacenter IP Facebook bounces the crawler to `/login/?next=<escaped
    story.php…>`, which still carries the ids — just one level down. Unquoting
    twice reaches them either way."""
    if not url:
        return None
    flat = url
    for _ in range(3):                     # nested encodings in `next=`
        un = unquote(flat)
        if un == flat:
            break
        flat = un
    story = re.search(r"[?&]story_fbid=(\d+)", flat)
    # `[?&]id=` so it can't match rdid= / fbid= / profile_id=.
    page = re.search(r"[?&]id=(\d+)", flat)
    if story and page:
        return f"{page.group(1)}_{story.group(1)}"
    return None


# A reel/video permalink: /reel/<id>/, /videos/<id>/, /watch/?v=<id>.
_VIDEO_ID_RE = re.compile(r"/(?:reel|videos)/(\d{6,})|[?&]v=(\d{6,})")


def _video_id_from_url(url: str) -> str | None:
    m = _VIDEO_ID_RE.search(url or "")
    return (m.group(1) or m.group(2)) if m else None


def _is_generic_title(title: str) -> bool:
    """A login/checkpoint wall renders the title 'Facebook' — worse than
    nothing, because it would have Neema confidently describe a post she never
    saw. Reels do this too: their page title is always just 'Facebook'."""
    t = (title or "").strip().lower().rstrip(".")
    return not t or t in (
        "facebook", "log in to facebook", "log into facebook",
        "facebook - log in or sign up", "watch", "error", "video",
    )


async def _fetch_video_context(video_id: str) -> dict | None:
    """Graph read for a reel/video node.

    The fields DIFFER from a post's — a video has description/permalink_url/
    picture, and asking a post's `message` of a video makes Meta reject the
    whole call, which is why this can't reuse fetch_post_context."""
    from app.core.config import settings
    if not settings.meta_page_token or not video_id:
        return None
    url = f"https://graph.facebook.com/{settings.meta_graph_version}/{video_id}"
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                url,
                params={"fields": "description,title,permalink_url,picture"},
                headers={"Authorization": f"Bearer {settings.meta_page_token}"},
            )
        if not resp.is_success:
            return None
        d = resp.json()
    except Exception:
        return None
    title = (d.get("description") or d.get("title") or "").strip()
    if not title:
        return None
    permalink = d.get("permalink_url") or ""
    if permalink.startswith("/"):
        permalink = f"https://www.facebook.com{permalink}"
    return {"title": title[:200], "permalink": permalink,
            "thumb": d.get("picture") or "", "post_id": video_id, "source": "graph"}


def _og(html: str, prop: str) -> str:
    m = re.search(
        rf'<meta\s+property=["\']og:{prop}["\']\s+content=["\']([^"\']*)["\']',
        html or "", re.I)
    return _html.unescape(m.group(1) if m else "").strip()


def _title_from_html(html: str) -> str:
    """The <title> holds a truncated caption ("Bethany House - Welcome to…"),
    which beats og:title (just the page name) for telling posts apart."""
    m = re.search(r"<title>([^<]{0,300})</title>", html or "", re.I)
    if not m:
        return ""
    t = _html.unescape(m.group(1)).strip()
    # Strip the leading "<Page> - " so what's left is the caption itself.
    return re.sub(r"^[^-|]{1,60}\s+[-|]\s+", "", t).strip()


def _caption_from_permalink(url: str) -> str:
    """Facebook slugifies the caption into the permalink path — the last resort
    when Graph is closed to us and the page title is only 'Facebook'. Reels put
    it under /videos/, ordinary posts under /posts/."""
    m = re.search(r"/(?:posts|videos|reel)/([a-z0-9][a-z0-9-]{11,})/?", url or "", re.I)
    if not m:
        return ""
    slug = m.group(1)
    if slug.isdigit():            # a bare id is not a caption
        return ""
    words = slug.replace("-", " ").strip()
    return words[:1].upper() + words[1:] if words else ""


async def resolve_facebook_link(url: str, redis=None) -> dict | None:
    """What a shared Facebook link points at.

    Returns {title, permalink, thumb, post_id, source} or None when the link
    can't be opened at all. Never raises."""
    if not url:
        return None
    cache_key = f"{_CACHE_PREFIX}{url}"
    if redis is not None:
        try:
            hit = await redis.get(cache_key)
            if hit:
                return json.loads(hit)
        except Exception:
            pass

    out: dict | None = None
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=20.0) as client:
            resp = await client.get(url, headers={"User-Agent": _CRAWLER_UA})
            final_url, html = str(resp.url), resp.text

        post_id = _post_id_from_url(final_url)
        if post_id:
            # Our own Page post — the Graph read gives the true caption + photo.
            from app.services.meta_send import fetch_post_context
            ctx = await fetch_post_context(post_id, "facebook")
            if ctx.get("title"):
                out = {"title": ctx["title"], "permalink": ctx.get("permalink") or final_url,
                       "thumb": ctx.get("thumb") or "", "post_id": post_id, "source": "graph"}

        if out is None:
            # Reels are the common share ("/share/r/…" → "/reel/<id>/") and need
            # the video node's own fields.
            vid = _video_id_from_url(final_url) or _video_id_from_url(_og(html, "url"))
            if vid:
                out = await _fetch_video_context(vid)

        if out is None:
            # Someone else's post, or an id we can't read: use the crawler's own
            # metadata rather than telling the customer we're blind. A generic
            # title ("Facebook") is discarded at every step — better to stay
            # silent than to describe a post we never saw.
            permalink = _og(html, "url") or final_url
            title = next(
                (c for c in (_title_from_html(html),
                             _caption_from_permalink(permalink),
                             _og(html, "title"))
                 if c and not _is_generic_title(c)),
                "")
            if title:
                out = {"title": title[:200], "permalink": permalink,
                       "thumb": _og(html, "image"), "post_id": post_id or "",
                       "source": "opengraph"}
    except Exception as exc:
        _log.info("shared link resolve failed for %s: %s", url[:80], exc)
        return None

    if out is None:
        return None
    if redis is not None:
        try:
            await redis.setex(cache_key, _CACHE_TTL, json.dumps(out))
        except Exception:
            pass
    _log.info("shared link resolved (%s): %s", out["source"], out["title"][:60])
    return out


async def shared_link_context(text: str | None, redis=None) -> str:
    """The system-prompt block describing a link the customer just shared."""
    url = find_facebook_link(text)
    if not url:
        return ""
    info = await resolve_facebook_link(url, redis)
    if not info:
        return ""
    # Only a Graph read proves the post is ours; Open Graph could be any page.
    whose = ("this is OUR OWN Facebook post" if info.get("source") == "graph"
             else "this is the post they linked")
    block = (f"\n\nTHE LINK THEY JUST SHARED — you CAN see it, {whose}, "
             "opened for you:\n"
             f'  "{info["title"]}"\n')
    if info.get("permalink"):
        block += f"  ({info['permalink']})\n"
    block += ("Treat it exactly like a photo they sent: name the product it "
              "shows, price it from the catalogue, and carry on. NEVER say you "
              "cannot open a link or ask them to describe it in words.")
    return block
