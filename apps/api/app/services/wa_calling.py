"""WhatsApp voice-calling — the accept/terminate half (Graph Cloud API).

The webhook (routers/whatsapp_webhook.py) receives a `connect` event with the
caller's SDP offer and stashes it in redis. When the agent answers in the
dashboard softphone, the browser builds a WebRTC SDP answer and hands it here;
we relay it to Meta with `pre_accept` then `accept` (pre_accept first so the media
connection is established before audio flows, avoiding clipping). Terminate ends
the call. All calls go to POST /<PHONE_NUMBER_ID>/calls with the WABA token.
"""
import logging

import httpx

from app.core.config import settings

_log = logging.getLogger("neema.wa")


async def _call_action(body: dict, what: str) -> dict:
    if not settings.waba_token or not settings.waba_phone_number_id:
        raise RuntimeError("WABA not configured — cannot " + what)
    url = (f"https://graph.facebook.com/{settings.waba_api_version}"
           f"/{settings.waba_phone_number_id}/calls")
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            url,
            headers={"Authorization": f"Bearer {settings.waba_token}"},
            json={"messaging_product": "whatsapp", **body},
            timeout=30.0,
        )
    if not resp.is_success:
        _log.error("WA call %s failed %s: %s", what, resp.status_code, resp.text)
        raise RuntimeError(f"WA call {what} failed ({resp.status_code}): {resp.text[:300]}")
    return resp.json() if resp.content else {}


async def pre_accept(call_id: str, sdp_answer: str) -> dict:
    """Establish the media connection before accepting — avoids audio clipping."""
    return await _call_action(
        {"call_id": call_id, "action": "pre_accept",
         "session": {"sdp_type": "answer", "sdp": sdp_answer}},
        "pre_accept")


async def accept(call_id: str, sdp_answer: str) -> dict:
    """Accept the call with our SDP answer — audio flows after this."""
    return await _call_action(
        {"call_id": call_id, "action": "accept",
         "session": {"sdp_type": "answer", "sdp": sdp_answer}},
        "accept")


async def terminate(call_id: str) -> dict:
    """Hang up / decline a call."""
    return await _call_action({"call_id": call_id, "action": "terminate"}, "terminate")


def ice_servers() -> list[dict]:
    """ICE server list for the browser's RTCPeerConnection: our coturn (if
    configured) plus a public STUN fallback for same-network testing."""
    servers: list[dict] = []
    if settings.turn_url:
        entry = {"urls": settings.turn_url}
        if settings.turn_username:
            entry["username"] = settings.turn_username
            entry["credential"] = settings.turn_credential
        servers.append(entry)
    if settings.stun_url:
        servers.append({"urls": settings.stun_url})
    return servers
