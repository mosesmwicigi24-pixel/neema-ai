"""/api/health answers the question that mattered: can Neema still reply?

The account once ran out of credit and every turn failed for days. Inbound
messages kept arriving, the inbox looked busy, and the only trace was an ERROR
line nobody was grepping. services/agent_health.py has recorded the reason ever
since — but only the 08:00 standup read it, so "why is Neema not replying?"
still needed SSH to the box. Now one curl answers it.

Coarse on purpose: this endpoint is public, so it carries the KIND of failure
and a count, never the raw provider error or the customer's number.
"""
import asyncio
import json
import types

import app.main  # noqa: F401 — registers models
from app.routers.health import health


class _Redis:
    """Just the two reads agent_health.read_turn_failures makes."""
    def __init__(self, kv=None):
        self.kv = kv or {}

    async def get(self, k):
        return self.kv.get(k)


def _req(redis):
    return types.SimpleNamespace(
        app=types.SimpleNamespace(state=types.SimpleNamespace(redis=redis)))


def _call(redis):
    return asyncio.run(health(_req(redis)))


def test_healthy_when_nothing_has_failed():
    out = _call(_Redis())
    assert out["status"] == "ok"
    assert out["agent"] == {"replies": "ok"}


def test_an_outage_names_its_kind_and_demands_a_human():
    out = _call(_Redis({
        "agent:fail:count": "12",
        "agent:fail:last": json.dumps({
            "kind": "credit",
            "error": "Your credit balance is too low to access the API",
            "wa_id": "254700000001",
            "at": "2026-08-16T12:00:00+00:00",
        }),
    }))
    assert out["agent"]["replies"] == "failing"
    assert out["agent"]["kind"] == "credit"
    assert out["agent"]["failed_last_hour"] == 12
    # credit/auth/model never clear themselves — someone must act
    assert out["agent"]["needs_a_human"] is True


def test_a_self_clearing_failure_does_not_cry_wolf():
    out = _call(_Redis({
        "agent:fail:count": "3",
        "agent:fail:last": json.dumps({"kind": "rate", "error": "429 rate limit"}),
    }))
    assert out["agent"]["kind"] == "rate"
    assert out["agent"]["needs_a_human"] is False      # throttling passes on its own


def test_the_public_payload_leaks_nothing():
    """The record holds the provider's error text and the customer's number.
    Neither may cross a public endpoint."""
    out = _call(_Redis({
        "agent:fail:count": "1",
        "agent:fail:last": json.dumps({
            "kind": "auth",
            "error": "invalid x-api-key sk-ant-SECRET",
            "wa_id": "254712345678",
        }),
    }))
    blob = json.dumps(out)
    assert "sk-ant" not in blob and "SECRET" not in blob
    assert "254712345678" not in blob
    assert "error" not in out["agent"] and "wa_id" not in out["agent"]


def test_monitoring_never_breaks_the_thing_it_monitors():
    """A redis outage must not take /health down with it — the endpoint still
    reports liveness and the running commit."""
    class _Broken:
        async def get(self, k):
            raise RuntimeError("redis is gone")

    out = _call(_Broken())
    assert out["status"] == "ok"
    assert "version" in out

    out_none = _call(None)                 # redis not attached at all
    assert out_none["status"] == "ok"
