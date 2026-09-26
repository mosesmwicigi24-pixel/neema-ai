"""WhatsApp Cloud API webhook — the front door.

Our API is the WABA callback URL. Every inbound event is processed NATIVELY
in-process (app/services/wa_native.py: parse, persist, debounce, reply) — the
n8n forward this door originally fronted was retired on 2026-07-30. The door
also taps the `calls` webhook field to drive voice calling — parsing
`connect`/`terminate` and ringing the dashboard over the existing WebSocket
(signaling only; call audio is a browser↔Meta WebRTC connection).

A failed ingest returns non-200 so Meta redelivers — a message is never
acked-and-lost. Calls are deduped on call id so a Meta retry never double-rings.
"""
import hashlib
import hmac
import json
import logging

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
    # WHATSAPP_APP_SECRET overrides for deployments where the WhatsApp product
    # lives in a different Meta app (different signing secret) than Messenger.
    secret = settings.whatsapp_app_secret or settings.meta_app_secret
    if not secret:
        return True                       # dev only
    if not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header.split("=", 1)[1])


@router.post("/webhook")
async def receive(request: Request):
    raw = await request.body()
    sig = request.headers.get("x-hub-signature-256")
    if not _valid_signature(raw, sig):
        _log.warning("WA webhook POST rejected: bad signature")
        return Response(status_code=403)
    return await process_payload(request, raw, sig)


async def process_payload(request: Request, raw: bytes, sig: str | None) -> Response:
    """Handle one signature-verified WhatsApp webhook delivery, from whichever
    route it arrived on (/api/wa/webhook, or /api/meta/webhook when the Meta app's
    WhatsApp callback was pointed there). Everything is processed in-process
    (app/services/wa_native.py): parse, persist, debounce, reply. `sig` was
    already verified by the caller; it stays in the signature for those callers."""
    redis = getattr(request.app.state, "redis", None)

    try:
        payload = json.loads(raw)
    except Exception:
        return PlainTextResponse("EVENT_RECEIVED")   # not JSON — nothing to do
    # The taps are best-effort: a redis blip in the calls/wamid handling must
    # never cost the customer messages riding in the same delivery.
    try:
        await _handle_calls(request, payload)
    except Exception as exc:
        _log.warning("WA calls tap failed (continuing): %s", exc)
    try:
        await _tap_inbound_wamids(payload, redis)
    except Exception as exc:
        _log.warning("WA wamid tap failed (continuing): %s", exc)
    try:
        await _tap_call_permission(payload, redis)
    except Exception as exc:
        _log.warning("WA call-permission tap failed (continuing): %s", exc)
    from app.services import wa_native
    n, failed = await wa_native.handle_webhook(payload, redis)
    if n or failed:
        _log.info("WA native webhook: %d message(s) ingested, %d failed", n, failed)
    if failed:
        # Failed events released their dedup guard — bounce so Meta
        # redelivers them. Never acked-and-lost.
        return Response(status_code=502)
    return PlainTextResponse("EVENT_RECEIVED")


async def _tap_call_permission(payload: dict, redis) -> None:
    """A customer answered our call-permission request (the interactive
    `call_permission_reply` message): remember it and tell every agent, so the
    one waiting to call sees "Allowed — call now" the moment they tap Allow."""
    from app.services import call_log
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            if change.get("field") != "messages":
                continue
            for m in (change.get("value") or {}).get("messages", []):
                inter = m.get("interactive") or {}
                if m.get("type") != "interactive" or inter.get("type") != "call_permission_reply":
                    continue
                await call_log.note_permission_reply(
                    redis, str(m.get("from") or ""), inter.get("call_permission_reply") or {})


async def _tap_inbound_wamids(payload: dict, redis) -> None:
    """Stash inbound WhatsApp message ids (wamid) keyed by (wa_id, text-hash), TTL
    1 day. The message-persistence service recovers them to set
    Message.waba_msg_id, so a human reply can quote the customer's message
    natively (Cloud API context). Best-effort and side-effect-free."""
    if redis is None:
        return
    import hashlib
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            if change.get("field") != "messages":
                continue
            for m in (change.get("value") or {}).get("messages", []):
                wamid = m.get("id")
                frm = m.get("from")
                body = ((m.get("text") or {}).get("body") or "").strip()
                if not (wamid and frm and body):
                    continue
                h = hashlib.sha1(body.encode("utf-8")).hexdigest()[:16]
                try:
                    await redis.set(f"wa:wamid:{frm}:{h}", wamid, ex=86400)
                except Exception:
                    pass


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
                from app.services import call_log
                if event == "connect" and sdp_type == "answer":
                    # Our OUTBOUND call was accepted: the customer's SDP ANSWER.
                    # Relay it to the device that placed the call so it can
                    # complete the WebRTC connection, then tell every agent.
                    await call_log.publish(redis, {
                        "type": "outbound_answer", "call_id": cid,
                        "sdp": (call.get("session") or {}).get("sdp"),
                    })
                    _log.warning("WA outbound call %s answered by customer", cid)
                    moved = await call_log.mark_answered(cid, None)
                    if moved is not None:
                        await call_log.publish(redis, {"type": "call_answered", "call_id": cid, **moved})
                    continue

                if event == "connect":
                    _log.info("WA incoming call %s from %s", cid, call.get("from"))
                    frm = call.get("from")
                    if redis is not None:
                        # Stash the SDP offer + metadata for the accept step.
                        await redis.set(
                            f"wa:call:offer:{cid}",
                            json.dumps({
                                "from": frm,
                                "to": call.get("to"),
                                "phone_number_id": phone_number_id,
                                "sdp": (call.get("session") or {}).get("sdp"),
                                "timestamp": call.get("timestamp"),
                            }),
                            ex=300,
                        )
                    # Ring first — every millisecond before an agent sees the call
                    # is the customer listening to silence — then log it and send
                    # the row (the person / chat links) as an update.
                    await call_log.publish(redis, {
                        "type": "incoming_call", "call_id": cid,
                        "from": frm,
                        "name": _contacts.get(str(frm)),
                        "at": call.get("timestamp"),
                        "channel": "whatsapp",
                    })
                    _log.warning("WA published incoming_call ring for %s", cid)
                    await call_log.record_ringing(cid, frm, _contacts.get(str(frm)))
                    await call_log.publish_update(redis, cid)
                elif event == "terminate":
                    _log.info("WA call %s terminated (status=%s, dur=%ss)",
                              cid, call.get("status"), (call.get("duration") or "?"))
                    info = await call_log.mark_ended(cid, duration=call.get("duration"))
                    if info is None:
                        # Already closed on our side (declined, callback, the stale
                        # sweep): still say so — a screen that missed that event
                        # must stop ringing now.
                        try:
                            from app.database import AsyncSessionLocal
                            async with AsyncSessionLocal() as db:
                                r = await call_log.row(db, cid)
                        except Exception:
                            r = None
                        info = {"call_id": cid, "outcome": (r or {}).get("status") or "completed",
                                "duration": (r or {}).get("duration") or call.get("duration"),
                                "direction": (r or {}).get("direction"),
                                "agent_id": (r or {}).get("agent_id"),
                                "agent_name": (r or {}).get("agent_name")}
                    info.pop("wa_id", None)
                    await call_log.publish(redis, {
                        "type": "call_ended", **info, "call_id": cid,
                        "status": call.get("status"),
                    })
