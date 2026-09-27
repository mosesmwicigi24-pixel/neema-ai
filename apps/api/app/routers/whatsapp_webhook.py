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
    try:
        await _tap_voicemail(payload, redis)
    except Exception as exc:
        _log.warning("WA voicemail tap failed (continuing): %s", exc)
    try:
        await _tap_account_updates(payload, redis)
    except Exception as exc:
        _log.warning("WA account-update tap failed (continuing): %s", exc)
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


async def _tap_voicemail(payload: dict, redis) -> None:
    """WhatsApp voicemail arrives on `messages` as an inbound audio message whose
    id is the call's WACID: link it to that call (the message itself is still
    ingested into the chat as usual — this only adds the link)."""
    from app.services import call_log
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            if change.get("field") != "messages":
                continue
            for m in (change.get("value") or {}).get("messages", []):
                mid = str(m.get("id") or "")
                if m.get("type") != "audio" or not mid.startswith("wacid."):
                    continue
                if redis is not None:
                    try:
                        if not await redis.set(f"wa:call:{mid}:voicemail", "1", nx=True, ex=3600):
                            continue
                    except Exception:
                        pass
                await call_log.link_voicemail(redis, mid, mid, str(m.get("from") or "") or None)


# Calling reasons Meta sends on `account_update` (ACCOUNT_VIOLATION /
# ACCOUNT_RESTRICTION) — matched anywhere in the value, since the brief gives
# the reason names but not every envelope field.
CALLING_RESTRICTION_REASONS = (
    "LOW_BUSINESS_INITIATED_CALLING_QUALITY", "LOW_USER_INITIATED_CALLING_QUALITY",
    "USER_INITIATED_CALLS_LOW_PICKUP_RATE", "RESTRICTED_USER_INITIATED_CALLING_CALL_BUTTON_HIDDEN",
    "RESTRICTED_BUSINESS_INITIATED_CALLING", "RESTRICTED_USER_INITIATED_CALLING",
)
CALL_SETTINGS_EVENT_KEY = "wa:call:settings:last_event"
CALL_RESTRICTION_KEY = "wa:call:restriction:last"


async def _tap_account_updates(payload: dict, redis) -> None:
    """`account_settings_update` (calling settings changed) and `account_update`
    (calling violations / restrictions): keep the latest in redis for the
    settings screen and tell every agent."""
    if payload.get("object") != "whatsapp_business_account":
        return
    from datetime import datetime, timezone
    from app.services import call_log
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            field = change.get("field")
            value = change.get("value") or {}
            if field not in ("account_settings_update", "account_update"):
                continue
            text = json.dumps(value)
            at = datetime.now(timezone.utc).isoformat()
            if field == "account_settings_update":
                record = {"type": "call_settings", "value": value, "at": at}
                key = CALL_SETTINGS_EVENT_KEY
            else:
                reasons = [r for r in CALLING_RESTRICTION_REASONS if r in text]
                if not reasons:
                    continue          # an account_update about something else
                record = {"type": "calling_restricted", "event": value.get("event"),
                          "reasons": reasons, "value": value, "at": at}
                key = CALL_RESTRICTION_KEY
            if redis is not None:
                try:
                    await redis.set(key, json.dumps(record), ex=30 * 86400)
                except Exception:
                    pass
            await call_log.publish(redis, record)


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
            for st in value.get("statuses", []) or []:
                if isinstance(st, dict) and st.get("type") == "call":
                    await _handle_call_status(redis, st)
            for call in value.get("calls", []):
                cid = call.get("id")
                event = call.get("event")
                _log.warning("WA call event=%s id=%s from=%s has_sdp=%s",
                             event, cid, call.get("from"),
                             bool((call.get("session") or {}).get("sdp")))
                if not cid:
                    continue
                # Dedup: process each (call id, event) once. A redis that can't
                # answer fails open — the handlers below are idempotent anyway.
                dedup_key = f"wa:call:{cid}:{event}"
                if not await _first_delivery(redis, dedup_key):
                    continue
                sdp_type = (call.get("session") or {}).get("sdp_type")
                # Our OUTBOUND call was accepted: the customer's SDP ANSWER arrives
                # as a connect event with sdp_type=answer. Relay it to the browser
                # that placed the call so it can complete the WebRTC connection.
                from app.services import call_log
                if event in ("call_transcription_available", "call_recording_available"):
                    from app.services import call_transcribe
                    call_transcribe.schedule_meta_artifact(
                        "transcription" if event == "call_transcription_available" else "recording",
                        cid, call)
                    continue
                # Our business-initiated call: the customer is `to`. When Meta
                # beat /calls/connect's row, write it from our opaque data.
                if call.get("biz_opaque_callback_data") and \
                        str(call.get("direction") or "").upper() != "USER_INITIATED":
                    await call_log.row_from_opaque(cid, str(call.get("to") or "") or None,
                                                   call.get("biz_opaque_callback_data"))
                if event == "connect" and sdp_type == "answer":
                    # Our OUTBOUND call was accepted: the customer's SDP ANSWER.
                    # Relay it to the device that placed the call so it can
                    # complete the WebRTC connection, then tell every agent.
                    # (Unless its terminate was logged first: the call is over.)
                    if await call_log.status_of(cid) in call_log.TERMINAL:
                        continue
                    await call_log.publish(redis, {
                        "type": "outbound_answer", "call_id": cid,
                        "sdp": (call.get("session") or {}).get("sdp"),
                    })
                    _log.warning("WA outbound call %s answered by customer", cid)
                    moved = await call_log.mark_answered(cid, None, redis)
                    if moved is not None:
                        await call_log.publish(redis, {"type": "call_answered", "call_id": cid, **moved})
                    elif not await call_log.known_call(cid):
                        # Beat /calls/connect's row: applied when it lands. (A row
                        # already over — its terminate came first — stays over.)
                        await call_log.park(redis, "answer", cid)
                    continue

                if event == "connect":
                    _log.info("WA incoming call %s from %s", cid, call.get("from"))
                    frm = call.get("from")
                    # Never ring a call that is already over: its terminate
                    # beat this connect, or this is a late redelivery of a call
                    # we logged long ago (the dedup key only lives an hour).
                    early_end = await call_log.ended_before_ring(redis, cid)
                    if early_end is not None:
                        if not await call_log.record_ringing(cid, frm, _contacts.get(str(frm))):
                            await _release(redis, dedup_key)   # parked end kept for a redelivery
                            continue
                        await call_log.apply_early(redis, cid)
                        await call_log.publish_update(redis, cid)
                        continue
                    if await call_log.known_call(cid):
                        continue
                    if redis is not None:
                        # Stash the SDP offer + metadata for the accept step.
                        try:
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
                        except Exception as exc:
                            _log.warning("WA call offer stash failed for %s: %s", cid, exc)
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
                    if not await call_log.record_ringing(cid, frm, _contacts.get(str(frm))):
                        # The row didn't land (database blip): let a redelivery
                        # write it; the terminate writes it too (on_terminate).
                        await _release(redis, dedup_key)
                        continue
                    # A terminate parked while we wrote the row is applied now.
                    await call_log.apply_early(redis, cid)
                    await call_log.publish_update(redis, cid)
                elif event == "terminate":
                    _log.info("WA call %s terminated (status=%s, dur=%ss)",
                              cid, call.get("status"), (call.get("duration") or "?"))
                    if not await on_terminate(redis, cid, call.get("duration"), call.get("status")):
                        await _release(redis, dedup_key)   # database blip: a redelivery applies it


async def _first_delivery(redis, key: str) -> bool:
    """True the first time this (call, event) is seen. Fails open when redis
    can't answer: every call handler is idempotent on the row."""
    if redis is None:
        return True
    try:
        return bool(await redis.set(key, "1", nx=True, ex=3600))
    except Exception as exc:
        _log.warning("call dedup unavailable (%s) — processing %s", exc, key)
        return True


async def _release(redis, key: str) -> None:
    if redis is None:
        return
    try:
        await redis.delete(key)
    except Exception:
        pass


async def _ring_stash(redis, cid: str) -> dict | None:
    """What the connect webhook stashed when it rang this call (None if it never did)."""
    if redis is None:
        return None
    try:
        raw = await redis.get(f"wa:call:offer:{cid}")
        return json.loads(raw) if raw else None
    except Exception:
        return None


async def _hang_up_intent(redis, cid: str) -> tuple[str | None, object]:
    """(declined | callback, agent id) when an agent's decline / call-back claimed
    this call — so Meta's terminate for it, landing before our own
    bookkeeping, logs what the agent did instead of "missed"."""
    if redis is None:
        return None, None
    try:
        raw = await redis.get(f"wa:call:answered:{cid}")
    except Exception:
        return None, None
    v = raw.decode() if isinstance(raw, bytes) else str(raw or "")
    parts = v.split("|")
    if len(parts) >= 3 and parts[-1] in ("declined", "callback"):
        import uuid as _uuid
        try:
            return parts[-1], _uuid.UUID(parts[0])
        except ValueError:
            return parts[-1], None
    return None, None


async def on_terminate(redis, cid: str, duration, status, extra: dict | None = None) -> bool:
    """Meta's `terminate` for a call (either channel): close the row and tell
    every agent. A call already closed on our side (declined, callback, the
    stale sweep) is still announced with its logged outcome — a screen that
    missed that event must stop ringing now. A terminate with no row yet is
    parked and announced (with the real outcome) when the row lands; only a
    call that already rang (its row lost to a database blip) is announced
    now, and its row is written from the ring stash so the log converges.
    Returns False when the database couldn't be reached (let a redelivery in)."""
    from app.services import call_log
    intent, intent_agent = await _hang_up_intent(redis, cid)
    info = await call_log.mark_ended(cid, status=intent, duration=duration, agent_id=intent_agent)
    moved = info is not None
    db_ok = True
    if info is None:
        try:
            from app.database import AsyncSessionLocal
            async with AsyncSessionLocal() as db:
                r = await call_log.row(db, cid)
        except Exception:
            r, db_ok = None, False
        if r is None:
            stash = await _ring_stash(redis, cid)
            if stash and db_ok:
                messenger = stash.get("channel") == "messenger"
                if await call_log.record_ringing(
                        cid, None if messenger else stash.get("from"), None,
                        channel="messenger" if messenger else "whatsapp",
                        external_id=stash.get("from") if messenger else None):
                    info = await call_log.mark_ended(cid, duration=duration)
                    moved = info is not None
            if info is None:
                # No row yet (this terminate beat the connect, or our
                # outbound row): park it for when it lands.
                if await call_log.park(redis, "end", cid, {
                        "duration": duration, "status": status, **(extra or {})}):
                    return True     # the row landed meanwhile: applied and announced
                if not stash:
                    return db_ok      # it never rang: the row's arrival announces it
                info = {"call_id": cid,
                        "outcome": "completed" if call_log._connected_by_meta(duration) else "missed",
                        "duration": duration, "direction": "inbound"}
        elif r.get("status") in call_log.LIVE:
            # Still live: the close itself failed (a database blip) — once more,
            # else leave it to Meta's redelivery / the stale sweep.
            info = await call_log.mark_ended(cid, status=intent, duration=duration, agent_id=intent_agent)
            moved = info is not None
            if info is None:
                return False
        else:
            info = {"call_id": cid, "outcome": r.get("status"),
                    "duration": r.get("duration") or duration,
                    "direction": r.get("direction"),
                    "agent_id": r.get("agent_id"),
                    "agent_name": r.get("agent_name")}
    info.pop("wa_id", None)
    await call_log.publish(redis, {
        "type": "call_ended", **info, "call_id": cid,
        "status": status, **(extra or {}),
    })
    if moved and info.get("outcome") == "missed":
        from app.services import missed_call
        missed_call.schedule(redis, cid)
    return moved or db_ok


async def _handle_call_status(redis, st: dict) -> None:
    """Business-initiated call status: RINGING (the customer's phone rings),
    ACCEPTED (audit only — the connect answer already moved the call),
    REJECTED (the customer declined our call). Deduped per (call, status)."""
    from app.services import call_log
    cid = st.get("id")
    status = str(st.get("status") or "").upper()
    if not cid or status not in ("RINGING", "ACCEPTED", "REJECTED"):
        return
    if not await _first_delivery(redis, f"wa:call:{cid}:status:{status}"):
        return
    if st.get("biz_opaque_callback_data"):
        await call_log.row_from_opaque(cid, str(st.get("recipient_id") or "") or None,
                                       st.get("biz_opaque_callback_data"))
    if status == "RINGING":
        # A RINGING that limps in after the call ended (REJECTED / terminate
        # first) must not flip a finished screen back to "Ringing…".
        if await call_log.status_of(cid) not in call_log.TERMINAL:
            await call_log.publish(redis, {"type": "call_status", "call_id": cid, "status": "ringing"})
    elif status == "REJECTED":
        info = await call_log.mark_rejected(cid)
        if info is None:
            if not await call_log.known_call(cid):
                # No row yet and nothing to build it from: park for the row.
                await call_log.park(redis, "rejected", cid, {"status": "REJECTED"})
            else:
                info = await call_log.mark_rejected(cid)   # the row landed a moment ago
            if info is None:
                return
        info.pop("wa_id", None)
        await call_log.publish(redis, {"type": "call_ended", **info, "status": "REJECTED"})
