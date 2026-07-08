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

META_CHANNELS = ("messenger", "instagram")


async def send_meta_message(recipient_id: str, text: str) -> None:
    """Send a text reply to a Messenger PSID / Instagram IGSID. Raises if the
    Page token is unset or Graph rejects the call (the caller decides how to
    surface it)."""
    if not settings.meta_page_token:
        raise RuntimeError("META_PAGE_TOKEN not configured — cannot send a Messenger/IG reply")
    url = f"https://graph.facebook.com/{settings.meta_graph_version}/me/messages"
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            url,
            params={"access_token": settings.meta_page_token},
            json={
                "recipient": {"id": recipient_id},
                "messaging_type": "RESPONSE",
                "message": {"text": text},
            },
            timeout=30.0,
        )
        if not resp.is_success:
            _log.error("Meta Send API error %s: %s", resp.status_code, resp.text)
            resp.raise_for_status()


async def send_to_channel(channel: str, recipient: str, text: str) -> None:
    """Dispatch an outbound text reply to the right transport for `channel`.
    `recipient` is the conversation's external_id (wa_id | PSID | IGSID)."""
    if channel in META_CHANNELS:
        await send_meta_message(recipient, text)
    else:
        # WhatsApp — the existing WABA sender expects a bare number (no '+').
        from app.services.n8n_bridge import _send_waba
        await _send_waba((recipient or "").lstrip("+"), text)
