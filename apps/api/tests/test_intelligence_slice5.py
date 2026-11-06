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
    assert "database" not in agent_health.ACTIONABLE and "database" not in agent_health.AI_DOWN
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
    assert "gate" not in agent_health.AI_DOWN
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
