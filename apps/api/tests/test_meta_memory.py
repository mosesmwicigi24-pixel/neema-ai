"""Meta-channel memory: a Messenger/IG/Facebook customer's facts live on their
PERSON (persons.state) — they have no User row — so a repeat social buyer is
remembered across conversations and the memory survives a WhatsApp merge.
"""
import asyncio
import uuid
from types import SimpleNamespace

from app.agent import memory as mem
from app.models.person import Person

PSID = "25583188007957753"


class _FakeDB:
    """Serves the Identity lookup, hands back a real Person, then makes the
    OrderEvent query blow up (best-effort path must swallow it)."""
    def __init__(self, ident, person):
        self._ident = ident
        self._person = person
        self.commits = 0
        self._calls = 0

    async def execute(self, stmt):
        self._calls += 1
        if self._calls == 1:                        # the Identity select
            return SimpleNamespace(scalar_one_or_none=lambda: self._ident)
        raise RuntimeError("orders query — must be swallowed")

    async def get(self, model, pk):
        return self._person

    async def commit(self):
        self.commits += 1


def _setup():
    person = Person(display_name=None, state={})
    person.id = uuid.uuid4()
    ident = SimpleNamespace(person_id=person.id, channel="messenger", external_id=PSID)
    return person, _FakeDB(ident, person)


def test_add_fact_writes_to_person_state_for_messenger():
    person, db = _setup()
    facts = asyncio.run(mem.add_fact(db, PSID, "Prefers black cassocks", channel="messenger"))
    assert facts == ["Prefers black cassocks"]
    assert person.state["agent_memory"] == ["Prefers black cassocks"]   # person-backed
    assert db.commits == 1


def test_build_memory_context_reads_person_facts_for_messenger():
    person, db = _setup()
    person.state = {"agent_memory": ["Reverend at PCEA Kikuyu", "Size 52 cassock"]}
    ctx = asyncio.run(mem.build_memory_context(db, None, PSID, channel="messenger"))
    assert "Reverend at PCEA Kikuyu" in ctx and "Size 52" in ctx


def test_unresolved_meta_contact_noops():
    db = _FakeDB(ident=None, person=None)
    assert asyncio.run(mem.add_fact(db, PSID, "x", channel="messenger")) == []
    assert db.commits == 0
