"""Unit tests for the real person-level merge (no DB) — matches the repo's
FakeDB convention. The full merge→unmerge round-trip is verified against a real
Postgres separately; this pins the service's logic: identities move to the
primary, only whatsapp handles index the wa_id cache refresh, the secondary is
tombstoned, the audit is recorded, and the guards fire. Requires Python 3.11.
"""
import asyncio
import types
import uuid
from datetime import datetime, timezone

from app.services.merge import merge_persons, unmerge
from app.models.person import Person, Identity, PersonMerge


class _FakeDB:
    def __init__(self, secondary_identities, persons):
        self._sec = secondary_identities
        self._persons = persons          # {person_id: Person}
        self.added = []
        self.update_count = 0            # bulk UPDATE ... person_id executes

    async def execute(self, stmt):
        if type(stmt).__name__ == "Select":
            return types.SimpleNamespace(
                scalars=lambda: types.SimpleNamespace(all=lambda: self._sec))
        self.update_count += 1           # an update() against a wa_id table
        return None

    async def get(self, model, pk):
        return self._persons.get(pk)

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        pass


def _ident(person_id, channel, external_id):
    i = Identity(person_id=person_id, channel=channel, external_id=external_id)
    i.id = uuid.uuid4()
    return i


def test_merge_moves_identities_tombstones_and_audits():
    primary, secondary = uuid.uuid4(), uuid.uuid4()
    wa = _ident(secondary, "whatsapp", "254722222222")
    ig = _ident(secondary, "instagram", "IGSID_999")     # non-whatsapp handle
    sec_person = Person()
    sec_person.id = secondary
    db = _FakeDB([wa, ig], {secondary: sec_person})

    audit = asyncio.run(merge_persons(
        db, primary, secondary, performed_by=None,
        primary_wa_id="254711111111", secondary_wa_id="254722222222"))

    # identities moved onto the primary
    assert wa.person_id == primary and ig.person_id == primary
    # both identities recorded; only the whatsapp handle indexes the wa_id cache
    assert len(audit.moved_identity_ids) == 2
    assert audit.moved_external_ids == ["254722222222"]
    # one bulk update per wa_id-keyed table (5) since there were whatsapp handles
    assert db.update_count == 5
    # secondary tombstoned + audit persisted
    assert sec_person.merged_into_id == primary and sec_person.merged_at is not None
    assert audit in db.added


def test_merge_with_no_whatsapp_handle_skips_cache_refresh():
    primary, secondary = uuid.uuid4(), uuid.uuid4()
    ig = _ident(secondary, "instagram", "IGSID_1")
    sec_person = Person(); sec_person.id = secondary
    db = _FakeDB([ig], {secondary: sec_person})

    audit = asyncio.run(merge_persons(db, primary, secondary))

    assert audit.moved_external_ids == []
    assert db.update_count == 0            # nothing to refresh in the wa_id tables
    assert ig.person_id == primary


def test_merge_into_self_raises():
    pid = uuid.uuid4()
    db = _FakeDB([], {})
    raised = False
    try:
        asyncio.run(merge_persons(db, pid, pid))
    except ValueError:
        raised = True
    assert raised


def test_unmerge_already_undone_raises():
    audit = PersonMerge()
    audit.undone_at = datetime.now(timezone.utc)
    db = _FakeDB([], {})
    raised = False
    try:
        asyncio.run(unmerge(db, audit))
    except ValueError:
        raised = True
    assert raised
