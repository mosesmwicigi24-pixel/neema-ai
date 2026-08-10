"""Outbound sender for Meta channels + a channel dispatcher.

`send_meta_message` posts a reply to Messenger / Instagram via the Graph Send API
(`/me/messages` with the Page token). `send_to_channel` is the single outbound
seam every reply path calls: it routes to WhatsApp (the existing WABA sender) or
to Meta by the conversation's channel, using the conversation's `external_id` as
the recipient (== wa_id for WhatsApp, PSID/IGSID for Meta).
"""
import logging
import re

import httpx

from app.core.config import settings

_log = logging.getLogger("neema.meta")

# Channels that send via the Meta Graph API (Page token) rather than WABA.
# "facebook" = Facebook Page comment conversations; it uses the same Send API
# and Page token as Messenger, so it routes identically here.
META_CHANNELS = ("messenger", "facebook", "instagram")


def token_for_page(page_id: str | None) -> str:
    """The Page token to act as: the page's own token when configured
    (META_PAGE_TOKENS="pageid:token,…"), else the global META_PAGE_TOKEN."""
    if page_id:
        tok = settings.page_token_map().get(str(page_id))
        if tok:
            return tok
    return settings.meta_page_token


async def _graph_post(path: str, body: dict, what: str, page_id: str | None = None) -> dict:
    """POST to the Graph API with the Page token in the Authorization header —
    NEVER in the URL, so the token can't leak into request logs or error
    messages. On failure, logs Facebook's message (token-free) and raises a clean
    error that carries no URL and no token."""
    token = token_for_page(page_id)
    if not token:
        raise RuntimeError(f"META_PAGE_TOKEN not configured — cannot {what}")
    url = f"https://graph.facebook.com/{settings.meta_graph_version}/{path}"
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            url,
            headers={"Authorization": f"Bearer {token}"},
            json=body,
            timeout=30.0,
        )
    if not resp.is_success:
        _log.error("Meta %s failed %s: %s", what, resp.status_code, resp.text)
        raise RuntimeError(f"Meta {what} failed ({resp.status_code}): {resp.text[:300]}")
    return resp.json() if resp.content else {}


async def send_meta_message(recipient_id: str, text: str, page_id: str | None = None,
                            human_agent: bool = False) -> None:
    """Send a text reply to a Messenger PSID / Instagram IGSID via the Send API,
    acting as the page that owns this PSID when page_id is given.

    `human_agent=True` sends under Meta's HUMAN_AGENT tag, which permits a reply
    up to SEVEN days after the customer's last message — the standard RESPONSE
    type is refused with error (#10) once the 24-hour window shuts. Only a real
    person may use it, so it is set by the human reply path and never by the AI.
    """
    body: dict = {
        "recipient": {"id": recipient_id},
        "message": {"text": text},
    }
    if human_agent:
        body["messaging_type"] = "MESSAGE_TAG"
        body["tag"] = "HUMAN_AGENT"
    else:
        body["messaging_type"] = "RESPONSE"
    await _graph_post("me/messages", body, "send message", page_id=page_id)


# Our media_type → Meta Send API attachment type.
_MEDIA_TYPE_TO_META = {"image": "image", "video": "video", "audio": "audio", "document": "file"}


async def send_meta_media(recipient_id: str, media_type: str, media_url: str,
                          caption: str | None = None, page_id: str | None = None) -> None:
    """Send an image / video / audio / file to a Messenger PSID or Instagram IGSID
    via the Send API (attachment by URL). Meta attachments carry no caption, so a
    caption follows as a short text message — the same way Messenger shows an image
    with a caption. (Instagram DMs accept images; other types may be rejected by
    Meta and surface as a send error, which the caller handles.)"""
    meta_type = _MEDIA_TYPE_TO_META.get(media_type, "file")
    await _graph_post("me/messages", {
        "recipient": {"id": recipient_id},
        "messaging_type": "RESPONSE",
        "message": {"attachment": {"type": meta_type,
                                   "payload": {"url": media_url, "is_reusable": True}}},
    }, "send media", page_id=page_id)
    if caption:
        await send_meta_message(recipient_id, caption, page_id=page_id)


async def send_meta_carousel(recipient_id: str, elements: list[dict],
                             page_id: str | None = None) -> None:
    """Send a horizontal carousel of product cards (photo + title + subtitle + a
    'View' button) via the Send API generic template — the NATIVE Messenger /
    Instagram equivalent of the web-chat product cards. Up to 10 cards.

    Each element: {title, subtitle?, image_url?, default_action?, buttons?}."""
    await _graph_post("me/messages", {
        "recipient": {"id": recipient_id},
        "message": {"attachment": {"type": "template", "payload": {
            "template_type": "generic",
            "elements": elements[:10],
        }}},
    }, "send carousel", page_id=page_id)


# ── The public square is link-free (owner rule, absolute) ────────────────────
# Meta suppresses the reach of posts AND comments that carry an external link,
# so a PUBLIC comment reply never carries a URL: we answer, we invite them to
# message us, and the storefront link rides the private reply / DM instead.
#
# This is the LAST of three gates, and the only one that cannot be talked out
# of it: (1) the `public_comment` prompt addendum forbids links, (2) the reply
# templates in app/agent/runtime.py no longer contain one, and (3) this. A model
# slip, a new template, or a future caller cannot publish a link past here.
#
# Scheme-ful URLs, `www.` hosts, bare domains (bethanyhouse.co.ke/product/x) and
# e-mail addresses all count — a bare domain is a link to everyone reading it.
_TLDS = ("co\\.ke|or\\.ke|ac\\.ke|go\\.ke|com|net|org|io|app|shop|store|link"
         "|site|online|biz|info|africa")
_URL_RE = re.compile(
    r"(?i)(?:"
    r"(?:https?://|ftp://|www\.)\S+"                       # explicit URLs
    r"|[\w.+-]+@[\w-]+(?:\.[\w-]+)+"                       # e-mail addresses
    rf"|\b(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+(?:{_TLDS})\b(?:/\S*)?"
    r")"
)
# "Order here 👉 <link>" without its link is not a sentence. When a URL is cut
# out we also drop the pointer that aimed at it, then bin any line left with no
# word in it at all.
_POINTER_RE = re.compile(r"(?:👉|➡️|➡|=>|->)")
# Last resort: everything in the reply was a link. Better a warm, link-free line
# than an empty comment (which the Graph API rejects anyway).
LINK_FREE_FALLBACK = "Thank you 🙏 Send us a message and we'll help you order 💛"


def sanitize_public_comment(text: str) -> tuple[str, list[str]]:
    """Strip every URL / e-mail out of a PUBLIC comment reply.

    Returns `(clean_text, removed)`. `removed` is empty when the text was
    already link-free, which is the normal case — the templates and the prompt
    are supposed to keep it that way, and a non-empty `removed` means one of
    them regressed and should be fixed at the source."""
    raw = (text or "").strip()
    removed = _URL_RE.findall(raw)
    if not removed:
        return raw, []
    lines: list[str] = []
    for line in _URL_RE.sub("", raw).splitlines():
        line = _POINTER_RE.sub("", line)
        line = re.sub(r"\s{2,}", " ", line).strip(" \t-–—,;:")
        # A remnant with no letters or digits ("👉", "()") is noise, and so is a
        # decapitated CTA like "Order here" — two words that now lead nowhere.
        if re.search(r"[0-9A-Za-z]", line) and len(line.split()) > 2:
            lines.append(line)
    return ("\n".join(lines).strip() or LINK_FREE_FALLBACK), removed


async def reply_to_comment(comment_id: str, text: str, page_id: str | None = None,
                           channel: str = "facebook") -> None:
    """Public reply posted under a Facebook/Instagram comment.

    NO OUTBOUND LINKS EVER LEAVE HERE — see `sanitize_public_comment`. This is
    the send boundary for the public square, so the rule is enforced here rather
    than trusted to whoever composed the text. Private replies, Messenger/IG DMs
    and WhatsApp are untouched: links belong in all of those.

    The endpoint DIFFERS by platform: Facebook nests a reply as a comment-on-a-
    comment (`/{comment-id}/comments`), while Instagram has a dedicated replies
    edge (`/{ig-comment-id}/replies`). Posting the Facebook shape to an IG comment
    fails, which is why IG replies must route here."""
    safe, removed = sanitize_public_comment(text)
    if removed:
        _log.warning(
            "stripped %d link(s) from a public comment reply on %s (%s): %s — "
            "public comments must be link-free; fix the source that composed it",
            len(removed), comment_id, channel, removed)
    edge = "replies" if channel == "instagram" else "comments"
    await _graph_post(f"{comment_id}/{edge}", {"message": safe},
                      "reply to comment", page_id=page_id)


async def send_private_reply(comment_id: str, text: str, page_id: str | None = None,
                             channel: str = "facebook") -> None:
    """Private reply to a comment — opens a DM thread with the commenter. One-shot
    per comment and time-limited by Meta; after it the conversation continues as a
    normal DM (which the agent already handles).

    BOTH channels go through the Send API, addressing the COMMENT as the
    recipient (`recipient: {comment_id: …}`). The old Facebook-specific
    `/{comment_id}/private_replies` edge 400s on current Graph versions
    ("does not support this operation", subcode 33) — verified live 2026-08-10:
    every comment DM was failing, so the storefront link never reached anyone."""
    await _graph_post("me/messages", {
        "recipient": {"comment_id": comment_id},
        "message": {"text": text},
    }, "send private reply", page_id=page_id)


async def fetch_profile(external_id: str, channel: str = "messenger") -> dict:
    """Best-effort: a Messenger/Instagram user's public profile (name + photo) via
    the User Profile API. Field names differ by platform — the Messenger Profile
    API exposes first_name/last_name (asking for `name` 400s the WHOLE call, which
    is why Messenger contacts read 'Unknown'); Instagram exposes name/username.
    Page token in the Authorization header only. Returns {} on any error."""
    if not settings.meta_page_token or not external_id:
        return {}
    fields = "name,username,profile_pic" if channel == "instagram" else "first_name,last_name,profile_pic"
    url = f"https://graph.facebook.com/{settings.meta_graph_version}/{external_id}"
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                url,
                params={"fields": fields},
                headers={"Authorization": f"Bearer {settings.meta_page_token}"},
                timeout=15.0,
            )
        if resp.is_success:
            d = resp.json()
            name = (d.get("name") or d.get("username")
                    or f"{d.get('first_name', '')} {d.get('last_name', '')}".strip())
            out = {"name": name or None, "profile_pic": d.get("profile_pic")}
            # Best-effort SECOND call for locale (e.g. "sw_KE") — a free country
            # hint. Separate request so an unapproved field can never break the
            # name fetch; any failure is silently ignored.
            try:
                async with httpx.AsyncClient() as client:
                    r2 = await client.get(
                        url, params={"fields": "locale"},
                        headers={"Authorization": f"Bearer {settings.meta_page_token}"},
                        timeout=10.0,
                    )
                if r2.is_success and r2.json().get("locale"):
                    out["locale"] = r2.json()["locale"]
            except Exception:
                pass
            return out
        _log.info("profile fetch for %s (%s) → %s: %s",
                  external_id, channel, resp.status_code, resp.text[:200])
    except Exception as exc:
        _log.info("profile fetch for %s failed: %s", external_id, exc)
    return {}


async def fetch_post_context(post_id: str, channel: str = "facebook") -> dict:
    """Best-effort: the source post a comment is replying to, so the inbox can
    show WHAT the customer is commenting on (they never say — "how much?" under a
    photo is meaningless without the photo).

    One Graph read on the post id with the Page token; returns a compact dict:
        {post_id, title, permalink, thumb, media_type, has_video}
    The FIELDS DIFFER by platform: a Facebook post has message/permalink_url/
    full_picture/attachments, an Instagram MEDIA object has caption/permalink/
    media_url/thumbnail_url/media_type. Meta rejects the whole call on unknown
    fields, so asking Facebook's shape of an IG media id returns nothing — which
    is why this is channel-aware. Returns {} on any error — the caller treats an
    empty context as "no card", never a failure. Callers should cache by post_id
    (posts don't change) to avoid re-fetching for every comment on the same post."""
    if not settings.meta_page_token or not post_id:
        return {}
    is_ig = channel == "instagram"
    url = f"https://graph.facebook.com/{settings.meta_graph_version}/{post_id}"
    fields = ("caption,permalink,media_url,media_type,thumbnail_url,timestamp" if is_ig else
              "message,permalink_url,full_picture,created_time,"
              "attachments{title,description,media_type,media{image{src}}}")
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                url,
                params={"fields": fields},
                headers={"Authorization": f"Bearer {settings.meta_page_token}"},
                timeout=15.0,
            )
        if not resp.is_success:
            _log.info("post context fetch for %s → %s", post_id, resp.status_code)
            return {}
        d = resp.json()
    except Exception as exc:
        _log.info("post context fetch for %s failed: %s", post_id, exc)
        return {}

    if is_ig:
        # IG media_type: IMAGE | VIDEO | CAROUSEL_ALBUM. A VIDEO's media_url IS
        # the mp4; thumbnail_url is its poster (images have no thumbnail_url).
        mt = (d.get("media_type") or "").lower()
        is_video = "video" in mt
        title = (d.get("caption") or "").strip() or (
            {"video": "Video post", "image": "Photo post",
             "carousel_album": "Photo album"}.get(mt, "a post"))
        thumb = d.get("thumbnail_url") or (None if is_video else d.get("media_url"))
        return {
            "post_id":    post_id,
            "title":      title[:200],
            "permalink":  d.get("permalink") or "",
            "thumb":      thumb or "",
            "media_type": "video" if is_video else ("photo" if mt else ""),
            "has_video":  is_video,
        }

    att = ((d.get("attachments") or {}).get("data") or [{}])[0]
    title = (d.get("message") or att.get("title") or att.get("description") or "").strip()
    mt = (att.get("media_type") or "").lower()
    if not title:
        _MEDIA_LABEL = {"photo": "Photo post", "video": "Video post",
                        "share": "Shared link", "album": "Photo album"}
        title = _MEDIA_LABEL.get(mt, "a post")
    thumb = (d.get("full_picture")
             or (((att.get("media") or {}).get("image") or {}).get("src")))
    is_video = "video" in mt or "reel" in mt
    return {
        "post_id":    post_id,
        "title":      title[:200],
        "permalink":  d.get("permalink_url") or "",
        "thumb":      thumb or "",
        # So the inbox can offer inline playback for a reel/video vs a photo.
        # The direct source URL expires, so it's fetched fresh on play (see
        # fetch_post_video_url), never cached with this stable context.
        "media_type": "video" if is_video else ("photo" if mt in ("photo", "album") else ""),
        "has_video":  is_video,
    }


async def fetch_post_video_url(post_id: str, channel: str = "facebook") -> str | None:
    """Fresh direct video source (MP4) for one of OUR page's video posts/reels,
    so the inbox can play it inline — the agent never leaves to Facebook. The URL
    is a short-lived signed CDN link, so callers cache it only briefly and
    re-fetch on demand. On Instagram the media object's `media_url` IS the mp4
    (there is no attachments edge). None when the post has no video or on error."""
    if not settings.meta_page_token or not post_id:
        return None
    base = f"https://graph.facebook.com/{settings.meta_graph_version}"
    hdr = {"Authorization": f"Bearer {settings.meta_page_token}"}
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            if channel == "instagram":
                r = await client.get(f"{base}/{post_id}",
                                     params={"fields": "media_type,media_url"}, headers=hdr)
                if not r.is_success:
                    return None
                d = r.json()
                if "video" in (d.get("media_type") or "").lower():
                    return d.get("media_url")
                return None
            resp = await client.get(
                f"{base}/{post_id}",
                params={"fields": "attachments{media_type,media{source},target{id}}"},
                headers=hdr,
            )
            if not resp.is_success:
                return None
            att = ((resp.json().get("attachments") or {}).get("data") or [{}])[0]
            src = ((att.get("media") or {}).get("source"))
            if src:
                return src
            vid = (att.get("target") or {}).get("id")   # fall back: the video object's source
            if vid:
                r2 = await client.get(f"{base}/{vid}", params={"fields": "source"}, headers=hdr)
                if r2.is_success:
                    return r2.json().get("source")
    except Exception as exc:
        _log.info("post video fetch for %s failed: %s", post_id, exc)
    return None


async def page_of_contact(channel: str, external_id: str) -> str | None:
    """Best-effort: the Meta page that owns this contact (stamped on the identity
    at capture — PSIDs are page-scoped). None → the global-token fallback. Skips
    the DB round-trip entirely on single-token setups."""
    if not settings.page_token_map():
        return None
    try:
        from sqlalchemy import select
        from app.database import AsyncSessionLocal
        from app.models.person import Identity
        async with AsyncSessionLocal() as db:
            rows = (await db.execute(
                select(Identity.raw_profile).where(
                    Identity.external_id == external_id,
                    Identity.channel.in_(META_CHANNELS))
            )).scalars().all()
        for rp in rows:
            pid = (rp or {}).get("page_id")
            if pid:
                return str(pid)
    except Exception:
        pass
    return None


async def send_typing_on(recipient: str, page_id: str | None = None) -> None:
    """Show Messenger/IG "typing…" bubbles while Neema composes — the presence
    a human at the page's inbox has. Clears when the reply sends. Best-effort:
    never delays or breaks the actual reply."""
    token = token_for_page(page_id)
    if not (token and recipient):
        return
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(
                f"https://graph.facebook.com/{settings.meta_graph_version}/me/messages",
                params={"access_token": token},
                json={"recipient": {"id": recipient}, "sender_action": "typing_on"},
            )
    except Exception:
        pass


async def send_to_channel(channel: str, recipient: str, text: str,
                          page_id: str | None = None,
                          context_wamid: str | None = None,
                          human_agent: bool = False) -> str | None:
    """Dispatch an outbound text reply to the right transport for `channel`.
    `recipient` is the conversation's external_id (wa_id | PSID | IGSID).
    `context_wamid` (WhatsApp only) makes the message a native reply-quote of the
    customer's message — Meta's DM Send API has no equivalent, so it's ignored there.
    Returns the sent message's wamid on WhatsApp (None on Meta channels) so the
    caller can stamp it on the outbound row and make it reply-quotable."""
    if channel in META_CHANNELS:
        if page_id is None:
            page_id = await page_of_contact(channel, recipient)
        await send_meta_message(recipient, text, page_id=page_id,
                                human_agent=human_agent)
        return None
    # WhatsApp — the existing WABA sender expects a bare number (no '+').
    from app.services.n8n_bridge import _send_waba
    return await _send_waba((recipient or "").lstrip("+"), text, context_wamid=context_wamid)


async def fetch_conversation_names(page_id: str | None = None, max_pages: int = 50) -> dict:
    """PSID → display name for everyone who has EVER messaged the page, from the
    page-level Conversations API (`/me/conversations?fields=participants`).

    This works where the per-user Profile API 400s: Meta only serves individual
    profile lookups for recently-active users, but the conversation participant
    list carries names for the whole history. One paged sweep names the entire
    backlog. Best-effort — returns {} on any failure."""
    token = token_for_page(page_id)
    if not token:
        return {}
    names: dict[str, str] = {}
    url = f"https://graph.facebook.com/{settings.meta_graph_version}/me/conversations"
    params = {"fields": "participants", "limit": "100"}
    try:
        async with httpx.AsyncClient() as client:
            for _ in range(max_pages):
                resp = await client.get(url, params=params,
                                        headers={"Authorization": f"Bearer {token}"},
                                        timeout=30.0)
                if not resp.is_success:
                    _log.info("conversation-names sweep → %s: %s",
                              resp.status_code, resp.text[:200])
                    break
                d = resp.json()
                for conv in d.get("data", []):
                    for part in ((conv.get("participants") or {}).get("data") or []):
                        pid, name = str(part.get("id") or ""), (part.get("name") or "").strip()
                        # Skip the page itself (it participates in every thread).
                        if pid and name and pid not in settings.page_token_map() \
                                and pid != str(page_id or ""):
                            names.setdefault(pid, name)
                nxt = ((d.get("paging") or {}).get("next"))
                if not nxt:
                    break
                url, params = nxt, None          # `next` is a full URL
    except Exception as exc:
        _log.info("conversation-names sweep failed: %s", exc)
    return names
