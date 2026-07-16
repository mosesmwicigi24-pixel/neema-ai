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


# ── The ref carries a real CART, not order details typed into a message ───────

_LINE = {"hub_product_id": 85, "name": "Thurible (L / GOLD)", "sku": "COM-T-001-L-GOL",
         "qty": 1, "unit_price": 15000.0, "made_to_order": False}


def test_build_cart_from_ref_seeds_empty_cart(monkeypatch):
    saved = {}

    async def fake_get(db, wa_id):
        return {"items": []}

    async def fake_save(db, wa_id, cart):
        saved["wa_id"], saved["cart"] = wa_id, cart
        return cart

    import app.agent.cart as cartmod
    monkeypatch.setattr(cartmod, "get_cart", fake_get)
    monkeypatch.setattr(cartmod, "save_cart", fake_save)

    ok = asyncio.run(idm._build_cart_from_ref(None, "254700", [_LINE]))
    assert ok is True
    assert saved["cart"]["items"] == [_LINE]       # real hub line, variant SKU + hub price


def test_build_cart_from_ref_never_clobbers_an_existing_cart(monkeypatch):
    async def fake_get(db, wa_id):
        return {"items": [{"name": "already shopping"}]}

    async def fake_save(db, wa_id, cart):
        raise AssertionError("must not overwrite a cart the customer started")

    import app.agent.cart as cartmod
    monkeypatch.setattr(cartmod, "get_cart", fake_get)
    monkeypatch.setattr(cartmod, "save_cart", fake_save)

    assert asyncio.run(idm._build_cart_from_ref(None, "254700", [_LINE])) is False
    assert asyncio.run(idm._build_cart_from_ref(None, "254700", [])) is False   # nothing to seed


def test_checkout_link_stores_a_resolved_cart_line(monkeypatch):
    """whatsapp_checkout_link must resolve the agreed item to a REAL hub line and
    carry it on the ref, so WhatsApp rebuilds the cart and pushes a true order."""
    from app.core.config import settings
    from app.agent import tools
    from app.agent.tools import _whatsapp_checkout_link
    monkeypatch.setattr(settings, "whatsapp_handoff_number", "+254700111222", raising=False)
    monkeypatch.setattr(settings, "media_public_url", "https://neema.example", raising=False)

    async def fake_catalog(db, redis):
        return [{"hub_product_id": 85, "name": "Thurible", "sku": "COM-T-001",
                 "price": 12000, "product_type": "variable", "is_producible": False,
                 "variants": [{"variant_id": 102, "sku": "COM-T-001-L-GOL",
                               "name": "L / GOLD", "price_kes": 15000.0,
                               "prices": {"KES": 15000.0}}]}]

    monkeypatch.setattr(tools.svc, "catalog_items", fake_catalog)

    class _R:
        def __init__(self): self.saved = {}
        async def set(self, k, v, ex=None): self.saved[k] = v

    r = _R()
    ctx = SimpleNamespace(db=None, redis=r, wa_id="PSID1", channel="messenger",
                          currency="USD", usd_rate=100)
    out = asyncio.run(_whatsapp_checkout_link({"product": "COM-T-001-L-GOL"}, ctx))
    assert out["cart_prepared"] is True
    payload = json.loads(r.saved[f"waref:{out['ref']}"])
    item = payload["items"][0]
    assert item["hub_product_id"] == 85           # a real hub line…
    assert item["sku"] == "COM-T-001-L-GOL"       # …at the exact variant…
    assert item["unit_price"] == 15000.0          # …and the hub's own price
