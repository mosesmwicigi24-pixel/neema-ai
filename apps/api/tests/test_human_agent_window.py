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
