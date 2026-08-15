"""Native TikTok Business Messaging — Neema speaks to TikTok herself.

The ManyChat relay (routers/manychat.py) proved the channel sells; this module
removes the middleman. TikTok's Business Messaging API gives an approved
developer app the same transport ManyChat uses: the owner's Business Account
authorizes our app once (OAuth), TikTok webhooks every DM to us in real time,
and we push replies through /business/message/send/ — asynchronous, so the
ManyChat 10-second squeeze disappears, and dashboard humans can finally reply
to TikTok threads.

Lifecycle (all inert until TIKTOK_APP_ID/SECRET are set):
  - authorize_url()/exchange_code(): one-time owner OAuth. Tokens live in the
    app_settings KV row "tiktok_oauth" — access ~24h (auto-refreshed here),
    refresh ~30d (expiry means the owner must re-connect; we surface that
    loudly rather than letting the channel rot silently).
  - send_to_user(): resolve the customer's TikTok conversation id (stamped on
    their Identity.raw_profile by the webhook) and send. Text only for now —
    TikTok DMs allow text or a single image, and text is the sale.
  - TikTok's platform rules still bind (they are TikTok's, not ManyChat's):
    48h reply window, ~10 automated messages per window, Business accounts
    only, and no EEA/UK contacts.

Endpoint shapes mirror Chatwoot's battle-tested integration (chatwoot/chatwoot
app/services/tiktok/*, MIT) against business-api.tiktok.com v1.3.
"""
import json
import logging
import secrets
from datetime import datetime, timezone, timedelta
from urllib.parse import urlencode

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings

_log = logging.getLogger("neema.tiktok")

API_BASE = "https://business-api.tiktok.com/open_api/v1.3"
AUTHORIZE_URL = "https://www.tiktok.com/v2/auth/authorize"
# Messaging + enough profile to greet by name. Mirrors the scope set TikTok
# grants Business Messaging integrations.
SCOPES = ("user.info.basic,user.info.username,user.info.profile,"
          "user.account.type,message.list.read,message.list.send,"
          "message.list.manage")
_TOKENS_KEY = "tiktok_oauth"          # app_settings row holding the token blob


class TikTokNotConnected(RuntimeError):
    """App configured but no (usable) owner authorization on file."""


def configured() -> bool:
    return bool(settings.tiktok_app_id and settings.tiktok_app_secret)


# ── token store (app_settings KV — owner-scoped, survives deploys) ───────────

async def _load_tokens(db: AsyncSession) -> dict | None:
    from app.models.app_setting import AppSetting
    row = await db.get(AppSetting, _TOKENS_KEY)
    if row is None or not (row.value or "").strip():
        return None
    try:
        return json.loads(row.value)
    except Exception:
        _log.error("tiktok token blob is corrupt — reconnect required")
        return None


async def _store_tokens(db: AsyncSession, data: dict) -> None:
    from app.models.app_setting import AppSetting
    row = await db.get(AppSetting, _TOKENS_KEY)
    if row is None:
        row = AppSetting(id=_TOKENS_KEY)
        db.add(row)
    row.value = json.dumps(data)
    await db.commit()


async def native_live(db: AsyncSession) -> bool:
    """True when the app is configured AND an owner authorization is on file
    (it may still need a refresh — that happens lazily on first use)."""
    return configured() and (await _load_tokens(db)) is not None


# ── OAuth (one-time owner connect + silent refresh) ──────────────────────────

def authorize_url(state: str) -> str:
    """Where to send the owner to connect their TikTok account.

    Preferred: the authorization URL TikTok mints for the app once its account-
    holder redirect URL is activated (settings.tiktok_authorize_url) — it already
    carries app_id and the granted scopes, so all we add is our CSRF state. This
    is the one-click "Connect" experience; ManyChat's button is the same thing
    against their own approved app. Fallback (unset): build the standard
    v2/auth/authorize URL ourselves."""
    portal = (settings.tiktok_authorize_url or "").strip()
    if portal:
        sep = "&" if "?" in portal else "?"
        return f"{portal}{sep}{urlencode({'state': state})}"
    return AUTHORIZE_URL + "?" + urlencode({
        "client_key": settings.tiktok_app_id,
        "response_type": "code",
        "scope": SCOPES,
        "redirect_uri": settings.tiktok_redirect_uri,
        "state": state,
    })


def mint_state() -> str:
    return secrets.token_urlsafe(24)


def _token_fields(data: dict, prev: dict | None = None) -> dict:
    now = datetime.now(timezone.utc)
    return {
        "business_id": data.get("open_id") or (prev or {}).get("business_id"),
        "scope": data.get("scope") or (prev or {}).get("scope"),
        "access_token": data["access_token"],
        "refresh_token": data["refresh_token"],
        "expires_at": (now + timedelta(seconds=int(data.get("expires_in", 0)))).isoformat(),
        "refresh_expires_at": (
            now + timedelta(seconds=int(data.get("refresh_token_expires_in", 0)))
        ).isoformat() if data.get("refresh_token_expires_in") else (prev or {}).get("refresh_expires_at"),
    }


async def _oauth_post(path: str, body: dict) -> dict:
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(f"{API_BASE}{path}", json=body,
                                 headers={"Accept": "application/json",
                                          "Content-Type": "application/json"})
    data = resp.json() if resp.content else {}
    if resp.status_code != 200 or data.get("code") not in (0, None):
        raise RuntimeError(f"TikTok OAuth call {path} failed: "
                           f"{resp.status_code} {json.dumps(data)[:300]}")
    return data.get("data") or {}


async def exchange_code(db: AsyncSession, auth_code: str) -> dict:
    """One-time: turn the owner's OAuth code into stored tokens. Returns the
    stored blob (business_id = the account's open_id)."""
    data = await _oauth_post("/tt_user/oauth2/token/", {
        "client_id": settings.tiktok_app_id,
        "client_secret": settings.tiktok_app_secret,
        "grant_type": "authorization_code",
        "auth_code": auth_code,
        "redirect_uri": settings.tiktok_redirect_uri,
    })
    blob = _token_fields(data)
    await _store_tokens(db, blob)
    _log.info("tiktok connected: business open_id %s", blob.get("business_id"))
    return blob


async def access_token(db: AsyncSession) -> tuple[str, str]:
    """(access_token, business_id), refreshing when within 2 min of expiry.
    Raises TikTokNotConnected when there is nothing usable — callers turn that
    into the loud 'reconnect needed' path, never a silent dead channel."""
    if not configured():
        raise TikTokNotConnected("TIKTOK_APP_ID/SECRET unset")
    blob = await _load_tokens(db)
    if blob is None:
        raise TikTokNotConnected("owner has not authorized the app yet")
    now = datetime.now(timezone.utc)
    exp = datetime.fromisoformat(blob["expires_at"]) if blob.get("expires_at") else now
    if exp - now > timedelta(seconds=120):
        return blob["access_token"], blob["business_id"]
    r_exp = (datetime.fromisoformat(blob["refresh_expires_at"])
             if blob.get("refresh_expires_at") else None)
    if r_exp is not None and r_exp <= now:
        raise TikTokNotConnected("refresh token expired — owner must reconnect")
    data = await _oauth_post("/tt_user/oauth2/refresh_token/", {
        "client_id": settings.tiktok_app_id,
        "client_secret": settings.tiktok_app_secret,
        "grant_type": "refresh_token",
        "refresh_token": blob["refresh_token"],
    })
    blob = _token_fields(data, prev=blob)
    await _store_tokens(db, blob)
    return blob["access_token"], blob["business_id"]


# ── sending ──────────────────────────────────────────────────────────────────

async def send_text(db: AsyncSession, conversation_id: str, text: str) -> str | None:
    """Send one text message into a TikTok conversation; returns message_id."""
    token, business_id = await access_token(db)
    body = {
        "business_id": business_id,
        "recipient_type": "CONVERSATION",
        "recipient": conversation_id,
        "message_type": "TEXT",
        "text": {"body": text},
    }
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(f"{API_BASE}/business/message/send/", json=body,
                                 headers={"Access-Token": token,
                                          "Content-Type": "application/json"})
    data = resp.json() if resp.content else {}
    if resp.status_code != 200 or data.get("code") != 0:
        raise RuntimeError(f"TikTok send failed: {resp.status_code} "
                           f"{json.dumps(data)[:300]}")
    return ((data.get("data") or {}).get("message") or {}).get("message_id")


async def conversation_id_for(db: AsyncSession, external_id: str) -> str | None:
    """The TikTok conversation the webhook last saw this customer in — stamped
    on their Identity.raw_profile. Without it we cannot address them (TikTok
    sends to conversations, not user ids)."""
    from sqlalchemy import select
    from app.models.person import Identity
    ident = (await db.execute(select(Identity).where(
        Identity.channel == "tiktok",
        Identity.external_id == external_id))).scalar_one_or_none()
    return (ident.raw_profile or {}).get("tt_conversation_id") if ident else None


async def send_to_user(external_id: str, text: str) -> str | None:
    """Send to a customer by their (tiktok, external_id) identity. Opens its
    own session so channel-agnostic callers (meta_send.send_to_channel) stay
    signature-stable. Raises loudly when unaddressable — the callers' failure
    paths (inbox error, hold-line flag) are built for that."""
    from app.database import AsyncSessionLocal
    async with AsyncSessionLocal() as db:
        conv_id = await conversation_id_for(db, external_id)
        if not conv_id:
            raise TikTokNotConnected(
                f"no TikTok conversation on file for {external_id} — "
                "the customer must message first (TikTok has no cold outreach)")
        return await send_text(db, conv_id, text)


# ── profile + webhook plumbing (best-effort niceties) ────────────────────────

async def business_profile(db: AsyncSession) -> dict:
    """{username, display_name, profile_image} of the connected account."""
    token, business_id = await access_token(db)
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(f"{API_BASE}/business/get/",
                                params={"business_id": business_id,
                                        "fields": '["username","display_name","profile_image"]'},
                                headers={"Access-Token": token})
    data = resp.json() if resp.content else {}
    return data.get("data") or {}


async def register_webhook() -> None:
    """Point TikTok's DIRECT_MESSAGE webhook at us. App-level (app id+secret),
    no user token needed. Called after a successful connect; harmless to rerun."""
    callback = settings.tiktok_redirect_uri.rsplit("/oauth/", 1)[0] + "/webhook/events"
    await _oauth_post("/business/webhook/update/", {
        "app_id": settings.tiktok_app_id,
        "secret": settings.tiktok_app_secret,
        "event_type": "DIRECT_MESSAGE",
        "callback_url": callback,
    })
    _log.info("tiktok webhook registered at %s", callback)
