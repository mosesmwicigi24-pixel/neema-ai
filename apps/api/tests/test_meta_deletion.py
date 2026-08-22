"""Meta data-deletion: signed_request verification, the purge's blast radius,
the callback contract, and the status receipt. Repo fake-db style (no fixtures).

Requires Python 3.11 (SQLAlchemy models). Imports app.main to register the mapper.
"""
import asyncio
import base64
import hashlib
import hmac
import json

import pytest

import app.main  # noqa: F401 — registers all SQLAlchemy models
import app.routers.meta_webhook as mw
from app.core.config import settings
from app.services import meta_deletion as md

SECRET = "app-secret-xyz"


def _signed(payload: dict, secret: str = SECRET) -> str:
    body = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    sig = hmac.new(secret.encode(), body.encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(sig).decode().rstrip("=") + "." + body


def _payload(user_id="PSID_1"):
    return {"algorithm": "HMAC-SHA256", "issued_at": 1755300000, "user_id": user_id}


# ── signed_request ───────────────────────────────────────────────────────────

def test_valid_signed_request_round_trips():
    out = md.parse_signed_request(_signed(_payload()), SECRET)
    assert out["user_id"] == "PSID_1"


def test_signed_request_rejections():
    for bad, why in [
        (_signed(_payload(), "wrong-secret"), "forged with another secret"),
        ("not-a-signed-request", "no dot separator"),
        ("!!!.!!!", "undecodable"),
        (_signed({**_payload(), "algorithm": "none"}), "downgraded algorithm"),
        ("", "empty"),
    ]:
        with pytest.raises(md.InvalidSignedRequest):
            md.parse_signed_request(bad, SECRET)


def test_unconfigured_secret_refuses_rather_than_trusts(monkeypatch):
    monkeypatch.setattr(settings, "meta_app_secret", "", raising=False)
    with pytest.raises(md.InvalidSignedRequest):
        md.parse_signed_request(_signed(_payload()))


def test_subject_hash_is_stable_and_not_the_id():
    h = md.subject_hash("PSID_1")
    assert h == md.subject_hash("PSID_1") and "PSID_1" not in h and len(h) == 16


# ── purge ────────────────────────────────────────────────────────────────────

class _Scalars:
    def __init__(self, rows):
        self._rows = rows
    def scalars(self):
        return list(self._rows)
    def scalar(self):
        return self._rows[0] if self._rows else 0


class _PurgeDB:
    """Answers the purge's queries in order, and records deletes."""
    def __init__(self, conv_ids=(), ident_persons=(), conv_persons=(),
                 messages=0, identities=0, survivors=()):
        self.script = [
            _Scalars(list(conv_ids)),        # conversation ids
            _Scalars(list(ident_persons)),   # person ids via identities
            _Scalars(list(conv_persons)),    # person ids via conversations
            _Scalars([messages]),            # message count
            _Scalars([identities]),          # identity count
        ]
        # _orphaned_persons asks 4 counts per person; a "survivor" answers 1 to
        # the first (another identity), an orphan answers 0 to all four.
        for pid in dict.fromkeys(list(ident_persons) + list(conv_persons)):
            self.script.extend([_Scalars([1])] if pid in survivors
                               else [_Scalars([0]) for _ in range(4)])
        self.i, self.deletes, self.commits = 0, [], 0
    async def execute(self, stmt, *a, **k):
        text = str(stmt).split("\n")[0].strip().upper()
        if text.startswith("DELETE"):
            self.deletes.append(text)
            return _Scalars([])
        r = self.script[self.i] if self.i < len(self.script) else _Scalars([])
        self.i += 1
        return r
    def add(self, o):
        pass
    async def commit(self):
        self.commits += 1
    async def get(self, model, key):
        return None


def test_dry_run_counts_but_deletes_nothing():
    db = _PurgeDB(conv_ids=["c1"], ident_persons=["p1"], messages=12, identities=1)
    out = asyncio.run(md.purge_meta_user(db, "PSID_1", dry_run=True))
    assert out == {"external_id": "PSID_1", "messages": 12, "conversations": 1,
                   "identities": 1, "persons": 1, "persons_kept": 0, "dry_run": True}
    assert db.deletes == []


def test_apply_deletes_messages_conversations_identities_and_orphan_person():
    db = _PurgeDB(conv_ids=["c1"], ident_persons=["p1"], messages=3, identities=1)
    out = asyncio.run(md.purge_meta_user(db, "PSID_1", dry_run=False))
    assert out["persons"] == 1
    joined = " | ".join(db.deletes)
    for table in ("MESSAGES", "CONVERSATIONS", "IDENTITIES", "PERSONS"):
        assert table in joined, f"{table} not deleted: {joined}"


def test_person_with_another_channel_is_kept():
    """A customer who also reached us on WhatsApp keeps that history — the
    request covers their Meta identity, not a phone they gave us directly."""
    db = _PurgeDB(conv_ids=["c1"], ident_persons=["p1"], messages=3, identities=1,
                  survivors={"p1"})
    out = asyncio.run(md.purge_meta_user(db, "PSID_1", dry_run=False))
    assert out["persons"] == 0 and out["persons_kept"] == 1
    assert "PERSONS" not in " | ".join(db.deletes)


def test_unknown_id_is_a_no_op():
    db = _PurgeDB()
    out = asyncio.run(md.purge_meta_user(db, "PSID_UNKNOWN", dry_run=False))
    assert out["messages"] == 0 and db.deletes == []


def test_purge_requires_an_id():
    with pytest.raises(ValueError):
        asyncio.run(md.purge_meta_user(_PurgeDB(), "  ", dry_run=True))


# ── callback contract ────────────────────────────────────────────────────────

def test_callback_purges_and_returns_url_and_code(monkeypatch):
    seen = {}

    async def fake_purge(db, ext, dry_run=True):
        seen["purged"] = (ext, dry_run)
        return {"external_id": ext, "messages": 2, "conversations": 1,
                "identities": 1, "persons": 1, "persons_kept": 0, "dry_run": dry_run}

    async def fake_receipt(db, code, ext, counts):
        seen["receipt"] = code

    monkeypatch.setattr(settings, "meta_app_secret", SECRET, raising=False)
    monkeypatch.setattr(settings, "media_public_url",
                        "https://neema.bethanyhouse.co.ke", raising=False)
    monkeypatch.setattr(md, "purge_meta_user", fake_purge)
    monkeypatch.setattr(md, "write_receipt", fake_receipt)

    db = _PurgeDB()
    out = asyncio.run(mw.data_deletion(signed_request=_signed(_payload("PSID_9")), db=db))
    assert seen["purged"] == ("PSID_9", False)          # real delete, not a dry run
    assert out["confirmation_code"] == seen["receipt"]
    assert out["url"].startswith("https://neema.bethanyhouse.co.ke/api/meta/data-deletion/status?code=")
    assert out["confirmation_code"] in out["url"]
    assert db.commits == 1


def test_callback_rejects_a_forged_request(monkeypatch):
    monkeypatch.setattr(settings, "meta_app_secret", SECRET, raising=False)
    resp = asyncio.run(mw.data_deletion(signed_request=_signed(_payload(), "attacker"),
                                        db=_PurgeDB()))
    assert resp.status_code == 400


def test_callback_500s_rather_than_confirming_a_failed_purge(monkeypatch):
    async def boom(db, ext, dry_run=True):
        raise RuntimeError("db down")

    async def noop_rollback():
        pass

    monkeypatch.setattr(settings, "meta_app_secret", SECRET, raising=False)
    monkeypatch.setattr(md, "purge_meta_user", boom)
    db = _PurgeDB()
    db.rollback = noop_rollback
    resp = asyncio.run(mw.data_deletion(signed_request=_signed(_payload()), db=db))
    assert resp.status_code == 500          # Meta retries; never a false "done"


def test_status_page_reports_and_names_nobody(monkeypatch):
    async def fake_read(db, code):
        return {"subject": md.subject_hash("PSID_1"),
                "completed_at": "2026-08-17T09:30:00+00:00",
                "removed": {"messages": 4, "conversations": 1, "identities": 1}}

    monkeypatch.setattr(md, "read_receipt", fake_read)
    resp = asyncio.run(mw.data_deletion_status(code="abc123", db=_PurgeDB()))
    body = resp.body.decode()
    assert "deleted" in body.lower() and "4 messages" in body
    assert "PSID_1" not in body

    async def none_read(db, code):
        return None

    monkeypatch.setattr(md, "read_receipt", none_read)
    missing = asyncio.run(mw.data_deletion_status(code="nope", db=_PurgeDB()))
    assert missing.status_code == 404
