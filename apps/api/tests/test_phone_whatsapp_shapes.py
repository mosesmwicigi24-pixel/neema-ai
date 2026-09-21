"""WhatsApp ids the phone library rejects, the E.164 length cap, and one number
stored under two country codes (production contacts export, 2026-09-21).

1. 116 customers who had written to us on WhatsApp failed `to_e164`:
   Mexico 521+10 (WhatsApp keeps the retired mobile "1") and Brazil 55+area+8
   (WhatsApp drops the mobile 9) are repaired to the real number; Côte d'Ivoire /
   Cameroon pre-renumbering handles, Benin's 2024 numbers and a few unknown
   KE/CD/ZM/TZ ranges have no honest conversion, so they are accepted as-is —
   only on proof of life (WhatsApp delivered inbound messages from that handle).
2. A 16-digit Messenger PSID starting 49 passed as a German number. E.164 caps a
   number at 15 digits.
3. capture_contact read a bare "0724…" as Kenyan before the customer's location
   was known, then as South African after — and kept both rows. 11 people.

Every number here is synthetic, in the shape of the production case.
"""
import asyncio
import types
import uuid

import pytest

import app.main  # noqa: F401 — registers models
from app.agent import tools
from app.agent.tools import ToolContext
from app.core import hub_client
from app.core.phone import (
    is_plausible_phone, national_digits, region_of, same_number, to_e164, whatsapp_ids,
)
from app.models.person import Person
from app.services import hub_events
from app.services import identity as idm

MX_WA = "5215512345678"        # 52 1 + 10: WhatsApp's form of +52 55 1234 5678
BR_WA = "551187654321"         # 55 11 + 8: WhatsApp's form of +55 11 98765 4321
CI_OLD = "22507123456"         # 225 + 8: Ivorian account from before renumbering
CM_OLD = "23777123456"         # 237 + 8: Cameroonian, same story
BJ_2024 = "2290197123456"      # 229 + 10: newer than the library's metadata
KE_UNKNOWN = "254140123456"    # a Kenyan range the library doesn't know
DE_PSID = "4930123456789012"   # 16 digits: a PSID the DE metadata would take


# ── 1a. Mexico and Brazil: repaired to the real number, no proof needed ──────

def test_mexico_drops_whatsapps_retired_mobile_one():
    assert to_e164(MX_WA) == "+525512345678"
    assert to_e164("+52 1 55 1234 5678") == "+525512345678"


def test_brazil_gets_its_mobile_nine_back():
    assert to_e164(BR_WA) == "+5511987654321"
    # A Brazilian landline (8 digits, valid as-is) is never given a 9.
    assert to_e164("551133334444") == "+551133334444"


def test_repaired_numbers_still_find_whatsapps_legacy_key():
    assert whatsapp_ids("+525512345678") == ["525512345678", MX_WA]
    assert whatsapp_ids("+5511987654321") == ["5511987654321", BR_WA]
    assert whatsapp_ids("+254712345678") == ["254712345678"]
    assert whatsapp_ids(None) == [] and whatsapp_ids("") == []
    for wa in (MX_WA, BR_WA):
        assert wa in whatsapp_ids(to_e164(wa))


def test_the_legacy_form_still_counts_as_giving_the_country_code():
    from app.core.phone import carries_country_code
    assert carries_country_code(MX_WA, "+525512345678") is True
    assert carries_country_code(BR_WA, "+5511987654321") is True
    assert carries_country_code("0712345678", "+254712345678") is False


def test_the_hub_matches_a_mexican_wa_id_to_the_real_number():
    assert same_number(MX_WA, "+52 55 1234 5678") is True
    assert same_number(BR_WA, "+55 11 98765 4321") is True


# ── 1b. Proof of life: accepted exactly as WhatsApp sent it, never converted ─

@pytest.mark.parametrize("handle", [CI_OLD, CM_OLD, BJ_2024, KE_UNKNOWN])
def test_a_handle_the_library_rejects_needs_proof_of_life(handle):
    assert to_e164(handle) is None                        # no proof: still rejected
    assert to_e164(handle, proven=True) == "+" + handle   # proof: as-is, no invented digits


def test_proof_never_overrides_a_valid_reading_or_a_repair():
    assert to_e164("254712345678", proven=True) == "+254712345678"
    assert to_e164(MX_WA, proven=True) == "+525512345678"
    # The Ivorian handle is NOT converted to the 10-digit renumbered form.
    assert to_e164(CI_OLD, proven=True) != "+2250712345678"


@pytest.mark.parametrize("text", [
    "225 07 12 34 56",            # formatted: human text, not WhatsApp's shape
    "web_22507123456",            # a web chat session key
    "022507123456",               # trunk 0: a local number, not a handle
    "99912345678",                # no such country calling code
    "12345",                      # too short
])
def test_proof_vouches_for_a_whatsapp_handle_not_for_free_text(text):
    assert to_e164(text, proven=True) is None


def test_same_number_carries_proof_only_to_the_identical_handle():
    # The hub stored the very wa_id Neema pushed (with or without '+').
    assert same_number(CI_OLD, CI_OLD, proven=True) is True
    assert same_number(CI_OLD, "+" + CI_OLD, proven=True) is True
    assert same_number(CI_OLD, CI_OLD) is False                    # no proof, no match
    assert same_number(CI_OLD, "22507123457", proven=True) is False
    # Trailing digits alone never match — the country code is part of it.
    assert same_number(CI_OLD, "07123456", proven=True) is False


def test_national_digits_and_region_follow_the_proof():
    assert national_digits(CI_OLD) is None
    assert national_digits(CI_OLD, proven=True) in CI_OLD           # an ILIKE substring
    assert region_of(CI_OLD) is None
    assert region_of(CI_OLD, proven=True) == "CI"
    assert region_of("27821234567") == "ZA"
    assert region_of(MX_WA) == "MX"
    assert region_of("web_3fa47c19d2e8b105a44f") is None


# ── 2. E.164 caps a number at 15 digits ──────────────────────────────────────

def test_a_sixteen_digit_psid_is_not_a_german_number():
    assert to_e164(DE_PSID) is None
    assert to_e164("+" + DE_PSID) is None
    assert to_e164("4930 1234 5678 9012") is None       # formatted: output cap
    assert to_e164(DE_PSID, proven=True) is None
    assert to_e164("26607384265628872", proven=True) is None      # 17-digit PSID
    assert is_plausible_phone(DE_PSID) is False


def test_the_cap_leaves_real_numbers_alone():
    assert to_e164("0712 345 678 ext 1234") == "+254712345678"
    assert to_e164("+254 712 345 678") == "+254712345678"


# ── Proof of life comes from WhatsApp traffic, not from a row existing ───────

class _ProofDB:
    """Serves the proof query: `rows` inbound WhatsApp messages exist."""
    def __init__(self, rows):
        self.rows, self.queries = rows, []

    async def execute(self, stmt):
        self.queries.append(str(stmt))
        items = [types.SimpleNamespace(id=uuid.uuid4())] * self.rows
        return types.SimpleNamespace(first=lambda: items[0] if items else None)


def test_whatsapp_handle_proven_reads_inbound_whatsapp_messages():
    db = _ProofDB(1)
    assert asyncio.run(idm.whatsapp_handle_proven(db, CI_OLD)) is True
    sql = db.queries[0]
    assert "messages.wa_id" in sql and "messages.channel" in sql and "messages.direction" in sql
    assert asyncio.run(idm.whatsapp_handle_proven(_ProofDB(0), CI_OLD)) is False


def test_a_non_handle_is_never_proven_and_costs_no_query():
    db = _ProofDB(1)
    assert asyncio.run(idm.whatsapp_handle_proven(db, "web_3fa47c19d2e8b105a44f")) is False
    assert asyncio.run(idm.whatsapp_handle_proven(db, None)) is False
    assert db.queries == []


def test_to_e164_with_proof():
    assert asyncio.run(idm.to_e164_with_proof(_ProofDB(1), CI_OLD)) == "+" + CI_OLD
    assert asyncio.run(idm.to_e164_with_proof(_ProofDB(0), CI_OLD)) is None
    db = _ProofDB(1)
    assert asyncio.run(idm.to_e164_with_proof(db, "254712345678")) == "+254712345678"
    assert db.queries == []                        # a known number costs nothing extra


# ── The hub↔Neema match, both directions ─────────────────────────────────────

def _hub_search_returns(monkeypatch, customers):
    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return {"data": customers}

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, headers=None, params=None):
            return _Resp()

    monkeypatch.setattr(hub_client.httpx, "AsyncClient", lambda **kw: _Client())


def test_a_proven_handle_finds_the_hub_customer_created_with_it(monkeypatch):
    _hub_search_returns(monkeypatch, [{"id": 7, "name": "Awa", "phone": CI_OLD}])
    got = asyncio.run(hub_client._search_customer_match(CI_OLD, proven=True))
    assert got == {"id": 7, "name": "Awa", "phone": CI_OLD}
    # Without proof: no match, so the order would mint a duplicate customer.
    assert asyncio.run(hub_client._search_customer_match(CI_OLD)) is None


def test_a_mexican_wa_id_finds_the_hub_customer_on_the_real_number(monkeypatch):
    _hub_search_returns(monkeypatch, [{"id": 9, "name": "Lupe", "phone": "+52 55 1234 5678"}])
    assert asyncio.run(hub_client._search_customer_match(MX_WA))["id"] == 9


class _ScriptedDB:
    """Every execute() pops the next result; records deletes."""
    def __init__(self, results, person=None):
        self._results, self._person = list(results), person
        self.deleted, self.commits = [], 0

    async def execute(self, stmt):
        nxt = self._results.pop(0) if self._results else None
        items = nxt if isinstance(nxt, list) else ([nxt] if nxt is not None else [])
        return types.SimpleNamespace(
            scalar_one_or_none=lambda: items[0] if items else None,
            first=lambda: items[0] if items else None,
            scalars=lambda: types.SimpleNamespace(all=lambda: items,
                                                  first=lambda: items[0] if items else None))

    async def get(self, model, pk):
        return self._person

    async def delete(self, obj):
        self.deleted.append(obj)

    async def commit(self):
        self.commits += 1

    def add(self, obj):
        pass

    async def flush(self):
        pass


def test_a_hub_event_reaches_the_conversation_of_a_proven_handle():
    conv = types.SimpleNamespace(wa_id=CI_OLD)
    # proof query (an inbound message) → conversation by wa_id
    db = _ScriptedDB([types.SimpleNamespace(id=1), conv])
    assert asyncio.run(hub_events._conversation_for_phone(db, CI_OLD)) is conv


def test_a_hub_event_reaches_a_mexican_conversation_in_its_legacy_key():
    conv = types.SimpleNamespace(wa_id=MX_WA)
    # +525512345678 is not a conversation; WhatsApp's 5215512345678 is.
    db = _ScriptedDB([None, conv])
    assert asyncio.run(hub_events._conversation_for_phone(db, "+52 55 1234 5678")) is conv


# ── 3. capture_contact: one number, one row ─────────────────────────────────

PSID = "26414904614761138"


def _person(location=None):
    p = Person(display_name="Thandi", state={"location": location} if location else {})
    p.id = uuid.uuid4()
    return p


def _ident(p, channel="messenger", external_id=PSID):
    return types.SimpleNamespace(person_id=p.id, channel=channel, external_id=external_id,
                                 display_name=None, raw_profile=None)


def _user(wa_id, **kw):
    base = dict(wa_id=wa_id, location=None, phone=None, country_iso=None, country=None,
                flag_url=None, name="")
    base.update(kw)
    return types.SimpleNamespace(**base)


def _phone_row(p, value, assumed):
    return types.SimpleNamespace(person_id=p.id, type="phone", value=value,
                                 raw={"as_given": "0724123456", "region_assumed": assumed})


def _capture(monkeypatch, results, person, args, *, wa_id=PSID, channel="messenger"):
    recorded = {}

    async def fake_attach(db, person_id, type_, value, *, source=None, confidence=None, raw=None):
        recorded.update({"value": value, "raw": raw})
        return types.SimpleNamespace(type=type_, value=value, raw=raw)
    monkeypatch.setattr("app.services.reconcile.attach_identifier", fake_attach)
    db = _ScriptedDB(results, person)
    ctx = ToolContext(db=db, redis=None, wa_id=wa_id, currency="USD", channel=channel)
    out = asyncio.run(tools._capture_contact(args, ctx))
    return out, recorded, db


def test_the_evidenced_reading_replaces_the_assumed_kenyan_twin(monkeypatch):
    """The production sequence: "0724…" with no location → +254 (assumed); a
    minute later the same "0724…" with "South Africa" → +27. Before, both rows
    stayed. Now the assumed one is replaced and the profile follows."""
    p = _person()
    shim = _user(PSID, phone="+254724123456")
    kenyan = _phone_row(p, "+254724123456", assumed=True)
    # select_identity → users (location) → users (phone) → their WhatsApp handles
    # (none) → whatsapp identity for +27… (none) → this person's phone rows → users
    out, rec, db = _capture(monkeypatch,
                            [_ident(p), [shim], [shim], [], None, [kenyan], [shim]], p,
                            {"phone": "0724123456", "location": "South Africa"})
    assert rec["value"] == "+27724123456"
    assert rec["raw"]["region_assumed"] is False
    assert rec["raw"]["supersedes"] == ["+254724123456"]
    assert db.deleted == [kenyan]
    assert shim.phone == "+27724123456"                 # the profile no longer shows +254
    assert out["country"] == "South Africa"


def test_a_reading_that_was_not_assumed_is_never_dropped(monkeypatch):
    """Given with its code, read on evidence, or written before the flag existed:
    those are claims, not guesses — leave them for a human."""
    p = _person()
    shim = _user(PSID)
    given = _phone_row(p, "+254724123456", assumed=False)
    legacy = types.SimpleNamespace(person_id=p.id, type="phone", value="+256724123456", raw={})
    other = _phone_row(p, "+254799000111", assumed=True)          # different digits
    _out, rec, db = _capture(monkeypatch,
                             [_ident(p), [shim], [shim], [], None, [given, legacy, other], [shim]],
                             p,
                             {"phone": "0724123456", "location": "South Africa"})
    assert rec["value"] == "+27724123456" and "supersedes" not in rec["raw"]
    assert db.deleted == []


def test_an_assumed_capture_drops_nothing(monkeypatch):
    p = _person()
    shim = _user(PSID)
    # No location, no WhatsApp: assumed Kenyan, and the twin query never runs.
    _out, rec, db = _capture(monkeypatch, [_ident(p), [shim], [], None, [shim]], p,
                             {"phone": "0724123456"})
    assert rec["value"] == "+254724123456" and rec["raw"]["region_assumed"] is True
    assert db.deleted == []


def test_a_local_number_is_read_against_their_own_whatsapp_country(monkeypatch):
    """A South African WhatsApp customer who shares "0712 345 678" means +27,
    not +254 — and their own number is evidence, so it is not 'assumed'."""
    p = _person()
    wa = "27821234567"
    user = _user(wa)
    out, rec, _ = _capture(monkeypatch,
                           [_ident(p, "whatsapp", wa), [user], [wa], None, [], [user]], p,
                           {"phone": "0712345678"}, wa_id=wa, channel="whatsapp")
    assert rec["value"] == "+27712345678"
    assert rec["raw"]["region_assumed"] is False
    assert out["country"] == "South Africa"


def test_a_linked_whatsapp_identity_places_a_messenger_customer(monkeypatch):
    p = _person()
    shim = _user(PSID)
    _out, rec, _ = _capture(monkeypatch,
                            [_ident(p), [shim], ["27821234567"], None, [], [shim]], p,
                            {"phone": "0712345678"})
    assert rec["value"] == "+27712345678" and rec["raw"]["region_assumed"] is False


def test_a_shared_mexican_number_links_to_the_legacy_whatsapp_identity(monkeypatch):
    p = _person()
    shim = _user(PSID)
    wa_person = uuid.uuid4()
    wa_ident = types.SimpleNamespace(person_id=wa_person, channel="whatsapp",
                                     external_id=MX_WA, display_name=None, raw_profile=None)
    merged = {}

    async def fake_merge(db, *, primary_person_id, secondary_person_id, primary_wa_id=None, **kw):
        merged.update(primary=primary_person_id, secondary=secondary_person_id, wa=primary_wa_id)
    monkeypatch.setattr("app.services.merge.merge_persons", fake_merge)
    # … → identity for 525512345678 (none) → for 5215512345678 (found) → phone rows → users
    out, rec, _ = _capture(monkeypatch,
                           [_ident(p), [shim], [], None, wa_ident, [], [shim]], p,
                           {"phone": "+52 55 1234 5678"})
    assert rec["value"] == "+525512345678"
    assert merged == {"primary": wa_person, "secondary": p.id, "wa": MX_WA}
    assert out.get("linked_whatsapp") is True
