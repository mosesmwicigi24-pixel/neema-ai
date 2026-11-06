"""OUTBOUND COMMUNICATION, STAGE 2 (audit, 2026-11-05) — one coordinated
intent system: a commitment's identity on the row, one contextual decision
in the dispatcher (shadow or enforce), the cart and payment sweeps as
planners, the 15:00 re-engage sweep retired. Unit level; the Postgres
scenarios are in test_outreach_stage2_db.py."""
import asyncio
import importlib
import importlib.util
import inspect
import pathlib
import types
from datetime import datetime, timedelta, timezone

import pytest

import app.main  # noqa: F401
from app.core.config import settings


def _migration():
    path = next(pathlib.Path(__file__).resolve().parents[1].glob(
        "alembic/versions/e8a1c3d5f7b9_*.py"))
    spec = importlib.util.spec_from_file_location("mig_e8a1", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ── A. identity ──────────────────────────────────────────────────────────────

def test_commitment_identity_rules():
    from app.services.actions import dedupe_key_for as k
    assert k("quote_follow_up", deal_id="d1") == "buying:d1"
    assert k("buying_follow_up", deal_id="d1") == "buying:d1"          # a quote and a cart: one moment
    assert k("follow_up", deal_id="d1") == "promise:d1"
    assert k("customer_promise", deal_id="d1") == "customer_promise:d1"
    assert k("check_in", reason="Customer-agreed check-in (WhatsApp): the quotation") == "check_in:purchase_decision"
    assert k("check_in", reason="Delivery check-in (WhatsApp): ready by Sunday") == "check_in:delivery"
    assert k("replenishment", reason="Supplies check-in (WhatsApp): divai") == "check_in:supplies"
    assert k("replenishment", reason="Customer-agreed check-in (WhatsApp): legacy") == "check_in:purchase_decision"
    assert k("fit_check", reason="Order BH-2417 was delivered 6 days ago") == "care:BH-2417"
    assert k("fit_check", reason="Order 1234 was delivered", conversation_id="c1") == "care:1234"
    assert k("payment_reminder", reference="501,502", conversation_id="c1") == "payment:501,502"
    # distinct matters stay distinct
    assert k("payment_reminder", reference="501") != k("payment_reminder", reference="502")
    assert k("fit_check", reference="BH-1") != k("fit_check", reference="BH-2")


def test_migration_backfill_agrees_with_the_code():
    from app.services.actions import dedupe_key_for
    mig = _migration()
    cases = [("quote_follow_up", "Quote follow-up: …", "d1", "c1"),
             ("follow_up", "Neema promised: x", "d1", "c1"),
             ("customer_promise", "Customer said…", None, "c1"),
             ("check_in", "Customer-agreed check-in (WhatsApp): q", None, "c1"),
             ("check_in", "Delivery check-in (WhatsApp): q", None, "c1"),
             ("replenishment", "Supplies check-in (WhatsApp): divai", None, "c1"),
             ("replenishment", "Customer-agreed check-in (WhatsApp): old", None, "c1"),
             ("fit_check", "Order BH-2417 was delivered 6 days ago", None, "c1"),
             ("fit_check", "no number here", None, "c1")]
    for kind, reason, deal, conv in cases:
        assert mig._key(kind, reason, deal, conv) == dedupe_key_for(
            kind, deal_id=deal, conversation_id=conv, reason=reason), (kind, reason)
    assert "WHERE status IN ('planned', 'needs_approval', 'sending')" in mig.UNIQUE_INDEX_SQL
    assert "ON agent_actions (conversation_id, dedupe_key)" in mig.UNIQUE_INDEX_SQL
    assert "DROP INDEX IF EXISTS uq_agent_actions_open_commitment" in inspect.getsource(mig.downgrade)


def test_every_planner_files_an_identity_and_a_source():
    from app.agent import tools
    from app.services import actions, hub_events, quote_followup
    assert 'dedupe_key=f"check_in:{about}"' in inspect.getsource(tools._schedule_check_in)
    assert 'source="tool"' in inspect.getsource(tools._schedule_check_in)
    assert 'dedupe_key=f"buying:{deal.id}"' in inspect.getsource(quote_followup.on_turn)
    assert 'dedupe_key=f"care:' in inspect.getsource(hub_events._plan_fit_check)
    assert 'source="scribe"' in inspect.getsource(actions.upsert_follow_up)
    assert "dedupe_key VARCHAR(80)" in " ".join(app.main.MIGRATION_STATEMENTS)


def test_scribe_rows_stay_one_per_deal_and_say_what_superseded_what():
    """A newer promise replaces an older quote nudge on the same deal — and the
    record shows why the nudge went."""
    from app.services.actions import upsert_follow_up
    quote = types.SimpleNamespace(kind="quote_follow_up", status="planned", reason="Quote…",
                                  draft="Shall I reserve it?", dedupe_key="buying:d1", source="scribe")
    class _R:
        def scalars(self): return types.SimpleNamespace(all=lambda: [quote])
        def scalar_one_or_none(self): return None          # plan(): no open row for the promise yet
    class _DB:
        def __init__(self): self.added = []
        async def execute(self, q): return _R()
        def add(self, row): self.added.append(row)
        async def commit(self): pass
    db = _DB()
    deal = types.SimpleNamespace(id="d1", conversation_id="c1")
    asyncio.run(upsert_follow_up(db, deal, due_at=datetime.now(timezone.utc), kind="follow_up",
                                 reason="Neema promised: confirm the embroidery"))
    assert quote.status == "vetoed" and "superseded by a newer follow_up" in quote.reason
    assert len(db.added) == 1 and db.added[0].dedupe_key == "promise:d1" and db.added[0].source == "scribe"


# ── B. the contextual decision ───────────────────────────────────────────────

def _row(kind, created_minutes_ago=30, **kw):
    now = datetime.now(timezone.utc)
    base = dict(id="a1", status="planned", due_at=now, kind=kind, conversation_id="c1", deal_id=None,
                reason=kw.pop("reason", "x"), draft=None, created_at=now - timedelta(minutes=created_minutes_ago),
                source=None, dedupe_key=None)
    base.update(kw)
    return types.SimpleNamespace(**base)


def _conv():
    from app.models.conversation import InterceptMode
    return types.SimpleNamespace(id="c1", channel="whatsapp", wa_id="254700000001", external_id=None,
                                 intercept_mode=InterceptMode.ai, person_id=None)


def test_decide_reads_the_conversation_not_a_clock(monkeypatch):
    from app.services import actions as act
    now = datetime.now(timezone.utc)
    turns = {"in": None, "human": None}
    today = {"n": 0}
    async def latest(db, conv): return turns["in"], turns["human"]
    async def sent_today(db, conv, now): return today["n"]
    monkeypatch.setattr(act, "_latest_turns", latest)
    monkeypatch.setattr(act, "_routine_sent_today", sent_today)

    def d(row):
        return asyncio.run(act.decide(None, _conv(), row, now=now))
    assert d(_row("quote_follow_up")) == ("go", "")
    turns["in"] = now - timedelta(minutes=5)                     # the customer wrote after planning
    assert d(_row("quote_follow_up"))[0] == "suppress" and "customer wrote" in d(_row("quote_follow_up"))[1]
    turns["in"] = now - timedelta(hours=2)                       # wrote before planning: still go
    assert d(_row("buying_follow_up"))[0] == "go"
    turns["human"] = now - timedelta(minutes=1)                  # a colleague replied after planning
    assert d(_row("follow_up"))[0] == "suppress" and "colleague" in d(_row("follow_up"))[1]
    turns["human"] = None
    today["n"] = 1                                               # one unprompted sales message already today
    assert d(_row("quote_follow_up")) == ("defer", "one unprompted sales message a day")
    # a kept promise and care about an order are not judged here
    assert d(_row("check_in", reason="Customer-agreed check-in (WhatsApp): q")) == ("go", "")
    assert d(_row("fit_check")) == ("go", "")
    assert d(_row("payment_reminder")) == ("go", "")


def _dispatcher(monkeypatch, rows, *, verdicts=None, conv=None, deal=None):
    from app.services import actions as act
    from tests._action_fakes import install
    install(monkeypatch)
    conv = conv or _conv()

    class _Rows:
        def scalars(self): return types.SimpleNamespace(all=lambda: list(rows))
        def scalar_one_or_none(self): return deal
        def scalar(self): return None
        def scalar_one(self): return 0
    convs = {}

    def _conv_for(pk):
        if pk not in convs:
            c = _conv()
            c.id, c.wa_id = pk, f"25470000000{len(convs) + 1}"
            convs[pk] = c
        return convs[pk]
    convs[conv.id] = conv

    class _DB:
        async def execute(self, *a, **k): return _Rows()
        async def get(self, model, pk): return _conv_for(pk) if model.__name__ == "Conversation" else deal
        async def commit(self): pass
        async def rollback(self): pass
    async def fake_window(db, c): return True
    monkeypatch.setattr("app.services.hub_events._within_window", fake_window)
    monkeypatch.setattr("app.services.hub_events.is_quiet_hours", lambda now=None: False)
    async def no_gate(db, d, c, in_window): return None
    monkeypatch.setattr(act, "needs_approval", no_gate)
    monkeypatch.setattr(settings, "agent_initiative", True, raising=False)
    composed = []
    async def compose(db, redis, c, reason):
        composed.append(reason)
        return f"About {reason[:20]}"
    monkeypatch.setattr(act, "_compose_follow_up", compose)
    async def not_repeat(db, c, t, **k): return False
    monkeypatch.setattr(act, "_repeats_earlier", not_repeat)
    async def not_opted(db, redis, c): return False
    monkeypatch.setattr("app.services.intent.opted_out", not_opted)
    if verdicts is not None:
        async def decide(db, c, a, *, now): return verdicts.get(a.kind, ("go", ""))
        monkeypatch.setattr(act, "decide", decide)
    sent = []
    async def send(db, redis, c, text, action=None, shadow=None):
        sent.append((getattr(action, "kind", None), text, list(shadow or [])))
    monkeypatch.setattr(act, "_send", send)
    return act, _DB(), sent, composed


def test_shadow_mode_sends_and_remembers_what_enforce_would_have_done(monkeypatch):
    now = datetime.now(timezone.utc)
    row = _row("quote_follow_up", draft="Shall I reserve it?")
    act, db, sent, _ = _dispatcher(monkeypatch, [row], verdicts={"quote_follow_up": ("suppress", "the customer wrote after this was planned")})
    monkeypatch.setattr(settings, "outreach_mode", "shadow", raising=False)
    assert asyncio.run(act.process_due(db, None, now=now)) == 1
    assert sent == [("quote_follow_up", "Shall I reserve it?", ["suppress: the customer wrote after this was planned"])]
    assert row.status == "sent"


def test_enforce_mode_holds(monkeypatch):
    now = datetime.now(timezone.utc)
    rows = [_row("quote_follow_up", id="a1", draft="Shall I reserve it?"),
            _row("buying_follow_up", id="a2", conversation_id="c2")]
    verdicts = {"quote_follow_up": ("suppress", "the customer wrote after this was planned"),
                "buying_follow_up": ("defer", "one unprompted sales message a day")}
    act, db, sent, _ = _dispatcher(monkeypatch, rows, verdicts=verdicts)
    monkeypatch.setattr(settings, "outreach_mode", "enforce", raising=False)
    assert asyncio.run(act.process_due(db, None, now=now)) == 0 and sent == []
    assert rows[0].status == "vetoed" and "customer wrote after this was planned" in rows[0].reason
    assert rows[1].status == "planned" and rows[1].due_at > now        # waits for the morning


def test_code_composed_rows_send_their_draft_the_rest_are_composed(monkeypatch):
    now = datetime.now(timezone.utc)
    rows = [_row("payment_reminder", id="a1", draft="Hi Grace 🙏 Just checking in on your order BH-501…",
                 dedupe_key="payment:501", source="payment_followup"),
            _row("buying_follow_up", id="a2", conversation_id="c2", reason="They built a cart — Alb",
                 source="cart_recovery", dedupe_key="buying:c2")]
    act, db, sent, composed = _dispatcher(monkeypatch, rows, verdicts={})
    async def unpaid(redis, action): return "unpaid"
    monkeypatch.setattr("app.jobs.payment_followup.live_verdict", unpaid)
    recorded = []
    async def rec(job, conv, *, ref=None): recorded.append((job, ref))
    monkeypatch.setattr("app.services.recovery_results.record_send", rec)
    assert asyncio.run(act.process_due(db, None, now=now)) == 2
    assert sent[0][1].startswith("Hi Grace") and composed == ["They built a cart — Alb"]
    assert sorted(recorded) == [("cart_recovery", "c2"), ("payment_followup", "501")]


def test_a_payment_reminder_never_chases_money_that_landed(monkeypatch):
    now = datetime.now(timezone.utc)
    paid = _row("payment_reminder", id="a1", draft="reminder", dedupe_key="payment:501")
    unknown = _row("payment_reminder", id="a2", conversation_id="c2", draft="reminder", dedupe_key="payment:502")
    act, db, sent, _ = _dispatcher(monkeypatch, [paid, unknown], verdicts={})
    async def verdict(redis, action):
        return {"payment:501": "paid", "payment:502": "unknown"}[action.dedupe_key]
    monkeypatch.setattr("app.jobs.payment_followup.live_verdict", verdict)
    assert asyncio.run(act.process_due(db, None, now=now)) == 0 and sent == []
    assert paid.status == "vetoed" and "paid — nothing to remind" in paid.reason
    assert unknown.status == "planned" and unknown.due_at > now


def test_live_verdict_reads_every_order_in_the_reminder(monkeypatch):
    from app.jobs import payment_followup as pf
    statuses = {501: {"payment_status": "paid"}, 502: {"payment_status": "unpaid"}, 503: None}
    async def fetch(oid, redis=None): return statuses[oid]
    monkeypatch.setattr("app.core.hub_client.fetch_order_status", fetch)
    row = lambda key: types.SimpleNamespace(dedupe_key=key)   # noqa: E731
    assert asyncio.run(pf.live_verdict(None, row("payment:501"))) == "paid"
    assert asyncio.run(pf.live_verdict(None, row("payment:501,502"))) == "unpaid"
    assert asyncio.run(pf.live_verdict(None, row("payment:501,503"))) == "unknown"
    assert asyncio.run(pf.live_verdict(None, row("buying:x"))) == "unpaid"


# ── C. planners, not senders ─────────────────────────────────────────────────

def test_the_sweeps_plan_and_the_re_engage_sweep_is_gone():
    from app.jobs import cart_recovery, payment_followup
    from app.services import recovery_jobs
    assert "actions.plan(" in inspect.getsource(cart_recovery._handle)
    assert "_send_waba" not in inspect.getsource(cart_recovery._handle)
    assert "actions.plan(" in inspect.getsource(payment_followup._handle)
    assert "_send_waba" not in inspect.getsource(payment_followup._handle)
    assert set(recovery_jobs.JOBS) == {"payment_followup", "cart_recovery"}
    assert importlib.util.find_spec("app.jobs.reengage") is None
    with pytest.raises(ValueError):
        asyncio.run(recovery_jobs._module_run("reengage", send=False, redis=None))
    from app.core.config import Settings
    assert "recovery_reengage_enabled" not in Settings.model_fields
    assert "outreach_mode" in Settings.model_fields and Settings.model_fields["outreach_mode"].default == "shadow"


def test_planned_action_kinds_and_classes():
    from app.services import actions as act
    from app.services import outreach_log as ol
    assert act.message_class(types.SimpleNamespace(kind="payment_reminder", reason="")) == ol.TRANSACTIONAL
    assert act.message_class(types.SimpleNamespace(kind="buying_follow_up", reason="")) == ol.ROUTINE
    assert "payment_reminder" in act.CODE_COMPOSED_KINDS and "buying_follow_up" in act.ROUTINE_KINDS
    assert act.template_purpose(types.SimpleNamespace(kind="buying_follow_up", reason="")) is None
    assert act.template_purpose(types.SimpleNamespace(kind="payment_reminder", reason="")) is None


def test_standup_reports_the_shadow_tally(monkeypatch):
    from app.jobs.self_qa import compose_standup
    from app.main import app as _app

    class _R:
        async def get(self, k): return None
        async def hgetall(self, k): return {"suppress": "3", "defer": "2"} if k.startswith("outreach:shadow:") else {}
    monkeypatch.setattr(_app.state, "redis", _R(), raising=False)
    monkeypatch.setattr(settings, "outreach_mode", "shadow", raising=False)

    class _Res:
        def scalar_one(self): return 0
        def scalars(self): return self
        def all(self): return []
        def one(self): return (0, 0)
    class _DB:
        async def execute(self, *a, **k): return _Res()
    out = asyncio.run(compose_standup(_DB()))
    assert "🧭 Outreach: yesterday the contextual rules would have held 3 and deferred 2" in out
    assert "shadow — sent anyway" in out
