"""Phantom-WhatsApp guards: a 16-17 digit Meta id (PSID/IGSID/comment-author id)
must never become a phone, a (whatsapp, …) identity, or a phantom contact.
"""
import asyncio
import uuid
from types import SimpleNamespace

from app.core.phone import is_plausible_phone
from app.services import identity as idm

PSID = "26607384265628872"      # 17 digits — a real observed phantom


def test_is_plausible_phone():
    assert is_plausible_phone("254712345678") is True       # wa_id shape
    assert is_plausible_phone("+254 712 345 678") is True   # formatted
    assert is_plausible_phone("13105551234") is True        # US
    assert is_plausible_phone(PSID) is False                # Meta id: 17 digits
    assert is_plausible_phone("2558318800795775 3") is False # 17 digits w/ space
    assert is_plausible_phone("12345") is False             # too short
    assert is_plausible_phone("") is False and is_plausible_phone(None) is False


class _Res:
    def __init__(self, items): self._items = items
    def scalars(self): return SimpleNamespace(first=lambda: self._items[0] if self._items else None)


class _FakeDB:
    """Records whether anything was added; serves a scripted identity lookup."""
    def __init__(self, existing=None):
        self.added = []
        self._existing = existing
    async def execute(self, stmt): return _Res([self._existing] if self._existing else [])
    def add(self, obj): self.added.append(obj)
    async def flush(self): pass
    def begin_nested(self): raise AssertionError("must not try to CREATE for a non-phone id")


def test_resolver_never_mints_whatsapp_identity_for_meta_id():
    db = _FakeDB(existing=None)
    got = asyncio.run(idm.resolve_person_id_for_wa_id(db, PSID))
    assert got is None and db.added == []       # no create, no adopt (nothing to adopt)


def test_resolver_adopts_existing_identity_for_meta_id():
    pid = uuid.uuid4()
    existing = SimpleNamespace(person_id=pid, channel="messenger", external_id=PSID)
    db = _FakeDB(existing=existing)
    got = asyncio.run(idm.resolve_person_id_for_wa_id(db, PSID))
    assert got == pid and db.added == []        # adopted the messenger identity's person


def test_iso_from_text_resolves_captured_locations():
    from app.core.countries import iso_from_text
    assert iso_from_text("Somerset East, Eastern Cape, South Africa") == "ZA"
    assert iso_from_text("Kampala, Uganda") == "UG"
    assert iso_from_text("Nairobi, Kenya") == "KE"
    assert iso_from_text("South Sudan, Juba") == "SS"    # longest name wins over Sudan
    assert iso_from_text("somewhere unknown") is None
    assert iso_from_text("") is None and iso_from_text(None) is None


def test_shared_number_normalizes_against_their_country():
    """A Messenger customer in South Africa sharing '0799223329' must become
    +27799223329 (strip the 0, add THEIR code) — never Kenya's +254."""
    from app.core.phone import to_e164
    assert to_e164("0799223329", "ZA") == "+27799223329"
    assert to_e164("0712345678", "KE") == "+254712345678"
