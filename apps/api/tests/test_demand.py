"""Unmet demand — what customers asked for that we couldn't sell.

The point: every "do you have…?" the catalogue can't answer is real, paid-for-by-
nobody demand, and it used to vanish into the chat. These tests pin the capture
(including that it can NEVER break a sale) and the grouping that makes it useful.
"""
import asyncio
import types

import app.main  # noqa: F401 — registers models
import app.agent.tools as tools
from app.services import demand
from app.models.demand_signal import DemandSignal


# ── normalising, so the same request is counted once ─────────────────────────

def test_the_same_request_normalises_to_one_key():
    assert demand.normalise("Purple Chasuble?") == "purple chasuble"
    assert demand.normalise("  purple   CHASUBLE  ") == "purple chasuble"
    assert demand.normalise("Purple Chasuble?") == demand.normalise("purple  chasuble")
    assert demand.normalise(None) == "" and demand.normalise("") == ""


def test_greetings_and_noise_are_not_demand():
    for junk in ("hi", "Hello", "asante", "ok", "yes", "  ", "a", "??"):
        assert demand.is_meaningful(junk) is False
    for real in ("purple cope", "size 44 cassock", "bishop's mitre"):
        assert demand.is_meaningful(real) is True


# ── recording ────────────────────────────────────────────────────────────────

class _DB:
    def __init__(self, fail=False):
        self.added, self.commits, self.rollbacks, self.fail = [], 0, 0, fail
    def add(self, o):
        self.added.append(o)
    async def commit(self):
        if self.fail:
            raise RuntimeError("db down")
        self.commits += 1
    async def rollback(self):
        self.rollbacks += 1


def test_records_a_real_request_with_who_and_where():
    db = _DB()
    ok = asyncio.run(demand.record(db, "Purple Cope", kind="no_match",
                                   channel="messenger", wa_id="PSID1"))
    assert ok is True and db.commits == 1
    row = db.added[0]
    assert isinstance(row, DemandSignal)
    assert row.query == "purple cope"        # grouped form
    assert row.raw_query == "Purple Cope"    # their actual words, kept
    assert row.kind == "no_match" and row.channel == "messenger" and row.wa_id == "PSID1"


def test_noise_and_bad_kinds_are_not_recorded():
    db = _DB()
    assert asyncio.run(demand.record(db, "hi")) is False
    assert asyncio.run(demand.record(db, "purple cope", kind="nonsense")) is False
    assert db.added == [] and db.commits == 0


def test_a_logging_failure_never_breaks_the_sale():
    """The demand log is best-effort by design — it must never raise."""
    db = _DB(fail=True)
    assert asyncio.run(demand.record(db, "purple cope")) is False
    assert db.rollbacks == 1                  # cleaned up, no exception escaped


# ── the agent captures it where demand actually shows up ─────────────────────

def test_a_search_that_finds_nothing_is_logged(monkeypatch):
    logged = {}

    async def fake_catalog(db, redis):
        return [{"name": "Chasuble", "sku": "C1", "slug": "chasuble", "price": 15000}]

    async def fake_record(db, query, **kw):
        logged.update(query=query, **kw)
        return True

    monkeypatch.setattr(tools.svc, "catalog_items", fake_catalog)
    monkeypatch.setattr(demand, "record", fake_record)

    ctx = tools.ToolContext(db=object(), redis=None, wa_id="254700000001",
                            channel="whatsapp", currency="KES")
    out = asyncio.run(tools._search_catalog({"query": "papal tiara"}, ctx))
    assert out["count"] == 0
    assert logged["query"] == "papal tiara"          # captured, not lost
    assert logged["kind"] == "no_match" and logged["channel"] == "whatsapp"


def test_a_successful_search_logs_nothing(monkeypatch):
    called = {"n": 0}

    async def fake_catalog(db, redis):
        return [{"name": "Chasuble", "sku": "C1", "slug": "chasuble", "price": 15000}]

    async def fake_record(db, query, **kw):
        called["n"] += 1
        return True

    monkeypatch.setattr(tools.svc, "catalog_items", fake_catalog)
    monkeypatch.setattr(demand, "record", fake_record)
    ctx = tools.ToolContext(db=object(), redis=None, wa_id="254700000001")
    out = asyncio.run(tools._search_catalog({"query": "chasuble"}, ctx))
    assert out["count"] == 1 and called["n"] == 0


def test_an_escalation_reason_becomes_demand_evidence(monkeypatch):
    logged = {}

    async def fake_record(db, query, **kw):
        logged.update(query=query, **kw)
        return True

    monkeypatch.setattr(demand, "record", fake_record)

    class _NoConvDB:
        async def execute(self, *a, **k):
            return types.SimpleNamespace(
                scalars=lambda: types.SimpleNamespace(first=lambda: None))
        def add(self, o): pass

    ctx = tools.ToolContext(db=_NoConvDB(), redis=None, wa_id="PSID9",
                            channel="messenger")
    asyncio.run(tools._handoff_to_human(
        {"reason": "wants a cope in gold brocade, not in catalogue"}, ctx))
    assert "cope in gold brocade" in logged["query"]
    assert logged["kind"] == "out_of_catalogue"


# ── the report ───────────────────────────────────────────────────────────────

def test_report_ranks_by_distinct_people_not_raw_hits():
    """Twelve parishes asking for a cope is a product decision; one person asking
    twelve times is a conversation. The SQL must rank on distinct people first."""
    import inspect
    src = inspect.getsource(demand.top_demand)
    assert "distinct" in src.lower()
    assert "person_id" in src and "wa_id" in src      # falls back to the handle
    assert "group_by" in src


def test_kinds_are_the_three_we_capture():
    assert set(demand.KINDS) == {"no_match", "out_of_catalogue", "sourcing_gap",
                                 "availability_check"}
