"""After 24 hours, the human route stays open — COMPLETELY (owner, 2026-08-19).

Priscilla's screenshot: the banner says "24h window closed — you can still
reply as a human agent for 5d 21h", and for TYPED TEXT that promise held (the
send path claims Meta's HUMAN_AGENT tag, good for 7 days). But two doors on
the same corridor were still locked:

  * a PHOTO or document sent by a person went out as messaging_type=RESPONSE —
    refused with (#10) once 24h passed, while the words beside it went through:
    half a reply;
  * APPROVING a held draft called send_to_channel with no tag at all — the
    very same words failed as an approval and succeeded when typed by hand.

Both now claim the window they are in. The tag stays human-only: the AI's own
send paths never set it, which is Meta's actual rule.
"""
import asyncio
import types

import app.main  # noqa: F401 — registers models
import app.services.meta_send as meta_send


def _capture(monkeypatch):
    sent = []

    async def _post(path, body, what, page_id=None):
        sent.append(body)
        return {}
    monkeypatch.setattr(meta_send, "_graph_post", _post)
    return sent


# ── the transport: media carries the tag exactly like text ───────────────────

def test_a_human_photo_after_24h_rides_the_human_agent_tag(monkeypatch):
    sent = _capture(monkeypatch)
    asyncio.run(meta_send.send_meta_media("psid1", "image", "https://x/y.jpg",
                                          caption="the blue set",
                                          human_agent=True))
    attach, caption = sent
    assert attach["messaging_type"] == "MESSAGE_TAG"
    assert attach["tag"] == "HUMAN_AGENT"
    # the caption follow-up must not fall back into the shut window
    assert caption["messaging_type"] == "MESSAGE_TAG" and caption["tag"] == "HUMAN_AGENT"


def test_inside_24h_media_stays_a_plain_response(monkeypatch):
    sent = _capture(monkeypatch)
    asyncio.run(meta_send.send_meta_media("psid1", "image", "https://x/y.jpg"))
    assert sent[0]["messaging_type"] == "RESPONSE" and "tag" not in sent[0]


def test_the_ai_send_paths_never_claim_the_tag():
    """Meta's rule: HUMAN_AGENT is for human agents. The AI's own senders must
    not be able to set it even by accident — their calls carry no human_agent
    argument at all."""
    import inspect
    import app.agent.tools as tools
    src = inspect.getsource(tools)
    # (`MsgSender.human_agent` row labels are fine — what must never appear is
    # the send-API argument itself)
    assert "human_agent=" not in src


# ── the two doors that were still locked ─────────────────────────────────────

def _conv(channel="messenger"):
    return types.SimpleNamespace(id="c1", channel=channel, wa_id=None,
                                 external_id="psid1", person_id=None)


def test_a_human_media_send_claims_the_window_it_is_in(monkeypatch):
    import app.services.conversation as convsvc
    calls = {}

    async def _win(db, conv):
        return {"mode": "human_agent"}
    monkeypatch.setattr(convsvc, "messaging_window", _win)

    async def _media(recipient, media_type, media_url, caption=None,
                     page_id=None, human_agent=False):
        calls["human_agent"] = human_agent
    monkeypatch.setattr(meta_send, "send_meta_media", _media)

    async def _page(channel, recipient):
        return "pg1"
    monkeypatch.setattr(meta_send, "page_of_contact", _page)

    class _DB:
        async def execute(self, *a, **k):
            return types.SimpleNamespace(scalar_one_or_none=_conv)

        def add(self, row): pass
        async def commit(self): pass
        async def refresh(self, row): pass

    agent = types.SimpleNamespace(id="a1", name="Priscilla")
    asyncio.run(convsvc.send_agent_media(
        _DB(), "c1", agent, "https://x/y.jpg", "image", None, None))
    assert calls["human_agent"] is True


def test_an_approved_draft_claims_the_window_too():
    import inspect
    import app.services.conversation as convsvc
    src = inspect.getsource(convsvc.approve_draft)
    assert 'human_agent=(win.get("mode") == "human_agent")' in src


def test_the_composer_says_whose_name_the_reply_goes_under():
    import os
    view = os.path.join(os.path.dirname(__file__), "..", "..", "web", "src",
                        "components", "views", "ConversationsView.tsx")
    s = open(view, encoding="utf-8").read()
    assert "goes out under your name (human agent)" in s
    # and the send button still only locks when the window is truly closed
    assert 'window24?.mode === "closed"' in s


# ── the ONE-TAP flow: a lapsed thread's reply is a tap away, not gone ────────
# (owner: "build the one-tap draft flow", 2026-08-19). Before this, the reply
# Neema composed for a lapsed thread survived only as a 220-char quote inside
# a flag note — the dashboard's draft card (which has the Approve button)
# never saw it, so a person had to retype what already existed.

class _WsRedis:
    def __init__(self):
        self.published = []

    async def publish(self, channel, payload):
        import json as _j
        self.published.append((channel, _j.loads(payload)))

    def __getattr__(self, name):
        async def _noop(*a, **kw):
            return None
        return _noop


def test_escalation_with_a_draft_feeds_the_one_tap_card(monkeypatch):
    import app.agent.runtime as runtime
    import app.database as database
    from app.models.conversation import InterceptMode
    from app.models.intercept import Intercept

    conv = types.SimpleNamespace(id="c9", intercept_mode=InterceptMode.ai)
    added = []

    class _Sess:
        async def __aenter__(self):
            return types.SimpleNamespace(
                execute=self._exec, add=added.append, commit=self._commit)

        async def __aexit__(self, *a):
            return False

        async def _exec(self, *a, **k):
            return types.SimpleNamespace(
                scalars=lambda: types.SimpleNamespace(first=lambda: conv))

        async def _commit(self):
            pass
    monkeypatch.setattr(database, "AsyncSessionLocal", _Sess)

    r = _WsRedis()
    ok = asyncio.run(runtime.escalate_to_human(
        "messenger", "psid9", "Outside Meta's 24-hour window — tap Approve.",
        draft="Karibu! The Cincture Rope is KES 1,500.", redis=r))
    assert ok and conv.intercept_mode == InterceptMode.human

    row = next(x for x in added if isinstance(x, Intercept))
    assert row.ai_reply_held == "Karibu! The Cincture Rope is KES 1,500."

    chans = dict(r.published)
    draft_evt = chans["ws:channel:c9"]
    assert draft_evt["type"] == "ai_draft_ready"
    assert draft_evt["draft"].startswith("Karibu!")
    ping = chans["ws:channel:agents:all"]
    assert ping["type"] == "draft_ready" and "one tap" in ping["title"]


def test_escalation_without_a_draft_stays_quiet_on_the_wire(monkeypatch):
    import app.agent.runtime as runtime
    import app.database as database
    from app.models.conversation import InterceptMode

    conv = types.SimpleNamespace(id="c9", intercept_mode=InterceptMode.ai)

    class _Sess:
        async def __aenter__(self):
            return types.SimpleNamespace(
                execute=self._exec, add=lambda row: None, commit=self._commit)

        async def __aexit__(self, *a):
            return False

        async def _exec(self, *a, **k):
            return types.SimpleNamespace(
                scalars=lambda: types.SimpleNamespace(first=lambda: conv))

        async def _commit(self):
            pass
    monkeypatch.setattr(database, "AsyncSessionLocal", _Sess)

    r = _WsRedis()
    asyncio.run(runtime.escalate_to_human("messenger", "psid9", "note", redis=r))
    assert r.published == []


def test_the_lapsed_window_catch_hands_over_the_whole_reply():
    import inspect
    import app.agent.runtime as runtime
    src = inspect.getsource(runtime._run_and_send_meta)
    assert "draft=(reply or None)" in src
    assert "[:220]" not in src, "the draft is whole now, not a quote in a note"


# ── order updates outside the 24h window go to a person ──────────────────────
# Meta sunset POST_PURCHASE_UPDATE on 2026-04-27 (error 100 on every send that
# carries it), so a Messenger order update after 24h was silently lost. Now it
# is treated like Instagram: a person is asked (they may use HUMAN_AGENT).

def test_send_to_channel_drops_any_tag_for_instagram(monkeypatch):
    sent = _capture(monkeypatch)

    async def _page(channel, recipient):
        return "pg1"
    monkeypatch.setattr(meta_send, "page_of_contact", _page)
    asyncio.run(meta_send.send_to_channel("instagram", "ig1", "hi", tag="SOME_TAG"))
    assert sent[0]["messaging_type"] == "RESPONSE" and "tag" not in sent[0]


def test_no_hub_path_sends_a_sunset_message_tag():
    import inspect
    import app.services.hub_events as hub
    src = inspect.getsource(hub)
    for dead in ("POST_PURCHASE_UPDATE", "CONFIRMED_EVENT_UPDATE", "ACCOUNT_UPDATE"):
        assert f'"{dead}"' not in src, f"{dead} was sunset by Meta on 2026-04-27"


def test_a_messenger_order_event_outside_the_window_asks_a_human(monkeypatch):
    import app.services.hub_events as hub
    import app.services.meta_send as ms

    sends, notified = [], []

    async def _send(*a, **kw):
        sends.append(kw)
    monkeypatch.setattr(ms, "send_to_channel", _send)

    async def _notify(redis, title, body, conv=None):
        notified.append(body)
    monkeypatch.setattr(hub, "_notify_agents", _notify)

    async def _compose(db, redis, conv, brief):
        return "Habari — your order has shipped."
    monkeypatch.setattr(hub, "_compose_announcement", _compose)
    monkeypatch.setattr(hub, "is_quiet_hours", lambda now=None: False)

    conv = types.SimpleNamespace(id="c1", channel="messenger", wa_id=None,
                                 external_id="psid1", contact_name=None)

    async def _win_closed(db, c):
        return False
    monkeypatch.setattr(hub, "_within_window", _win_closed)
    out = asyncio.run(hub._celebrate(None, None, conv,
                                     {"type": "order.shipped", "order_number": "ORD-1"}))
    assert out == {"handled": True, "sent": "notified_human"}
    assert not sends, "nothing automated may go out after 24h"
    assert notified and "only a person may message them" in notified[0]


def test_a_messenger_order_event_inside_the_window_sends_untagged(monkeypatch):
    import app.services.hub_events as hub
    import app.services.meta_send as ms
    import app.services.n8n_bridge as svc

    calls = []

    async def _send(channel, recipient, text, tag=None, **kw):
        calls.append({"channel": channel, "tag": tag, **kw})
    monkeypatch.setattr(ms, "send_to_channel", _send)

    async def _compose(db, redis, conv, brief):
        return "Habari — your order has shipped."
    monkeypatch.setattr(hub, "_compose_announcement", _compose)
    monkeypatch.setattr(hub, "is_quiet_hours", lambda now=None: False)

    async def _save(*a, **k):
        pass
    monkeypatch.setattr(svc, "save_outbound_channel_message", _save, raising=False)

    async def _win_open(db, c):
        return True
    monkeypatch.setattr(hub, "_within_window", _win_open)
    conv = types.SimpleNamespace(id="c1", channel="messenger", wa_id=None,
                                 external_id="psid1")
    out = asyncio.run(hub._celebrate(None, None, conv,
                                     {"type": "order.shipped", "order_number": "ORD-1"}))
    assert out == {"handled": True, "sent": "freeform"}
    assert calls[-1]["tag"] is None and not calls[-1].get("human_agent")


def test_an_instagram_order_event_outside_the_window_still_asks_a_human(monkeypatch):
    import app.services.hub_events as hub
    notified = []

    async def _notify(redis, title, body, conv=None):
        notified.append(title)
    monkeypatch.setattr(hub, "_notify_agents", _notify)
    monkeypatch.setattr(hub, "is_quiet_hours", lambda now=None: False)

    async def _win_closed(db, c):
        return False
    monkeypatch.setattr(hub, "_within_window", _win_closed)
    conv = types.SimpleNamespace(id="c1", channel="instagram", wa_id=None,
                                 external_id="ig1", contact_name=None)
    out = asyncio.run(hub._celebrate(None, None, conv,
                                     {"type": "order.shipped", "order_number": "ORD-2"}))
    assert out == {"handled": True, "sent": "notified_human"}
    assert notified, "nobody was told to send the news by hand"
