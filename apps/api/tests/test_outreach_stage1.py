"""OUTBOUND COMMUNICATION, STAGE 1 (audit, 2026-11-05) — the confirmed defects:
duplicate commitments, duplicate live replies, uncertain WhatsApp send
outcomes, wrong templates, repeated greetings, open availability checks that
nothing read, and opt-outs nobody recognised. Unit level; the Postgres
scenarios are in test_outreach_stage1_db.py."""
import asyncio
import inspect
import types
from datetime import datetime, timedelta, timezone

import pytest

import app.main  # noqa: F401 — registers models
from app.core.config import settings


# ── D. the template registry ─────────────────────────────────────────────────

def test_registry_maps_purposes_and_refuses_what_it_has_no_template_for(monkeypatch):
    from app.services import templates as T
    monkeypatch.setattr(settings, "wa_event_template", "order_update", raising=False)
    monkeypatch.setattr(settings, "wa_event_body", "Hello {1}, your order {2} is {3}.", raising=False)
    monkeypatch.setattr(settings, "wa_followup_template", "", raising=False)
    for purpose in ("order_update", "care", "replenishment"):
        assert T.for_purpose(purpose).name == "order_update"
    assert T.for_purpose("check_in") is None              # a deciding customer has no template
    with pytest.raises(T.TemplateRefused):
        asyncio.run(T.send("254700", "check_in", ["Judas"]))
    monkeypatch.setattr(settings, "wa_followup_template", "enquiry_followup", raising=False)
    tpl = T.for_purpose("check_in")
    assert tpl.name == "enquiry_followup" and tpl.slots == ("first_name",)
    assert tpl.render(["Judas"]).startswith("Hello Judas, this is Bethany House following up")


def test_registry_never_sends_nonsense_parameters(monkeypatch):
    from app.services import templates as T
    monkeypatch.setattr(settings, "wa_event_template", "order_update", raising=False)
    tpl = T.for_purpose("order_update")
    # The Judas rows: "sent" scraped from a sentence is not an order number.
    for bad in (["Judas", "sent", "the check-in you asked for"],
                ["Judas", "", "shipped"],
                ["Judas", "ORD-1", "{{3}}"],
                ["Judas", "ORD-1234", "None"],
                ["Judas", "ORD-1234"]):
        with pytest.raises(T.TemplateRefused):
            T.validate_params(tpl, bad)
    assert T.validate_params(tpl, ["Judas", "ORD-1234", "shipped"]) == ["Judas", "ORD-1234", "shipped"]
    assert T.validate_params(tpl, ["Judas", "your order", "shipped"])[1] == "your order"
    assert T.order_number_param("sent") == "your order"
    assert T.order_number_param("BH-2417") == "BH-2417"
    assert T.first_name_param("PASTOR : SURDAS Emmanuel") == "PASTOR"
    assert T.first_name_param(None) == "there"


def test_registry_renders_what_the_customer_reads_and_tags_the_row(monkeypatch):
    from app.services import templates as T
    monkeypatch.setattr(settings, "wa_event_template", "order_update", raising=False)
    monkeypatch.setattr(settings, "wa_event_body", "", raising=False)
    tpl = T.for_purpose("order_update")
    # No mirror configured: the row says plainly which template went, never invented words.
    text = tpl.render(["Judas", "ORD-7", "shipped and on its way"])
    assert text.startswith("[WhatsApp template «order_update» sent]") and "ORD-7" in text
    assert T.meta(tpl, ["Judas", "ORD-7", "x"])["kind"] == "template"


def test_template_send_goes_through_validation_before_meta(monkeypatch):
    from app.services import templates as T
    calls = []
    async def fake(wa_id, name, lang, params):
        calls.append((name, lang, params))
        return {"messages": [{"id": "wamid.1"}]}
    monkeypatch.setattr("app.services.messaging.send_wa_template", fake)
    monkeypatch.setattr(settings, "wa_event_template", "order_update", raising=False)
    monkeypatch.setattr(settings, "wa_event_body", "Hi {1}: {2} {3}", raising=False)
    rendered, wamid, tpl = asyncio.run(T.send("254700", "care", ["Moses", "BH-1", "fits?"]))
    assert rendered == "Hi Moses: BH-1 fits?" and wamid == "wamid.1" and calls
    with pytest.raises(T.TemplateRefused):
        asyncio.run(T.send("254700", "care", ["Moses", "sent", "fits?"]))
    assert len(calls) == 1                                # nothing reached Meta


# ── C. the send path: unknown outcomes ───────────────────────────────────────

def test_send_waba_classifies_transport_errors():
    import httpx
    from app.services import messaging as svc

    class _Client:
        def __init__(self, exc): self.exc = exc
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, *a, **k): raise self.exc

    def _run(exc):
        real = svc.httpx.AsyncClient
        svc.httpx.AsyncClient = lambda **k: _Client(exc)
        try:
            return asyncio.run(svc._send_waba("254700", "hi"))
        finally:
            svc.httpx.AsyncClient = real

    with pytest.raises(svc.SendOutcomeUnknown):          # after the write: unknown
        _run(httpx.ReadTimeout("slow"))
    with pytest.raises(svc.SendOutcomeUnknown):
        _run(httpx.RemoteProtocolError("dropped"))
    with pytest.raises(httpx.ConnectTimeout):            # never left: a plain failure
        _run(httpx.ConnectTimeout("refused"))
    assert svc._SEND_TIMEOUT.read == 30.0 and svc._SEND_TIMEOUT.connect == 10.0


def test_live_turn_records_an_unknown_outcome_and_never_resends():
    from app.agent import runtime
    src = inspect.getsource(runtime._run_and_send)
    assert "SendOutcomeUnknown" in src and '"status": "unknown"' in src
    assert src.index("SendOutcomeUnknown") < src.index("save_outbound_message")
    # the cassock ladder's second message is not sent on top of an unknown first
    assert 'facts.get("follow_up") and not unknown' in src


def test_planned_action_with_unknown_outcome_parks_for_a_person(monkeypatch):
    from app.services import actions as act
    from app.services.messaging import SendOutcomeUnknown
    from tests._action_fakes import install
    from app.models.conversation import InterceptMode
    install(monkeypatch)
    now = datetime.now(timezone.utc)
    action = types.SimpleNamespace(id="a1", status="planned", due_at=now, kind="follow_up",
                                   conversation_id="c1", deal_id="d1",
                                   reason="Neema promised: check gold thread", draft=None)
    conv = types.SimpleNamespace(id="c1", channel="whatsapp", wa_id="254700000001",
                                 external_id=None, intercept_mode=InterceptMode.ai, person_id=None)
    deal = types.SimpleNamespace(id="d1", status="open", items_snapshot=[], next_action=None)

    class _Rows:
        def scalars(self): return types.SimpleNamespace(all=lambda: [action])
    class _DB:
        async def execute(self, *a, **k): return _Rows()
        async def get(self, model, pk): return conv if model.__name__ == "Conversation" else deal
        async def commit(self): pass
        async def rollback(self): pass

    async def fake_window(db, c): return True
    monkeypatch.setattr("app.services.hub_events._within_window", fake_window)
    monkeypatch.setattr("app.services.hub_events.is_quiet_hours", lambda now=None: False)
    async def no_gate(db, d, c, in_window): return None
    monkeypatch.setattr(act, "needs_approval", no_gate)
    monkeypatch.setattr(settings, "agent_initiative", True, raising=False)
    async def compose(db, redis, c, reason): return "Following up on the gold thread."
    monkeypatch.setattr(act, "_compose_follow_up", compose)
    async def not_repeat(db, c, t): return False
    monkeypatch.setattr(act, "_repeats_earlier", not_repeat)
    async def not_opted(db, redis, c, **kw): return False
    monkeypatch.setattr("app.services.intent.opted_out", not_opted)
    async def readable_no(db, redis, c): return "no"
    monkeypatch.setattr("app.services.intent.opt_out_state", readable_no)
    async def unknown(db, redis, c, text, action=None, **kw): raise SendOutcomeUnknown("ReadTimeout")
    monkeypatch.setattr(act, "_send", unknown)
    n = asyncio.run(act.process_due(_DB(), None, now=now))
    assert n == 0
    assert action.status == "needs_approval"
    assert "outcome unknown" in action.reason and "check the thread" in action.reason


def test_delivery_statuses_are_parsed_from_the_webhook():
    from app.services.wa_native import parse_statuses
    payload = {"entry": [{"changes": [{"field": "messages", "value": {"statuses": [
        {"id": "wamid.A", "status": "delivered", "timestamp": "1762300000", "recipient_id": "254700"},
        {"id": "wamid.B", "status": "failed", "timestamp": "1762300001",
         "errors": [{"code": 131026, "title": "Message undeliverable"}]},
        {"id": "wamid.C", "status": "bogus"},
        {"id": "call.1", "status": "completed", "type": "call"},
    ]}}]}]}
    out = parse_statuses(payload)
    assert [s["wamid"] for s in out] == ["wamid.A", "wamid.B"]
    assert out[1]["error"].startswith("131026") and out[0]["at"].startswith("2025-11-04")


def test_delivery_statuses_land_on_the_row_and_never_regress():
    from app.services import messaging as svc
    row = types.SimpleNamespace(raw_meta={"kind": "outreach"}, created_at=None)

    class _R:
        def scalar_one_or_none(self): return row
    class _DB:
        def __init__(self): self.commits = 0
        async def execute(self, *a, **k): return _R()
        async def commit(self): self.commits += 1
        async def rollback(self): pass
    db = _DB()
    assert asyncio.run(svc.record_delivery_statuses(db, [{"wamid": "w", "status": "read", "at": "t1"}])) == 1
    assert row.raw_meta["delivery"]["status"] == "read" and row.raw_meta["kind"] == "outreach"
    # a late "sent" never overwrites "read"; "failed" always lands
    asyncio.run(svc.record_delivery_statuses(db, [{"wamid": "w", "status": "sent", "at": "t2"}]))
    assert row.raw_meta["delivery"]["status"] == "read"
    asyncio.run(svc.record_delivery_statuses(db, [{"wamid": "w", "status": "failed", "error": "131026: x"}]))
    assert row.raw_meta["delivery"] == {"status": "failed", "at": None, "error": "131026: x"}


def test_webhook_records_statuses_before_ingesting_messages():
    from app.services import wa_native
    src = inspect.getsource(wa_native.handle_webhook)
    assert "parse_statuses(payload)" in src and "record_delivery_statuses" in src
    assert src.index("record_delivery_statuses") < src.index("parse_events(payload)")


# ── B. overlapping inbound messages ──────────────────────────────────────────

def test_inbound_row_ids_ride_the_debounce_buffer():
    from app.services import wa_native

    class _R:
        def __init__(self): self.kv, self.lists = {}, {}
        async def rpush(self, k, v): self.lists.setdefault(k, []).append(v)
        async def expire(self, k, s): pass
        async def incr(self, k):
            self.kv[k] = self.kv.get(k, 0) + 1
            return self.kv[k]
        async def get(self, k): return self.kv.get(k)
        async def lrange(self, k, a, b): return list(self.lists.get(k, []))
        async def delete(self, k): self.lists.pop(k, None)

    async def go():
        r = _R()
        await wa_native._enqueue(r, "254700", "first", None, "id-1")
        t = await wa_native._enqueue(r, "254700", "second", None, "id-2")
        return await wa_native._drain(r, "254700", t)
    text, media, ids = asyncio.run(go())
    assert text == "first\nsecond" and ids == ["id-1", "id-2"]
    # the ids travel: debounce → schedule_reply → _run_and_send → run_turn
    assert "inbound_ids=inbound_ids" in inspect.getsource(wa_native._reply_after_debounce)
    from app.agent import runtime
    assert "inbound_ids=inbound_ids" in inspect.getsource(runtime.schedule_reply)
    assert "inbound_ids=inbound_ids" in inspect.getsource(runtime._run_and_send)
    # every inbound row gets its id chosen before it is stored
    src = inspect.getsource(wa_native._ingest_guarded)
    assert "row_id = voice_id or uuid.uuid4()" in src and "message_id=row_id" in src


def test_history_excludes_the_rows_being_answered_and_notes_an_overlap():
    from app.agent import runtime
    src = inspect.getsource(runtime.run_turn)
    assert "exclude_ids=inbound_ids" in src
    assert "_answered_after(db, key, channel, inbound_ids)" in src
    assert "turn_notes.append(OVERLAP_NOTE)" in src
    assert "reply with NOTHING" in runtime.OVERLAP_NOTE
    hsrc = inspect.getsource(runtime._history)
    assert "Message.id.notin_(_ex)" in hsrc


def test_answered_after_reads_the_clocks_right():
    from app.agent import runtime
    import uuid
    t0 = datetime(2026, 11, 5, 19, 20, tzinfo=timezone.utc)
    answers = {"min": t0, "max": t0 + timedelta(seconds=35)}     # our reply came after msg₂

    class _R:
        def __init__(self, v): self.v = v
        def scalar(self): return self.v
    class _DB:
        def __init__(self): self.n = 0
        async def execute(self, q):
            self.n += 1
            return _R(answers["min"] if self.n == 1 else answers["max"])
    assert asyncio.run(runtime._answered_after(_DB(), "254700", "whatsapp", [str(uuid.uuid4())])) is True
    answers["max"] = t0 - timedelta(seconds=5)                  # reply before: a normal turn
    assert asyncio.run(runtime._answered_after(_DB(), "254700", "whatsapp", [str(uuid.uuid4())])) is False
    assert asyncio.run(runtime._answered_after(_DB(), "254700", "whatsapp", ["not-a-uuid"])) is False


# ── E. one voice for every composed message ──────────────────────────────────

def test_every_composer_speaks_as_a_continuation():
    from app.agent.composer import CONTINUATION_NOTE
    from app.services import actions, hub_events
    from app.jobs import cart_recovery
    from app.routers import admin
    assert "CONTINUATION_NOTE" in inspect.getsource(actions._compose_follow_up)
    assert "CONTINUATION_NOTE" in inspect.getsource(hub_events._compose_announcement)
    assert "CONTINUATION_NOTE" in inspect.getsource(cart_recovery._draft)
    assert "CONTINUATION_NOTE as _CONTINUATION" in inspect.getsource(admin.answer_through_neema)
    assert "No greeting" in CONTINUATION_NOTE and "last 24 hours" in CONTINUATION_NOTE
    assert "never 'just checking in'" in CONTINUATION_NOTE.lower()


def test_repeated_greetings_are_stripped_when_we_spoke_today():
    from app.agent.composer import strip_repeated_greeting as strip, recently_spoke
    assert strip("Good morning, Judas. There's no rush on our side — your quotation stands.",
                 recent=True) == "Judas, there's no rush on our side — your quotation stands."
    assert strip("Good morning Judas, your selection is 2 Aluminium Trays. Shall we go ahead?",
                 recent=True) == "Judas, your selection is 2 Aluminium Trays. Shall we go ahead?"
    assert strip("Jai Masih Ki, Pastor Emmanuel 🙏 I'm writing about the Cope.", recent=True) \
        .startswith("Pastor Emmanuel, I'm writing about the Cope")
    assert strip("Habari Willy, ulikuwa unaangalia Golden Communion Tray.", recent=True) \
        == "Willy, ulikuwa unaangalia Golden Communion Tray."
    assert strip("Good morning from Bethany House! Your trays shipped today.", recent=True) \
        == "Your trays shipped today."
    # a greeting after days of silence is natural, and stays
    kept = "Good morning, Judas. A week on, as you asked: shall we go ahead?"
    assert strip(kept, recent=False) == kept
    # no greeting → untouched; a greeting that IS the whole message → untouched
    assert strip("Your trays shipped today.", recent=True) == "Your trays shipped today."
    assert strip("Good morning, Judas.", recent=True) == "Good morning, Judas."
    now = datetime(2026, 11, 5, 9, 0, tzinfo=timezone.utc)
    assert recently_spoke(now - timedelta(hours=3), now=now)
    assert not recently_spoke(now - timedelta(hours=30), now=now)
    assert not recently_spoke(None)


# ── A. one check-in per purpose ──────────────────────────────────────────────

class _ConvDB:
    def __init__(self, conv, open_rows=None):
        self._conv, self._open = conv, list(open_rows or [])
        self.added, self.commits = [], 0
    async def execute(self, *a, **k):
        c, rows = self._conv, self._open
        return types.SimpleNamespace(scalar_one_or_none=lambda: c,
                                     scalars=lambda: types.SimpleNamespace(all=lambda: rows))
    def add(self, obj): self.added.append(obj)
    async def commit(self): self.commits += 1


def _ctx(db, **kw):
    from app.agent.tools import ToolContext
    return ToolContext(db=db, redis=None, wa_id="254712345678", **kw)


def test_check_in_purpose_is_read_from_the_call_or_the_reason():
    from app.agent.tools import check_in_about
    assert check_in_about({"about": "supplies", "reason": "x"}) == "supplies"
    assert check_in_about({"reason": "divai and cups will run out in two weeks"}) == "supplies"
    assert check_in_about({"reason": "the $335 quotation; friend collects or DHL to Juba"}) == "purchase_decision"
    assert check_in_about({"about": "delivery", "reason": "ready by Sunday"}) == "delivery"


def test_second_call_for_the_same_purpose_moves_the_one_check_in():
    from app.agent import tools
    conv = types.SimpleNamespace(id="c1")
    db = _ConvDB(conv)
    first = asyncio.run(tools._schedule_check_in(
        {"on_day": "thursday", "reason": "the $335 quotation — collect in Nairobi or DHL to Juba"},
        _ctx(db)))
    assert first["ok"] and first["already_booked"] is False and first["about"] == "purchase_decision"
    row = db.added[0]
    assert row.kind == "check_in" and row.reason.startswith("Customer-agreed check-in")
    # The same turn — or the next one re-reading the thread — books Thursday again.
    db2 = _ConvDB(conv, open_rows=[row])
    second = asyncio.run(tools._schedule_check_in(
        {"on_day": "thursday", "reason": "check in about the quotation"}, _ctx(db2)))
    assert second["already_booked"] is True and db2.added == []
    assert "already booked" in second["note"] and "do not book again" in second["note"]
    assert row.status == "planned"
    # A newer date for the same matter MOVES it (the customer's latest word wins).
    db3 = _ConvDB(conv, open_rows=[row])
    moved = asyncio.run(tools._schedule_check_in(
        {"on_day": "next week", "reason": "they now say next week"}, _ctx(db3)))
    assert moved["already_booked"] is True and "moved to" in moved["note"] and db3.added == []
    assert (row.due_at - datetime.now(timezone.utc)).days >= 6


def test_different_commitments_stay_separate_rows():
    from app.agent import tools
    conv = types.SimpleNamespace(id="c1")
    db = _ConvDB(conv)
    asyncio.run(tools._schedule_check_in(
        {"on_day": "thursday", "reason": "the $335 quotation"}, _ctx(db)))
    decision = db.added[0]
    db2 = _ConvDB(conv, open_rows=[decision])
    out = asyncio.run(tools._schedule_check_in(
        {"days_from_now": 14, "about": "supplies", "reason": "divai and cups run out then"},
        _ctx(db2)))
    assert out["already_booked"] is False and len(db2.added) == 1
    supplies = db2.added[0]
    assert supplies.kind == "replenishment" and supplies.reason.startswith("Supplies check-in")
    assert decision.kind == "check_in"


def test_legacy_replenishment_rows_count_as_the_purchase_decision():
    """Rows booked before purposes existed carry kind 'replenishment' and a
    'Customer-agreed check-in' reason: they are decision check-ins, so a new
    decision check-in updates them instead of adding a second."""
    from app.agent import tools
    conv = types.SimpleNamespace(id="c1")
    legacy = types.SimpleNamespace(kind="replenishment", status="planned", draft=None,
                                   due_at=datetime.now(timezone.utc) + timedelta(days=1),
                                   reason="Customer-agreed check-in (WhatsApp): the quotation")
    db = _ConvDB(conv, open_rows=[legacy])
    out = asyncio.run(tools._schedule_check_in(
        {"on_day": "thursday", "reason": "the quotation"}, _ctx(db)))
    assert out["already_booked"] is True and db.added == [] and legacy.kind == "check_in"


def test_the_tool_and_the_prompt_say_one_check_in_per_matter():
    from app.agent.tools import TOOLS
    from app.agent.prompt import build_system_prompt
    spec = next(t for t in TOOLS if t["name"] == "schedule_check_in")
    assert "ONE open check-in per customer per purpose" in spec["description"]
    assert "about" in spec["input_schema"]["properties"]
    flat = " ".join(build_system_prompt(country_iso="KE", currency="KES").split())
    assert "ONE check-in per matter" in flat
    assert "never book or promise it again" in flat


# ── the scheduler: one message per customer per tick; holds ──────────────────

def _scheduler(monkeypatch, actions_list, conv, deal, *, opted=False):
    from app.services import actions as act
    from tests._action_fakes import install
    install(monkeypatch)

    class _Rows:
        def scalars(self): return types.SimpleNamespace(all=lambda: list(actions_list))
        def scalar_one_or_none(self): return deal
    class _DB:
        async def execute(self, *a, **k): return _Rows()
        async def get(self, model, pk): return conv if model.__name__ == "Conversation" else deal
        async def commit(self): pass
        async def rollback(self): pass
    async def fake_window(db, c): return True
    monkeypatch.setattr("app.services.hub_events._within_window", fake_window)
    monkeypatch.setattr("app.services.hub_events.is_quiet_hours", lambda now=None: False)
    async def no_gate(db, d, c, in_window): return None
    monkeypatch.setattr(act, "needs_approval", no_gate)
    monkeypatch.setattr(settings, "agent_initiative", True, raising=False)
    async def compose(db, redis, c, reason): return f"About: {reason[:30]}"
    monkeypatch.setattr(act, "_compose_follow_up", compose)
    async def not_repeat(db, c, t): return False
    monkeypatch.setattr(act, "_repeats_earlier", not_repeat)
    async def opted_out(db, redis, c, **kw): return opted
    monkeypatch.setattr("app.services.intent.opted_out", opted_out)
    # the dispatcher reads the three-state form (slice 5, 2026-11-06)
    async def opt_out_state(db, redis, c): return "yes" if opted else "no"
    monkeypatch.setattr("app.services.intent.opt_out_state", opt_out_state)
    sent = []
    async def send(db, redis, c, text, action=None, **kw): sent.append((getattr(action, "kind", None), text))
    monkeypatch.setattr(act, "_send", send)
    return act, _DB(), sent


def _conv():
    from app.models.conversation import InterceptMode
    return types.SimpleNamespace(id="c1", channel="whatsapp", wa_id="254700000001",
                                 external_id=None, intercept_mode=InterceptMode.ai, person_id=None)


def test_three_due_rows_for_one_customer_become_one_message(monkeypatch):
    """Judas, Wednesday morning: a customer-promise row, a check-in row and a
    promise row all due at 08:00 — one message, the routine extras merged, a
    care row deferred to tomorrow morning."""
    now = datetime.now(timezone.utc)
    mk = lambda i, kind, reason: types.SimpleNamespace(   # noqa: E731
        id=f"a{i}", status="planned", due_at=now - timedelta(minutes=i), kind=kind,
        conversation_id="c1", deal_id=None, reason=reason, draft=None)
    rows = [mk(3, "customer_promise", "Customer said they'd respond (tomorrow)"),
            mk(2, "check_in", "Customer-agreed check-in (WhatsApp): the quotation"),
            mk(1, "follow_up", "Neema promised: confirm DHL to Juba"),
            mk(0, "fit_check", "Order BH-1 was delivered 6 days ago")]
    act, db, sent = _scheduler(monkeypatch, rows, _conv(), None)
    n = asyncio.run(act.process_due(db, None, now=now))
    assert n == 1 and len(sent) == 1 and sent[0][0] == "customer_promise"
    assert rows[1].status == "vetoed" and "merged" in rows[1].reason      # routine extras merged
    assert rows[2].status == "vetoed" and "merged" in rows[2].reason
    assert rows[3].status == "planned" and rows[3].due_at > now            # care waits for morning


def test_opted_out_customer_gets_no_routine_message(monkeypatch):
    now = datetime.now(timezone.utc)
    rows = [types.SimpleNamespace(id="a1", status="planned", due_at=now, kind="quote_follow_up",
                                  conversation_id="c1", deal_id=None,
                                  reason="Quote follow-up: Neema quoted …", draft="Shall I reserve it?"),
            types.SimpleNamespace(id="a2", status="planned", due_at=now, kind="fit_check",
                                  conversation_id="c1", deal_id=None,
                                  reason="Order BH-1 was delivered", draft=None)]
    act, db, sent = _scheduler(monkeypatch, rows, _conv(), None, opted=True)
    assert asyncio.run(act.process_due(db, None, now=now)) == 0 and sent == []
    assert rows[0].status == "vetoed" and "asked not to be messaged" in rows[0].reason
    assert rows[1].status == "needs_approval" and "asked not to be messaged" in rows[1].reason


def test_open_team_check_holds_sales_follow_ups(monkeypatch):
    """Pastor Emmanuel: the gold embroidery is with the workshop — the quote
    nudge is withdrawn and the promise row waits visibly for a person."""
    now = datetime.now(timezone.utc)
    deal = types.SimpleNamespace(id="d1", status="open", items_snapshot=[],
                                 next_action={"kind": "team_check", "item": "gold embroidery on the cope",
                                              "since": now.isoformat()})
    rows = [types.SimpleNamespace(id="a1", status="planned", due_at=now, kind="quote_follow_up",
                                  conversation_id="c1", deal_id="d1", reason="Quote follow-up", draft="x"),
            types.SimpleNamespace(id="a2", status="planned", due_at=now, kind="customer_promise",
                                  conversation_id="c1", deal_id="d1", reason="Customer said…", draft=None)]
    act, db, sent = _scheduler(monkeypatch, rows, _conv(), deal)
    assert asyncio.run(act.process_due(db, None, now=now)) == 0 and sent == []
    assert rows[0].status == "vetoed" and "team check open: gold embroidery" in rows[0].reason
    assert rows[1].status == "needs_approval" and "team still confirming: gold embroidery" in rows[1].reason


def test_deciding_customer_outside_the_window_waits_for_a_person(monkeypatch):
    """Judas, Thursday 18:00: the window is closed and no follow-up template is
    approved — the check-in parks for a person; the replenishment template is
    never borrowed."""
    now = datetime.now(timezone.utc)
    row = types.SimpleNamespace(id="a1", status="planned", due_at=now, kind="check_in",
                                conversation_id="c1", deal_id=None,
                                reason="Customer-agreed check-in (WhatsApp): the $335 quotation", draft=None)
    act, db, sent = _scheduler(monkeypatch, [row], _conv(), None)
    async def closed(db, c): return False
    monkeypatch.setattr("app.services.hub_events._within_window", closed)
    async def gate(db, d, c, in_window): return None if in_window else "outside the 24h messaging window"
    monkeypatch.setattr(act, "needs_approval", gate)
    monkeypatch.setattr(settings, "wa_event_template", "order_update", raising=False)
    monkeypatch.setattr(settings, "wa_followup_template", "", raising=False)
    tpl_calls = []
    async def fake_tpl(*a, **k):
        tpl_calls.append(a)
        return {"messages": [{"id": "w"}]}
    monkeypatch.setattr("app.services.messaging.send_wa_template", fake_tpl)
    assert asyncio.run(act.process_due(db, None, now=now)) == 0
    assert tpl_calls == [] and sent == []
    assert row.status == "needs_approval" and "no approved template for purpose 'check_in'" in row.reason


def test_a_colleagues_reply_withdraws_routine_nudges_and_closes_the_check():
    from app.services import conversation
    src = inspect.getsource(conversation.send_agent_reply)
    assert "clear_team_check(db, conv.id" in src and "withdraw_routine(db, conv.id" in src
    from app.routers import admin
    asrc = inspect.getsource(admin.answer_through_neema)
    assert "clear_team_check" in asrc and "withdraw_routine" in asrc


def test_withdraw_routine_leaves_promises_and_care_alone():
    from app.services.actions import withdraw_routine
    rows = [types.SimpleNamespace(kind="quote_follow_up", status="planned", reason="q"),
            types.SimpleNamespace(kind="follow_up", status="needs_approval", reason="p")]
    class _R:
        def scalars(self): return types.SimpleNamespace(all=lambda: rows)
    class _DB:
        def __init__(self): self.commits = 0
        async def execute(self, q): return _R()
        async def commit(self): self.commits += 1
    db = _DB()
    # the query names only the routine kinds — a check-in or a fit check is never withdrawn
    src = inspect.getsource(withdraw_routine)
    assert '("follow_up", "quote_follow_up", "buying_follow_up")' in src
    assert asyncio.run(withdraw_routine(db, "c1", why="a colleague replied")) == 2
    assert all(r.status == "vetoed" and "a colleague replied" in r.reason for r in rows) and db.commits == 1


# ── F. the open availability check as state ──────────────────────────────────

def test_team_check_state_is_read_and_expires():
    from app.services.deals import team_check_open
    now = datetime(2026, 11, 5, 12, 0, tzinfo=timezone.utc)
    fresh = types.SimpleNamespace(next_action={"kind": "team_check", "item": "gold embroidery",
                                               "since": (now - timedelta(days=1)).isoformat()})
    assert team_check_open(fresh, now=now) == "gold embroidery"
    stale = types.SimpleNamespace(next_action={"kind": "team_check", "item": "x",
                                               "since": (now - timedelta(days=8)).isoformat()})
    assert team_check_open(stale, now=now) is None
    assert team_check_open(types.SimpleNamespace(next_action={"kind": "follow_up"})) is None
    assert team_check_open(types.SimpleNamespace(next_action=None)) is None


def test_check_availability_records_the_check_and_forbids_closing_on_it():
    from app.agent import tools
    src = inspect.getsource(tools._check_availability)
    assert "open_team_check(ctx.db, conv, item)" in src
    assert "do NOT ask them to start, confirm or" in src and "pay for THIS item" in src
    assert '"team_check_open": True' in src


def test_prompt_no_longer_tells_her_to_close_on_an_unconfirmed_item():
    from app.agent.prompt import build_system_prompt
    flat = " ".join(build_system_prompt(country_iso="KE", currency="KES").split())
    assert "CONTINUE the sale meanwhile — colour, measurements, the other items on their list" in flat
    assert "the order itself; the team's answer arrives" not in flat
    assert "never ask them to start, confirm or pay for the item under confirmation" in flat


# ── G. opt-out ───────────────────────────────────────────────────────────────

def test_opt_out_is_recognised_in_our_customers_languages():
    from app.services.intent import is_opt_out
    yes = ["Please stop messaging me.", "stop texting me", "Don't message me again", "unsubscribe",
           "Remove my number please", "No more messages", "Acha kunitumia ujumbe", "usinitumie meseji",
           "Sitaki ujumbe tena", "Arrêtez de m'écrire svp", "Ne me contactez plus",
           "No me escriban más", "Pare de me mandar mensagens", "Bitte keine Nachrichten mehr",
           "मुझे मैसेज मत भेजें", "mujhe message mat bhejo"]
    for t in yes:
        assert is_opt_out(t), t
    no = ["Can you stop by the shop tomorrow?", "Stop! I love it — how much is the stole?",
          "message received, thanks", "I'll message you tomorrow", "Please send me more photos",
          "Not interested in the red one, do you have blue?",
          "stop " * 60]
    for t in no:
        assert not is_opt_out(t), t


def test_opt_out_acknowledgement_speaks_their_language():
    from app.services.intent import acknowledgement
    assert acknowledgement("Acha kunitumia ujumbe").startswith("Sawa")
    assert acknowledgement("Arrêtez de m'écrire").startswith("Entendu")
    assert acknowledgement("मुझे मैसेज मत भेजें").startswith("ठीक है")
    assert acknowledgement("please stop messaging me").startswith("Understood")


def test_opt_out_is_handled_at_the_door_once():
    from app.agent import runtime
    src = inspect.getsource(runtime.schedule_reply)
    assert "_intent.is_opt_out(text)" in src and "_handle_opt_out(" in src
    assert src.index("_intent.is_opt_out(text)") < src.index("closer_gate(")
    h = inspect.getsource(runtime._handle_opt_out)
    assert "record_opt_out(" in h and "withdraw_routine(" in h
    assert "if already:\n                return" in h                   # no second acknowledgement


def test_opt_out_is_durable_on_the_person_and_read_back(monkeypatch):
    from app.services import intent
    person = types.SimpleNamespace(state={})
    conv = types.SimpleNamespace(id="c1", person_id="p1", channel="whatsapp", wa_id="254700")
    added = []
    class _DB:
        async def get(self, model, pk): return person
        def add(self, row): added.append(row)
        async def commit(self): pass
        async def rollback(self): pass
    class _R:
        def __init__(self): self.kv = {}
        async def get(self, k): return self.kv.get(k)
        async def set(self, k, v, ex=None): self.kv[k] = v
    r = _R()
    asyncio.run(intent.record_opt_out(_DB(), r, conv, "please stop messaging me",
                                      channel="whatsapp", key="254700"))
    assert person.state["contact_preferences"]["opt_out"]["said"] == "please stop messaging me"
    assert added and "asked not to be messaged" in added[0].note
    assert asyncio.run(intent.opted_out(_DB(), r, conv)) is True
    # redis cold (a flush, another worker): the person's record is the truth
    assert asyncio.run(intent.opted_out(_DB(), _R(), conv)) is True
    assert asyncio.run(intent.opted_out(_DB(), None, types.SimpleNamespace(
        id="c2", person_id=None, channel="whatsapp", wa_id="1"))) is False


def test_every_unprompted_sender_checks_the_opt_out_and_stamps_its_rows():
    from app.jobs import cart_recovery, payment_followup
    from app.services import actions, hub_events
    for mod, fn in ((cart_recovery, cart_recovery._handle), (payment_followup, payment_followup._handle),
                    (hub_events, hub_events._celebrate)):
        src = inspect.getsource(fn)
        assert "opted_out(" in src, mod.__name__
    # the planners file rows (the dispatcher stamps); the hub celebration stamps its own
    assert "actions.plan(" in inspect.getsource(cart_recovery._handle)
    assert "actions.plan(" in inspect.getsource(payment_followup._handle)
    assert "_stamp" in inspect.getsource(hub_events._celebrate)
    assert "opt_out_state(db, redis, conv)" in inspect.getsource(actions.process_due)
    assert "ol.stamp(" in inspect.getsource(actions._send)
    # the event-driven and campaign paths the audit verification (2026-11-06)
    # found without the check: seasonal campaign, missed-call text, recording
    # notice, the comment-engagement DM
    from app.jobs import seasonal_outreach
    from app.services import missed_call, recording_notice
    from app.agent import runtime
    assert "opted_out(" in inspect.getsource(seasonal_outreach.run)
    assert "opted_out(" in inspect.getsource(missed_call._follow_up)
    assert "opted_out(" in inspect.getsource(recording_notice.send_for_call)
    assert "_comment_dm_allowed(" in inspect.getsource(runtime._run_comment_engage)


# ── H. the trace reads what the stamps say ───────────────────────────────────

def test_outreach_stamp_and_trace_origin_agree():
    from app.services import outreach_log as ol
    from app.jobs.outreach_trace import _origin
    m = types.SimpleNamespace(raw_meta=ol.stamp("actions", ol.PROMISE, action_id="a1", kind="check_in"),
                              sender=None, media_type=None, text="x", waba_msg_id="w")
    assert _origin(m) == "actions promise check_in"
    legacy = types.SimpleNamespace(raw_meta=None, sender=types.SimpleNamespace(value="ai"),
                                   media_type=None, text="[template orderupdate_category] replenishment on sent",
                                   waba_msg_id="w")
    assert _origin(legacy) == "template (legacy marker)"
