"""Unit tests for the outbound channel dispatcher (no network). Requires Python 3.11."""
import asyncio

from app.services import meta_send
from app.core.config import settings


def test_send_to_channel_routes_meta_channels(monkeypatch):
    sent = []

    async def fake_meta(rid, text):
        sent.append((rid, text))

    monkeypatch.setattr(meta_send, "send_meta_message", fake_meta)
    asyncio.run(meta_send.send_to_channel("messenger", "PSID_1", "hi"))
    asyncio.run(meta_send.send_to_channel("instagram", "IGSID_1", "yo"))
    assert sent == [("PSID_1", "hi"), ("IGSID_1", "yo")]


def test_send_to_channel_routes_whatsapp_and_strips_plus(monkeypatch):
    sent = []

    async def fake_waba(num, text):
        sent.append((num, text))

    import app.services.n8n_bridge as nb
    monkeypatch.setattr(nb, "_send_waba", fake_waba)
    asyncio.run(meta_send.send_to_channel("whatsapp", "+254712345678", "hello"))
    assert sent == [("254712345678", "hello")]   # '+' stripped for WABA


def test_send_meta_message_requires_page_token(monkeypatch):
    monkeypatch.setattr(settings, "meta_page_token", "", raising=False)
    raised = False
    try:
        asyncio.run(meta_send.send_meta_message("PSID_1", "hi"))
    except RuntimeError:
        raised = True
    assert raised
