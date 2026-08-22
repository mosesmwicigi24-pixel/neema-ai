"""Meta data-deletion requests — verify, purge, receipt.

When a Facebook/Instagram user asks Meta to delete their data, Meta is obliged
to pass the request to every app that received it (Platform Terms 3(d)(i)).
Apps that register a *data deletion callback* get a signed POST and handle it in
seconds; apps that don't get an email to a human. This module is the former.

Two entry points, one purge:
  - parse_signed_request(): verify Meta's `signed_request` (HMAC-SHA256 over the
    base64url payload with the app secret) and return the payload, whose
    `user_id` is the app-scoped id we store as Identity.external_id.
  - purge_meta_user(): remove that person's Meta-channel trace — messages,
    conversations, the identity itself — and the person row too when nothing
    else is left of them.

What deliberately SURVIVES a purge, and why:
  - A person who ALSO reached us on WhatsApp keeps their person row and that
    WhatsApp history. The request covers data Meta gave us about their Meta
    identity, not a phone number the customer typed to us directly on another
    platform.
  - Orders, deals and production enquiries survive with person_id nulled
    (the FKs are ON DELETE SET NULL). Those are business and tax records of a
    real transaction; what they lose is the link back to a named human.
"""
import base64
import hashlib
import hmac
import json
import logging
import secrets
from datetime import datetime, timezone

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.conversation import Conversation
from app.models.message import Message
from app.models.person import Identifier, Identity, Person
from app.models.user import User

_log = logging.getLogger("neema.meta.deletion")

# Meta app-scoped ids live on these channels. "facebook" is the public-comment
# surface — a commenter's id is the same person-scoped id, so it purges too.
META_CHANNELS = ("messenger", "instagram", "facebook")

# Receipts live in the app_settings KV so the status URL Meta requires can answer
# later without a migration. Keyed by confirmation code; the subject's id is
# stored ONLY as a hash — retaining the raw id in a deletion receipt would
# defeat the deletion.
RECEIPT_PREFIX = "meta_deletion_"


class InvalidSignedRequest(ValueError):
    """Signature missing, malformed, or not ours."""


def _b64url(segment: str) -> bytes:
    return base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4))


def subject_hash(external_id: str) -> str:
    """Stable, non-reversible reference to a purged id, for the receipt."""
    return hashlib.sha256((external_id or "").encode()).hexdigest()[:16]


def parse_signed_request(signed_request: str, app_secret: str | None = None) -> dict:
    """Verify Meta's signed_request and return the decoded payload.

    Raises InvalidSignedRequest on anything untrusted — an unsigned request must
    never be allowed to delete a customer."""
    secret = app_secret if app_secret is not None else (settings.meta_app_secret or "")
    if not secret:
        raise InvalidSignedRequest("META_APP_SECRET is not configured")
    if not signed_request or "." not in signed_request:
        raise InvalidSignedRequest("malformed signed_request")
    sig_b64, _, payload_b64 = signed_request.partition(".")
    try:
        signature = _b64url(sig_b64)
        payload = json.loads(_b64url(payload_b64))
    except Exception as exc:
        raise InvalidSignedRequest(f"undecodable signed_request: {exc}") from exc
    if not isinstance(payload, dict):
        raise InvalidSignedRequest("payload is not an object")
    if str(payload.get("algorithm", "")).upper() != "HMAC-SHA256":
        raise InvalidSignedRequest("unexpected signing algorithm")
    expected = hmac.new(secret.encode(), payload_b64.encode(), hashlib.sha256).digest()
    if not hmac.compare_digest(expected, signature):
        raise InvalidSignedRequest("signature mismatch")
    return payload


async def _orphaned_persons(db: AsyncSession, person_ids: set, external_id: str,
                            conv_ids: list) -> list:
    """Of these persons, which would be left with nothing after the purge?

    A person survives if ANY of these remains: another messaging identity, a
    volunteered identifier (phone/email), a WhatsApp user profile, or a
    conversation on another channel."""
    orphans = []
    for pid in person_ids:
        if pid is None:
            continue
        identities = (await db.execute(select(func.count()).select_from(Identity).where(
            Identity.person_id == pid,
            ~(Identity.channel.in_(META_CHANNELS) & (Identity.external_id == external_id)),
        ))).scalar() or 0
        if identities:
            continue
        if (await db.execute(select(func.count()).select_from(Identifier).where(
                Identifier.person_id == pid))).scalar():
            continue
        if (await db.execute(select(func.count()).select_from(User).where(
                User.person_id == pid))).scalar():
            continue
        others = select(func.count()).select_from(Conversation).where(Conversation.person_id == pid)
        if conv_ids:
            others = others.where(Conversation.id.notin_(conv_ids))
        if (await db.execute(others)).scalar():
            continue
        orphans.append(pid)
    return orphans


async def purge_meta_user(db: AsyncSession, external_id: str, *,
                          dry_run: bool = True) -> dict:
    """Erase one Meta app-scoped id. Returns the row counts (what WOULD go, when
    dry_run). The caller owns the commit."""
    ext = (external_id or "").strip()
    if not ext:
        raise ValueError("external_id is required")

    conv_ids = list((await db.execute(select(Conversation.id).where(
        Conversation.channel.in_(META_CHANNELS),
        Conversation.external_id == ext))).scalars())
    person_ids = set((await db.execute(select(Identity.person_id).where(
        Identity.channel.in_(META_CHANNELS),
        Identity.external_id == ext))).scalars())
    person_ids |= {p for p in (await db.execute(select(Conversation.person_id).where(
        Conversation.channel.in_(META_CHANNELS),
        Conversation.external_id == ext))).scalars() if p is not None}

    messages = (await db.execute(select(func.count()).select_from(Message).where(
        Message.channel.in_(META_CHANNELS), Message.external_id == ext))).scalar() or 0
    identities = (await db.execute(select(func.count()).select_from(Identity).where(
        Identity.channel.in_(META_CHANNELS), Identity.external_id == ext))).scalar() or 0
    orphans = await _orphaned_persons(db, person_ids, ext, conv_ids)

    counts = {"external_id": ext, "messages": messages, "conversations": len(conv_ids),
              "identities": identities, "persons": len(orphans),
              "persons_kept": len(person_ids) - len(orphans), "dry_run": dry_run}
    if dry_run or not (messages or conv_ids or identities):
        return counts

    # Order matters: messages first (they carry the words), then conversations
    # (cascades intercepts + any stragglers), then the identity, then the person
    # — identities hold an ON DELETE RESTRICT reference to persons.
    await db.execute(delete(Message).where(
        Message.channel.in_(META_CHANNELS), Message.external_id == ext))
    if conv_ids:
        await db.execute(delete(Conversation).where(Conversation.id.in_(conv_ids)))
    await db.execute(delete(Identity).where(
        Identity.channel.in_(META_CHANNELS), Identity.external_id == ext))
    if orphans:
        await db.execute(delete(Person).where(Person.id.in_(orphans)))
    _log.info("meta deletion purged %s: %s", subject_hash(ext), counts)
    return counts


async def write_receipt(db: AsyncSession, code: str, external_id: str,
                        counts: dict) -> None:
    """Record that this request was carried out, so the status URL can answer.
    Stores the subject as a hash, never the raw id."""
    from app.models.app_setting import AppSetting
    key = f"{RECEIPT_PREFIX}{code}"
    row = await db.get(AppSetting, key)
    if row is None:
        row = AppSetting(id=key)
        db.add(row)
    row.value = json.dumps({
        "subject": subject_hash(external_id),
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "removed": {k: v for k, v in counts.items() if k != "external_id"},
    })


async def read_receipt(db: AsyncSession, code: str) -> dict | None:
    from app.models.app_setting import AppSetting
    row = await db.get(AppSetting, f"{RECEIPT_PREFIX}{(code or '').strip()}")
    if row is None or not (row.value or "").strip():
        return None
    try:
        return json.loads(row.value)
    except Exception:
        return None


def new_confirmation_code() -> str:
    return secrets.token_hex(12)


def status_url(code: str) -> str:
    """Where Meta (and the customer) can check the request. Uses the Neema host,
    falling back to the storefront if media_public_url isn't configured."""
    base = (settings.media_public_url or settings.storefront_url or "").rstrip("/")
    return f"{base}/api/meta/data-deletion/status?code={code}"
