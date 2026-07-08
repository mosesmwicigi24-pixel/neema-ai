"""Unit tests for the payment reconciler's DB-free paths. The full four-way
match (whatsapp / new / phone identifier / deterministic phone-merge), country
normalization and order stamping are verified against a real Postgres separately;
this pins the guard that a malformed MSISDN can never break a payment webhook.
Requires Python 3.11.
"""
import asyncio

from app.services.reconcile import reconcile_payment


class _ExplodingDB:
    """Any DB access is a bug for the unparseable path — it must return before
    touching the session."""
    async def execute(self, *a, **k):
        raise AssertionError("reconcile_payment touched the DB for an unparseable MSISDN")

    async def flush(self):
        raise AssertionError("reconcile_payment flushed for an unparseable MSISDN")


def test_unparseable_msisdn_returns_unresolved_without_db():
    for bad in ("not-a-phone", "", "   ", "+", "12"):
        r = asyncio.run(reconcile_payment(_ExplodingDB(), payer_msisdn=bad))
        assert r["resolved"] is False
        assert r["reason"] == "unparseable_msisdn"
        assert r["msisdn"] == bad
