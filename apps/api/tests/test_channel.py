"""Unit tests for the channel-aware conversation resolver (no DB) — matches the
repo's FakeDB convention. The migration + ORM defaults + unique enforcement are
verified against a real Postgres separately. Requires Python 3.11.
"""
import asyncio
import types

# Import the full ORM registry so Conversation's relationships (Agent, Message,
# Intercept) resolve when a Conversation is instantiated.
import app.models.agent, app.models.message, app.models.intercept  # noqa: F401
import app.models.person, app.models.user  # noqa: F401
from app.services.channel import get_or_create_conversation
from app.models.conversation import Conversation


class _FakeDB:
    def __init__(self, existing=None):
        self._existing = existing
        self.added = []

    async def execute(self, stmt):
        return types.SimpleNamespace(scalar_one_or_none=lambda: self._existing)

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        pass


def test_creates_messenger_conversation_with_null_wa_id():
    db = _FakeDB(None)
    conv = asyncio.run(get_or_create_conversation(db, "messenger", "PSID_1", person_id="p1"))
    assert conv.channel == "messenger" and conv.external_id == "PSID_1"
    assert conv.wa_id is None and conv.person_id == "p1"
    assert db.added == [conv]


def test_whatsapp_wa_id_mirrors_external_id():
    db = _FakeDB(None)
    conv = asyncio.run(get_or_create_conversation(db, "whatsapp", "254712345678"))
    assert conv.wa_id == "254712345678" and conv.external_id == "254712345678"


def test_existing_conversation_is_reused_and_adopts_person():
    existing = Conversation(channel="messenger", external_id="PSID_2", wa_id=None)
    existing.person_id = None
    db = _FakeDB(existing)
    conv = asyncio.run(get_or_create_conversation(db, "messenger", "PSID_2", person_id="pX"))
    assert conv is existing and conv.person_id == "pX"
    assert db.added == []            # nothing created


def test_requires_external_id():
    db = _FakeDB(None)
    raised = False
    try:
        asyncio.run(get_or_create_conversation(db, "messenger", "   "))
    except ValueError:
        raised = True
    assert raised
