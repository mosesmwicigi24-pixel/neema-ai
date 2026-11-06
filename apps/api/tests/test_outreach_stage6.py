"""OUTBOUND COMMUNICATION, STAGE 6 — the long tail: the Meta live turn at
parity with WhatsApp (inbound ids through the burst buffer, an unknown send
outcome recorded and never resent), the parked-row backlog readable by why
and by age, and one plan() behind every planner."""
import asyncio
import json
import types
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app.services import outreach_log as ol


def run(coro):
    return asyncio.run(coro)


# ── A. Meta parity ───────────────────────────────────────────────────────────

class _Redis:
    def __init__(self):
        self.lists, self.kv = {}, {}
    async def rpush(self, k, v): self.lists.setdefault(k, []).append(v)
    async def expire(self, k, s): pass
    async def incr(self, k):
        self.kv[k] = int(self.kv.get(k, 0)) + 1
        return self.kv[k]
    async def get(self, k): return self.kv.get(k)
    async def lrange(self, k, a, b): return list(self.lists.get(k, []))
    async def delete(self, k): self.lists.pop(k, None)


def test_the_burst_buffer_carries_every_row_id(monkeypatch):
    from app.agent import runtime
    from app.core.config import settings
    monkeypatch.setattr(settings, "meta_debounce_seconds", 5, raising=False)
    r = _Redis()
    run(runtime._meta_enqueue(r, "messenger", "psid", "Hi", None, "row-1"))
    tok = run(runtime._meta_enqueue(r, "messenger", "psid", "I want a cassock", None, "row-2"))
    text, media, ids = run(runtime._meta_drain(r, "messenger", "psid", tok))
    assert text == "Hi\nI want a cassock" and media is None and ids == ["row-1", "row-2"]


def test_the_burst_hands_the_ids_to_the_turn(monkeypatch):
    from app.agent import runtime
    from app.core.config import settings
    monkeypatch.setattr(settings, "meta_debounce_seconds", 1, raising=False)
    seen = {}
    async def fake_run(redis, channel, ext, text, page_id=None, media=None, **kw):
        seen.update(text=text, ids=kw.get("inbound_ids"))
        return True
    async def no_sleep(s): pass
    monkeypatch.setattr(runtime, "_run_and_send_meta", fake_run)
    monkeypatch.setattr(runtime.asyncio, "sleep", no_sleep)
    r = _Redis()
    run(runtime._meta_enqueue(r, "instagram", "ig", "Bei?", None, "a"))
    tok = run(runtime._meta_enqueue(r, "instagram", "ig", "ya stola", None, "b"))
    assert run(runtime._run_meta_after_burst(r, "instagram", "ig", "ya stola", None, None, tok)) is True
    assert seen == {"text": "Bei?\nya stola", "ids": ["a", "b"]}
    # no buffer (no redis): the single id still rides along
    assert run(runtime._run_meta_after_burst(None, "instagram", "ig", "Hi", None, None, None,
                                             inbound_ids=["solo"])) is True
    assert seen["ids"] == ["solo"]


def test_a_dropped_connection_after_the_write_is_an_unknown_outcome(monkeypatch):
    from app.services import meta_send
    from app.services.messaging import SendOutcomeUnknown
    from app.core.config import settings
    monkeypatch.setattr(settings, "meta_page_token", "t0ken", raising=False)

    class _Client:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, *a, **k): raise httpx.ReadTimeout("no answer")
    monkeypatch.setattr(meta_send.httpx, "AsyncClient", _Client)
    with pytest.raises(SendOutcomeUnknown):
        run(meta_send.send_meta_message("psid", "hello"))

    class _Refused(_Client):
        async def post(self, *a, **k): raise httpx.ConnectError("refused")
    monkeypatch.setattr(meta_send.httpx, "AsyncClient", _Refused)
    with pytest.raises(httpx.ConnectError):                     # before the write: a plain failure
        run(meta_send.send_meta_message("psid", "hello"))


def test_the_meta_turn_records_an_unknown_outcome_and_never_resends():
    import inspect
    from app.agent import runtime
    src = inspect.getsource(runtime._run_and_send_meta)
    assert "except svc.SendOutcomeUnknown" in src
    assert '"delivery": {"status": "unknown"' in src
    assert 'if facts.get("follow_up") and not unknown' in src
    assert "inbound_ids=inbound_ids" in src
    from app.routers import meta_webhook
    assert "inbound_id=row_id" in inspect.getsource(meta_webhook)


# ── B. the backlog ───────────────────────────────────────────────────────────

def test_rows_are_bucketed_by_why_they_wait_and_how_long():
    assert ol.backlog_bucket("Quote… [needs approval: outside the 24h messaging window]") == "window"
    assert ol.backlog_bucket("x [needs approval: team still confirming: purple chasuble]") == "team_check"
    assert ol.backlog_bucket("x [they write in 'hi' — a person should write this]") == "language"
    assert ol.backlog_bucket("x [needs approval: sent? outcome unknown — check the thread]") == "unknown_outcome"
    assert ol.backlog_bucket("x [needs approval: auto-send failed 3× — needs a human]") == "failed"
    assert ol.backlog_bucket("x [needs approval: deal total above KES 50,000]") == "sensitive"
    assert ol.backlog_bucket("plain") == "other" and ol.backlog_bucket(None) == "other"
    now = datetime(2026, 11, 6, tzinfo=timezone.utc)
    assert ol.backlog_age(now - timedelta(days=2), now) == "under_7d"
    assert ol.backlog_age(now - timedelta(days=20), now) == "7_to_30d"
    assert ol.backlog_age(now - timedelta(days=90), now) == "over_30d"
    assert ol.backlog_age(datetime(2026, 10, 1), now) == "over_30d"            # naive timestamps too
    assert ol.backlog_age(None, now) == "unknown"


def test_the_view_counts_without_contents():
    now = datetime(2026, 11, 6, tzinfo=timezone.utc)
    rows = [("quote_follow_up", "q [needs approval: outside the 24h messaging window]", now - timedelta(days=40)),
            ("check_in", "Customer-agreed check-in [needs approval: outside the 24h messaging window]", now - timedelta(days=3)),
            ("fit_check", "Order BH-1 … [needs approval: team still confirming: x]", now - timedelta(days=10))]
    class _DB:
        async def execute(self, q): return types.SimpleNamespace(all=lambda: rows)
    view = run(ol.backlog_view(_DB(), now=now))
    assert view == {"total": 3, "by_reason": {"window": 2, "team_check": 1},
                    "by_age": {"over_30d": 1, "under_7d": 1, "7_to_30d": 1},
                    "by_kind": {"quote_follow_up": 1, "check_in": 1, "fit_check": 1}}
    assert "BH-1" not in json.dumps(view)


def test_the_cli_refuses_to_retire_anything_young():
    from app.jobs import outreach_backlog
    with pytest.raises(SystemExit):
        outreach_backlog.main(["--retire-older-than", "3"])


# ── C. one plan() behind every planner ───────────────────────────────────────

def test_the_scribe_and_the_fit_check_file_through_plan():
    """The check-in tool keeps its own path: it must read rows booked before
    purposes existed and map them to a purpose first (test_outreach_stage1)."""
    import inspect
    from app.services import actions, hub_events
    for fn in (actions.upsert_follow_up, hub_events._plan_fit_check):
        src = inspect.getsource(fn)
        assert "await plan(" in src and "AgentAction(" not in src, fn.__name__
