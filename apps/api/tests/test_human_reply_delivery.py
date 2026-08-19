"""Human replies must actually arrive — on every channel (owner, 2026-08-19).

The Mukami thread: an agent intercepted a Messenger conversation, typed a
reply, hit send — and nothing appeared. Two defects stacked:

  1. MISROUTED: her thread was opened by a Facebook comment funnel, so its
     newest inbound carries `comment_context` — and `_deliver_agent_reply`'s
     old rule (`has comment_context → comment edge`) sent the human's typed
     DM to the PUBLIC comment on the post instead of the DM they were typing
     in. Now: when a DM window is open, the DM is the door; the comment edge
     remains for the `facebook` channel (which IS the comment thread) and for
     commenters with no DM open at all (DMing them 400s — the original fix).
  2. SILENCED: when delivery fails, the endpoint answers 200 {ok:false,error}
     — and the client ignored it: no bubble, no toast, no clue. The client
     now surfaces the server's reason and restores the typed text (pinned at
     source below).

Also pinned: the duplicate handoff briefings (five in one thread — each a
full model turn) — one briefing per takeover, whoever schedules it.
"""
import asyncio
import types

import app.main  # noqa: F401
import app.services.conversation as convsvc
import app.services.meta_send as meta_send


def _conv(channel="messenger"):
    return types.SimpleNamespace(id="c1", channel=channel, wa_id=None,
                                 external_id="psid1")


def _wire(monkeypatch, *, ctx, window_mode):
    sent, commented = [], []

    async def _latest(db, cid):
        return types.SimpleNamespace(comment_context=ctx, waba_msg_id="cmt_9")
    monkeypatch.setattr(convsvc, "_latest_inbound", _latest)

    async def _win(db, conv):
        return {"mode": window_mode}
    monkeypatch.setattr(convsvc, "messaging_window", _win)

    async def _send(channel, recipient, text, **kw):
        sent.append((channel, recipient, text, kw))
        return None
    monkeypatch.setattr(convsvc, "send_to_channel", _send)

    async def _cmt(comment_id, text, channel=None, **kw):
        commented.append((comment_id, text, channel))
    monkeypatch.setattr(meta_send, "reply_to_comment", _cmt)
    return sent, commented


def test_an_open_dm_thread_gets_the_dm_even_when_comment_funnelled(monkeypatch):
    """The Mukami case: messenger thread, newest inbound is the mirrored
    comment, window OPEN — the human's reply belongs in the DM, never on the
    public post."""
    sent, commented = _wire(monkeypatch, ctx={"post_id": "p1"}, window_mode="open")
    asyncio.run(convsvc._deliver_agent_reply(object(), _conv("messenger"), "Yes we do have ropes"))
    assert sent and not commented
    assert sent[0][0] == "messenger" and sent[0][1] == "psid1"


def test_a_commenter_with_no_dm_open_still_gets_the_comment_reply(monkeypatch):
    """The original 500-fix survives: no DM window → the comment edge is the
    only door that works."""
    sent, commented = _wire(monkeypatch, ctx={"post_id": "p1"}, window_mode="closed")
    asyncio.run(convsvc._deliver_agent_reply(object(), _conv("instagram"), "Karibu!"))
    assert commented and not sent
    assert commented[0][0] == "cmt_9" and commented[0][2] == "instagram"


def test_the_facebook_channel_is_always_the_comment_thread(monkeypatch):
    sent, commented = _wire(monkeypatch, ctx=None, window_mode="open")
    asyncio.run(convsvc._deliver_agent_reply(object(), _conv("facebook"), "Thank you 🙏"))
    assert commented and not sent


def test_human_agent_tag_rides_when_the_window_needs_it(monkeypatch):
    sent, _ = _wire(monkeypatch, ctx=None, window_mode="human_agent")
    asyncio.run(convsvc._deliver_agent_reply(object(), _conv("messenger"), "hello"))
    assert sent[0][3].get("human_agent") is True


# ── the client surfaces delivery failure instead of swallowing it ────────────

def test_the_client_shows_a_failed_send_instead_of_losing_it():
    import os
    view = os.path.join(os.path.dirname(__file__), "..", "..", "web", "src",
                        "components", "views", "ConversationsView.tsx")
    s = open(view, encoding="utf-8").read()
    assert "res.ok === false" in s
    assert "throw new Error(res.error" in s
    assert "err?.message?.slice(0, 160)" in s          # the reason reaches the toast
    assert "setReplyText(text)" in s                    # the typed reply is never lost


# ── one briefing per takeover, whoever schedules it ──────────────────────────

class _Redis:
    def __init__(self):
        self.kv = {}

    async def set(self, k, v, nx=False, ex=None):
        if nx and k in self.kv:
            return None
        self.kv[k] = v
        return True

    def __getattr__(self, name):
        async def _noop(*a, **kw):
            return None
        return _noop


def test_rapid_reclicks_produce_one_briefing_not_five(monkeypatch):
    import app.database as database
    import app.agent.runtime as runtime
    import app.services.copilot as copilot

    conv = types.SimpleNamespace(id="c1", channel="messenger", wa_id=None,
                                 external_id="psid1", person_id=None)
    added = []

    class _Sess:
        async def __aenter__(self):
            return types.SimpleNamespace(
                get=_get, add=added.append, commit=_commit, execute=_exec)

        async def __aexit__(self, *a):
            return False

    async def _get(model, _id):
        return conv

    async def _commit():
        pass

    async def _exec(*a, **k):
        return types.SimpleNamespace(scalar_one_or_none=lambda: None,
                                     scalars=lambda: types.SimpleNamespace(all=lambda: []))
    monkeypatch.setattr(database, "AsyncSessionLocal", _Sess)

    turns = []

    async def _turn(*a, **kw):
        turns.append(1)
        return "- the sale stands at the Cincture Rope"
    monkeypatch.setattr(runtime, "run_turn", _turn)
    monkeypatch.setattr(runtime, "build_llm", lambda model=None: object())

    r = _Redis()
    asyncio.run(copilot._briefing(r, "c1"))
    asyncio.run(copilot._briefing(r, "c1"))            # the re-click
    asyncio.run(copilot._briefing(r, "c1"))            # and another
    assert len(turns) == 1, "duplicate briefings each burned a model turn"


def test_an_idempotent_intercept_reclick_never_schedules_a_briefing():
    import inspect
    from app.routers import admin
    src = inspect.getsource(admin.intercept)
    assert 'if not out.get("already")' in src
    assert "schedule_briefing" in src
