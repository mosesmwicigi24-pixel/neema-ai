"""The outage catch-up answers what the outage silenced — and nothing else.

After the 2026-08-19 page-token outage, two backlogs existed with no automatic
path back:

  * DM threads whose 3-strike counters (the sweeper's cost bound) were burnt
    on a dead token — with the counters alive in redis for 2 days, the sweeper
    re-escalated instead of retrying, forever bouncing "Flagged → Released".
  * comment threads, which are answered on capture and never swept: a comment
    whose reply 401'd simply stayed unanswered.

python -m app.tools.catchup clears both, through the system's own paths (the
sweeper for DMs, the engage worker for comments) so every existing guard —
intent gate, budget breaker, pause, window — applies unchanged.
"""
import asyncio
import types
from datetime import datetime, timedelta, timezone

import app.main  # noqa: F401 — registers models
from app.tools import catchup


# ── strike clearing ──────────────────────────────────────────────────────────

class _Redis:
    def __init__(self, keys=()):
        self.kv = {k: "5" for k in keys}

    async def scan_iter(self, match=None, count=None):
        import fnmatch
        for k in list(self.kv):
            if fnmatch.fnmatch(k, match or "*"):
                yield k

    async def delete(self, k):
        self.kv.pop(k, None)


def test_the_burnt_strike_counters_are_cleared_locks_too():
    r = _Redis(["agent:missed:tries:m1", "agent:missed:tries:m2",
                "agent:missed:lock:messenger:psid9", "other:key"])
    n = asyncio.run(catchup._clear_strikes(r))
    assert n == 3
    assert list(r.kv) == ["other:key"], "an unrelated key was deleted"


# ── flag-escalation release ──────────────────────────────────────────────────

class _Res:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return types.SimpleNamespace(all=lambda: self._rows, first=lambda: (self._rows or [None])[0])

    def all(self):
        return self._rows


class _DB:
    def __init__(self, rows):
        self._rows, self.commits = rows, 0

    async def execute(self, *a, **k):
        return _Res(self._rows)

    async def commit(self):
        self.commits += 1


def test_only_unassigned_human_threads_are_released():
    """The query itself excludes picked-up and paused threads; what it returns
    is exactly what flips back to ai."""
    from app.models.conversation import InterceptMode
    flagged = types.SimpleNamespace(intercept_mode=InterceptMode.human,
                                    assigned_agent_id=None)
    db = _DB([flagged])
    n = asyncio.run(catchup._release_flag_escalations(db))
    assert n == 1 and flagged.intercept_mode == InterceptMode.ai and db.commits == 1
    # the SQL is pinned at source: escalations never assign, pickups always do
    import inspect
    src = inspect.getsource(catchup._release_flag_escalations)
    assert "assigned_agent_id.is_(None)" in src
    assert "InterceptMode.human" in src


# ── unanswered-comment selection ─────────────────────────────────────────────

def _msg(cid, conv_id="c1", direction="inbound", reply_to=None, channel="facebook"):
    from app.models.message import MsgDirection
    return types.SimpleNamespace(
        id=f"m-{cid}", channel=channel, conversation_id=conv_id,
        external_id="u1", waba_msg_id=cid if direction == "inbound" else None,
        direction=MsgDirection.inbound if direction == "inbound" else MsgDirection.outbound,
        comment_context=({"reply_to": reply_to} if reply_to
                         else {"post_id": "p1", "title": "Cassock reel"}),
        text="How much?", created_at=datetime.now(timezone.utc) - timedelta(hours=2))


def test_a_replied_comment_is_left_alone_an_unanswered_one_is_returned():
    conv = types.SimpleNamespace(id="c1")
    answered = _msg("cmt_1")
    unanswered = _msg("cmt_2")
    reply = _msg("x", direction="outbound", reply_to="cmt_1")

    class _Db:
        def __init__(self):
            self.calls = 0

        async def execute(self, *a, **k):
            self.calls += 1
            if self.calls == 1:                     # the inbound query
                return _Res([(answered, conv), (unanswered, conv)])
            return _Res([reply])                    # the outbound replies
    out = asyncio.run(catchup._pending_comments(_Db()))
    assert [m.waba_msg_id for m, _ in out] == ["cmt_2"]


def test_the_engage_path_is_the_normal_one(monkeypatch):
    """The catch-up must not invent a send path — it rebuilds the webhook's
    comment dict and calls the same worker, so intent gate + budget apply."""
    import app.agent.runtime as runtime
    calls = []

    async def _engage(redis, channel, comment, own_pages):
        calls.append((channel, comment))
    monkeypatch.setattr(runtime, "_run_comment_engage", _engage)
    monkeypatch.setattr(catchup.asyncio, "sleep", _noop_sleep)

    class _Sess:
        async def __aenter__(self):
            return _DB([])

        async def __aexit__(self, *a):
            return False
    import app.database as database
    monkeypatch.setattr(database, "AsyncSessionLocal", _Sess)

    conv = types.SimpleNamespace(id="c1")
    n = asyncio.run(catchup._answer_comments(None, [(_msg("cmt_9"), conv)]))
    assert n == 1 and len(calls) == 1
    ch, c = calls[0]
    assert ch == "facebook"
    assert c["comment_id"] == "cmt_9" and c["post_id"] == "p1"
    assert c["from_id"] == "u1" and c["post_context"]["title"] == "Cassock reel"


async def _noop_sleep(_s):
    return None


def test_the_vps_wrapper_exists_and_uses_the_module():
    import os
    p = os.path.join(os.path.dirname(__file__), "..", "..", "..",
                     "scripts", "catchup-unanswered.sh")
    s = open(p, encoding="utf-8").read()
    assert "python -m app.tools.catchup" in s
    assert "docker-compose.vps.yml" in s
