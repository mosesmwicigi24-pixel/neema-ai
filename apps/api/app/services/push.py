"""Push — a call rings every signed-in phone, even one whose app is closed.

Every call event is already broadcast on the live socket (call_log.publish),
which reaches only phones whose app is running. Android closes a backgrounded
app sooner or later (and Samsung sooner), so the same three events also go to
every registered phone as a high-priority Firebase Cloud Messaging data
message: it wakes the app, which rings exactly as for the socket frame
(apps/android … NeemaPushService). The first phone to answer takes the call;
call_answered / call_ended stop the others ringing.

  incoming_call  → ring              high priority, time to live 60 s (a later ring is useless)
  call_answered  → stop ringing      normal priority, 120 s
  call_ended     → stop ringing / end normal priority, 120 s

One collapse key per call, so a phone that was offline gets only the latest
word on it, never a ring for a call already over.

Off until FCM_SERVICE_ACCOUNT_JSON is set (core/config.py). Best-effort
throughout: a push failure is logged and never touches the call itself. A token
Firebase calls unknown (the app was uninstalled, or its data cleared) is deleted.
"""
import asyncio
import json
import logging
import time

import httpx
import jwt
from sqlalchemy import delete, select

from app.core.config import settings

_log = logging.getLogger("neema.push")

SCOPE = "https://www.googleapis.com/auth/firebase.messaging"
FCM_URL = "https://fcm.googleapis.com/v1/projects/{project}/messages:send"
CALL_EVENTS = {"incoming_call": "60s", "call_answered": "120s", "call_ended": "120s"}
# What the phone needs from the socket frame (all strings, as FCM data must be).
FIELDS = ("type", "call_id", "from", "name", "channel", "at", "external_id",
          "conversation_id", "person_id", "agent_id", "agent_name", "outcome", "direction")

_account_cache: tuple[str, dict | None] | None = None
_token_cache: dict = {"value": None, "expires": 0.0}
_tasks: set[asyncio.Task] = set()


def _account() -> dict | None:
    """The service account, parsed once per configured value. None when push is off
    or the value can't be read (said once in the log)."""
    global _account_cache
    raw = (settings.fcm_service_account_json or "").strip()
    if _account_cache and _account_cache[0] == raw:
        return _account_cache[1]
    acc = None
    if raw:
        try:
            text = raw if raw.startswith("{") else _file_or_base64(raw)
            acc = json.loads(text)
            if not all(acc.get(k) for k in ("project_id", "client_email", "private_key")):
                _log.warning("push: FCM service account lacks project_id/client_email/private_key — push is off")
                acc = None
        except Exception as exc:
            _log.warning("push: FCM service account unreadable (%s) — push is off", type(exc).__name__)
            acc = None
    _account_cache = (raw, acc)
    return acc


def _file_or_base64(raw: str) -> str:
    """A path to the key file, else the key base64-encoded (one line, safe in .env)."""
    import base64
    import os
    if os.path.exists(raw):
        return open(raw, encoding="utf-8").read()
    return base64.b64decode(raw, validate=True).decode("utf-8")


def configured() -> bool:
    return _account() is not None


async def _access_token(client: httpx.AsyncClient, acc: dict) -> str:
    """An OAuth access token for FCM, from the service account (JWT bearer grant),
    kept until five minutes before it expires."""
    now = time.time()
    if _token_cache["value"] and _token_cache["expires"] - 300 > now:
        return _token_cache["value"]
    token_uri = acc.get("token_uri") or "https://oauth2.googleapis.com/token"
    assertion = jwt.encode(
        {"iss": acc["client_email"], "scope": SCOPE, "aud": token_uri, "iat": int(now), "exp": int(now) + 3600},
        acc["private_key"], algorithm="RS256",
    )
    r = await client.post(token_uri, data={
        "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer", "assertion": assertion,
    })
    r.raise_for_status()
    body = r.json()
    _token_cache["value"] = body["access_token"]
    _token_cache["expires"] = now + float(body.get("expires_in", 3600))
    return _token_cache["value"]


def message_for(token: str, event: dict) -> dict:
    """The FCM v1 message for one phone: data only (the app draws the call
    screen itself); a ring is high priority, delivered at once to a sleeping phone."""
    data = {k: str(event[k]) for k in FIELDS if event.get(k) is not None}
    return {"message": {
        "token": token,
        "data": data,
        "android": {
            # Only the ring is urgent. Android lowers an app's high-priority
            # messages that show nothing, and answered / ended show nothing: the
            # woken app hears them on its socket (and polls every 2.5 s) anyway.
            "priority": "HIGH" if event.get("type") == "incoming_call" else "NORMAL",
            "ttl": CALL_EVENTS.get(event.get("type"), "60s"),
            "collapse_key": f"call-{event.get('call_id', '')}"[:64],
        },
    }}


def _dead_token(r: httpx.Response) -> bool:
    """Firebase's word that this token will never work again."""
    if r.status_code == 404:
        return True
    if r.status_code != 400:
        return False
    try:
        err = r.json().get("error", {})
    except Exception:
        return False
    codes = {d.get("errorCode") for d in err.get("details", []) if isinstance(d, dict)}
    return "UNREGISTERED" in codes or ("INVALID_ARGUMENT" in codes and "token" in str(err.get("message", "")).lower())


async def _tokens() -> list[str]:
    from app.database import AsyncSessionLocal
    from app.models.agent import Agent
    from app.models.push_device import PushDevice
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(select(PushDevice.token, PushDevice.agent_id))).all()
        if not rows:
            return []
        live = {str(a) for a in (await db.execute(select(Agent.id))).scalars().all()}
    # A phone still registered to an agent who was since removed never rings.
    return [t for t, a in rows if a in live]


async def _forget(tokens: list[str]) -> None:
    if not tokens:
        return
    from app.database import AsyncSessionLocal
    from app.models.push_device import PushDevice
    async with AsyncSessionLocal() as db:
        await db.execute(delete(PushDevice).where(PushDevice.token.in_(tokens)))
        await db.commit()


async def send_call_event(event: dict, *, tokens: list[str] | None = None,
                          transport: httpx.AsyncBaseTransport | None = None) -> dict:
    """Push one call event to every registered phone. Returns counts (sent,
    failed, forgotten) for the log and tests; never raises."""
    out = {"sent": 0, "failed": 0, "forgotten": 0}
    acc = _account()
    if acc is None or event.get("type") not in CALL_EVENTS or not event.get("call_id"):
        return out
    try:
        targets = tokens if tokens is not None else await _tokens()
        if not targets:
            return out
        url = FCM_URL.format(project=acc["project_id"])
        async with httpx.AsyncClient(timeout=10.0, transport=transport) as client:
            bearer = await _access_token(client, acc)
            headers = {"Authorization": f"Bearer {bearer}"}

            async def one(tok: str):
                try:
                    return tok, await client.post(url, json=message_for(tok, event), headers=headers)
                except Exception as exc:
                    _log.warning("push: send failed (%s)", type(exc).__name__)
                    return tok, None

            results = await asyncio.gather(*(one(t) for t in targets))
        dead = []
        for tok, r in results:
            if r is not None and r.is_success:
                out["sent"] += 1
            else:
                out["failed"] += 1
                if r is not None and _dead_token(r):
                    dead.append(tok)
                elif r is not None and r.status_code == 401:
                    _token_cache["value"] = None     # a stale access token: fetch afresh next time
        if dead:
            await _forget(dead)
            out["forgotten"] = len(dead)
        _log.info("push: %s %s → sent %s, failed %s, forgotten %s", event.get("type"),
                  event.get("call_id"), out["sent"], out["failed"], out["forgotten"])
    except Exception as exc:
        _log.warning("push: %s for %s not sent (%s: %s)", event.get("type"), event.get("call_id"),
                     type(exc).__name__, exc)
    return out


def schedule(event: dict) -> None:
    """Fire-and-forget from call_log.publish: the webhook answering Meta never waits on Firebase."""
    if event.get("type") not in CALL_EVENTS or not configured():
        return
    try:
        task = asyncio.get_running_loop().create_task(send_call_event(dict(event)))
    except RuntimeError:
        return
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
