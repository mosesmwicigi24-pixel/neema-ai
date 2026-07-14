"""WhatsApp Cloud API webhook — the front door (Option A).

Our API becomes the WABA callback URL. It is a TRANSPARENT PROXY: every inbound
event is forwarded verbatim (raw body + signature header) to n8n, so the existing
WhatsApp messaging pipeline keeps working byte-for-byte. On top of that, it taps
the `calls` webhook field to drive voice calling — parsing `connect`/`terminate`
and ringing the dashboard over the existing WebSocket. No audio here; media is a
browser↔Meta WebRTC connection set up in a later slice. Signaling only.

The forward is best-effort-but-loud: if n8n can't be reached we return non-200 so
Meta retries (a message is never silently dropped). Calls are deduped on call id
so a Meta retry never double-rings.
"""
import hashlib
import hmac
import json
import logging

import httpx
from fastapi import APIRouter, Request, Response
from fastapi.responses import PlainTextResponse

from app.core.config import settings

router = APIRouter()
_log = logging.getLogger("neema.wa")


def _verify_token() -> str:
    return settings.whatsapp_verify_token or settings.meta_verify_token


@router.get("/webhook")
async def verify(request: Request):
    """Meta subscription handshake — echo hub.challenge on a matching token."""
    p = request.query_params
    tok = _verify_token()
    if not tok:
        _log.warning("WA webhook GET but no verify token configured — refusing.")
        return Response(status_code=403)
    if p.get("hub.mode") == "subscribe" and p.get("hub.verify_token") and \
            hmac.compare_digest(p.get("hub.verify_token"), tok):
        return PlainTextResponse(p.get("hub.challenge", ""))
    return Response(status_code=403)


def _valid_signature(raw: bytes, header: str | None) -> bool:
    if not settings.meta_app_secret:
        return True                       # dev only
    if not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(settings.meta_app_secret.encode(), raw, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header.split("=", 1)[1])


async def _forward_to_n8n(raw: bytes, sig: str | None) -> bool:
    """Relay the event verbatim to n8n so messaging is unaffected. Returns True on
    success (or when no forward URL is set — nothing to do)."""
    url = (settings.whatsapp_forward_url or "").strip()
    if not url:
        return True
    headers = {"Content-Type": "application/json"}
    if sig:
        headers["X-Hub-Signature-256"] = sig
    try:
        async with httpx.AsyncClient() as client:
            r = await client.post(url, content=raw, headers=headers, timeout=15.0)
        if r.is_success:
            return True
        _log.error("WA forward to n8n → %s: %s", r.status_code, r.text[:200])
        return False
    except Exception as exc:
        _log.error("WA forward to n8n failed: %s", exc)
        return False


@router.post("/webhook")
async def receive(request: Request):
    raw = await request.body()
    sig = request.headers.get("x-hub-signature-256")
    if not _valid_signature(raw, sig):
        _log.warning("WA webhook POST rejected: bad signature")
        return Response(status_code=403)

    # 1) TRANSPARENT FORWARD — messaging must keep flowing to n8n untouched. If it
    #    fails, tell Meta to retry (non-200) so no message is lost.
    forwarded = await _forward_to_n8n(raw, sig)

    # 2) TAP calls — best-effort; never let it affect the messaging forward result.
    try:
        payload = json.loads(raw)
        await _handle_calls(request, payload)
    except Exception as exc:
        _log.warning("WA calls handling failed (acking anyway): %s", exc)

    if not forwarded:
        return Response(status_code=502)      # Meta retries; message not dropped
    return PlainTextResponse("EVENT_RECEIVED")


async def _handle_calls(request: Request, payload: dict) -> None:
    """Ring the dashboard on an inbound call; log a terminate. Deduped on call id
    via redis so a Meta retry never double-rings. SDP is kept for the answer step
    (a later slice); here we only surface the incoming call."""
    if payload.get("object") != "whatsapp_business_account":
        return
    redis = getattr(request.app.state, "redis", None)
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            if change.get("field") != "calls":
                continue
            # WARNING level so it's always visible in prod logs (INFO may be
            # filtered). Calls are rare + important, so this is fine.
            _log.warning("WA calls webhook received: %s", json.dumps(change.get("value") or {})[:400])
            value = change.get("value") or {}
            phone_number_id = (value.get("metadata") or {}).get("phone_number_id")
            # Caller name from the WABA contacts block (e.g. "Pastor Mwicigi").
            _contacts = {str(c.get("wa_id")): (c.get("profile") or {}).get("name")
                         for c in (value.get("contacts") or [])}
            for call in value.get("calls", []):
                cid = call.get("id")
                event = call.get("event")
                _log.warning("WA call event=%s id=%s from=%s has_sdp=%s",
                             event, cid, call.get("from"),
                             bool((call.get("session") or {}).get("sdp")))
                if not cid:
                    continue
                # Dedup: process each (call id, event) once.
                if redis is not None:
                    fresh = await redis.set(f"wa:call:{cid}:{event}", "1", nx=True, ex=3600)
                    if not fresh:
                        continue
                sdp_type = (call.get("session") or {}).get("sdp_type")
                # Our OUTBOUND call was accepted: the customer's SDP ANSWER arrives
                # as a connect event with sdp_type=answer. Relay it to the browser
                # that placed the call so it can complete the WebRTC connection.
                if event == "connect" and sdp_type == "answer":
                    if redis is not None:
                        await redis.publish("ws:channel:calls", json.dumps({
                            "type": "outbound_answer", "call_id": cid,
                            "sdp": (call.get("session") or {}).get("sdp"),
                        }))
                        _log.warning("WA outbound call %s answered by customer", cid)
                    try:
                        from app.services import call_log
                        await call_log.mark_answered(cid, None)
                    except Exception:
                        pass
                    continue

                if event == "connect":
                    _log.info("WA incoming call %s from %s", cid, call.get("from"))
                    try:
                        from app.services import call_log
                        await call_log.record_ringing(cid, call.get("from"),
                                                      _contacts.get(str(call.get("from"))))
                    except Exception:
                        pass
                    if redis is not None:
                        # Stash the SDP offer + metadata for the accept step.
                        await redis.set(
                            f"wa:call:offer:{cid}",
                            json.dumps({
                                "from": call.get("from"),
                                "to": call.get("to"),
                                "phone_number_id": phone_number_id,
                                "sdp": (call.get("session") or {}).get("sdp"),
                                "timestamp": call.get("timestamp"),
                            }),
                            ex=300,
                        )
                        await redis.publish("ws:channel:calls", json.dumps({
                            "type": "incoming_call", "call_id": cid,
                            "from": call.get("from"),
                            "name": _contacts.get(str(call.get("from"))),
                            "at": call.get("timestamp"),
                        }))
                        _log.warning("WA published incoming_call ring for %s", cid)
                elif event == "terminate":
                    _log.info("WA call %s terminated (status=%s, dur=%ss)",
                              cid, call.get("status"), (call.get("duration") or "?"))
                    try:
                        from app.services import call_log
                        await call_log.mark_ended(cid, duration=call.get("duration"))
                    except Exception:
                        pass
                    if redis is not None:
                        await redis.publish("ws:channel:calls", json.dumps({
                            "type": "call_ended", "call_id": cid,
                            "status": call.get("status"), "duration": call.get("duration"),
                        }))
