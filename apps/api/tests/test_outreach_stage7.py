"""OUTBOUND COMMUNICATION, STAGE 7 — the corrections the audit-execution
verification (2026-11-06) listed: the opt-out on the paths that lacked it,
TikTok's inbound ids, the stamped order confirmation, sales nudges withdrawn
when an order is paid, and the explicit tests the briefs asked for that did not
yet exist (a job retried after a failure, a quotation updated after planning)."""
import asyncio
import inspect
import types
from datetime import datetime, timezone

from app.core.config import settings


def run(coro):
    return asyncio.run(coro)


# ── opt-out on the remaining paths ──────────────────────────────────────────

def test_the_comment_dm_stands_down_for_an_opted_out_contact(monkeypatch):
    """The public reply still goes; the private DM does not."""
    from app.agent import runtime
    src = inspect.getsource(runtime._run_comment_engage)
    assert "_comment_dm_allowed(" in src and "raise _OptedOut()" in src
    assert src.index("_comment_dm_allowed(") < src.index("await send_private_reply(")


def test_seasonal_missed_call_and_recording_notice_check_the_person():
    from app.jobs import seasonal_outreach
    from app.services import missed_call, recording_notice
    assert "opted_out(db, redis, row[\"conv\"], fail_closed=True)" in inspect.getsource(seasonal_outreach.run)
    src = inspect.getsource(missed_call._follow_up)
    assert "opted_out(db, redis, conv, fail_closed=True)" in src and src.index("opted_out(") < src.index("call:missed-msg")
    src = inspect.getsource(recording_notice.send_for_call)
    assert "return OPTED_OUT" in src and src.index("return OPTED_OUT") < src.index("insert(RecordingNotice)")
    assert recording_notice.OPTED_OUT == "opted_out"


def test_a_redis_flag_alone_answers_the_opt_out_for_a_comment_only_contact():
    """Comment engagement has no person row to read: the redis flag the
    acknowledgement wrote is enough, and no database is touched."""
    from app.services import intent

    class _Redis:
        def __init__(self, flagged): self.flagged = flagged
        async def get(self, k): return "1" if self.flagged and k.endswith(":psid-9") else None
    conv = types.SimpleNamespace(channel="facebook", wa_id=None, external_id="psid-9", person_id=None)
    assert run(intent.opted_out(None, _Redis(True), conv)) is True
    assert run(intent.opted_out(None, _Redis(False), conv)) is False


# ── TikTok parity ────────────────────────────────────────────────────────────

def test_tiktok_hands_the_row_id_to_the_turn():
    from app.routers import tiktok_webhook
    src = inspect.getsource(tiktok_webhook)
    assert "row_id = _uuid.uuid4()" in src and "Message(id=row_id" in src
    assert "inbound_id=str(row_id)" in src


# ── the order confirmation is a stamped transactional row ────────────────────

def test_the_order_confirmation_relay_is_stamped():
    from app.services import messaging, outreach_log as ol
    src = inspect.getsource(messaging._relay_order_confirmation)
    assert 'raw_meta=_ol.stamp("order_confirmation", _ol.TRANSACTIONAL' in src
    m = ol.stamp("order_confirmation", ol.TRANSACTIONAL, kind="order_confirmation")
    assert m["kind"] == "outreach" and m["class"] == "transactional" and m["source"] == "order_confirmation"


# ── paid ⇒ no more sales nudges ──────────────────────────────────────────────

def test_a_paid_order_withdraws_the_pending_sales_nudges():
    from app.services import actions, hub_events
    src = inspect.getsource(hub_events._celebrate)
    assert 'withdraw_routine(db, conv.id, why="order paid")' in src
    assert src.index("mark_won_for_conversation") < src.index("withdraw_routine")
    assert '"buying_follow_up"' in inspect.getsource(actions.withdraw_routine)

    rows = [types.SimpleNamespace(kind=k, status="planned", reason="r") for k in
            ("follow_up", "quote_follow_up", "buying_follow_up")]
    class _R:
        def scalars(self): return types.SimpleNamespace(all=lambda: rows)
    class _DB:
        async def execute(self, q): return _R()
        async def commit(self): pass
    n = run(actions.withdraw_routine(_DB(), "c1", why="order paid"))
    assert n == 3 and all(r.status == "vetoed" and "[order paid]" in r.reason for r in rows)


# ── a job retried after a failure, bounded ───────────────────────────────────

def test_a_send_that_keeps_failing_is_retried_three_times_then_parked(monkeypatch):
    """Brief §7: 'a scheduled job being retried after a timeout'. A send that
    raises (not an unknown outcome — a plain failure) leaves the row planned
    for the next tick; the fourth attempt parks it for a person."""
    from tests.test_outreach_stage2 import _dispatcher, _row
    now = datetime.now(timezone.utc)
    row = _row("buying_follow_up", id="a9", draft="Still thinking about the tray?",
               source="cart_recovery", dedupe_key="buying:c1")
    act, db, sent, _ = _dispatcher(monkeypatch, [row], verdicts={})

    class _Redis:
        def __init__(self): self.kv, self.hashes = {}, {}
        async def incr(self, k):
            self.kv[k] = int(self.kv.get(k, 0)) + 1
            return self.kv[k]
        async def expire(self, k, s): pass
        async def set(self, k, v, nx=False, ex=None):
            if nx and k in self.kv:
                return None
            self.kv[k] = v
            return True
        async def get(self, k): return self.kv.get(k)
        async def delete(self, k): self.kv.pop(k, None)
        async def hincrby(self, k, f, n): self.hashes.setdefault(k, {})[f] = self.hashes.get(k, {}).get(f, 0) + n
        async def publish(self, ch, msg): pass
        async def hgetall(self, k): return {}
    r = _Redis()
    async def boom(db, redis, c, text, action=None, shadow=None):
        raise RuntimeError("Graph 500")
    monkeypatch.setattr(act, "_send", boom)
    async def no_notify(*a, **k): pass
    monkeypatch.setattr(act, "_notify", no_notify)
    monkeypatch.setattr(settings, "outreach_mode", "shadow", raising=False)

    for attempt in range(1, 4):
        row.status = "planned"
        assert run(act.process_due(db, r, now=now)) == 0
        assert row.status == "planned", attempt          # retried on the next tick
    row.status = "planned"
    assert run(act.process_due(db, r, now=now)) == 0
    assert row.status == "needs_approval" and "auto-send failed 3×" in row.reason
    assert r.kv["actions:tries:a9"] == 4 and sent == []
