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

    async def incr(self, k):
        self.kv[k] = int(self.kv.get(k, 0)) + 1
        return self.kv[k]

    async def expire(self, k, s):
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
                get=_get, add=added.append, commit=_commit, execute=_exec,
                delete=_delete)

        async def __aexit__(self, *a):
            return False

    async def _get(model, _id):
        return conv

    async def _commit():
        pass

    async def _exec(*a, **k):
        return types.SimpleNamespace(
            scalar_one_or_none=lambda: None, scalar=lambda: 0,
            scalars=lambda: types.SimpleNamespace(all=lambda: [], first=lambda: None))

    async def _delete(_row):
        pass
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


# ── the failing CREDENTIAL is named (owner's toast, 2026-08-19) ──────────────
# The live toast finally showed the truth: 'Meta send message failed (401):
# Error validating access token: The session has been invalidated because the
# user changed their password'. classify() saw '401' and called it "auth" —
# whose remedy says 'check ANTHROPIC_API_KEY'. A morning was lost to the wrong
# key. Channel credentials are now classified before AI credentials.

def test_a_dead_page_token_is_named_meta_never_ai_auth():
    from app.services.agent_health import ACTIONABLE, classify, describe
    exc = RuntimeError(
        'Meta send message failed (401): {"error":{"message":"Error validating '
        'access token: The session has been invalidated because the user '
        'changed their password"}}')
    assert classify(exc) == "meta"
    assert "meta" in ACTIONABLE
    line = describe({"kind": "meta", "count": 5, "error": str(exc)})
    assert "PAGE TOKEN" in line and "META_PAGE_TOKEN" in line
    assert "ANTHROPIC" not in line


def test_waba_send_failures_are_named_whatsapp():
    from app.services.agent_health import classify
    assert classify("WhatsApp template send failed (401): bad token") == "whatsapp"
    # and the AI key's own failures still classify as before
    assert classify("authentication_error: invalid x-api-key") == "auth"
    assert classify("Your credit balance is too low") == "credit"


def test_a_failed_human_send_reaches_the_health_signal():
    import inspect
    src = inspect.getsource(convsvc.send_agent_reply)
    assert "record_turn_failure" in src


def test_the_hourly_selfcheck_probes_every_page_token(monkeypatch):
    """A dead token is flagged by the watchdog within the hour — before a
    customer send has to fail first. Network blips never cry wolf."""
    import app.services.selfcheck as selfcheck
    from app.core.config import settings
    monkeypatch.setattr(settings, "meta_page_token", "tok_dead", raising=False)

    class _Resp:
        status_code = 401
        text = '{"error":{"type":"OAuthException","message":"Error validating access token"}}'

    class _Client:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, *a, **k): return _Resp()

    import httpx
    monkeypatch.setattr(httpx, "AsyncClient", _Client)
    r = _Redis()
    findings = asyncio.run(selfcheck._probe_meta_tokens(None, r))
    assert findings and "REJECTED by Graph (401)" in findings[0]
    assert "META_TOKEN_ROTATION" in findings[0]
    # and the health signal now carries kind=meta from the probe itself
    assert "agent:fail:count" in r.kv

    # a VALID token that is not a PAGE token (a System User's own token
    # answers /me but has no messages edge — every send 400s while a naive
    # probe stays green; today's second outage) must be flagged too
    class _SysUser(_Resp):
        status_code = 200
        text = '{"id":"122","name":"neema-bot"}'
    class _ClientSys(_Client):
        async def get(self, *a, **k): return _SysUser()
    monkeypatch.setattr(httpx, "AsyncClient", _ClientSys)
    findings = asyncio.run(selfcheck._probe_meta_tokens(None, _Redis()))
    assert findings and "NOT a Page token" in findings[0]
    assert "me/accounts" in findings[0]

    class _OK(_Resp):
        status_code = 200
        text = '{"id":"123","name":"Bethany House","category":"Religious Organization"}'
    class _ClientOK(_Client):
        async def get(self, *a, **k): return _OK()
    monkeypatch.setattr(httpx, "AsyncClient", _ClientOK)
    assert asyncio.run(selfcheck._probe_meta_tokens(None, _Redis())) == []


# ── a dying token is announced BEFORE it dies (owner's rotation, 2026-08-19) ─
# The replacement page token installed at 10:20 UTC carried
# `expires_at: 1787140800` — 12:00 UTC the same day. Every other check was
# green: valid, right page, right scopes. It would have stopped every send at
# lunchtime with no warning whatsoever. Graph knows the expiry; now so do we.

def _graph(handlers):
    """An httpx.AsyncClient stub that answers by URL."""
    class _R:
        def __init__(self, body, code=200):
            self.text, self.status_code = body, code

        def json(self):
            import json as _j
            return _j.loads(self.text)

    class _C:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False

        async def get(self, url, **kw):
            for frag, (body, code) in handlers.items():
                if frag in url:
                    return _R(body, code)
            raise AssertionError(f"unexpected Graph call: {url}")
    return _C


_PAGE_OK = '{"id":"1556733441275467","name":"Bethany House","category":"Religious Organization"}'


def _run_probe(monkeypatch, handlers):
    import httpx
    import app.services.selfcheck as selfcheck
    from app.core.config import settings
    monkeypatch.setattr(settings, "meta_page_token", "tok", raising=False)
    monkeypatch.setattr(settings, "meta_app_secret", "s3cr3t", raising=False)
    monkeypatch.setattr(httpx, "AsyncClient", _graph(handlers))
    return asyncio.run(selfcheck._probe_meta_tokens(None, _Redis()))


def test_a_token_expiring_today_is_flagged_hours_ahead(monkeypatch):
    import time
    soon = int(time.time()) + 5400                      # 90 minutes from now
    findings = _run_probe(monkeypatch, {
        "/me": (_PAGE_OK, 200),
        "debug_token": ('{"data":{"type":"PAGE","expires_at":%d,"is_valid":true}}' % soon, 200),
    })
    assert findings and "EXPIRES in 1h" in findings[0]
    assert "META_TOKEN_ROTATION" in findings[0]


def test_a_never_expiring_token_says_nothing(monkeypatch):
    assert _run_probe(monkeypatch, {
        "/me": (_PAGE_OK, 200),
        "debug_token": ('{"data":{"type":"PAGE","expires_at":0,"is_valid":true}}', 200),
    }) == []


def test_a_token_with_weeks_left_says_nothing(monkeypatch):
    import time
    later = int(time.time()) + 40 * 86400
    assert _run_probe(monkeypatch, {
        "/me": (_PAGE_OK, 200),
        "debug_token": ('{"data":{"type":"PAGE","expires_at":%d}}' % later, 200),
    }) == []


def test_a_graph_blip_on_the_expiry_call_never_cries_wolf(monkeypatch):
    assert _run_probe(monkeypatch, {
        "/me": (_PAGE_OK, 200),
        "debug_token": ("<html>502 Bad Gateway</html>", 502),
    }) == []


# ── an unset app secret is an OPEN webhook, not a quiet default ──────────────
# The box had no META_APP_SECRET line at all. Both webhook front doors skip
# X-Hub-Signature-256 verification when the secret is empty (a dev
# convenience), so every inbound payload was taken on trust for months —
# invisibly, because inbound "always worked".

def test_an_unset_app_secret_is_reported_as_an_open_webhook(monkeypatch):
    import app.services.selfcheck as selfcheck
    from app.core.config import settings
    monkeypatch.setattr(settings, "meta_app_secret", "", raising=False)
    monkeypatch.setattr(settings, "whatsapp_app_secret", "", raising=False)
    findings = asyncio.run(selfcheck._probe_webhook_signature(None, _Redis()))
    assert len(findings) == 2
    assert "META_APP_SECRET is UNSET" in findings[0] and "UNSIGNED" in findings[0]
    assert "WhatsApp" in findings[1]


def test_a_configured_secret_is_silent(monkeypatch):
    import app.services.selfcheck as selfcheck
    from app.core.config import settings
    monkeypatch.setattr(settings, "meta_app_secret", "s3cr3t", raising=False)
    monkeypatch.setattr(settings, "whatsapp_app_secret", "", raising=False)
    assert asyncio.run(selfcheck._probe_webhook_signature(None, _Redis())) == []


def test_the_probe_is_actually_registered(monkeypatch):
    import app.services.selfcheck as selfcheck
    names = [n for n, _ in selfcheck.PROBES]
    assert "webhook_signature" in names and "meta_tokens" in names


# ── the rotation is one command, not an archaeology dig ──────────────────────

def test_the_install_script_verifies_before_it_writes():
    import os
    p = os.path.join(os.path.dirname(__file__), "..", "..", "..",
                     "scripts", "meta-token-install.sh")
    s = open(p, encoding="utf-8").read()
    assert "read -rsp" in s                       # tokens never echo, never hit history
    assert "is NOT a page token" in s             # the page-kind trap
    assert "META_PAGE_TOKENS=" in s               # the map overrides the fallback
    assert "--force-recreate api" in s            # restart does not re-read .env
    assert "Number of the page to use" in s       # pick by number, not by id
