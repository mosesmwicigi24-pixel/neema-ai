"""WhatsApp voice-calling — every Graph request calling makes (Cloud API).

The webhook (routers/whatsapp_webhook.py) receives a `connect` event with the
caller's SDP offer and stashes it in redis. When the agent answers in the
dashboard softphone, the browser builds a WebRTC SDP answer and hands it here;
we relay it to Meta with `accept`. Terminate ends the call. All call actions go
to POST /<PHONE_NUMBER_ID>/calls with the WABA token, on
`settings.waba_calling_api_version`.

Also here: the call-permission query (`GET /<PNID>/call_permissions`), the
permission request (free-form inside the 24 h window, template outside it),
the call-permission template admin, the calling settings, media download for
Meta's recordings / transcripts, and the error table every route speaks.

Degrades, never breaks: every failure is a `MetaError` (a RuntimeError, so the
older `except Exception` callers keep working) carrying the HTTP status and
Meta's error code. Only idempotent requests retry (GET permission, settings
read, terminate: once, on 429 / 5xx / network, with jitter). `connect` and
`accept` NEVER retry — a duplicate would place a second call (138003).
"""
import asyncio
import json
import logging
import random
import re
from datetime import datetime, timezone

import httpx

from app.core.config import settings

_log = logging.getLogger("neema.wa")

# Seconds (min, max) to wait before the single retry — tests set (0, 0).
RETRY_JITTER = (0.2, 0.8)


class MetaError(RuntimeError):
    """A Graph request that failed. `status` 0 = no response (network/timeout)."""

    def __init__(self, message: str, *, status: int = 0, code: int | None = None,
                 body: dict | None = None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.body = body or {}


def _version() -> str:
    return settings.waba_calling_api_version or settings.waba_api_version


def _graph(path: str) -> str:
    return f"https://graph.facebook.com/{_version()}/{path.lstrip('/')}"


def _auth() -> dict:
    return {"Authorization": f"Bearer {settings.waba_token}"}


def _require(what: str) -> None:
    if not settings.waba_token or not settings.waba_phone_number_id:
        raise MetaError(f"WABA not configured — cannot {what}")


def _error_of(resp) -> tuple[int | None, dict]:
    try:
        body = resp.json()
    except Exception:
        body = {}
    err = (body or {}).get("error") if isinstance(body, dict) else None
    code = None
    if isinstance(err, dict):
        try:
            code = int(err.get("code")) if err.get("code") is not None else None
        except (TypeError, ValueError):
            code = None
    return code, body if isinstance(body, dict) else {}


def _retryable(exc: MetaError) -> bool:
    return exc.status == 0 or exc.status == 429 or exc.status >= 500 or exc.code == 613


async def _send(method: str, url: str, what: str, *, json_body: dict | None = None,
                params: dict | None = None, retry: bool = False,
                token: str | None = None, label: str = "WA") -> dict:
    """One Graph request → parsed JSON. Raises MetaError. `retry` = once more on
    429 / 5xx / network (only for requests that are safe to repeat). `token`
    overrides the WABA token (the Messenger adapter passes the Page token)."""
    attempts = 2 if retry else 1
    last: MetaError | None = None
    headers = {"Authorization": f"Bearer {token}"} if token else _auth()
    for attempt in range(attempts):
        try:
            async with httpx.AsyncClient() as client:
                if method == "GET":
                    resp = await client.get(url, headers=headers, params=params, timeout=15.0)
                else:
                    resp = await client.post(url, headers=headers, json=json_body, timeout=30.0)
        except Exception as exc:          # timeout / DNS / connection reset
            last = MetaError(f"{label} {what} failed (network): {exc}", status=0)
        else:
            if resp.is_success:
                try:
                    return resp.json() if resp.content else {}
                except Exception:
                    return {}
            code, body = _error_of(resp)
            _log.error("%s %s failed %s: %s", label, what, resp.status_code, resp.text[:300])
            last = MetaError(f"{label} {what} failed ({resp.status_code}): {resp.text[:300]}",
                             status=resp.status_code, code=code, body=body)
        if attempt + 1 < attempts and _retryable(last):
            await asyncio.sleep(random.uniform(*RETRY_JITTER))
            continue
        break
    raise last  # type: ignore[misc]


async def _call_action(body: dict, what: str, *, retry: bool = False) -> dict:
    _require(what)
    return await _send("POST", _graph(f"{settings.waba_phone_number_id}/calls"), f"call {what}",
                       json_body={"messaging_product": "whatsapp", **body}, retry=retry)


# ── Per-call recording / transcription (Meta, opt-in) ────────────────────────

def media_options() -> dict:
    """The `recording` / `transcription` objects for connect / accept, when the
    owner switched them on. Meta speaks the purpose to the customer."""
    out: dict = {}
    spec = {"status": "ENABLED",
            "purpose": (settings.call_recording_purpose or "")[:250],
            "announcement_language": settings.call_recording_language or "en"}
    if settings.call_meta_recording:
        out["recording"] = dict(spec)
    if settings.call_meta_transcription:
        out["transcription"] = dict(spec)
    return out


def opaque(agent_id, conversation_id=None) -> str:
    """`biz_opaque_callback_data`: who placed / took the call, compact (≤512)."""
    return json.dumps({"a": str(agent_id) if agent_id else None,
                       "c": str(conversation_id) if conversation_id else None},
                      separators=(",", ":"))


def parse_opaque(raw) -> dict:
    """{agent_id, conversation_id} from our `biz_opaque_callback_data` ({} if not ours)."""
    if not raw or not isinstance(raw, str):
        return {}
    try:
        data = json.loads(raw)
    except Exception:
        return {}
    if not isinstance(data, dict) or "a" not in data:
        return {}
    return {"agent_id": data.get("a"), "conversation_id": data.get("c")}


# ── Call actions ─────────────────────────────────────────────────────────────

async def pre_accept(call_id: str, sdp_answer: str) -> dict:
    """Establish the media connection before accepting — avoids audio clipping."""
    return await _call_action(
        {"call_id": call_id, "action": "pre_accept",
         "session": {"sdp_type": "answer", "sdp": sdp_answer}},
        "pre_accept")


async def accept(call_id: str, sdp_answer: str, *, biz_opaque: str | None = None) -> dict:
    """Accept the call with our SDP answer — audio flows after this. Never
    retried: a second accept can't help and may confuse Meta."""
    body: dict = {"call_id": call_id, "action": "accept",
                  "session": {"sdp_type": "answer", "sdp": sdp_answer}}
    if biz_opaque:
        body["biz_opaque_callback_data"] = biz_opaque
    body.update(media_options())
    return await _call_action(body, "accept")


async def terminate(call_id: str) -> dict:
    """Hang up / decline a call. Safe to repeat, so retried once on 429 / 5xx."""
    return await _call_action({"call_id": call_id, "action": "terminate"}, "terminate", retry=True)


async def connect(to: str, sdp_offer: str, *, biz_opaque: str | None = None) -> dict:
    """Business-INITIATED call: place a call to a customer with our SDP offer.
    Returns {calls:[{id}]}. Requires the customer's call permission — else Meta
    returns 138006. The customer's SDP answer arrives later on a `connect`
    webhook with sdp_type=answer. NEVER retried (138003 duplicate call)."""
    body: dict = {"to": to.lstrip("+"), "action": "connect",
                  "session": {"sdp_type": "offer", "sdp": sdp_offer}}
    if biz_opaque:
        body["biz_opaque_callback_data"] = biz_opaque
    body.update(media_options())
    return await _call_action(body, "connect")


# ── Call permission ──────────────────────────────────────────────────────────

_DEFAULT_REQUEST_TEXT = ("Hi! Bethany House would like to call you to help with your "
                         "order. Tap Allow to let us call you here on WhatsApp.")


async def request_call_permission(to: str, text: str | None = None) -> dict:
    """Ask a customer for permission to call them — the free-form interactive
    `call_permission_request` (only inside the 24 h customer-service window).
    The `call_permission_reply` webhook confirms (accept/reject)."""
    _require("request call permission")
    payload = {
        "messaging_product": "whatsapp", "recipient_type": "individual",
        "to": to.lstrip("+"), "type": "interactive",
        "interactive": {
            "type": "call_permission_request",
            "action": {"name": "call_permission_request"},
            "body": {"text": text or _DEFAULT_REQUEST_TEXT},
        },
    }
    return await _send("POST", _graph(f"{settings.waba_phone_number_id}/messages"),
                       "call-permission request", json_body=payload)


def template_params(first_name: str | None, full_name: str | None) -> list[str]:
    """The template's body parameters from settings.call_permission_template_params."""
    out = []
    for tok in (settings.call_permission_template_params or "").split(","):
        tok = tok.strip()
        if not tok:
            continue
        if tok == "first_name":
            out.append(first_name or "there")
        elif tok == "name":
            out.append(full_name or first_name or "there")
        else:
            out.append(tok)
    return out


async def request_call_permission_template(to: str, name: str, lang: str,
                                           params: list[str]) -> dict:
    """The permission request as an approved template (outside the 24 h window)."""
    _require("request call permission")
    template: dict = {"name": name, "language": {"code": lang or "en"}}
    if params:
        template["components"] = [{"type": "body", "parameters": [
            {"type": "text", "text": p} for p in params]}]
    payload = {"messaging_product": "whatsapp", "recipient_type": "individual",
               "to": to.lstrip("+"), "type": "template", "template": template}
    return await _send("POST", _graph(f"{settings.waba_phone_number_id}/messages"),
                       "call-permission template", json_body=payload)


def _ts_iso(v) -> str | None:
    """Unix seconds (int / numeric string) or an ISO string → ISO (UTC)."""
    if v in (None, ""):
        return None
    try:
        return datetime.fromtimestamp(int(float(v)), tz=timezone.utc).isoformat()
    except (TypeError, ValueError):
        pass
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        return (d if d.tzinfo else d.replace(tzinfo=timezone.utc)).isoformat()
    except ValueError:
        return None


def normalize_permission(raw: dict) -> dict:
    """Meta's `call_permissions` answer → the shape the clients read:
    {status, meta_status, permanent, expires_at, can_call, can_request,
     request_available_at, calls_left_today}. `status` here is only granted |
    unknown — denied / requested come from our own store (call_log merges)."""
    raw = raw if isinstance(raw, dict) else {}
    perm = raw.get("permission") or {}
    meta_status = str(perm.get("status") or "no_permission").lower()
    permanent = meta_status == "permanent"
    # The sample says `expiration_time`, the parameter table `expiration`.
    expires_at = None if permanent else _ts_iso(perm.get("expiration_time", perm.get("expiration")))
    granted = meta_status in ("temporary", "permanent")
    if granted and expires_at and datetime.fromisoformat(expires_at) <= datetime.now(timezone.utc):
        granted, meta_status, expires_at = False, "no_permission", None

    actions: dict[str, dict] = {}
    for a in raw.get("actions") or []:
        if isinstance(a, dict):
            actions[str(a.get("action_name") or a.get("name") or "")] = a
    limits: dict[str, list] = {}
    for name, a in actions.items():
        limits.setdefault(name, []).extend(x for x in (a.get("limits") or []) if isinstance(x, dict))
    for x in raw.get("limits") or []:        # top-level limits, when Meta sends them there
        if isinstance(x, dict):
            limits.setdefault(str(x.get("action_name") or "send_call_permission_request"), []).append(x)

    def can(name: str, default: bool) -> bool:
        a = actions.get(name)
        if a is None or a.get("can_perform_action") is None:
            return default
        return bool(a.get("can_perform_action"))

    can_call = can("start_call", granted)
    can_request = can("send_call_permission_request", not granted)
    request_at = None
    if not can_request:
        hits = []
        for x in limits.get("send_call_permission_request", []):
            try:
                full = int(x.get("current_usage") or 0) >= int(x.get("max_allowed") or 0)
            except (TypeError, ValueError):
                full = False
            iso = _ts_iso(x.get("limit_expiration_time"))
            if full and iso:
                hits.append(iso)
        request_at = max(hits) if hits else None
    calls_left = None
    for x in limits.get("start_call", []):
        if str(x.get("time_period") or "").upper() == "PT24H":
            try:
                calls_left = max(0, int(x.get("max_allowed")) - int(x.get("current_usage") or 0))
            except (TypeError, ValueError):
                calls_left = None
    return {"status": "granted" if granted else "unknown", "meta_status": meta_status,
            "permanent": permanent, "expires_at": expires_at, "can_call": can_call,
            "can_request": can_request, "request_available_at": request_at,
            "calls_left_today": calls_left}


async def get_call_permission(wa_id: str) -> dict:
    """Meta's truth about whether we may call this customer, normalised.
    Retried once on 429 / 5xx; raises MetaError when Meta can't say."""
    _require("read call permission")
    raw = await _send("GET", _graph(f"{settings.waba_phone_number_id}/call_permissions"),
                      "call-permission read", params={"user_wa_id": wa_id.lstrip("+")}, retry=True)
    return normalize_permission(raw)


# ── Call-permission template admin ───────────────────────────────────────────

async def find_template(name: str, lang: str | None = None) -> dict | None:
    """The WABA's template of that name (matching language when given), or None."""
    if not settings.waba_business_account_id or not settings.waba_token:
        raise MetaError("WABA_BUSINESS_ACCOUNT_ID not configured — cannot read templates")
    raw = await _send("GET", _graph(f"{settings.waba_business_account_id}/message_templates"),
                      "template read", params={"name": name}, retry=True)
    rows = [t for t in (raw.get("data") or []) if isinstance(t, dict) and t.get("name") == name]
    if lang:
        exact = [t for t in rows if t.get("language") == lang]
        rows = exact or rows
    return rows[0] if rows else None


async def create_permission_template(name: str, lang: str, body_text: str,
                                     example_name: str = "Grace") -> dict:
    """Create the UTILITY template carrying the `call_permission_request`
    component (Meta reviews it; status starts PENDING)."""
    if not settings.waba_business_account_id or not settings.waba_token:
        raise MetaError("WABA_BUSINESS_ACCOUNT_ID not configured — cannot create templates")
    body: dict = {"type": "BODY", "text": body_text}
    if "{{1}}" in body_text:
        body["example"] = {"body_text": [[example_name]]}
    payload = {"name": name, "language": lang, "category": "UTILITY",
               "components": [body, {"type": "call_permission_request"}]}
    return await _send("POST", _graph(f"{settings.waba_business_account_id}/message_templates"),
                       "template create", json_body=payload)


# ── Calling settings ─────────────────────────────────────────────────────────

async def get_settings() -> dict:
    """The number's `calling` settings object ({} when Meta returns none)."""
    _require("read calling settings")
    raw = await _send("GET", _graph(f"{settings.waba_phone_number_id}/settings"),
                      "settings read", retry=True)
    return (raw or {}).get("calling") or {}


async def update_settings(calling: dict) -> dict:
    """POST only the `calling` fields given (never retried: not ours to repeat)."""
    _require("update calling settings")
    return await _send("POST", _graph(f"{settings.waba_phone_number_id}/settings"),
                       "settings update", json_body={"calling": calling})


# ── Media (Meta's recordings / transcripts / voicemail) ──────────────────────

async def download_media(media_id: str) -> tuple[bytes, str]:
    """GET /<media-id> → url (valid 5 minutes) → the bytes, fetched at once with
    the token. Returns (content, mime_type)."""
    _require("download media")
    meta = await _send("GET", _graph(str(media_id)), "media lookup", retry=True)
    url = meta.get("url")
    if not url:
        raise MetaError("WA media lookup returned no url")
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, headers=_auth(), timeout=60.0)
    except Exception as exc:
        raise MetaError(f"WA media download failed (network): {exc}") from exc
    if not resp.is_success:
        raise MetaError(f"WA media download failed ({resp.status_code})", status=resp.status_code)
    return resp.content, str(meta.get("mime_type") or resp.headers.get("content-type") or "")


# ── ICE ──────────────────────────────────────────────────────────────────────

def ice_servers() -> list[dict]:
    """ICE servers for the browser's RTCPeerConnection. Our own coturn is primary;
    a public STUN + a public TURN (openrelay) are added as fallbacks so media can
    still relay if coturn is unreachable — voice needs a working relay to traverse
    NAT/mobile networks in both directions (browser ↔ Meta)."""
    servers: list[dict] = []
    if settings.turn_url:
        entry: dict = {"urls": settings.turn_url}
        if settings.turn_username:
            entry["username"] = settings.turn_username
            entry["credential"] = settings.turn_credential
        servers.append(entry)
    if settings.stun_url:
        servers.append({"urls": settings.stun_url})
    # Public relay fallback (free, widely used) — over UDP:80, TCP:80 and TLS:443
    # so it survives restrictive networks. Ensures a relay candidate exists even
    # before our coturn is fully proven.
    servers.append({
        "urls": ["turn:openrelay.metered.ca:80",
                 "turn:openrelay.metered.ca:443",
                 "turn:openrelay.metered.ca:443?transport=tcp"],
        "username": "openrelayproject", "credential": "openrelayproject",
    })
    return servers


# ── Errors: Meta's code → what the agent reads and what they can do ──────────
# action: retry | request_permission | wait | admin | none
# Unknown codes fall through to a plain "couldn't reach them" — never a promise.

_CALL_ERRORS: dict[str, tuple[str, str]] = {
    "100": ("The call setup was rejected — try again.", "retry"),
    "190": ("WhatsApp access token expired — an admin must renew it.", "admin"),
    "613": ("WhatsApp is busy answering permission checks — try again in a minute.", "wait"),
    "131009": ("WhatsApp doesn't support call buttons from this business's country.", "none"),
    "131026": ("Their WhatsApp can't receive this — they may need to update the app.", "none"),
    "131030": ("This test number can only call numbers on its allowed list — an admin must add them.", "admin"),
    "131044": ("WhatsApp calling has no valid payment method — an admin must add one in WhatsApp Manager.", "admin"),
    "131055": ("This number uses SIP calling, so it can't call from here — an admin must change the setup.", "admin"),
    "138000": ("WhatsApp calling isn't switched on for this number — an admin must enable it.", "admin"),
    "138001": ("Their WhatsApp can't take calls right now (an old app version or an unsupported device).", "none"),
    "138002": ("Too many calls are already in progress — try again in a moment.", "retry"),
    "138003": ("A call to this customer is already in progress.", "none"),
    "138004": ("The call couldn't connect — try again.", "retry"),
    "138005": ("Too many calls to this customer in a short time — try again later or message them.", "wait"),
    "138006": ("This customer hasn't allowed calls yet. Send them a call request — "
               "you can call as soon as they tap Allow.", "request_permission"),
    # A connect-time timeout on Meta's side — not the customer declining.
    "138007": ("The call couldn't connect in time — try again.", "retry"),
    "138009": ("You've already asked recently — WhatsApp allows 1 call request a day and 2 a week.", "wait"),
    "138012": ("You've reached WhatsApp's limit of calls to this customer for today — try again tomorrow "
               "or message them.", "wait"),
    "138013": ("WhatsApp doesn't allow business calls to this customer's country.", "none"),
    "138014": ("WhatsApp has paused calling for this number because of low call quality — an admin "
               "should check WhatsApp Manager.", "admin"),
    "138015": ("Calling can't be enabled until this number's messaging limit is at least 2,000 — "
               "an admin must check WhatsApp Manager.", "admin"),
    "138017": ("They've already allowed calls permanently — you can call now.", "none"),
    "138018": ("WhatsApp calling isn't set up (no calls webhook) — an admin must fix the setup.", "admin"),
    "138019": ("The call couldn't be set up — try again.", "retry"),
    "138020": ("The call couldn't reach WhatsApp's relay — try again.", "retry"),
    "138021": ("No audio reached us from the call — try again.", "retry"),
    "138022": ("Our audio didn't reach the customer — try again.", "retry"),
    "138023": ("The call was answered but no audio flowed — try again.", "retry"),
}

_CODE_RE = re.compile(r'"code"\s*:\s*(\d+)')
_TOKEN_EXPIRED = ("error validating access token", "session has expired", "access token has expired",
                  "oauthexception")


def classify_error(msg) -> dict:
    """{code, reason, action} for a failed Graph request (a MetaError or its text)."""
    code = getattr(msg, "code", None)
    status = getattr(msg, "status", None)
    text = str(msg or "")
    low = text.lower()
    if code is None:
        m = _CODE_RE.search(text)
        if m:
            code = int(m.group(1))
    if code is None:
        for k in _CALL_ERRORS:
            if k.startswith("13") and k in text:
                code = int(k)
                break
    if code is not None and str(code) in _CALL_ERRORS:
        reason, action = _CALL_ERRORS[str(code)]
        return {"code": str(code), "reason": reason, "action": action}
    if any(t in low for t in _TOKEN_EXPIRED):
        reason, action = _CALL_ERRORS["190"]
        return {"code": "190", "reason": reason, "action": action}
    if "not configured" in low:
        return {"code": "not_configured", "reason": "WhatsApp calling isn't configured on the server — "
                "an admin must set it up.", "action": "admin"}
    if status == 429 or "(429)" in text:
        return {"code": "rate_limited", "reason": "WhatsApp is rate-limiting us — try again in a minute.",
                "action": "wait"}
    if status == 0 or (isinstance(status, int) and status >= 500) or re.search(r"\(5\d\d\)|\(network\)", text):
        return {"code": "meta_unavailable", "reason": "WhatsApp isn't answering right now — try again.",
                "action": "retry"}
    return {"code": str(code) if code is not None else "unknown",
            "reason": "Couldn't reach the customer on WhatsApp right now.", "action": "retry"}


def friendly_error(msg) -> str:
    """The agent-facing reason a request failed, from Meta's error text."""
    return classify_error(msg)["reason"]
