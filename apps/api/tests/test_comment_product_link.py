"""The DM that a comment opens links to the PRODUCT they asked about on the
Bethany House storefront (not a bare wa.me short link), and the cart follows the
PERSON across every channel. The PUBLIC comment itself never links anywhere.

Two behaviours pinned here:
 1. run_turn exposes the catalogue rows the agent actually priced (product_sink),
    so the link is the exact product — never guessed from the reply text.
 2. cart._load_store keeps ONE cart per person: a WhatsApp contact with a linked
    person reads/writes the person's cart (the same one Facebook/Instagram use),
    and a pre-existing WhatsApp-only cart is adopted onto the person once.
"""
import asyncio
import json
import types

import app.main  # noqa: F401 — registers models
import app.agent.runtime as rt
import app.agent.tools as tools
import app.agent.cart as cartmod
from app.core.config import settings


# ── the public comment CTA ────────────────────────────────────────────────────

def test_public_reply_goes_link_free_when_the_dm_landed():
    """Links are DM-only (owner, 2026-08-08): Meta suppresses the reach of
    link-carrying comments, so when the DM opened, the public reply is the
    answer + an inbox nudge and the storefront link rides the DM instead."""
    out = rt._comment_public_reply(
        "That red chasuble is $150.", dm_sent=True, name_tag=" Charity", seed="X",
        product_known=True, product_name="Red Chasuble")
    assert "http" not in out                        # NO link of any kind in public
    assert "WhatsApp" not in out
    assert out == "That red chasuble is $150."      # the answer IS the reply — no nudge


def test_no_public_link_even_when_the_dm_did_not_open():
    """The 2026-08-10 tightening: a DM failure is NOT a reason to publish a
    link. We answered the question; the next step is an invitation, not a URL."""
    out = rt._comment_public_reply(
        "That red chasuble is $150.", dm_sent=False, name_tag=" Charity", seed="X",
        product_known=True, product_name="Red Chasuble")
    assert "http" not in out and "bethanyhouse" not in out
    assert "Neema can help you right there" not in out   # the old link tail, gone
    assert "WhatsApp" not in out
    assert out == "That red chasuble is $150."      # a DM failure appends nothing either


def test_answer_without_a_product_still_never_links():
    out = rt._comment_public_reply("It is $150.", dm_sent=False, name_tag="", seed="X")
    assert "http" not in out
    assert out.startswith("It is $150.")            # buyer never stranded — invited
    # DM landed and no product → the inbox nudge, unchanged behaviour
    out2 = rt._comment_public_reply("It is $150.", dm_sent=True, name_tag="", seed="X")
    assert "It is $150." in out2 and "http" not in out2


# ── the storefront product link carries identity + the cart line ──────────────

class _FakeRedis:
    def __init__(self):
        self.store = {}
    async def set(self, k, v, nx=False, ex=None):
        self.store[k] = v
        return True


def test_storefront_product_link_carries_ref_and_cart_line(monkeypatch):
    monkeypatch.setattr(settings, "storefront_url", "https://bethanyhouse.co.ke", raising=False)

    async def fake_resolve(product, ctx):
        return [{"hub_product_id": 7, "name": "Red Chasuble", "qty": 1, "unit_price": 15000}]

    monkeypatch.setattr(tools, "_resolve_cart_items", fake_resolve)
    monkeypatch.setattr("app.database.AsyncSessionLocal", lambda: _NullDB())

    r = _FakeRedis()
    url = asyncio.run(rt._storefront_product_link(
        r, "facebook", "FBID", {"slug": "red-chasuble", "name": "Red Chasuble"}))

    assert url.startswith("https://bethanyhouse.co.ke/product/red-chasuble?ref=")
    ref = url.split("ref=")[1]
    payload = json.loads(r.store[f"waref:{ref}"])
    assert payload["channel"] == "facebook" and payload["external_id"] == "FBID"
    assert payload["target"] == "https://bethanyhouse.co.ke/product/red-chasuble"
    assert payload["items"][0]["hub_product_id"] == 7      # the cart follows the ref
    assert payload["product"] == "Red Chasuble"


class _NullDB:
    async def __aenter__(self): return self
    async def __aexit__(self, *a): return False


def test_no_slug_means_no_product_link():
    assert asyncio.run(rt._storefront_product_link(None, "facebook", "F", {"name": "x"})) == ""
    assert asyncio.run(rt._storefront_product_link(None, "facebook", "F", {})) == ""


# ── the agent exposes the product it actually priced ─────────────────────────

def test_search_catalog_records_the_rows_it_priced(monkeypatch):
    async def fake_catalog(db, redis):
        return [{"name": "Red Chasuble", "sku": "RC1", "slug": "red-chasuble",
                 "price": 15000, "price_usd": 150},
                {"name": "No Slug", "sku": "NS", "slug": "", "price": 100}]

    monkeypatch.setattr(tools.svc, "catalog_items", fake_catalog)
    sink: list = []
    ctx = tools.ToolContext(db=object(), redis=None, wa_id="FBID", channel="facebook",
                            currency="USD", seen_products=sink)
    out = asyncio.run(tools._search_catalog({"query": "chasuble"}, ctx))

    assert out["count"] >= 1
    assert sink and sink[0]["slug"] == "red-chasuble"   # full hub row, carries the slug
    assert all(p.get("slug") for p in sink)            # slug-less rows are not linkable
    # the model's own view still omits the slug
    assert "slug" not in out["results"][0]


def test_currency_override_still_fills_the_same_sink(monkeypatch):
    """_search_catalog does dataclasses.replace(ctx, currency=…) — the sink must
    still be the caller's list, or the link would silently lose the product."""
    async def fake_catalog(db, redis):
        return [{"name": "Ring", "sku": "R", "slug": "ring", "price": 1500, "price_usd": 15}]

    monkeypatch.setattr(tools.svc, "catalog_items", fake_catalog)
    sink: list = []
    ctx = tools.ToolContext(db=object(), redis=None, wa_id="254700", channel="whatsapp",
                            currency="USD", seen_products=sink)
    asyncio.run(tools._search_catalog({"query": "ring", "currency": "KES"}, ctx))
    assert sink and sink[0]["slug"] == "ring"


# ── ONE cart per person, across every channel ────────────────────────────────

class _CartDB:
    """Serves a User by wa_id and a Person by id; records commits."""
    def __init__(self, user=None, person=None):
        self.user, self.person, self.commits = user, person, 0
    async def execute(self, *a, **k):
        return types.SimpleNamespace(scalar_one_or_none=lambda: self.user)
    async def get(self, model, pk):
        return self.person
    async def commit(self):
        self.commits += 1


def test_whatsapp_cart_uses_the_person_when_linked():
    from app.models.person import Person
    from app.models.user import User
    person = Person(state={"agent_cart": {"items": [{"name": "Chasuble", "qty": 1}]}})
    user = User(wa_id="254700", phone="254700", state={})
    user.person_id = "P1"
    db = _CartDB(user=user, person=person)

    store = asyncio.run(cartmod._load_store(db, "254700", "whatsapp"))
    assert store is person                                  # person-scoped, not the User row
    cart = asyncio.run(cartmod.get_cart(db, "254700", "whatsapp"))
    assert cart["items"][0]["name"] == "Chasuble"            # the Facebook cart is visible


def test_existing_whatsapp_only_cart_is_adopted_onto_the_person():
    from app.models.person import Person
    from app.models.user import User
    person = Person(state={})                                # person has no cart yet
    user = User(wa_id="254700", phone="254700",
                state={"agent_cart": {"items": [{"name": "Mitre", "qty": 2}]}})
    user.person_id = "P1"
    db = _CartDB(user=user, person=person)

    store = asyncio.run(cartmod._load_store(db, "254700", "whatsapp"))
    assert store is person
    assert person.state["agent_cart"]["items"][0]["name"] == "Mitre"   # carried over
    assert db.commits == 1


def test_whatsapp_without_a_person_still_uses_the_user_row():
    from app.models.user import User
    user = User(wa_id="254700", phone="254700",
                state={"agent_cart": {"items": [{"name": "Alb", "qty": 1}]}})
    user.person_id = None
    db = _CartDB(user=user, person=None)
    store = asyncio.run(cartmod._load_store(db, "254700", "whatsapp"))
    assert store is user                                     # historical home, unchanged
