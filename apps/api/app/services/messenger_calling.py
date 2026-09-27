"""Messenger voice calling — every Graph request the Messenger Calling API needs.

The second channel adapter next to services/wa_calling.py: same error type
(`wa_calling.MetaError`), same `{code, reason, action}` error shape, same
"connect / accept never retry" rule. Shapes are the documented ones
(docs/research/META_CALLING_2026-09.md §7a). All calls go to
`/{page-id}/calls` (or `/{page-id}/messages`, `/{page-id}/messenger_call_permissions`)
with that Page's access token.

The one real difference from WhatsApp: for a customer's call Meta sends NO
offer. The softphone builds the SDP **offer**, `accept` carries it, and Meta's
**answer** (plus, sometimes, a renegotiation offer) comes back in the response.
For our own call `connect` returns the answer synchronously too.

Voice only: we never send `media_update` (video) — Neema never offers video.
"""
import logging
import re
from datetime import datetime, timezone

from app.core.config import settings
from app.services import wa_calling
from app.services.wa_calling import MetaError

_log = logging.getLogger("neema.meta")

CHANNEL = "messenger"
PLATFORM = "messenger"
# Meta: "You have 60 seconds to accept the call" (consumer → business).
ACCEPT_WINDOW_S = 60


def enabled() -> bool:
    """Whether Messenger calls may ring agents and be placed."""
    return bool(settings.messenger_calling_enabled)


def configured() -> bool:
    return bool(settings.meta_page_token or settings.page_token_map())


def default_page_id() -> str:
    """Our first configured Page, else `me` (a Page token resolves `me` to its Page)."""
    for p in (settings.meta_page_id or "").split(","):
        if p.strip():
            return p.strip()
    return "me"


async def page_for(psid: str | None, page_id: str | None = None) -> str:
    """The Page to act as for this PSID: the one Meta named, else the page the
    contact was captured on (PSIDs are page-scoped), else our default."""
    if page_id:
        return str(page_id)
    if psid:
        from app.services.meta_send import page_of_contact
        try:
            p = await page_of_contact(CHANNEL, psid)
        except Exception:
            p = None
        if p:
            return p
    return default_page_id()


def _token(page_id: str) -> str:
    from app.services.meta_send import token_for_page
    tok = token_for_page(None if page_id == "me" else page_id)
    if not tok:
        raise MetaError("Messenger page token not configured — cannot call on Messenger")
    return tok


def _graph(path: str) -> str:
    return f"https://graph.facebook.com/{settings.meta_graph_version}/{path.lstrip('/')}"


async def _post(page_id: str, edge: str, body: dict, what: str, *, retry: bool = False) -> dict:
    return await wa_calling._send("POST", _graph(f"{page_id}/{edge}"), what, json_body=body,
                                  retry=retry, token=_token(page_id), label="Messenger")


async def _call_action(page_id: str, body: dict, what: str, *, retry: bool = False) -> dict:
    return await _post(page_id, "calls", {"platform": PLATFORM, **body}, f"call {what}", retry=retry)


def _sdp_of(v) -> str | None:
    """An SDP that Meta returns either as a string or as {sdp_type, sdp} (the
    docs show both)."""
    if isinstance(v, str):
        return v or None
    if isinstance(v, dict):
        s = v.get("sdp")
        return s if isinstance(s, str) and s else None
    return None


def session_of(resp: dict) -> dict:
    """{answer, renegotiation} from an accept / connect response."""
    sess = (resp or {}).get("session") or {}
    if not isinstance(sess, dict):
        sess = {}
    return {"answer": _sdp_of(sess.get("sdp_response")),
            "renegotiation": _sdp_of(sess.get("sdp_renegotiation"))}


# ── Call actions ─────────────────────────────────────────────────────────────

async def accept(call_id: str, sdp_offer: str, *, page_id: str) -> dict:
    """Accept a customer's call with OUR SDP offer. Returns {answer,
    renegotiation}: apply the answer, then the renegotiation offer (if any)
    and answer it locally. Never retried."""
    resp = await _call_action(page_id, {"call_id": call_id, "action": "accept",
                                        "session": {"sdp_type": "offer", "sdp": sdp_offer}}, "accept")
    return session_of(resp)


async def reject(call_id: str, *, page_id: str) -> dict:
    """Decline a ringing customer call. Safe to repeat → retried once."""
    return await _call_action(page_id, {"call_id": call_id, "action": "reject"}, "reject", retry=True)


async def terminate(call_id: str, *, page_id: str) -> dict:
    """Hang up a call (either direction). Safe to repeat → retried once."""
    return await _call_action(page_id, {"call_id": call_id, "action": "terminate"}, "terminate",
                              retry=True)


async def connect(psid: str, sdp_offer: str, *, page_id: str) -> dict:
    """Business-initiated call. Returns {id, answer, renegotiation}. Needs the
    customer's call permission. NEVER retried (a second call would ring)."""
    resp = await _call_action(page_id, {"to": psid, "action": "connect",
                                        "session": {"sdp_type": "offer", "sdp": sdp_offer}}, "connect")
    return {"id": (resp or {}).get("id"), **session_of(resp)}


# ── Permission ───────────────────────────────────────────────────────────────

def _ts_iso(v) -> str | None:
    return wa_calling._ts_iso(v)


def normalize_permission(raw: dict) -> dict:
    """Meta's `messenger_call_permissions` answer → the same shape as
    wa_calling.normalize_permission (status granted | unknown; denied /
    requested come from our store). Tolerant: `can_perform` (Messenger) or
    `can_perform_action` (WhatsApp's spelling)."""
    raw = raw if isinstance(raw, dict) else {}
    perm = raw.get("permission") or {}
    meta_status = str(perm.get("status") or "no_permission").lower()
    granted = meta_status == "has_permission"
    expires_at = _ts_iso(perm.get("expiration_time", perm.get("expiration")))
    if granted and expires_at and datetime.fromisoformat(expires_at) <= datetime.now(timezone.utc):
        granted, meta_status, expires_at = False, "no_permission", None
    actions: dict[str, dict] = {}
    for a in raw.get("actions") or []:
        if isinstance(a, dict):
            actions[str(a.get("action_name") or a.get("name") or "")] = a

    def can(name: str, default: bool) -> bool:
        a = actions.get(name)
        if a is None:
            return default
        v = a.get("can_perform", a.get("can_perform_action"))
        return default if v is None else bool(v)

    can_request = can("send_call_permission_request", not granted)
    calls_left = None
    for x in (actions.get("start_call") or {}).get("limits") or []:
        if isinstance(x, dict) and str(x.get("time_period") or "").upper() == "PT24H":
            try:
                calls_left = max(0, int(x.get("max_allowed")) - int(x.get("current_usage") or 0))
            except (TypeError, ValueError):
                calls_left = None
    return {"status": "granted" if granted else "unknown", "meta_status": meta_status,
            "permanent": False, "expires_at": expires_at if granted else None,
            "can_call": can("start_call", granted), "can_request": can_request,
            # Meta gives the 2-a-day usage but no reset time.
            "request_available_at": None, "calls_left_today": calls_left}


async def get_call_permission(psid: str, page_id: str | None = None) -> dict:
    """Meta's truth about whether we may call this PSID, normalised."""
    page = await page_for(psid, page_id)
    raw = await wa_calling._send("GET", _graph(f"{page}/messenger_call_permissions"),
                                 "call-permission read", params={"psid": psid}, retry=True,
                                 token=_token(page), label="Messenger")
    return normalize_permission(raw)


async def request_call_permission(psid: str, page_id: str | None = None) -> dict:
    """Send the `calling_optin` template (Accept / Decline buttons). At most 2
    per thread per day; the Send API's 24 h window applies. Never retried."""
    page = await page_for(psid, page_id)
    return await _post(page, "messages", {
        "recipient": {"id": psid},
        "message": {"attachment": {"type": "template",
                                   "payload": {"template_type": "calling_optin"}}},
    }, "call-permission request")


async def feature_status(page_id: str | None = None) -> str | None:
    """`messenger_api_calling` status for the Page ("enabled" when on), or None."""
    page = page_id or default_page_id()
    raw = await _post(page, "business_messaging_feature_status",
                      {"features": [{"feature": "messenger_api_calling"}]}, "feature status",
                      retry=True)
    for f in (raw or {}).get("data") or []:
        if isinstance(f, dict) and f.get("feature") == "messenger_api_calling":
            return str(f.get("status") or "").lower() or None
    return None


# ── Errors: Meta's code → what the agent reads and what they can do ──────────

_CALL_ERRORS: dict[str, tuple[str, str]] = {
    "4": ("Messenger is rate-limiting us — try again in a minute.", "wait"),
    "10": ("The Page's app lacks the permission Messenger calling needs — an admin must fix it.", "admin"),
    "190": ("Messenger page token expired — an admin must renew it.", "admin"),
    "200": ("The Page's app lacks the permission Messenger calling needs — an admin must fix it.", "admin"),
    "551": ("This person isn't available on Messenger right now.", "none"),
    "613": ("Messenger is rate-limiting us — try again in a minute.", "wait"),
    "2018389": ("Messenger calling isn't enabled for this Page — an admin must check it.", "admin"),
    "2018390": ("This Messenger call is no longer available.", "none"),
    "2018391": ("The call setup was rejected — try again.", "retry"),
    "2018392": ("The call setup was rejected — try again.", "retry"),
    "2018393": ("This call belongs to a different Page — an admin must check the Page setup.", "admin"),
    "2018394": ("This call belongs to a different Page — an admin must check the Page setup.", "admin"),
    "2018395": ("This call has already ended.", "none"),
    "2018396": ("This call has already ended.", "none"),
}
# Send API: code 10 / subcode 2018278 = outside the 24 h messaging window.
_OUTSIDE_WINDOW = "2018278"
_NO_PERMISSION = ("has not given permission", "not given permission to call", "no_permission",
                  "no call permission")
_CODE_RE = re.compile(r'"code"\s*:\s*(\d+)')
_SUB_RE = re.compile(r'"error_subcode"\s*:\s*(\d+)')

NO_PERMISSION_REASON = ("This customer hasn't allowed Messenger calls yet. Send them a call "
                        "request — you can call as soon as they tap Accept.")


def classify_error(msg) -> dict:
    """{code, reason, action} for a failed Messenger Graph request."""
    code = getattr(msg, "code", None)
    status = getattr(msg, "status", None)
    body = getattr(msg, "body", None) or {}
    text = str(msg or "")
    low = text.lower()
    err = body.get("error") if isinstance(body, dict) else None
    sub = str((err or {}).get("error_subcode") or "") if isinstance(err, dict) else ""
    if not sub:
        m = _SUB_RE.search(text)
        sub = m.group(1) if m else ""
    if code is None:
        m = _CODE_RE.search(text)
        if m:
            code = int(m.group(1))
    if any(t in low for t in _NO_PERMISSION):
        return {"code": "no_permission", "reason": NO_PERMISSION_REASON, "action": "request_permission"}
    if sub == _OUTSIDE_WINDOW:
        return {"code": "outside_window",
                "reason": "Messenger only allows a call request within 24 hours of their last message.",
                "action": "none"}
    if code is not None and str(code) in _CALL_ERRORS:
        reason, action = _CALL_ERRORS[str(code)]
        return {"code": str(code), "reason": reason, "action": action}
    if "not configured" in low:
        return {"code": "not_configured", "reason": "Messenger calling isn't configured on the server — "
                "an admin must set it up.", "action": "admin"}
    if status == 429 or "(429)" in text:
        return {"code": "rate_limited", "reason": "Messenger is rate-limiting us — try again in a minute.",
                "action": "wait"}
    if status == 0 or (isinstance(status, int) and status >= 500) or re.search(r"\(5\d\d\)|\(network\)", text):
        return {"code": "meta_unavailable", "reason": "Messenger isn't answering right now — try again.",
                "action": "retry"}
    return {"code": str(code) if code is not None else "unknown",
            "reason": "Couldn't reach the customer on Messenger right now.", "action": "retry"}
