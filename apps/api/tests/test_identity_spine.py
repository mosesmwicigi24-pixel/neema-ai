"""Identity resolver unit tests (no DB, no network) — matches the repo's
FakeDB convention. Exercises app.services.identity.resolve_or_create_person and
resolve_person_id_for_wa_id: idempotent adoption of an existing identity, the
create path (person + identity, correctly linked), and wa_id normalization.

The migration + backfill + the resolver against a real Postgres are verified
separately (see docs/MULTICHANNEL_IDENTITY_PLAN.md / the epic verification);
this pins the branching logic so it can't silently regress. Requires Python
3.11 (SQLAlchemy 2.0 models).
"""
import asyncio
import uuid

from app.services import identity as idmod
from app.models.person import Person, Identity


class _Res:
    def __init__(self, one=None):
        self._one = one

    def scalar_one_or_none(self):
        return self._one


class _Nested:
    """Stand-in for AsyncSession.begin_nested()'s async context manager."""
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _FakeDB:
    """Returns a fixed identity for the first lookup; records add()/flush().
    flush() emulates SQLAlchemy assigning the uuid PK default so the resolver
    can link identity.person_id to the freshly-created person."""
    def __init__(self, existing_identity=None):
        self._existing = existing_identity
        self.added = []
        self.flushes = 0

    async def execute(self, *a, **k):
        return _Res(one=self._existing)

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        self.flushes += 1
        for o in self.added:
            if getattr(o, "id", None) is None:
                o.id = uuid.uuid4()

    def begin_nested(self):
        return _Nested()


def test_resolve_existing_identity_is_idempotent_and_enriches_name():
    person_id = uuid.uuid4()
    ident = Identity(person_id=person_id, channel="whatsapp",
                     external_id="254712345678", display_name=None)
    db = _FakeDB(existing_identity=ident)

    got = asyncio.run(idmod.resolve_or_create_person(
        db, "whatsapp", "254712345678", display_name="Alice"))

    assert got is ident                      # same identity, not a new one
    assert got.person_id == person_id
    assert got.display_name == "Alice"       # empty display_name filled
    assert db.added == []                    # nothing created


def test_resolve_creates_linked_person_and_identity_for_new_handle():
    db = _FakeDB(existing_identity=None)

    got = asyncio.run(idmod.resolve_or_create_person(
        db, "whatsapp", "254799999999", display_name="Bob",
        source="whatsapp_inbound", confidence="deterministic"))

    persons = [o for o in db.added if isinstance(o, Person)]
    idents = [o for o in db.added if isinstance(o, Identity)]
    assert len(persons) == 1 and len(idents) == 1
    p, i = persons[0], idents[0]
    assert i is got
    assert i.person_id == p.id               # identity linked to the new person
    assert (i.channel, i.external_id) == ("whatsapp", "254799999999")
    assert i.source == "whatsapp_inbound" and i.confidence == "deterministic"


def test_resolve_person_id_normalizes_plus_and_guards_empty():
    db = _FakeDB(existing_identity=None)

    assert asyncio.run(idmod.resolve_person_id_for_wa_id(db, "  ")) is None
    assert asyncio.run(idmod.resolve_person_id_for_wa_id(db, "+")) is None
    assert db.added == []                     # empty wa_id creates nothing

    pid = asyncio.run(idmod.resolve_person_id_for_wa_id(db, "+254700111222"))
    idents = [o for o in db.added if isinstance(o, Identity)]
    assert len(idents) == 1
    assert idents[0].external_id == "254700111222"   # leading + stripped
    assert idents[0].confidence == "deterministic"
    assert pid == idents[0].person_id


def test_resolve_requires_external_id():
    db = _FakeDB(existing_identity=None)
    raised = False
    try:
        asyncio.run(idmod.resolve_or_create_person(db, "whatsapp", "   "))
    except ValueError:
        raised = True
    assert raised
