"""Backend security gaps (owner, 2026-09-26) — the parts that need no database.

The route-level proof (agents, roles, actions, the live feed on a real
Postgres) is tests/test_security_db.py. Pinned here:

  · permissions resolve exactly as the dashboard's lib/permissions.ts does;
  · a refresh token no longer opens the API or the live feed;
  · the live feed refuses a missing, forged, wrong-agent or refresh token;
  · a reply that went out is never reported as failed because its record
    didn't save (the agent pressed Send again and the customer got it twice);
  · the same client_msg_id is sent once, however many times it arrives.
"""
import asyncio
import types

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

import app.main  # noqa: F401 — registers all SQLAlchemy models
import app.services.conversation as convsvc
from app.core.permissions import ALL_PERMISSIONS, LEGACY_FALLBACK, agent_public, effective_permissions
from app.core.security import create_access_token, create_refresh_token


# ── Permissions: web parity ───────────────────────────────────────────────────

def test_permissions_resolve_like_the_dashboard():
    everything = set(ALL_PERMISSIONS)
    assert effective_permissions(role="readonly", is_superuser=True) == everything
    assert effective_permissions(role="admin", is_superuser=False) == everything
    assert effective_permissions(role="agent", is_superuser=False) == set(LEGACY_FALLBACK["agent"])
    assert "manage_agents" not in effective_permissions(role="agent", is_superuser=False)
    # The custom role's list replaces the legacy defaults…
    assert effective_permissions(role="agent", is_superuser=False,
                                 role_permissions=["manage_agents"]) == {"manage_agents"}
    # …a per-agent override replaces the role's (JSON text as the driver may hand it)…
    assert effective_permissions(role="agent", is_superuser=False,
                                 custom_permissions='["view_orders"]',
                                 role_permissions=["manage_agents"]) == {"view_orders"}
    # …and an EMPTY override falls back to the legacy role, not to the custom role.
    assert effective_permissions(role="readonly", is_superuser=False, custom_permissions=[],
                                 role_permissions=["manage_agents"]) == set(LEGACY_FALLBACK["readonly"])
    assert effective_permissions(role="nobody", is_superuser=False) == set()


def test_the_permission_keys_match_the_web():
    import pathlib
    import re
    web = pathlib.Path(__file__).resolve().parents[2] / "web/src/lib/permissions.ts"
    if not web.exists():
        pytest.skip("web source not present")
    keys = set(re.findall(r':\s*"([a-z_]+)",', web.read_text().split("} as const")[0]))
    assert keys == set(ALL_PERMISSIONS)


def test_an_agent_is_shown_without_its_password_hash():
    a = types.SimpleNamespace(id="a1", name="Ann", email="a@x.ke", role=types.SimpleNamespace(value="admin"),
                              is_available=True, is_superuser=False, active_convs=0, avatar_url=None,
                              created_at=None, last_seen_at=None, password_hash="$2b$secret")
    shown = agent_public(a)
    assert "password_hash" not in shown and shown["role"] == "admin"


# ── Tokens ────────────────────────────────────────────────────────────────────

def test_a_refresh_token_does_not_open_the_api():
    from app.routers.admin import get_current_agent
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=create_refresh_token("a1"))
    with pytest.raises(HTTPException) as e:
        asyncio.run(get_current_agent(creds, db=None))
    assert e.value.status_code == 401


def test_the_live_feed_refuses_anything_but_the_agents_access_token():
    from app.routers.websocket import _authorised
    aid = "7f5b2f0e-1111-4b2a-9c1d-2a3b4c5d6e7f"
    other = "0a1b2c3d-2222-4b2a-9c1d-2a3b4c5d6e7f"
    for token in (None, "", "not-a-jwt", create_refresh_token(aid), create_access_token(other)):
        assert asyncio.run(_authorised(token, aid)) is False
    assert asyncio.run(_authorised(create_access_token("not-a-uuid"), "not-a-uuid")) is False


# ── Replies: sent once, never reported failed once they went out ─────────────

class _Redis:
    def __init__(self):
        self.kv = {}

    async def set(self, k, v, nx=None, ex=None):
        if nx and k in self.kv:
            return None
        self.kv[k] = v
        return True

    async def get(self, k):
        return self.kv.get(k)

    async def delete(self, k):
        self.kv.pop(k, None)


class _Res:
    def __init__(self, one):
        self._one = one

    def scalar_one_or_none(self):
        return self._one


class _DB:
    def __init__(self, conv, commit_fails=False):
        self.conv, self.commit_fails = conv, commit_fails
        self.added, self.rolled_back = [], False

    async def execute(self, *a, **k):
        return _Res(self.conv)

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        if self.commit_fails:
            raise RuntimeError("connection reset by peer")

    async def refresh(self, obj):
        obj.id = "m1"

    async def rollback(self):
        self.rolled_back = True


def _conv():
    from app.models.conversation import InterceptMode
    return types.SimpleNamespace(id="c1", channel="whatsapp", wa_id="254700000001", external_id=None,
                                 person_id=None, intercept_mode=InterceptMode.ai, assigned_agent_id=None,
                                 last_message_at=None, last_message_preview=None)


def _wire(monkeypatch, fail_delivery=False):
    sent = []

    async def deliver(db, conv, text, quoted=None):
        if fail_delivery:
            raise RuntimeError("Graph said no")
        sent.append(text)
        return f"wamid.{len(sent)}"

    async def broadcast(*a, **k):
        pass
    monkeypatch.setattr(convsvc, "_deliver_agent_reply", deliver)
    monkeypatch.setattr(convsvc, "_broadcast", broadcast)
    return sent


_AGENT = types.SimpleNamespace(id="a1", is_superuser=False)


def test_a_reply_that_went_out_is_never_reported_failed(monkeypatch):
    sent = _wire(monkeypatch)
    db = _DB(_conv(), commit_fails=True)
    res = asyncio.run(convsvc.send_agent_reply(db, "c1", _AGENT, "Karibu!", _Redis()))
    assert sent == ["Karibu!"]
    assert res.get("ok") is not False and res["saved"] is False and res["text"] == "Karibu!"
    assert db.rolled_back


def test_the_same_client_msg_id_sends_once(monkeypatch):
    sent = _wire(monkeypatch)
    redis = _Redis()
    first = asyncio.run(convsvc.send_agent_reply(_DB(_conv()), "c1", _AGENT, "Habari", redis,
                                                 client_msg_id="out-1"))
    again = asyncio.run(convsvc.send_agent_reply(_DB(_conv()), "c1", _AGENT, "Habari", redis,
                                                 client_msg_id="out-1"))
    assert sent == ["Habari"] and again == first
    asyncio.run(convsvc.send_agent_reply(_DB(_conv()), "c1", _AGENT, "Habari", redis, client_msg_id="out-2"))
    assert sent == ["Habari", "Habari"]


def test_a_repeat_while_the_first_is_still_sending_is_refused(monkeypatch):
    _wire(monkeypatch)
    redis = _Redis()
    redis.kv["reply:once:c1:out-9"] = "pending"
    with pytest.raises(HTTPException) as e:
        asyncio.run(convsvc.send_agent_reply(_DB(_conv()), "c1", _AGENT, "Habari", redis, client_msg_id="out-9"))
    assert e.value.status_code == 409


def test_a_failed_delivery_frees_the_id_for_a_retry(monkeypatch):
    _wire(monkeypatch, fail_delivery=True)
    redis = _Redis()
    res = asyncio.run(convsvc.send_agent_reply(_DB(_conv()), "c1", _AGENT, "Habari", redis, client_msg_id="out-3"))
    assert res["ok"] is False and "reply:once:c1:out-3" not in redis.kv
    sent = _wire(monkeypatch)
    asyncio.run(convsvc.send_agent_reply(_DB(_conv()), "c1", _AGENT, "Habari", redis, client_msg_id="out-3"))
    assert sent == ["Habari"]


def test_without_an_id_or_redis_a_reply_sends_as_before(monkeypatch):
    sent = _wire(monkeypatch)
    asyncio.run(convsvc.send_agent_reply(_DB(_conv()), "c1", _AGENT, "One", None, client_msg_id="x"))
    asyncio.run(convsvc.send_agent_reply(_DB(_conv()), "c1", _AGENT, "Two", _Redis()))
    assert sent == ["One", "Two"]
