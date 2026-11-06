"""Slice 5 (2026-11-06): the model-independent reliability defects recorded
in UNFINISHED_REGISTER / verification pass 3b, each proven by behaviour.

  1. a database or reply-gate failure is classified by TYPE, never read as
     an AI-account failure that pauses the sweep for an hour;
  2. the opt-out read has three answers; every unprompted sender treats
     "unknown" as "do not send", and the dispatcher defers (never vetoes);
  3. the comment-DM gate fails closed on any read failure;
  4. the once-more draft re-checks its own token ceiling;
  5. the WhatsApp resolver guard shares the door's phone predicate;
  6. a bare question (no buying word) lifts a hold (W2-3, mutant M6).
"""
import asyncio
import inspect
import types

from app.services import agent_health, intent
from app.services import customer_state as cs


# ── 1. failure kinds by type ───────────────────────────────────────────────

def test_a_database_error_is_never_read_as_the_ai_account():
    from sqlalchemy.exc import OperationalError, ProgrammingError
    # messages that the text rules would read as auth / model
    exc = OperationalError("SELECT 1", {}, Exception("FATAL: permission denied for table persons"))
    assert agent_health.classify(exc) == "database"
    exc2 = ProgrammingError("SELECT 1", {}, Exception('relation "parishes" does not exist'))
    assert agent_health.classify(exc2) == "database"
    # the same words as plain text still classify as before (provider errors arrive as text too)
    assert agent_health.classify("permission denied: 401") == "auth"
    # verification pass 5 (finding 2): a database failure DOES stand the sweep
    # down and DOES need a person — see test_a_database_or_gate_failure_stands_the_sweep_down…
    assert "database" in agent_health._HUMAN and "gate" in agent_health._HUMAN


def test_a_driver_error_counts_as_database_by_module():
    class _Err(Exception):
        pass
    _Err.__module__ = "asyncpg.exceptions"
    assert agent_health.classify(_Err("current transaction is aborted")) == "database"
    _Err.__module__ = "somewhere.else"
    assert agent_health.classify(_Err("current transaction is aborted")) == "other"


def test_the_gate_s_own_error_is_named_gate_not_other():
    exc = RuntimeError("reply gate error: KeyError('figures')")
    assert agent_health.classify(exc) == "gate"
    assert "gate" in agent_health.AI_DOWN            # pass 5 finding 2
    # and the live turn reports the gate failure with exactly that prefix
    from app.agent import runtime as rt
    assert 'RuntimeError(f"reply gate error: {error}")' in inspect.getsource(rt._gate_failed_closed)


# ── 2. three-state opt-out read ────────────────────────────────────────────

class _BrokenDB:
    """A session whose reads fail — a database outage mid-tick."""
    async def get(self, model, pk):
        raise RuntimeError("connection is closed")

    async def execute(self, *a, **k):
        raise RuntimeError("connection is closed")


class _QuietRedis:
    async def get(self, k):
        return None

    async def set(self, *a, **k):
        return True


def _conv(**kw):
    base = dict(id="c1", person_id=None, channel="whatsapp", wa_id="254700000001", external_id=None)
    base.update(kw)
    return types.SimpleNamespace(**base)


def test_an_unreadable_preference_is_unknown_not_no():
    assert asyncio.run(intent.opt_out_state(_BrokenDB(), _QuietRedis(), _conv())) == intent.OPT_OUT_UNKNOWN
    assert asyncio.run(intent.opt_out_state(None, _QuietRedis(), _conv())) == intent.OPT_OUT_UNKNOWN
    # the yes/no view: a door keeps "no" (it only decides whether to re-acknowledge) …
    assert asyncio.run(intent.opted_out(_BrokenDB(), _QuietRedis(), _conv())) is False
    # … an unprompted sender gets "yes": nothing goes out on a guess
    assert asyncio.run(intent.opted_out(_BrokenDB(), _QuietRedis(), _conv(), fail_closed=True)) is True
    assert asyncio.run(intent.opted_out(None, _QuietRedis(), _conv(), fail_closed=True)) is True


def test_a_readable_no_is_still_no_for_a_sender(monkeypatch):
    from app.services import identity

    async def _none(db, channel, external_id):
        return None
    monkeypatch.setattr(identity, "_select_identity", _none)

    class _DB:
        async def get(self, model, pk):
            return None
    assert asyncio.run(intent.opt_out_state(_DB(), _QuietRedis(), _conv())) == intent.OPT_OUT_NO
    assert asyncio.run(intent.opted_out(_DB(), _QuietRedis(), _conv(), fail_closed=True)) is False


def test_every_unprompted_sender_reads_the_opt_out_fail_closed():
    """The senders that message a customer without a prompt: each either
    passes fail_closed=True or reads the three-state and handles unknown."""
    from app.jobs import cart_recovery, seasonal_outreach, payment_followup
    from app.services import actions, reply_sweeper, hub_events, missed_call, recording_notice
    for mod, needle in [
        (cart_recovery, "opted_out(db, redis, conv, fail_closed=True)"),
        (seasonal_outreach, 'opted_out(db, redis, row["conv"], fail_closed=True)'),
        (payment_followup, "opted_out(_db, redis, conv, fail_closed=True)"),
        (reply_sweeper, "_opted_out(db, redis, sib, fail_closed=True)"),
        (hub_events, "opted_out(db, redis, conv, fail_closed=True)"),
        (missed_call, "opted_out(db, redis, conv, fail_closed=True)"),
        (recording_notice, "opted_out(db, redis, conv, fail_closed=True)"),
        (actions, "opt_out_state(db, redis, conv)"),
    ]:
        assert needle in inspect.getsource(mod), mod.__name__


def test_cart_recovery_skips_the_nudge_when_the_preference_cannot_be_read(monkeypatch):
    from app.jobs import cart_recovery

    class _Sess:
        async def __aenter__(self):
            return _BrokenDB()

        async def __aexit__(self, *a):
            return False
    monkeypatch.setattr(cart_recovery, "AsyncSessionLocal", lambda: _Sess())
    row = {"conv": _conv(), "to": "254700000001", "items": [], "total": 0}
    res = asyncio.run(cart_recovery._handle(_QuietRedis(), row, send=True))
    assert res["sent"] is False and res["skipped"] == "customer asked not to be messaged"

    # and when no session can be opened at all (the wrapper's own except)
    def _no_session():
        raise RuntimeError("pool exhausted")
    monkeypatch.setattr(cart_recovery, "AsyncSessionLocal", _no_session)
    res = asyncio.run(cart_recovery._handle(_QuietRedis(), row, send=True))
    assert res["sent"] is False and res["skipped"] == "customer asked not to be messaged"


def test_the_dispatcher_defers_a_row_it_cannot_read_the_preference_for(monkeypatch):
    """Behaviour through process_due: the opt-out read fails, the row is
    neither sent nor vetoed nor parked — it stays planned for the next tick."""
    from tests import _action_fakes
    from tests.test_cost_circuit_breaker import _action_world
    from app.services import identity
    _action_fakes.install(monkeypatch)            # the breaker file's autouse fixture
    actions, db, r, action, composed, sent_out = _action_world(monkeypatch, tries_burned=0)

    async def _boom(db, channel, external_id):
        raise RuntimeError("connection is closed")
    monkeypatch.setattr(identity, "_select_identity", _boom)
    done = asyncio.run(actions.process_due(db, r))
    assert done == 0 and not composed and not sent_out
    assert action.status == "planned" and "not be messaged" not in (action.reason or "")


# ── 3. the comment-DM gate ─────────────────────────────────────────────────

def test_the_comment_dm_gate_fails_closed_on_any_read_failure(monkeypatch):
    from app.agent import runtime as rt
    import app.database as database

    class _Sess:
        def __init__(self, db):
            self._db = db

        async def __aenter__(self):
            return self._db

        async def __aexit__(self, *a):
            return False

    # a query error → no DM
    monkeypatch.setattr(database, "AsyncSessionLocal", lambda: _Sess(_BrokenDB()))
    assert asyncio.run(rt._comment_dm_allowed(_QuietRedis(), "messenger", "PSID_9")) is False

    # a session error → no DM
    def _no_session():
        raise RuntimeError("pool exhausted")
    monkeypatch.setattr(database, "AsyncSessionLocal", _no_session)
    assert asyncio.run(rt._comment_dm_allowed(_QuietRedis(), "messenger", "PSID_9")) is False

    # a readable "no" → DM allowed
    from app.services import identity

    async def _none(db, channel, external_id):
        return None
    monkeypatch.setattr(identity, "_select_identity", _none)

    class _DB:
        async def get(self, model, pk):
            return None
    monkeypatch.setattr(database, "AsyncSessionLocal", lambda: _Sess(_DB()))
    assert asyncio.run(rt._comment_dm_allowed(_QuietRedis(), "messenger", "PSID_9")) is True

    # and the comment flow sends the DM only through this gate
    src = inspect.getsource(rt._run_comment_engage)
    assert "if not await _comment_dm_allowed(redis, channel, ext):" in src
    assert src.index("_comment_dm_allowed(") < src.index("await send_private_reply(")


# ── 4. the once-more draft re-checks its own ceiling ───────────────────────

def test_the_once_more_draft_is_cut_to_a_whole_sentence_when_it_hits_the_ceiling():
    from app.agent import runtime as rt

    class _LLM:
        def __init__(self, text, stop):
            self._r = types.SimpleNamespace(text=text, stop_reason=stop)

        async def complete(self, **kw):
            return self._r

    msgs = [{"role": "user", "content": "how much is the stole"}]
    cut = asyncio.run(rt._reply_in_words(_LLM("The Double sided stole is KES 4,000. It comes in", "max_tokens"), [], msgs, []))
    assert cut == "The Double sided stole is KES 4,000."
    whole = asyncio.run(rt._reply_in_words(_LLM("The Double sided stole is KES 4,000. It comes in", "end_turn"), [], msgs, []))
    assert whole == "The Double sided stole is KES 4,000. It comes in"
    # nothing to keep: the draft as written (the settle helper's "kept")
    kept = asyncio.run(rt._reply_in_words(_LLM("The Double sided stole is KES 4,000 and it", "max_tokens"), [], msgs, []))
    assert kept == "The Double sided stole is KES 4,000 and it"


# ── 5. the resolver guard shares the door's phone predicate ────────────────

def test_the_opt_out_resolver_uses_the_door_s_phone_predicate(monkeypatch):
    from app.services import identity

    made = []

    async def recorder(db, channel, external_id, **kw):
        made.append((channel, external_id))
        return types.SimpleNamespace(person_id="p1")
    monkeypatch.setattr(identity, "resolve_or_create_person", recorder)
    monkeypatch.setattr("app.services.intent.flag_modified", lambda *a, **k: None, raising=False)

    class _DB:
        async def get(self, model, pk):
            return None

        def add(self, o):
            pass

        async def commit(self):
            pass

        async def rollback(self):
            pass

    def _run(key):
        made.clear()
        conv = _conv(wa_id=key)
        asyncio.run(intent.record_opt_out(_DB(), _QuietRedis(), conv, "stop", channel="whatsapp", key=key))
        return list(made)

    assert _run("+254700000001") == [("whatsapp", "254700000001")]   # a "+" resolves, normalised
    assert _run("254700000001") == [("whatsapp", "254700000001")]
    assert _run("web_abc123") == []                                      # a web visitor never does
    assert _run("12345678901234567") == []                               # a 17-digit Meta id never does


# ── 6. a bare question lifts a hold (W2-3, mutant M6) ──────────────────────

def test_a_bare_question_with_no_buying_word_lifts_a_hold():
    """Verification pass 4: the earlier test's question was also a buying
    signal. "Are you there?" carries none (cooling._BUY_RE has no match), so
    only the "?" branch can lift this hold."""
    from app.agent.cooling import buying_signal
    assert not buying_signal("Are you there?")
    assert cs._buying_message("Are you there?") and not cs._buying_message("Are you there")

    class _DB:
        async def commit(self):
            pass
    deal = types.SimpleNamespace(next_action={"kind": "follow_up", "hold": {"until": "2026-11-13T07:00:00", "said": "needs_time"}},
                                 blocking="Asked for time — until 13 Nov")
    conv = types.SimpleNamespace(person_id=None)
    changed = asyncio.run(cs.apply(_DB(), conv, deal, {"customer_said": "none"}, source="floor",
                                   inbound_text="Are you there?"))
    assert changed.get("hold_cleared") is True
    assert "hold" not in (deal.next_action or {}) and deal.blocking is None


# ── verification pass 5 repairs ────────────────────────────────────────────

def test_the_once_more_draft_is_kept_when_the_dropped_tail_carried_an_answer():
    """Pass 5 finding 1: cutting "…It costs KES 4," would drop the price the
    gate would otherwise hold; the retry goes out as written for the gate."""
    from app.agent import runtime as rt

    class _LLM:
        def __init__(self, text, stop):
            self._r = types.SimpleNamespace(text=text, stop_reason=stop)

        async def complete(self, **kw):
            return self._r
    msgs = [{"role": "user", "content": "how much is the stole"}]
    out = asyncio.run(rt._reply_in_words(_LLM("The stole comes in blue and gold. It costs KES 4,", "max_tokens"), [], msgs, []))
    assert out == "The stole comes in blue and gold. It costs KES 4,"
    out2 = asyncio.run(rt._reply_in_words(_LLM("The stole is KES 4,000. Shall I reserve one? Also we", "max_tokens"), [], msgs, []))
    assert out2 == "The stole is KES 4,000. Shall I reserve one?"


def test_a_database_or_gate_failure_stands_the_sweep_down_and_needs_a_person():
    """Pass 5 finding 2: a persistent database or gate failure must stand the
    missed-reply sweep down (AI_DOWN) and read as needing a person (ACTIONABLE),
    and a completed turn clears it like the other actionable kinds."""
    import json

    class _R:
        def __init__(self, kind):
            self.kv = {"agent:fail:count": "3", "agent:fail:last": json.dumps({"kind": kind})}
            self.deleted = []

        async def get(self, k):
            return self.kv.get(k)

        async def delete(self, k):
            self.deleted.append(k)
    for kind in ("database", "gate"):
        assert kind in agent_health.AI_DOWN and kind in agent_health.ACTIONABLE
        assert asyncio.run(agent_health.ai_down(_R(kind))) == kind
        r = _R(kind)
        assert asyncio.run(agent_health.record_turn_success(r)) is True and len(r.deleted) == 2
    assert asyncio.run(agent_health.ai_down(_R("other"))) is None


def test_psycopg_errors_count_as_database_too():
    class _Err(Exception):
        pass
    for mod in ("psycopg.errors", "psycopg2.errors", "asyncpg.exceptions"):
        _Err.__module__ = mod
        assert agent_health.classify(_Err("permission denied")) == "database", mod


def test_the_dispatcher_s_deferral_is_counted_rolled_back_and_parks_after_three(monkeypatch):
    """Pass 5 finding 4: the row stays due (not re-dued), the try is counted,
    the aborted session is rolled back before the next row, and the fourth
    unreadable tick parks the row for a person."""
    from tests import _action_fakes
    from tests.test_cost_circuit_breaker import _action_world
    from app.services import identity
    _action_fakes.install(monkeypatch)

    async def _boom(db, channel, external_id):
        raise RuntimeError("connection is closed")

    actions, db, r, action, composed, sent_out = _action_world(monkeypatch, tries_burned=0)
    monkeypatch.setattr(identity, "_select_identity", _boom)   # after the world's own "no" patch
    rolled = []

    async def _rollback():
        rolled.append(1)
    db.rollback = _rollback
    due_before = action.due_at
    assert asyncio.run(actions.process_due(db, r)) == 0
    assert action.status == "planned" and action.due_at == due_before      # kept due for the next tick
    assert r.kv["actions:tries:7"] == 1 and rolled == [1]                 # counted, session cleaned
    assert not composed and not sent_out

    actions, db, r, action, composed, sent_out = _action_world(monkeypatch, tries_burned=3)
    monkeypatch.setattr(identity, "_select_identity", _boom)
    assert asyncio.run(actions.process_due(db, r)) == 0
    assert action.status == "needs_approval" and "could not be read" in action.reason
    assert not composed and not sent_out


class _RaisingSess:
    """A session factory whose session raises on every read."""
    def __call__(self):
        return self

    async def __aenter__(self):
        return _BrokenDB()

    async def __aexit__(self, *a):
        return False


def test_payment_follow_up_skips_when_the_preference_cannot_be_read(monkeypatch):
    from app.jobs import payment_followup
    monkeypatch.setattr(payment_followup, "AsyncSessionLocal", _RaisingSess())

    # one customer with one order still due a reminder; the opt-out read
    # raises before any write
    order = types.SimpleNamespace(id=1, hub_order_id="o1", hub_order_number="BH-1", hub_total=1000, subtotal=1000)
    group = {"conv": _conv(), "to": "254700000001", "orders": [order]}
    res = asyncio.run(payment_followup._handle(_QuietRedis(), group, send=True, write=True))
    assert res["sent"] is False and res["skipped"] == "customer asked not to be messaged"   # the read's own fail-closed

    # and when no session can be opened at all: the surrounding except skips too
    class _NoSess:
        def __call__(self):
            return self

        async def __aenter__(self):
            raise RuntimeError("pool exhausted")

        async def __aexit__(self, *a):
            return False
    monkeypatch.setattr(payment_followup, "AsyncSessionLocal", _NoSess())
    res = asyncio.run(payment_followup._handle(_QuietRedis(), group, send=True, write=True))
    assert res["sent"] is False and "could not be read" in (res["skipped"] or "")


def test_seasonal_outreach_drops_a_row_whose_preference_cannot_be_read(monkeypatch):
    """The seasonal loop keeps only rows whose read answered; a raising read
    (the surrounding except) drops the row instead of keeping it (pass 5 #3)."""
    from app.jobs import seasonal_outreach as so
    src = inspect.getsource(so.run)
    # the except branch continues (drops the row) — it used to `pass` into kept.append
    i = src.index('opted_out(db, redis, row["conv"], fail_closed=True)')
    tail = src[i:i + 600]
    assert "except Exception as exc:" in tail and tail.index("continue", tail.index("except Exception as exc:")) < tail.index("kept.append(row)")


def test_missed_call_and_recording_notice_skip_on_an_unreadable_preference():
    from app.services import missed_call, recording_notice
    src = inspect.getsource(missed_call._follow_up)
    j = src.index("except Exception as exc:", src.index("opted_out(db, redis, conv, fail_closed=True)"))
    import re
    before_return = src[j:j + 400].split("return False")[0]
    assert "return False" in src[j:j + 400] and not re.search(r"^\s+pass\s*$", before_return, re.M)
    src = inspect.getsource(recording_notice.send_for_call)
    j = src.index("except Exception as exc:", src.index("opted_out(db, redis, conv, fail_closed=True)"))
    assert "return OPTED_OUT" in src[j:j + 400]


def test_the_complaint_dm_goes_through_the_same_gate():
    """Pass 5 finding 5: the private message after a serious complaint is a
    DM too, and must pass `_comment_dm_allowed` before it is sent."""
    from app.agent import runtime as rt
    src = inspect.getsource(rt._run_comment_engage)
    assert "if severity >= 2 and await _comment_dm_allowed(redis, channel, ext):" in src
    assert src.index("_comment_dm_allowed(redis, channel, ext):\n                    private_sent") < src.index("_private_complaint_message(")


def test_a_formatted_number_resolves_to_one_person_and_one_redis_key(monkeypatch, caplog):
    """Pass 5 findings 7 and 8: "+254 700-000 001" resolves as the digits the
    door stores, the redis key is the same digits, and a key that cannot
    resolve logs "redis only"."""
    import logging
    from app.services import identity

    made = []

    async def recorder(db, channel, external_id, **kw):
        made.append((channel, external_id))
        return types.SimpleNamespace(person_id="p1")
    monkeypatch.setattr(identity, "resolve_or_create_person", recorder)
    monkeypatch.setattr("app.services.intent.flag_modified", lambda *a, **k: None, raising=False)

    class _DB:
        async def get(self, model, pk):
            return None

        def add(self, o):
            pass

        async def commit(self):
            pass

        async def rollback(self):
            pass

    class _R:
        def __init__(self):
            self.keys = []

        async def set(self, k, v, ex=None):
            self.keys.append(k)

    r = _R()
    conv = _conv(wa_id="+254 700-000 001")
    asyncio.run(intent.record_opt_out(_DB(), r, conv, "stop", channel="whatsapp", key="+254 700-000 001"))
    assert made == [("whatsapp", "254700000001")]
    assert r.keys == ["agent:optout:whatsapp:254700000001"]

    made.clear()
    with caplog.at_level(logging.INFO, logger="neema.intent"):
        caplog.clear()
        asyncio.run(intent.record_opt_out(_DB(), _R(), _conv(wa_id="web_abc123"), "stop", channel="whatsapp", key="web_abc123"))
    assert made == [] and any("redis only" in rec.getMessage() for rec in caplog.records)
