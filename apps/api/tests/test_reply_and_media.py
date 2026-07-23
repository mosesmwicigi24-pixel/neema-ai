"""Reply-to (native WhatsApp quote) + Meta media send.

Pure/mock style, no DB. Requires Python 3.11 (SQLAlchemy models registered).
"""
import asyncio

import app.main  # noqa: F401
from app.services import n8n_bridge as nb
from app.services import meta_send as ms
from app.core.config import settings


class _Resp:
    is_success = True
    status_code = 200
    text = "{}"


class _Client:
    def __init__(self, sink):
        self._sink = sink
    async def __aenter__(self):
        return self
    async def __aexit__(self, *a):
        return False
    async def post(self, url, headers=None, json=None):
        self._sink.append(json)
        return _Resp()


# ── WhatsApp native reply-quote ───────────────────────────────────────────────

def test_send_waba_includes_reply_context(monkeypatch):
    monkeypatch.setattr(settings, "waba_token", "T", raising=False)
    monkeypatch.setattr(settings, "waba_phone_number_id", "PNID", raising=False)
    sent: list = []
    monkeypatch.setattr(nb.httpx, "AsyncClient", lambda *a, **k: _Client(sent))

    asyncio.run(nb._send_waba("254700", "hi", context_wamid="wamid.123"))
    assert sent[0]["context"] == {"message_id": "wamid.123"}
    assert sent[0]["text"]["body"] == "hi"

    sent.clear()
    asyncio.run(nb._send_waba("254700", "hi"))
    assert "context" not in sent[0]   # plain message when not a reply


def test_send_to_channel_whatsapp_passes_context(monkeypatch):
    captured: dict = {}

    async def fake_waba(num, text, context_wamid=None):
        captured.update(num=num, text=text, ctx=context_wamid)

    monkeypatch.setattr("app.services.n8n_bridge._send_waba", fake_waba)
    asyncio.run(ms.send_to_channel("whatsapp", "+254700", "hi", context_wamid="w.1"))
    assert captured["num"] == "254700" and captured["ctx"] == "w.1"


# ── Meta media send ───────────────────────────────────────────────────────────

def test_send_meta_media_builds_attachment_and_caption(monkeypatch):
    calls: list = []

    async def fake_graph(path, body, what, page_id=None):
        calls.append(body)
        return {}

    monkeypatch.setattr(ms, "_graph_post", fake_graph)
    asyncio.run(ms.send_meta_media("PSID", "image", "https://x/i.jpg", caption="Cross", page_id="P1"))

    # 1) the attachment, 2) the caption as a follow-up text message
    assert calls[0]["message"]["attachment"]["type"] == "image"
    assert calls[0]["message"]["attachment"]["payload"]["url"] == "https://x/i.jpg"
    assert calls[1]["message"]["text"] == "Cross"


def test_meta_media_type_mapping():
    assert ms._MEDIA_TYPE_TO_META["document"] == "file"
    assert ms._MEDIA_TYPE_TO_META["image"] == "image"


def test_send_meta_media_no_caption_sends_one_message(monkeypatch):
    calls: list = []

    async def fake_graph(path, body, what, page_id=None):
        calls.append(body)
        return {}

    monkeypatch.setattr(ms, "_graph_post", fake_graph)
    asyncio.run(ms.send_meta_media("PSID", "document", "https://x/f.pdf", page_id="P1"))
    assert len(calls) == 1 and calls[0]["message"]["attachment"]["type"] == "file"
