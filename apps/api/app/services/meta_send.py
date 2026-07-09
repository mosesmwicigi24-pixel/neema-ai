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


async def _graph_post(path: str, body: dict, what: str) -> dict:
    """POST to the Graph API with the Page token in the Authorization header —
    NEVER in the URL, so the token can't leak into request logs or error
    messages. On failure, logs Facebook's message (token-free) and raises a clean
    error that carries no URL and no token."""
    if not settings.meta_page_token:
        raise RuntimeError(f"META_PAGE_TOKEN not configured — cannot {what}")
    url = f"https://graph.facebook.com/{settings.meta_graph_version}/{path}"
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            url,
            headers={"Authorization": f"Bearer {settings.meta_page_token}"},
            json=body,
            timeout=30.0,
        )
    if not resp.is_success:
        _log.error("Meta %s failed %s: %s", what, resp.status_code, resp.text)
        raise RuntimeError(f"Meta {what} failed ({resp.status_code}): {resp.text[:300]}")
    return resp.json() if resp.content else {}


async def send_meta_message(recipient_id: str, text: str) -> None:
    """Send a text reply to a Messenger PSID / Instagram IGSID via the Send API."""
    await _graph_post("me/messages", {
        "recipient": {"id": recipient_id},
        "messaging_type": "RESPONSE",
        "message": {"text": text},
    }, "send message")


async def reply_to_comment(comment_id: str, text: str) -> None:
    """Public reply posted under a Facebook/Instagram comment."""
    await _graph_post(f"{comment_id}/comments", {"message": text}, "reply to comment")


async def send_private_reply(comment_id: str, text: str) -> None:
    """Private reply to a comment — opens a Messenger thread with the commenter.
    One-shot per comment and time-limited by Meta; after it, the conversation
    continues as a normal Messenger DM (which the agent already handles)."""
    await _graph_post(f"{comment_id}/private_replies", {"message": text}, "send private reply")


async def send_to_channel(channel: str, recipient: str, text: str) -> None:
    """Dispatch an outbound text reply to the right transport for `channel`.
    `recipient` is the conversation's external_id (wa_id | PSID | IGSID)."""
    if channel in META_CHANNELS:
        await send_meta_message(recipient, text)
    else:
        # WhatsApp — the existing WABA sender expects a bare number (no '+').
        from app.services.n8n_bridge import _send_waba
        await _send_waba((recipient or "").lstrip("+"), text)
