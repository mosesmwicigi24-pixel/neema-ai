"""Notice when Neema can no longer reply.

The Anthropic account ran out of credit. Every llm.complete() raised, so every
WhatsApp turn failed — for days, to customers in Kenya, Nigeria, South Africa,
India, Congo and Australia alike. Inbound kept arriving and kept being stored,
so the inbox looked busy; the only trace was an `ERROR ... tier2 background turn
failed` line nobody was grepping. A person found it, not the system.

The self-check watched media, stuck actions, briefings and human-held threads —
but nothing watched the thing the business runs on: that she can still answer.
Two probes now do, from both ends: WHY turns are failing, and WHETHER customers
are being left waiting (whatever the cause).
"""
import asyncio
import json
import types
from datetime import datetime, timedelta, timezone

from app.services import agent_health, selfcheck


class _FakeRedis:
    def __init__(self): self.kv = {}
    async def incr(self, k):
        self.kv[k] = int(self.kv.get(k, 0)) + 1
        return self.kv[k]
    async def expire(self, k, ttl): return True
    async def set(self, k, v, ex=None, nx=None):
        self.kv[k] = v
        return True
    async def get(self, k): return self.kv.get(k)


# ── classifying what a human must actually do ────────────────────────────────

def test_the_real_outage_is_classified_as_credit():
    """The exact error that took WhatsApp down."""
    assert agent_health.classify(
        "Your credit balance is too low to access the Anthropic API") == "credit"
    assert "credit" in agent_health.ACTIONABLE


def test_other_kinds():
    assert agent_health.classify("authentication_error: invalid x-api-key") == "auth"
    assert agent_health.classify("model: claude-sonnet-5 not_found") == "model"
    assert agent_health.classify("429 rate limit exceeded") == "rate"
    assert agent_health.classify("connection reset by peer") == "other"
    # transient kinds must NOT be treated as needing human action
    assert "rate" not in agent_health.ACTIONABLE
    assert "other" not in agent_health.ACTIONABLE


def test_failures_are_recorded_and_read_back():
    r = _FakeRedis()
    exc = RuntimeError("Your credit balance is too low to access the Anthropic API")
    asyncio.run(agent_health.record_turn_failure(r, "254712345678", exc))
    asyncio.run(agent_health.record_turn_failure(r, "2348132500498", exc))
    got = asyncio.run(agent_health.read_turn_failures(r))
    assert got["count"] == 2 and got["kind"] == "credit"
    assert "credit balance" in got["error"]


def test_recording_never_raises_without_redis():
    asyncio.run(agent_health.record_turn_failure(None, "254712345678", Exception("x")))
    assert asyncio.run(agent_health.read_turn_failures(None)) == {}


def test_the_operator_line_says_what_to_do():
    line = agent_health.describe({"count": 47, "kind": "credit",
                                  "error": "Your credit balance is too low"})
    assert "47 agent replies FAILED" in line
    assert "OUT OF CREDIT" in line          # unmistakable, not a stack trace


# ── probe 1: why she is failing ──────────────────────────────────────────────

def test_a_single_credit_failure_is_reported_immediately():
    """It never recovers on its own, so one is enough to raise it."""
    r = _FakeRedis()
    asyncio.run(agent_health.record_turn_failure(
        r, "254712345678", Exception("credit balance is too low")))
    out = asyncio.run(selfcheck._probe_agent_failures(None, r))
    assert out and "OUT OF CREDIT" in out[0]


def test_one_transient_failure_is_not_noise():
    r = _FakeRedis()
    asyncio.run(agent_health.record_turn_failure(r, "254712345678", Exception("timeout")))
    assert asyncio.run(selfcheck._probe_agent_failures(None, r)) == []


def test_repeated_transient_failures_do_get_reported():
    r = _FakeRedis()
    for _ in range(3):
        asyncio.run(agent_health.record_turn_failure(r, "254712345678", Exception("timeout")))
    assert asyncio.run(selfcheck._probe_agent_failures(None, r)) != []


def test_silence_when_all_is_well():
    assert asyncio.run(selfcheck._probe_agent_failures(None, _FakeRedis())) == []


# ── probe 2: customers left waiting, whatever the cause ──────────────────────

class _DB:
    def __init__(self, waiting): self._waiting = waiting
    async def execute(self, *a, **k):
        return types.SimpleNamespace(
            scalars=lambda: types.SimpleNamespace(all=lambda: self._waiting))


def test_a_pile_up_of_unanswered_customers_is_reported():
    old = datetime.now(timezone.utc) - timedelta(hours=5)
    out = asyncio.run(selfcheck._probe_unanswered_customers(_DB([old, old, old, old]), None))
    assert out and "4 customer(s) waiting on the AI" in out[0]
    assert "check that Neema can still answer" in out[0]


def test_a_couple_of_quiet_threads_are_not_an_outage():
    old = datetime.now(timezone.utc) - timedelta(hours=2)
    assert asyncio.run(selfcheck._probe_unanswered_customers(_DB([old, old]), None)) == []


def test_naive_timestamps_do_not_crash_the_probe():
    naive = datetime.utcnow() - timedelta(hours=3)      # no tzinfo
    out = asyncio.run(selfcheck._probe_unanswered_customers(_DB([naive] * 3), None))
    assert out and "waiting on the AI" in out[0]


# ── both probes are actually wired into the runner ───────────────────────────

def test_probes_are_registered_first():
    names = [n for n, _ in selfcheck.PROBES]
    assert "agent_failures" in names and "unanswered_customers" in names
    # they lead — "can she reply at all" outranks media housekeeping
    assert names.index("agent_failures") < names.index("media_dir")
