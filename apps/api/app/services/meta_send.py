"""Outbound sender for Meta channels + a channel dispatcher.

`send_meta_message` posts a reply to Messenger / Instagram via the Graph Send API
(`/me/messages` with the Page token). `send_to_channel` is the single outbound
seam every reply path calls: it routes to WhatsApp (the existing WABA sender) or
to Meta by the conversation's channel, using the conversation's `external_id` as
the recipient (== wa_id for WhatsApp, PSID/IGSID for Meta).
"""
import logging

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


async def send_meta_message(recipient_id: str, text: str, page_id: str | None = None) -> None:
    """Send a text reply to a Messenger PSID / Instagram IGSID via the Send API,
    acting as the page that owns this PSID when page_id is given."""
    await _graph_post("me/messages", {
        "recipient": {"id": recipient_id},
        "messaging_type": "RESPONSE",
        "message": {"text": text},
    }, "send message", page_id=page_id)


async def reply_to_comment(comment_id: str, text: str, page_id: str | None = None) -> None:
    """Public reply posted under a Facebook/Instagram comment."""
    await _graph_post(f"{comment_id}/comments", {"message": text}, "reply to comment", page_id=page_id)


async def send_private_reply(comment_id: str, text: str, page_id: str | None = None) -> None:
    """Private reply to a comment — opens a Messenger thread with the commenter.
    One-shot per comment and time-limited by Meta; after it, the conversation
    continues as a normal Messenger DM (which the agent already handles)."""
    await _graph_post(f"{comment_id}/private_replies", {"message": text}, "send private reply", page_id=page_id)


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


async def fetch_post_context(post_id: str) -> dict:
    """Best-effort: the source post a comment is replying to, so the inbox can
    show WHAT the customer is commenting on (they never say — "how much?" under a
    photo is meaningless without the photo).

    One Graph read on the post id with the Page token; returns a compact dict:
        {post_id, title, permalink, thumb}
    `title` is the post caption, else the first attachment's title/description,
    else a type label ("Photo", "Video", "Shared link"). `thumb` is the post's
    picture when there is one. Returns {} on any error — the caller treats an
    empty context as "no card", never a failure. Callers should cache by post_id
    (posts don't change) to avoid re-fetching for every comment on the same post."""
    if not settings.meta_page_token or not post_id:
        return {}
    url = f"https://graph.facebook.com/{settings.meta_graph_version}/{post_id}"
    fields = "message,permalink_url,full_picture,created_time,attachments{title,description,media_type,media{image{src}}}"
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

    att = ((d.get("attachments") or {}).get("data") or [{}])[0]
    title = (d.get("message") or att.get("title") or att.get("description") or "").strip()
    if not title:
        _MEDIA_LABEL = {"photo": "Photo post", "video": "Video post",
                        "share": "Shared link", "album": "Photo album"}
        title = _MEDIA_LABEL.get((att.get("media_type") or "").lower(), "a post")
    thumb = (d.get("full_picture")
             or (((att.get("media") or {}).get("image") or {}).get("src")))
    return {
        "post_id":   post_id,
        "title":     title[:200],
        "permalink": d.get("permalink_url") or "",
        "thumb":     thumb or "",
    }


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


async def send_to_channel(channel: str, recipient: str, text: str,
                          page_id: str | None = None) -> None:
    """Dispatch an outbound text reply to the right transport for `channel`.
    `recipient` is the conversation's external_id (wa_id | PSID | IGSID)."""
    if channel in META_CHANNELS:
        if page_id is None:
            page_id = await page_of_contact(channel, recipient)
        await send_meta_message(recipient, text, page_id=page_id)
    else:
        # WhatsApp — the existing WABA sender expects a bare number (no '+').
        from app.services.n8n_bridge import _send_waba
        await _send_waba((recipient or "").lstrip("+"), text)


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
