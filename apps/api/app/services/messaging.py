"""The messaging persistence + delivery service.

The message / conversation / user persistence layer and the WhatsApp (WABA)
sender, imported across the app: the native WhatsApp pipeline, web chat, the
Meta channels, the sweeps and the admin routes all save and send through here.
"""
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
import json
import httpx
from datetime import datetime, timezone, timedelta

from app.core import money
from app.core.media_urls import sign_for_meta as _sign_for_meta
from app.models.conversation import Conversation, InterceptMode
from app.models.message import Message, MsgDirection, MsgSender
from app.models.user import User
from app.models.order_event import OrderEvent
from app.models.customer_history import CustomerHistory
from app.core.config import settings


# ── Shared timestamp helpers ──────────────────────────────

def _fmt_ts(dt: datetime | None) -> str:
    """UTC datetime → Firestore timestampValue string (no microseconds)."""
    if dt is None:
        dt = datetime.now(timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def _fmt_ts_ms(dt: datetime | None) -> str:
    """UTC datetime → timestampValue/tsIso with millisecond precision (.000Z)."""
    if dt is None:
        dt = datetime.now(timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"

def _fmt_precise(dt: datetime | None) -> str:
    """UTC datetime → createTime/updateTime string with microseconds."""
    if dt is None:
        dt = datetime.now(timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")

# Normalize wa_id by stripping leading + and whitespace to ensure consistent storage and lookup.
def _normalize_wa_id(wa_id: str) -> str:
    """Always store wa_id without a leading + to ensure consistent lookup."""
    return wa_id.lstrip("+").strip() if wa_id else wa_id


async def provision_user(
    db: AsyncSession,
    wa_id: str,
    *,
    name: str | None = None,
    last_text: str | None = None,
    last_direction: str | None = None,
) -> User:
    """Find-or-create the User row behind a wa_id and enrich it server-side.

    This is the single place that guarantees every conversation has a backing
    profile. It is server-AUTHORITATIVE for country (resolved from the dialing
    prefix, so it never depends on any external enrichment) and it
    captures the WhatsApp profile name without ever clobbering a name an
    operator has confirmed.

    - name: only fills an empty, non-operator-confirmed name (the WhatsApp
      profile name). Operator edits set name_confirmed=True and win.
    - country/country_iso/flag_url: filled from the phone prefix whenever the
      row has no country yet.

    Caller owns the commit (this only flushes so the row is usable within the
    same transaction).
    """
    from app.core.countries import resolve_country

    from app.core.phone import is_plausible_phone

    wa_id = _normalize_wa_id(wa_id)
    is_phone = is_plausible_phone(wa_id)
    result = await db.execute(select(User).where(User.wa_id == wa_id))
    user = result.scalar_one_or_none()
    created = False
    if user is None:
        # A 16-17 digit Meta id is not a phone — never surface it in the phone
        # field (that's how PSIDs ended up displayed as "Phone" in the CRM).
        user = User(wa_id=wa_id, phone=(wa_id if is_phone else None))
        db.add(user)
        created = True

    clean_name = (name or "").strip()
    if clean_name and not user.name_confirmed and not (user.name or "").strip():
        user.name = clean_name[:100]

    if not user.country:
        loc = resolve_country(wa_id)
        if loc["country"]:
            user.country = loc["country"]
            user.country_iso = loc["country_iso"]
            user.flag_url = loc["flag_url"]

    if last_text is not None:
        user.last_text = last_text
    if last_direction is not None:
        user.last_direction = last_direction
    if created or last_text is not None:
        user.last_message_at = datetime.now(timezone.utc)

    # ── Identity spine: bind this WhatsApp profile to a person ─────────────────
    # Additive — guarantees every user row carries a person_id (the backfill did
    # history; this does the future). A phone IS the person in World A, so the
    # (whatsapp, wa_id) identity is deterministic. Never overwrites an existing
    # person link (that only changes via an audited merge).
    # Guard: only a real phone can become a (whatsapp, …) identity. A Meta id
    # reaching this path (e.g. the CRM's orphan-conversation fallback) must not
    # mint a phantom "WhatsApp" identity — adopt an existing one instead.
    if is_phone:
        from app.services.identity import resolve_or_create_person, WHATSAPP
        ident = await resolve_or_create_person(
            db, WHATSAPP, wa_id,
            display_name=(user.name or clean_name or None),
            source="whatsapp_inbound", confidence="deterministic",
        )
        if user.person_id is None:
            user.person_id = ident.person_id
    elif user.person_id is None:
        from app.services.identity import resolve_person_id_for_wa_id
        user.person_id = await resolve_person_id_for_wa_id(db, wa_id)  # adopt-only for non-phones

    await db.flush()
    return user


def _wamid_of(resp) -> str | None:
    """The wamid Graph returned for a send (messages[0].id) — the id an inbound
    reply-quote later carries back as context.message_id. Best-effort: None when
    the response body isn't parseable."""
    try:
        return (resp.json().get("messages") or [{}])[0].get("id") or None
    except Exception:
        return None


async def _send_waba_image(wa_id: str, image_url: str, caption: str = "") -> str | None:
    """Send an image by public link (e.g. the how-to-measure guide).
    Returns the sent message's wamid."""
    url = (f"https://graph.facebook.com/{settings.waba_api_version}"
           f"/{settings.waba_phone_number_id}/messages")
    image: dict = {"link": _sign_for_meta(image_url)}
    if caption:
        image["caption"] = caption
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            url,
            headers={"Authorization": f"Bearer {settings.waba_token}"},
            json={
                "messaging_product": "whatsapp",
                "to": wa_id,
                "type": "image",
                "image": image,
            },
            timeout=30.0,
        )
        if not resp.is_success:
            import logging
            logging.error(f"WABA image error {resp.status_code}: {resp.text}")
            resp.raise_for_status()
        return _wamid_of(resp)


async def _send_waba_audio(wa_id: str, audio_url: str) -> str | None:
    """Send a pre-generated TTS audio file to WhatsApp via a public link.
    Returns the sent message's wamid."""
    url = (f"https://graph.facebook.com/{settings.waba_api_version}"
           f"/{settings.waba_phone_number_id}/messages")
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            url,
            headers={"Authorization": f"Bearer {settings.waba_token}"},
            json={
                "messaging_product": "whatsapp",
                "to": wa_id,
                "type": "audio",
                "audio": {"link": _sign_for_meta(audio_url)},
            },
            timeout=30.0,
        )
        if not resp.is_success:
            import logging
            logging.error(f"WABA audio error {resp.status_code}: {resp.text}")
            resp.raise_for_status()
        return _wamid_of(resp)

# ── WABA Sender ───────────────────────────────────────────

class SendOutcomeUnknown(RuntimeError):
    """The request reached Meta but no answer came back in time (a read
    timeout, a dropped connection after the write). The message MAY have been
    accepted and delivered — the Cloud API has no idempotency key, so a blind
    retry is how a customer gets the same text twice. Callers record the
    attempt as `unknown` and never resend automatically; a person checks the
    thread (audit, 2026-11-05)."""


# Connect timeouts and refused connections mean the request never left:
# retrying is safe. Anything after the write is ambiguous.
_SEND_TIMEOUT = httpx.Timeout(30.0, connect=10.0)
_UNKNOWN_AFTER_WRITE = (httpx.ReadTimeout, httpx.WriteTimeout, httpx.PoolTimeout,
                        httpx.RemoteProtocolError, httpx.ReadError, httpx.WriteError)


async def _post_graph(url: str, body: dict) -> httpx.Response:
    """One Graph POST with an explicit timeout. Raises SendOutcomeUnknown when
    the outcome cannot be known; other transport errors mean "not sent"."""
    try:
        async with httpx.AsyncClient(timeout=_SEND_TIMEOUT) as client:
            return await client.post(
                url, headers={"Authorization": f"Bearer {settings.waba_token}"}, json=body)
    except _UNKNOWN_AFTER_WRITE as exc:
        raise SendOutcomeUnknown(f"{type(exc).__name__}: outcome unknown") from exc


async def _send_waba(wa_id: str, text: str, context_wamid: str | None = None) -> str | None:
    url = (f"https://graph.facebook.com/{settings.waba_api_version}"
           f"/{settings.waba_phone_number_id}/messages")
    body: dict = {
        "messaging_product": "whatsapp",
        "to": wa_id,
        "type": "text",
        "text": {"body": text},
    }
    # Native reply-quote: the customer sees this message quoting theirs.
    if context_wamid:
        body["context"] = {"message_id": context_wamid}
    resp = await _post_graph(url, body)
    if not resp.is_success:
        import logging
        logging.error(f"WABA error {resp.status_code}: {resp.text}")
        resp.raise_for_status()
    return _wamid_of(resp)


async def _send_waba_product_card(wa_id: str, *, image_url: str | None, title: str,
                                  body: str, url: str | None, button: str = "View") -> str | None:
    """Send a WhatsApp PRODUCT CARD — the visual equivalent of the web-chat card:
    the product photo as the header, name + price in the body, and a tappable
    "View" button that opens the product page on the storefront.

    Implemented as an interactive `cta_url` message. Falls back to an
    image+caption (then plain text) message if the interactive send is rejected
    — e.g. the header image isn't reachable by Meta, or the 24h window quirks —
    so the customer always gets the photo, price and link, never nothing.

    Returns the sent card's wamid (from whichever send succeeded) so the mirror
    row can carry it — that's what lets a customer's reply-quote of the card
    resolve back to it."""
    import logging
    _l = logging.getLogger("neema.wa")
    endpoint = (f"https://graph.facebook.com/{settings.waba_api_version}"
                f"/{settings.waba_phone_number_id}/messages")
    headers = {"Authorization": f"Bearer {settings.waba_token}"}
    image_url = _sign_for_meta(image_url)   # our media store → a link Meta may fetch

    # A cta_url card needs a link. Without one (an unpublished item, or the
    # local catalogue fallback) go straight to image+caption — the PHOTO is
    # what sells; a missing link is no reason to send the customer bare text.
    if url:
        interactive: dict = {
            "type": "cta_url",
            "body": {"text": f"*{title}*\n{body}"[:1024]},
            "action": {"name": "cta_url",
                       "parameters": {"display_text": (button or "View")[:20], "url": url}},
        }
        if image_url:
            interactive["header"] = {"type": "image", "image": {"link": image_url}}
        payload = {"messaging_product": "whatsapp", "recipient_type": "individual",
                   "to": wa_id, "type": "interactive", "interactive": interactive}
        async with httpx.AsyncClient() as client:
            resp = await client.post(endpoint, headers=headers, json=payload, timeout=30.0)
        if resp.is_success:
            return _wamid_of(resp)
        _l.warning("WA product card (cta_url) %s: %s — falling back to image+caption",
                   resp.status_code, resp.text[:200])

    caption = "\n".join(x for x in (f"*{title}*", body, url) if x)[:1024]
    if image_url:
        fb = {"messaging_product": "whatsapp", "to": wa_id, "type": "image",
              "image": {"link": image_url, "caption": caption}}
    else:
        fb = {"messaging_product": "whatsapp", "to": wa_id, "type": "text",
              "text": {"body": caption}}
    async with httpx.AsyncClient() as client:
        r2 = await client.post(endpoint, headers=headers, json=fb, timeout=30.0)
    if not r2.is_success:
        _l.error("WA product card fallback %s: %s", r2.status_code, r2.text[:200])
        r2.raise_for_status()
    return _wamid_of(r2)


async def send_wa_template(wa_id: str, template: str, lang: str,
                           body_params: list[str] | None = None) -> dict:
    """Send an APPROVED WhatsApp template (the only way to message a customer
    who hasn't opened a session with us). `body_params` fill the body's {{1}}…
    placeholders in order. Returns the Graph response; raises on failure so the
    caller can surface a clear error."""
    components = []
    if body_params:
        components.append({
            "type": "body",
            "parameters": [{"type": "text", "text": p} for p in body_params],
        })
    url = (f"https://graph.facebook.com/{settings.waba_api_version}"
           f"/{settings.waba_phone_number_id}/messages")
    resp = await _post_graph(url, {
        "messaging_product": "whatsapp",
        "to": wa_id,
        "type": "template",
        "template": {
            "name": template,
            "language": {"code": lang},
            **({"components": components} if components else {}),
        },
    })
    if not resp.is_success:
        import logging
        logging.error("WABA template error %s: %s", resp.status_code, resp.text)
        raise RuntimeError(f"WhatsApp template send failed ({resp.status_code}): {resp.text[:300]}")
    return resp.json() if resp.content else {}


# ── Delivery statuses (WhatsApp `statuses` webhooks) ─────────────────────────
# Rank so a late "sent" never overwrites "delivered"; "failed" always wins.
_STATUS_RANK = {"sent": 1, "delivered": 2, "read": 3, "failed": 9, "deleted": 9}


async def record_meta_receipt(db, channel: str, external_id: str, status: str,
                              watermark_ms: int | None) -> int:
    """Stamp a Messenger/Instagram delivery or read receipt onto the outbound
    rows it covers. Meta's receipts carry no per-message id we stored (the
    Send API's id is not kept) but a WATERMARK: every message to that contact
    sent up to that moment is delivered/read. Rows already at a higher status
    keep it. Returns the rows updated. Best-effort, never raises
    (investigation 1.10, 2026-11-06: receipts were discarded, so "delivered"
    was never known on Messenger/Instagram)."""
    from datetime import datetime, timezone
    from sqlalchemy.orm.attributes import flag_modified
    status = (status or "").lower()
    if status not in _STATUS_RANK or not external_id or not watermark_ms:
        return 0
    try:
        until = datetime.fromtimestamp(int(watermark_ms) / 1000, tz=timezone.utc)
        rows = (await db.execute(
            select(Message).where(Message.channel == channel,
                                  Message.external_id == external_id,
                                  Message.direction == MsgDirection.outbound,
                                  Message.created_at <= until)
            .order_by(Message.created_at.desc()).limit(20))).scalars().all()
        n = 0
        for row in rows:
            meta = dict(row.raw_meta or {})
            prev = (meta.get("delivery") or {}).get("status") or ""
            if _STATUS_RANK.get(status, 0) <= _STATUS_RANK.get(prev, 0):
                continue
            meta["delivery"] = {"status": status, "at": until.isoformat(timespec="seconds")}
            row.raw_meta = meta
            try:
                flag_modified(row, "raw_meta")
            except Exception:
                pass
            n += 1
        if n:
            await db.commit()
        return n
    except Exception as exc:
        logging.getLogger("neema.meta").info("meta receipt not recorded for %s/%s: %s", channel, external_id[-4:], exc)
        try:
            await db.rollback()
        except Exception:
            pass
        return 0


async def record_delivery_statuses(db, statuses: list[dict]) -> int:
    """Stamp provider delivery statuses onto the outbound rows they belong to
    (`messages.raw_meta.delivery`), matched on the wamid Graph returned at send
    time. Returns the number of rows updated. Best-effort, never raises."""
    from sqlalchemy.orm.attributes import flag_modified
    n = 0
    for st in statuses or []:
        wamid, status = st.get("wamid"), (st.get("status") or "").lower()
        if not wamid or not status:
            continue
        try:
            row = (await db.execute(
                select(Message).where(Message.waba_msg_id == wamid)
                .order_by(Message.created_at.desc()).limit(1))).scalar_one_or_none()
            if row is None:
                continue
            meta = dict(row.raw_meta or {})
            prev = (meta.get("delivery") or {}).get("status") or ""
            if _STATUS_RANK.get(status, 0) < _STATUS_RANK.get(prev, 0):
                continue
            entry = {"status": status, "at": st.get("at")}
            if st.get("error"):
                entry["error"] = str(st["error"])[:300]
            meta["delivery"] = entry
            row.raw_meta = meta
            try:
                flag_modified(row, "raw_meta")
            except Exception:
                pass
            n += 1
        except Exception as exc:
            import logging
            logging.getLogger("neema.wa_native").info("delivery status not recorded: %s", exc)
    if n:
        try:
            await db.commit()
        except Exception:
            await db.rollback()
            return 0
    return n


# ── Redis Broadcast ───────────────────────────────────────

def _public_meta(meta):
    from app.services.inbound_kinds import public_meta
    return public_meta(meta)


async def _broadcast(redis, channel: str, payload: dict) -> None:
    await redis.publish(f"ws:channel:{channel}", json.dumps(payload))


# ── Context ───────────────────────────────────────────────

import re as _re

# Trivial inbound messages that don't need the expensive reasoning model — a
# cheap templated reply (or a mini model) is enough. Kept deliberately small
# and high-precision so real sales questions never get short-circuited.
_GREETING_RE = _re.compile(
    r"^(hi+|hey+|hello+|helo+|habari|niaje|mambo|sasa|yo+|good\s*(morning|afternoon|evening)|"
    r"vipi|shalom)[\s!.,]*$",
    _re.IGNORECASE,
)
# Only PURE gratitude / closers are safe to short-circuit. Affirmatives like
# "yes", "no", "ok", "sure", "sawa", "poa", "fine", "alright" are load-bearing in
# a sales flow — a bare "yes" is how a customer CONFIRMS an order — so they must
# reach the AI. (Runaway loops are still capped by the cooldown below.)
_ACK_RE = _re.compile(
    r"^(thanks?|thank\s*you|asante(\s*sana)?|thx|ty|amen|👍+|🙏+|❤️*|😊+)[\s!.,🙏👍❤😊]*$",
    _re.IGNORECASE,
)


async def log_agent_usage(db: AsyncSession, wa_id: str, model: str, totals: dict,
                          node: str = "run_turn") -> dict:
    """Persist aggregated Tier 2 agent token usage for one customer turn, so
    spend + cache effectiveness are measurable. `totals` carries the summed
    input/output/cache-read/cache-write tokens across the turn's tool loop.
    `node` says WHERE the spend happened ("whatsapp", "facebook:comment", …) so
    the bill can be split by purpose, not just by model."""
    from app.models.ai_usage import AiUsage
    from app.core.ai_pricing import estimate_cost_usd

    inp = int(totals.get("input_tokens", 0) or 0)
    out = int(totals.get("output_tokens", 0) or 0)
    cread = int(totals.get("cache_read_tokens", 0) or 0)
    cwrite = int(totals.get("cache_write_tokens", 0) or 0)
    cwrite_1h = int(totals.get("cache_write_1h_tokens", 0) or 0)
    prompt_total = inp + cread + cwrite
    cost = estimate_cost_usd(model, prompt_total, out, cached_tokens=cread,
                             cache_write_tokens=cwrite, cache_write_1h_tokens=cwrite_1h)
    db.add(AiUsage(
        wa_id=_normalize_wa_id(wa_id) if wa_id else None,
        workflow="tier2-agent", node=(node or "run_turn")[:80], model=model,
        prompt_tokens=prompt_total, completion_tokens=out,
        cached_tokens=cread, cost_usd=cost,
    ))
    await db.commit()
    return {"ok": True, "cost_usd": cost}


async def ai_cost_summary(db: AsyncSession, days: int = 30) -> dict:
    """Aggregate token spend for the admin cost view."""
    from app.models.ai_usage import AiUsage
    from sqlalchemy import func

    since = datetime.now(timezone.utc) - timedelta(days=days)
    rows = (await db.execute(
        select(
            AiUsage.model,
            func.count().label("calls"),
            func.sum(AiUsage.prompt_tokens),
            func.sum(AiUsage.completion_tokens),
            func.sum(AiUsage.cached_tokens),
            func.sum(AiUsage.cost_usd),
        ).where(AiUsage.created_at >= since).group_by(AiUsage.model)
    )).all()

    by_model = [{
        "model": r[0], "calls": r[1],
        "prompt_tokens": int(r[2] or 0), "completion_tokens": int(r[3] or 0),
        "cached_tokens": int(r[4] or 0), "cost_usd": float(r[5] or 0),
    } for r in rows]

    total_cost = round(sum(m["cost_usd"] for m in by_model), 4)
    total_calls = sum(m["calls"] for m in by_model)
    return {
        "days": days,
        "total_cost_usd": total_cost,
        "total_calls": total_calls,
        "avg_cost_per_call": round(total_cost / total_calls, 6) if total_calls else 0,
        "by_model": sorted(by_model, key=lambda m: -m["cost_usd"]),
    }


async def catalog_items(db: AsyncSession, redis) -> list[dict]:
    """The product catalogue the AI quotes from.

    Source of truth is the Bethany House hub (shared with POS & website). Falls
    back to Neema's local table only if the hub is unreachable, so a live
    conversation never loses its price list mid-sale. Hub items carry
    `hub_product_id` — required to push a confirmed order back to the hub.
    """
    from app.models.catalog import Catalog

    if settings.catalog_source == "hub":
        try:
            from app.core.hub_client import fetch_hub_catalog
            return await fetch_hub_catalog(redis)
        except Exception as exc:
            import logging
            logging.getLogger("neema.hub").warning(
                "hub catalogue unavailable (%s) — serving local table this turn", exc
            )

    res = await db.execute(
        select(Catalog).where(Catalog.in_stock == True).order_by(Catalog.category, Catalog.name)
    )
    return [{
        "sku": str(i.sku), "name": str(i.name), "category": str(i.category or ""),
        "price": float(i.price), "unit": str(i.unit or ""),
        "description": str(i.description or ""), "aliases": i.aliases or [], "in_stock": i.in_stock,
    } for i in res.scalars().all()]


# ── Upsert Message ────────────────────────────────────────
# Stores media_type / media_url when present.
# An inbound attachment Neema cannot read (video, document, sticker) is FLAGGED
# for an agent to view — but the conversation stays in AI mode, so she keeps
# serving the customer instead of going silent while nobody is watching.
# Returns a Firestore-style document array (the shape the callers and the
# dashboard previews were built on).

async def upsert_message(db: AsyncSession, redis, body, *, message_id=None,
                         transcript_status: str | None = None) -> list:
    """`message_id` / `transcript_status` are set only by in-process callers
    (wa_native, for a voice note it will transcribe in the background) — never
    from a request body."""
    # Normalise wa_id so inbound and outbound messages always resolve to the
    # same Conversation row regardless of whether the '+' prefix is present.
    body.wa_id = _normalize_wa_id(body.wa_id)

    result = await db.execute(
        select(Conversation).where(Conversation.wa_id == body.wa_id)
    )
    conv = result.scalar_one_or_none()
    if not conv:
        conv = Conversation(wa_id=body.wa_id)
        db.add(conv)
        await db.flush()

    # Guarantee a backing profile for every conversation, capturing the
    # WhatsApp profile name (body.name) and resolving the country server-side.
    # Only inbound messages carry a trustworthy profile name.
    user = await provision_user(
        db,
        body.wa_id,
        name=body.name if body.direction == "inbound" else None,
        last_text=(body.text or None),
        last_direction=body.direction,
    )
    # Identity spine (additive): stamp the conversation with its person/channel.
    if conv.person_id is None:
        conv.person_id = user.person_id
    if conv.channel is None:
        conv.channel = "whatsapp"

    sender    = MsgSender.user       if body.direction == "inbound" else MsgSender.ai
    direction = MsgDirection.inbound if body.direction == "inbound" else MsgDirection.outbound

    media_type  = getattr(body, "media_type", None)
    media_url   = getattr(body, "media_url",  None)
    media_id    = getattr(body, "media_id",   None)
    mime_type   = getattr(body, "mime_type",  None)
    filename    = getattr(body, "filename",   None)
    # image_analysis is populated by the Product Image Recognition sub-workflow
    # (GPT-4o description of the image). It is stored in media_caption so the
    # UI ImageBubble can render it as a collapsible "Image analysis" toggle,
    # mirroring how audio transcriptions are stored and displayed.
    # If image_analysis is absent, fall back to any explicit media_caption sent.
    image_analysis = getattr(body, "image_analysis", None)
    media_caption  = image_analysis or getattr(body, "media_caption", None)

    ts_ms: int | None = getattr(body, "ts_ms", None)
    ts_iso_raw: str | None = getattr(body, "ts_iso", None)
    if not ts_ms and ts_iso_raw:
        try:
            ts_ms = int(
                datetime.fromisoformat(ts_iso_raw.replace("Z", "+00:00"))
                .timestamp() * 1000
            )
        except (ValueError, AttributeError):
            pass
    if not ts_ms:
        ts_ms = int(datetime.now(timezone.utc).timestamp() * 1000)

    msg = Message(
        **({"id": message_id} if message_id is not None else {}),
        transcript_status=transcript_status,
        conversation_id=conv.id,
        wa_id=body.wa_id,
        person_id=conv.person_id,
        channel="whatsapp",
        direction=direction,
        sender=sender,
        text=body.text or (media_caption or f"[{media_type} received]" if media_type else ""),
        media_type=media_type,
        media_url=media_url,
        media_id=media_id,
        media_caption=media_caption,
        mime_type=mime_type,
        filename=filename,
        ts_ms=ts_ms,
        raw_meta=getattr(body, "raw_meta", None),
    )
    # Recover the customer's WhatsApp message id (wamid), captured by the API front
    # door keyed on (wa_id, text-hash), so a human reply can quote it natively
    # (the DTO itself doesn't carry the wamid). Best-effort.
    if direction == MsgDirection.inbound and (body.text or "").strip() and redis is not None:
        try:
            import hashlib as _hl
            _h = _hl.sha1((body.text or "").strip().encode("utf-8")).hexdigest()[:16]
            _wamid = await redis.get(f"wa:wamid:{body.wa_id}:{_h}")
            if _wamid:
                msg.waba_msg_id = _wamid
        except Exception:
            pass
    db.add(msg)

    # ── Selective auto-escalation for inbound media ───────────────────────────
    # Voice notes are transcribed in-process (services/voice_notes) and answered
    # by the AI; images are read natively by Claude vision inside run_turn (the
    # photo check, services/photo_check, decides when a person must price one).
    # Neither escalates here. Only video and document messages still need a
    # human to review, so those auto-escalate.
    escalated = False
    is_ai_handled_media = (
        media_type == "audio"
        or bool(mime_type and mime_type.startswith("audio/"))
        or media_type == "image"
        or bool(mime_type and mime_type.startswith("image/"))
    )
    intercept_log = None
    if direction == MsgDirection.inbound and media_type and not is_ai_handled_media:
        # A video / document / sticker Neema cannot read. This used to switch the
        # conversation to human mode — which, with no auto-release at the time,
        # silenced the AI on that customer permanently: a customer who sent a
        # video of the item they wanted never heard from us again. Flag it for the
        # team instead and LEAVE THE THREAD IN AI MODE, so Neema stays in the
        # conversation and can ask them to describe or photograph the item.
        if conv.intercept_mode != InterceptMode.human:
            from app.models.intercept import Intercept, InterceptAction
            reason = (f"Customer sent a {media_type} Neema cannot open — please review. "
                      "She is still answering in the thread and will ask them to "
                      "describe or photograph it.")
            intercept_log = Intercept(
                conversation_id=conv.id,
                agent_id=None,
                action=InterceptAction.flag,
                note=reason,
                created_at=datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc) + timedelta(seconds=1),
            )
            db.add(intercept_log)

    await db.commit()
    await db.refresh(msg)

    # ── Broadcast WebSocket events ────────────────────────────────────────────
    await _broadcast(redis, str(conv.id), {
        "type":           "new_message",
        "conversationId": str(conv.id),
        "waId":           body.wa_id,
        # id + direction + time: without them the dashboard appended the live
        # bubble under a random id, on the OUTBOUND side, until the next reload.
        "id":             str(msg.id),
        "direction":      direction.value,
        "transcriptStatus": msg.transcript_status,
        "created_at":     msg.created_at.isoformat() if msg.created_at else None,
        "sender":         sender.value,
        "text":           msg.text,
        "mediaType":      media_type,
        "mediaId":        media_id,
        "mediaUrl":       media_url,
        "mediaCaption":   media_caption,
        "mimeType":       mime_type,
        "filename":       filename,
        "meta":           _public_meta(msg.raw_meta),
    })

    if intercept_log is not None:
        # The team is still notified about an attachment Neema can't open — they
        # just aren't the customer's only hope of a reply, because the thread
        # stays in AI mode (see the flag above).
        reason = (
            f"Customer sent a {media_type}"
            + " — agent review required"
        )
        # Broadcast to all agents — anyone can pick it up
        await _broadcast(redis, "agents:all", {
            "event":          "notification",
            "type":           "human_transfer",
            "title":          f"Media received — {media_type}",
            "body":           f"{body.wa_id} sent a {media_type} — agent review required",
            "waId":           body.wa_id,
            "conversationId": str(conv.id),
            "mediaType":      media_type,
        })
        # The conversation stays with the AI, so this is a FLAG for the timeline,
        # not an intercept — broadcasting mode "human" here would make the
        # frontend pill lie about who is handling the thread.
        await _broadcast(redis, str(conv.id), {
            "type":           "intercept_changed",
            "conversationId": str(conv.id),
            "mode":           "ai",
            "eventKind":      "flag",
            "eventReason":    reason,
        })

    # ── Build response ────────────────────────────────────────────────────────
    doc_id        = f"{msg.wa_id}_{ts_ms}"
    created_at    = msg.created_at or datetime.now(timezone.utc)
    ttl_expire_at = created_at + timedelta(days=120)
    ts_dt    = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
    ts_iso   = _fmt_ts_ms(ts_dt)
    ttl_iso  = _fmt_ts_ms(ttl_expire_at)
    now_str  = _fmt_precise(created_at)

    fields = {
        "tsMs":        {"integerValue": str(ts_ms)},
        "direction":   {"stringValue": str(direction.value)},
        "ttlExpireAt": {"timestampValue": ttl_iso},
        "text":        {"stringValue": msg.text or ""},
        "tsIso":       {"stringValue": ts_iso},
        "wa_id":       {"stringValue": body.wa_id},
    }

    if media_type:
        fields["mediaType"]    = {"stringValue": media_type}
    if media_id:
        fields["mediaId"]      = {"stringValue": media_id}
    if media_url:
        fields["mediaUrl"]     = {"stringValue": media_url}
    if media_caption:
        fields["mediaCaption"] = {"stringValue": media_caption}
    if mime_type:
        fields["mimeType"]     = {"stringValue": mime_type}
    if filename:
        fields["filename"]     = {"stringValue": filename}
    if escalated:
        fields["escalated"]    = {"booleanValue": True}

    # Expose the identity/message fields at the TOP LEVEL too — not just inside
    # the Firestore-style `fields` envelope — so callers can read `wa_id`,
    # `docid` and the timestamps without unwrapping the envelope. Additive: the
    # nested `fields` and doc `name` are unchanged, so existing readers still work.
    result = {
        "name": f"projects/neema-6037c/databases/(default)/documents/messages/{doc_id}",
        "fields": fields,
        "createTime": now_str,
        "updateTime": now_str,
        # top-level identity/message fields
        "wa_id": body.wa_id,
        "docid": doc_id,
        "tsMs": ts_ms,
        "tsIso": ts_iso,
        "text": msg.text or "",
        "direction": direction.value,
        "msgText": msg.text or "",
    }
    if media_type:
        result["media_type"] = media_type
    if media_url:
        result["media_url"] = media_url
    if media_caption:
        result["media_caption"] = media_caption
    return [result]


# ── Upsert Order Event ────────────────────────────────────

async def upsert_order_event(db: AsyncSession, body, redis=None) -> dict:

    event_id = f"{body.wa_id}_{int(datetime.now(timezone.utc).timestamp() * 1000)}"

    # Identity spine (additive): bind the order to a person.
    from app.services.identity import resolve_person_id_for_wa_id
    person_id = await resolve_person_id_for_wa_id(db, body.wa_id, source="whatsapp_order")

    stmt = pg_insert(OrderEvent).values(
        id=event_id,
        wa_id=body.wa_id,
        person_id=person_id,
        session_id=body.session_id,
        event_type=body.event_type,
        items=body.items,
        subtotal=body.subtotal,
        currency=body.currency,
        status=body.status,
        payment_status=body.payment_status,
        fulfillment_status=body.fulfillment_status,
        reply_text=body.reply_text,
        channel=body.channel,
        state=body.state,
    ).on_conflict_do_update(
        index_elements=["id"],
        set_={
            "status": body.status,
            "payment_status": body.payment_status,
            "fulfillment_status": body.fulfillment_status,
            "reply_text": body.reply_text,
            "state": body.state,
            "items": body.items,
            "subtotal": body.subtotal,
        },
    )
    await db.execute(stmt)
    await db.commit()

    result = {"ok": True, "event_id": event_id}
    # Part B / Loop C — best-effort; never breaks the order-event save.
    try:
        push = await _maybe_push_order_to_hub(db, redis, body, event_id)
        if push:
            result.update(push)
    except Exception as exc:
        import logging
        logging.getLogger("neema.hub").warning(
            "hub order push errored for %s (%s) — order-event saved regardless",
            body.wa_id, exc,
        )
    return result


async def _maybe_push_order_to_hub(db: AsyncSession, redis, body, event_id: str) -> dict | None:
    """Push a CONFIRMED WhatsApp cart into the Bethany House hub (Part B), then
    relay the payment link to the customer (Loop C).

    A confirmed order-event is the only kind that carries item lines (snapshots
    are empty), so `items` being non-empty is the trigger. Idempotent per
    session: if this session already produced a hub order, we copy its ids and
    skip. Failures are recorded on the row for retry on the next confirmed event.
    """
    from app.core import hub_client
    from app.core.countries import resolve_country

    items = list(body.items or [])
    if not settings.hub_push_orders or not settings.hub_api_token or not settings.hub_outlet_id:
        return None
    if not items:                       # snapshot / non-order event — nothing to push
        return None

    import logging
    log = logging.getLogger("neema.hub")

    async def _save(**cols):
        await db.execute(
            update(OrderEvent).where(OrderEvent.id == event_id).values(**cols)
        )
        await db.commit()

    # ── Idempotency: one hub order per WhatsApp session ───────────────────────
    dedupe_col = OrderEvent.session_id if body.session_id else OrderEvent.wa_id
    dedupe_val = body.session_id or body.wa_id
    prior = (await db.execute(
        select(OrderEvent)
        .where(dedupe_col == dedupe_val, OrderEvent.hub_order_id.isnot(None))
        .order_by(OrderEvent.created_at.desc())
        .limit(1)
    )).scalar_one_or_none()
    if prior is not None:
        await _save(
            hub_order_id=prior.hub_order_id,
            hub_order_number=prior.hub_order_number,
            hub_payment_url=prior.hub_payment_url,
            hub_push_status="skipped_dup",
        )
        return {"hub_order_id": prior.hub_order_id, "hub_push_status": "skipped_dup"}

    # ── Customer identity ─────────────────────────────────────────────────────
    from app.models.user import User
    user = (await db.execute(select(User).where(User.wa_id == body.wa_id))).scalar_one_or_none()
    first_name = ((user.name if user else None) or "WhatsApp Customer").split()[0]
    country_iso = (resolve_country(body.wa_id) or {}).get("country_iso")

    # ── Resolve lines against the live hub catalogue + create the order ───────
    try:
        catalog = await catalog_items(db, redis)
    except Exception as exc:
        await _save(hub_push_status="failed", hub_last_error=f"catalog: {exc}")
        return {"hub_push_status": "failed"}

    # The figures we collected must reach the workshop WITH the order — the
    # whole point of measuring in chat (best-effort; staff still confirm).
    measurement_note = ""
    try:
        from app.agent import measurements as mm
        sizes = mm.describe(await mm.get_measurements(db, body.wa_id, "whatsapp"))
        if sizes:
            measurement_note = (f"Measurements on file: {sizes}. "
                                "Confirm with the customer before production.")
    except Exception:
        pass

    try:
        pushed = await hub_client.push_pending_order(
            catalog, wa_id=body.wa_id, first_name=first_name,
            country_iso=country_iso, items=items,
            measurement_note=measurement_note,
        )
    except ValueError as exc:            # nothing matched a hub product
        unmatched = getattr(exc, "unmatched", [])
        await _save(hub_push_status="skipped_nomatch",
                    hub_last_error=f"no hub match for: {unmatched}")
        log.warning("hub push: no product match for %s (%s)", body.wa_id, unmatched)
        return {"hub_push_status": "skipped_nomatch", "unmatched": unmatched}
    except Exception as exc:
        await _save(hub_push_status="failed", hub_last_error=str(exc)[:500])
        log.warning("hub push failed for %s: %s", body.wa_id, exc)
        return {"hub_push_status": "failed"}

    hub_order_id = pushed.get("order_id")
    await _save(
        hub_order_id=hub_order_id,
        hub_order_number=pushed.get("order_number"),
        hub_currency=pushed.get("currency_code"),
        hub_total=pushed.get("total_amount"),
        hub_push_status="pushed",
        hub_pushed_at=datetime.now(timezone.utc),
        hub_last_error=None,
    )
    log.info("hub order created: #%s (%s) for %s",
             hub_order_id, pushed.get("order_number"), body.wa_id)

    out = {
        "hub_order_id": hub_order_id,
        "hub_order_number": pushed.get("order_number"),
        "hub_push_status": "pushed",
        "unmatched": pushed.get("unmatched") or [],
    }

    # ── Loop C: relay the payment link to the customer ────────────────────────
    if settings.hub_relay_receipt and hub_order_id:
        try:
            pay_url = await hub_client.fetch_payment_link(hub_order_id)
            if pay_url:
                await _save(hub_payment_url=pay_url)
                await _relay_order_confirmation(
                    db, redis, body.wa_id,
                    order_number=pushed.get("order_number"),
                    currency=pushed.get("currency_code"),
                    total=pushed.get("total_amount"),
                    pay_url=pay_url,
                )
                out["hub_payment_url"] = pay_url
        except Exception as exc:
            log.warning("Loop C receipt relay failed for %s: %s", body.wa_id, exc)

    return out


async def save_outbound_message(db, redis, wa_id: str, text: str,
                                waba_msg_id: str | None = None,
                                raw_meta: dict | None = None) -> None:
    """Persist an AI outbound message + broadcast it (used by the Tier 2 agent,
    which sends its own reply rather than going through the Tier 1 outbound gate).
    Pass the wamid `_send_waba` returned so a customer's reply-quote of this
    message can resolve back to the row. `raw_meta` says what the row IS when
    it is not an ordinary reply (the hold line)."""
    wa_id = _normalize_wa_id(wa_id)
    conv = (await db.execute(
        select(Conversation).where(Conversation.wa_id == wa_id)
    )).scalar_one_or_none()
    if conv is None:
        conv = Conversation(wa_id=wa_id)
        db.add(conv)
        await db.flush()
    if conv.person_id is None:
        from app.services.identity import resolve_person_id_for_wa_id
        conv.person_id = await resolve_person_id_for_wa_id(db, wa_id, source="whatsapp_agent")
    if conv.channel is None:
        conv.channel = "whatsapp"
    db.add(Message(
        wa_id=wa_id, conversation_id=conv.id, person_id=conv.person_id, channel="whatsapp",
        direction=MsgDirection.outbound, sender=MsgSender.ai, text=text,
        waba_msg_id=waba_msg_id, raw_meta=raw_meta,
    ))
    await db.commit()
    try:
        await _broadcast(redis, str(conv.id), {
            "type": "message", "conversationId": str(conv.id),
            "waId": wa_id, "direction": "outbound", "text": text,
        })
    except Exception:
        pass


async def save_outbound_channel_message(db, redis, channel: str, external_id: str, text: str,
                                        reply_to_comment_id: str | None = None,
                                        raw_meta: dict | None = None) -> None:
    """Persist an AI outbound reply for a non-WhatsApp channel (Messenger/IG/FB) and
    broadcast it, so it shows in the unified inbox. Keyed on (channel, external_id).
    Pass reply_to_comment_id for a PUBLIC comment reply so the inbox can thread it
    under the comment it answers (stored on comment_context.reply_to)."""
    from app.services.channel import get_or_create_conversation
    conv = await get_or_create_conversation(db, channel, external_id)
    db.add(Message(
        channel=channel, external_id=external_id, wa_id=None,
        person_id=conv.person_id, conversation_id=conv.id,
        direction=MsgDirection.outbound, sender=MsgSender.ai, text=text,
        comment_context=({"reply_to": reply_to_comment_id} if reply_to_comment_id else None),
        raw_meta=raw_meta,
    ))
    conv.last_message_at = datetime.now(timezone.utc)
    conv.last_message_preview = (text or "")[:100]
    await db.commit()
    try:
        await _broadcast(redis, str(conv.id), {
            "type": "message", "conversationId": str(conv.id),
            "channel": channel, "sender": "ai", "direction": "outbound", "text": text,
            "reply_to": reply_to_comment_id,
        })
    except Exception:
        pass


async def _relay_order_confirmation(db, redis, wa_id, *, order_number, currency, total, pay_url) -> None:
    """WhatsApp the customer their order confirmation + secure payment link, and
    save it to history so it appears in the conversation (Loop C)."""
    _n = money.num(total)
    amount = f"{currency or 'KES'} {_n}" if _n else ""
    num = f" {order_number}" if order_number else ""
    text = (
        f"✅ Your order{num} is confirmed{(' — total ' + amount) if amount else ''}.\n\n"
        f"Pay securely here:\n{pay_url}\n\n"
        "Once payment is received we'll prepare and ship your order. "
        "You can ask me \"where's my order?\" anytime for an update."
    )

    wamid = await _send_waba(wa_id, text)

    # Persist as an outbound message (one row, like every other send).
    conv = (await db.execute(
        select(Conversation).where(Conversation.wa_id == wa_id)
    )).scalar_one_or_none()
    if conv is None:
        conv = Conversation(wa_id=wa_id)
        db.add(conv)
        await db.flush()
    if conv.person_id is None:
        from app.services.identity import resolve_person_id_for_wa_id
        conv.person_id = await resolve_person_id_for_wa_id(db, wa_id, source="whatsapp_receipt")
    if conv.channel is None:
        conv.channel = "whatsapp"
    from app.services import outreach_log as _ol
    db.add(Message(
        wa_id=wa_id,
        raw_meta=_ol.stamp("order_confirmation", _ol.TRANSACTIONAL, kind="order_confirmation"),
        conversation_id=conv.id,
        person_id=conv.person_id,
        channel="whatsapp",
        direction=MsgDirection.outbound,
        sender=MsgSender.ai,
        text=text,
        waba_msg_id=wamid,
    ))
    await db.commit()
    try:
        await _broadcast(redis, str(conv.id), {
            "type": "message", "conversationId": str(conv.id),
            "waId": wa_id, "direction": "outbound", "text": text,
        })
    except Exception:
        pass


# ── Upsert Customer History ───────────────────────────────

async def upsert_customer_history(db: AsyncSession, body) -> dict:

    # Identity spine (additive): bind the history snapshot to a person.
    from app.services.identity import resolve_person_id_for_wa_id
    person_id = await resolve_person_id_for_wa_id(db, body.wa_id, source="whatsapp_history")

    stmt = pg_insert(CustomerHistory).values(
        wa_id=body.wa_id,
        person_id=person_id,
        last_status=body.last_status,
        has_open_order=body.has_open_order,
        last_event=body.last_event or {},
        last_chat={},
        last_order={},
        counts=body.counts or {},
    ).on_conflict_do_update(
        index_elements=["wa_id"],
        set_={
            "last_status": body.last_status,
            "has_open_order": body.has_open_order,
            "last_event": body.last_event or {},
            "counts": body.counts or {},
        },
    )
    await db.execute(stmt)
    await db.commit()
    return {"ok": True}