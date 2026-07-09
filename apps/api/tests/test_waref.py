"""Cross-channel bridge: a WhatsApp arrival carrying a wa.me deep-link `ref`
links back to the social contact that generated it (and attributes the source).
"""
import asyncio
import json
from types import SimpleNamespace

from app.services import identity as idm


def test_waref_regex_extracts_ref():
    assert idm._WAREF_RE.search("I'd like a cassock. (ref 9F2A7C)").group(1) == "9F2A7C"
    assert idm._WAREF_RE.search("order ref: ABC123 please").group(1).upper() == "ABC123"
    assert idm._WAREF_RE.search("no reference here") is None
    assert idm._WAREF_RE.search("referral program") is None   # 'ref' inside a word ≠ a token


class _FakeRedis:
    def __init__(self, store=None):
        self.store = store or {}
        self.deleted = []

    async def get(self, k):
        return self.store.get(k)

    async def delete(self, k):
        self.deleted.append(k)
        self.store.pop(k, None)


def test_reconcile_noops_without_ref_or_redis():
    run = asyncio.run
    assert run(idm.reconcile_waref(None, None, "254700", "hello")) is False        # no redis
    assert run(idm.reconcile_waref(None, _FakeRedis(), "254700", "no ref")) is False  # no token
    # token present but redis has no such ref → no-op
    assert run(idm.reconcile_waref(None, _FakeRedis(), "254700", "(ref 9F2A7C)")) is False


def test_reconcile_merges_social_into_phone_and_consumes(monkeypatch):
    redis = _FakeRedis({"waref:9F2A7C": json.dumps({"channel": "messenger",
                                                    "external_id": "PSID1"})})
    social = SimpleNamespace(person_id="social-p", raw_profile={"source_post": "POST9"})

    async def fake_select(db, channel, ext):
        return social if (channel, ext) == ("messenger", "PSID1") else None

    async def fake_resolve(db, wa_id, **kw):
        return "wa-p"

    merged = {}

    async def fake_merge(db, primary_person_id, secondary_person_id, **kw):
        merged["primary"], merged["secondary"] = primary_person_id, secondary_person_id

    class _FakeDB:
        async def get(self, model, pid):
            return SimpleNamespace(state={})

        async def commit(self):
            pass

        async def rollback(self):
            pass

    monkeypatch.setattr(idm, "_select_identity", fake_select)
    monkeypatch.setattr(idm, "resolve_person_id_for_wa_id", fake_resolve)
    monkeypatch.setattr("app.services.merge.merge_persons", fake_merge)

    ok = asyncio.run(idm.reconcile_waref(_FakeDB(), redis, "254700", "order it (ref 9F2A7C)"))
    assert ok is True
    assert merged == {"primary": "wa-p", "secondary": "social-p"}   # phone person stays primary
    assert "waref:9F2A7C" in redis.deleted                          # one-shot: ref consumed
