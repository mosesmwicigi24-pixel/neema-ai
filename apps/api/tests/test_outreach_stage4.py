"""OUTBOUND COMMUNICATION, STAGE 4 — the shadow week is readable from one
public curl: counts only, today and yesterday, and the rows waiting for a
person. Nothing that could identify a customer."""
import asyncio
import json
from datetime import datetime, timedelta, timezone

from app.services import outreach_log as ol


def run(coro):
    return asyncio.run(coro)


class _Redis:
    def __init__(self, hashes=None):
        self.hashes = hashes or {}
    async def hgetall(self, k):
        return {kk.encode(): str(v).encode() for kk, v in self.hashes.get(k, {}).items()}


def _key(offset=0):
    return "outreach:shadow:" + (datetime.now(timezone.utc) + timedelta(hours=3) - timedelta(days=offset)).strftime("%Y%m%d")


class _NoDB:
    def __call__(self):
        raise RuntimeError("no database in this test")


def test_the_view_reads_both_days_and_only_known_fields():
    r = _Redis({_key(0): {"suppress": 2, "hold_customer": 1, "bogus": 9, "park_language": "x"},
                _key(1): {"defer": 3, "enforced_suppress": 1}})
    view = run(ol.health_view(r, db_factory=_NoDB()))
    assert view["mode"] in ("shadow", "enforce")
    assert view["today"] == {"suppress": 2, "hold_customer": 1}
    assert view["yesterday"] == {"defer": 3, "enforced_suppress": 1}
    assert "rows" not in view                                     # the DB part failed quietly


def test_the_view_counts_waiting_rows_without_their_contents():
    class _Res:
        def __init__(self, rows=None, scalar=None): self._rows, self._scalar = rows, scalar
        def all(self): return self._rows
        def scalar(self): return self._scalar

    class _DB:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def execute(self, q):
            if "GROUP BY" in str(q):
                return _Res(rows=[("planned", 4), ("needs_approval", 2)])
            return _Res(scalar=1)
    view = run(ol.health_view(_Redis(), db_factory=_DB))
    assert view["rows"] == {"planned": 4, "needs_approval": 2, "unknown_outcome": 1}
    assert view["today"] == {} and view["yesterday"] == {}


def test_the_public_payload_carries_counts_only():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.routers.health import router
    app = FastAPI()
    app.include_router(router)
    app.state.redis = _Redis({_key(0): {"suppress": 1}})
    out = TestClient(app).get("/health").json()
    assert out["status"] == "ok" and out["outreach"]["today"] == {"suppress": 1}
    flat = json.dumps(out["outreach"])
    for banned in ("254", "255", "+", "@", "reason", "draft", "wa_id"):
        assert banned not in flat


def test_the_dispatcher_tallies_every_decision_the_read_out_shows():
    import inspect
    from app.services import actions
    src = inspect.getsource(actions.process_due)
    for field in ("hold_customer", "hold_team_check", "park_language", "park_template", "unknown_outcome"):
        assert f'_shadow_count(redis, "{field}")' in src
        assert field in ol.TALLY_FIELDS
