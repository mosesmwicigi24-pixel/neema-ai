"""Lean sales, no contradictions — the Nicole case (2026-09-05).

Under a photo of a green chasuble with an African-print stole and gold piping,
"How much" was answered: "Bless you Nicole! 🙏 the Ornate Chasuble — Embroidered
is $140 — which quantity works for you? 🤍". The owner's reading of it:

  · "many people want a piece. We should not ask how many do you want";
  · "get the colour and some details from the image";
  · "we sell it at 13,000 … if outside Kenya, we use USD";
  · "we can add we ship worldwide".

Each of the four was contradicted somewhere — in the canned pools, in the
comment rules, in the currency default — while the system prompt itself said
the opposite ("never open with 'how many?'"; the owner's own welcome shape).
These tests pin the aligned version: ONE PIECE IS THE DEFAULT; the item named
as seen; the KES home price with the USD figure for outside Kenya beside it
until a cue places the customer; and "we ship worldwide by DHL", once.
"""
import asyncio
import inspect
import json
import types

import app.main  # noqa: F401 — registers models
import app.agent.runtime as rt
from app.agent import tools
from app.agent.tools import ToolContext, _search_catalog
from app.agent.prompt import build_system_prompt


# ── 1. one piece is the default — the pools never ask a quantity ─────────────

def test_single_piece_pools_close_on_the_piece_not_a_count():
    for line in rt._OVER_CAP_SELL_POOL + rt._FIRST_SELL_POOL:
        low = line.lower()
        assert "how many" not in low and "quantity" not in low, line
        assert "reserve" in low or "set one aside" in low, line
        assert "dhl" in low, line                       # "we ship worldwide", once
        assert "{product}" in line and "{price}" in line


def test_per_piece_goods_are_still_sold_by_the_count():
    for line in rt._OVER_CAP_SELL_EACH_POOL:
        assert "how many" in line.lower(), line
        assert "{price} each" in line, line


def test_first_comment_gets_the_owners_welcome_shape():
    for line in rt._FIRST_SELL_POOL:
        assert line.lower().startswith(("welcome", "karibu")), line


def test_public_reply_picks_the_piece_pool_the_each_pool_or_the_welcome():
    seen = "green chasuble with an African-print stole down the middle and gold piping"
    price = "KES 13,000, or $140 outside Kenya"
    out = rt._comment_public_reply("", dm_sent=False, name_tag=" Nicole", seed="s",
                                   product_known=True, product_name=seen, price_text=price)
    assert f"the {seen} is {price}" in out
    assert "how many" not in out.lower() and "quantity" not in out.lower()
    assert "Nicole" in out
    first = rt._comment_public_reply("", dm_sent=False, name_tag=" Nicole", seed="s",
                                     product_known=True, product_name=seen,
                                     price_text=price, first_contact=True)
    assert first.lower().startswith(("welcome", "karibu")) and price in first
    each = rt._comment_public_reply("", dm_sent=False, name_tag=" Nicole", seed="s",
                                    product_known=True, product_name="Plastic Communion Cups",
                                    price_text="KES 10", per_piece=True)
    assert "KES 10 each" in each and "how many" in each.lower()


def test_live_which_pool_keeps_the_calm_register():
    for line in rt._LIVE_WHICH_POOL:
        assert not line.startswith(("Great", "Happy", "Perfect", "Awesome")), line


# ── 2. the public price: KES home price, USD for outside Kenya beside it ─────

def test_public_price_text_carries_both_doors():
    assert rt._public_price_text(13000, 140) == "KES 13,000, or $140 outside Kenya"
    assert rt._public_price_text(13000, None) == "KES 13,000"
    assert rt._public_price_text(None, 140) == "$140"
    assert rt._public_price_text(450, 4.5) == "KES 450, or $4.50 outside Kenya"
    assert rt._public_price_text(None, None) == ""


def test_the_engine_composes_the_public_line_from_these_parts():
    src = inspect.getsource(rt._run_comment_engage)
    assert "price_text = _public_price_text(_kes, _usd)" in src
    assert "per_piece=per_piece, first_contact=first" in src
    assert 'product_name = _known_product["seen"]' in src
    assert "_remember_post_product(redis, channel, post_id, matched, thumb=thumb)" in src
    # the free path and the cap gate are exactly as the cost tests pin them
    assert 'free_ask = bool(_known_product.get("name")) and is_bare_price_ask(prompt_text)' in src


# ── 3. search_catalog: the USD figure rides beside KES until they are placed ─

def _catalog():
    return [{"name": "Ornate Chasuble — Embroidered", "sku": "CH1", "price": 13000,
             "price_usd": 140, "prices": {"KES": 13000, "USD": 140},
             "category": "Vestments", "product_type": "simple", "is_producible": True,
             "variants": [{"attributes": {"Size": "L"}, "sku": "CH1-L",
                           "price_kes": 13000, "price_usd": 140,
                           "prices": {"KES": 13000, "USD": 140}}]},
            {"name": "Plain Stole", "sku": "ST1", "price": 3600, "price_usd": None,
             "prices": {"KES": 3600}, "category": "Vestments", "product_type": "simple"}]


def test_unplaced_customer_rows_carry_the_usd_figure_for_outside_kenya(monkeypatch):
    async def fake_catalog(db, redis):
        return _catalog()
    monkeypatch.setattr(tools.svc, "catalog_items", fake_catalog)
    ctx = ToolContext(db=None, redis=None, wa_id="PSID", currency="KES", placed=False)
    out = asyncio.run(_search_catalog({"query": "chasuble stole"}, ctx))
    rows = {r["name"]: r for r in out["results"]}
    ch = rows["Ornate Chasuble — Embroidered"]
    assert ch["price"] == 13000 and ch["currency"] == "KES"
    assert ch["usd_outside_kenya"] == 140                  # the hub's own USD, untouched
    assert ch["variants"][0]["usd_outside_kenya"] == 140
    assert rows["Plain Stole"]["usd_outside_kenya"] == 36  # no hub USD → KES / rate
    assert "quote_rule" in out and "usd_outside_kenya" in out["quote_rule"]
    assert "never ask which country" in out["quote_rule"]


def test_placed_customers_get_one_currency_only(monkeypatch):
    async def fake_catalog(db, redis):
        return _catalog()
    monkeypatch.setattr(tools.svc, "catalog_items", fake_catalog)
    kenyan = asyncio.run(_search_catalog({"query": "chasuble"},
                                         ToolContext(db=None, redis=None, wa_id="254700",
                                                     currency="KES", placed=True)))
    assert "usd_outside_kenya" not in kenyan["results"][0] and "quote_rule" not in kenyan
    abroad = asyncio.run(_search_catalog({"query": "chasuble"},
                                         ToolContext(db=None, redis=None, wa_id="PSID",
                                                     currency="USD", placed=False)))
    assert abroad["results"][0]["price"] == 140
    assert "usd_outside_kenya" not in abroad["results"][0]
    assert ToolContext(db=None, redis=None, wa_id="x").placed is True


# ── 4. the market: home price until a cue places them ───────────────────────

class _FakeDB:
    def __init__(self, results, person=None):
        self._results, self._person = list(results), person

    async def execute(self, stmt):
        nxt = self._results.pop(0) if self._results else None
        items = nxt if isinstance(nxt, list) else ([nxt] if nxt is not None else [])
        return types.SimpleNamespace(
            scalar_one_or_none=lambda: items[0] if items else None,
            scalars=lambda: types.SimpleNamespace(all=lambda: items))

    async def get(self, model, pk):
        return self._person


def test_meta_market_home_price_until_placed_then_their_money():
    import uuid
    from app.models.person import Person
    p = Person(display_name="Nicole Kioko", state={})
    p.id = uuid.uuid4()
    ident = types.SimpleNamespace(person_id=p.id, channel="facebook", external_id="PSID",
                                  display_name=None, raw_profile=None)
    cur, loc, name, _ = asyncio.run(rt._meta_market(_FakeDB([ident, None, []], p),
                                                    "facebook", "PSID"))
    assert cur == "KES" and loc == {} and name == "Nicole Kioko"
    q = Person(display_name="Amos", state={"location": "Kampala, Uganda"})
    q.id = uuid.uuid4()
    ident2 = types.SimpleNamespace(person_id=q.id, channel="facebook", external_id="PSID",
                                   display_name=None, raw_profile=None)
    cur2, loc2, _, _ = asyncio.run(rt._meta_market(_FakeDB([ident2, None, []], q),
                                                   "facebook", "PSID"))
    assert cur2 == "USD" and loc2["country_iso"] == "UG"


def test_run_turn_passes_placed_into_the_tools_and_the_addenda():
    src = inspect.getsource(rt.run_turn)
    assert 'placed = bool(loc.get("country_iso"))' in src
    assert "read_only=read_only, placed=placed)" in src
    assert "_public_comment_addendum(currency, placed)" in src
    assert "_meta_addendum(currency, placed)" in src
    assert "_tiktok_addendum(currency, placed)" in src
    assert 'if loc.get("country_iso") else "KES"' in src   # a web visitor nobody placed


# ── 5. the rules agree with each other ───────────────────────────────────────

def test_the_prompt_has_one_piece_as_the_default_everywhere():
    for p in (build_system_prompt(country_iso="", currency="KES"),
              build_system_prompt(country_iso="KE", currency="KES"),
              build_system_prompt(country_iso="US", currency="USD")):
        assert "ONE PIECE IS THE DEFAULT" in p
        assert '"Shall I reserve it for you?" is a sale' in p
        assert "quote USD confidently" not in p
        # a photo is priced AS SEEN, never by its catalogue label alone
        assert "naming it as THEY see it" in p


def test_the_unplaced_prompt_quotes_both_doors_and_never_asks():
    p = build_system_prompt(country_iso="", currency="KES")
    assert "Quote our HOME price in KES" in p
    assert "usd_outside_kenya" in p
    assert "we ship worldwide by DHL" in p
    assert 'NEVER ask "are you in Kenya?"' in p
    assert "quote ONLY their money from then on" in p


def test_comment_rules_are_aligned_with_the_owner():
    a = rt._public_comment_addendum("KES", placed=False)
    assert "NOT YET PLACED" in a and "usd_outside_kenya" in a
    assert "KES 13,000, or $130 outside Kenya — we ship worldwide by DHL" in a
    assert "SAY WHAT THEY SEE" in a
    assert "never the bare catalogue label ('Ornate Chasuble — Embroidered')" in a
    assert "ONE PIECE IS THE DEFAULT" in a
    assert "'How many?' is a pull only for goods bought in numbers" in a
    assert "(shall I reserve it for you? which colour? which city for delivery?)" in a
    assert "which colour? how many? which country" not in a
    # the owner's first-contact welcome and the no-daypart rule no longer collide
    assert "FIRST CONTACT — THE WELCOME" in a and "never 'Good morning' under a comment" in a
    assert "the FIRST CONTACT greeting rules do not apply" not in a
    # placed: one currency, no dual line
    b = rt._public_comment_addendum("USD", placed=True)
    assert "NOT YET PLACED" not in b and "SAY WHAT THEY SEE" in b
    # the ZMW example the market tests pin still holds
    assert "ZMW 1,300" in rt._public_comment_addendum("ZMW")


def test_messenger_and_tiktok_rules_carry_the_same_default():
    assert "NOT YET PLACED" in rt._meta_addendum("KES", placed=False)
    assert "NOT YET PLACED" not in rt._meta_addendum("KES", placed=True)
    assert "convert" in rt._meta_addendum("USD").lower()           # placed abroad, unchanged
    assert "NOT YET PLACED" in rt._tiktok_addendum("KES", placed=False)
    for a in (rt._meta_addendum("KES", placed=False), rt._tiktok_addendum("KES", placed=False)):
        assert "ONE PIECE IS THE DEFAULT" in a
        assert "size → quantity → their city" not in a


# ── 6. the item as seen, remembered once per post ────────────────────────────

class _Redis:
    def __init__(self):
        self.store = {}

    async def get(self, k):
        return self.store.get(k)

    async def set(self, k, v, ex=None):
        self.store[k] = v


def test_post_identity_remembers_how_the_item_looks(monkeypatch):
    calls = []

    async def fake_describe(thumb):
        calls.append(thumb)
        return "green chasuble with an African-print stole down the middle and gold piping"
    monkeypatch.setattr(rt, "_describe_post_image", fake_describe)
    r = _Redis()
    prod = {"name": "Ornate Chasuble — Embroidered", "slug": "ornate-chasuble", "hub_product_id": 7}
    asyncio.run(rt._remember_post_product(r, "facebook", "P1", prod, thumb="https://x/y.jpg"))
    known = asyncio.run(rt._recall_post_product(r, "facebook", "P1"))
    assert known["name"] == prod["name"] and known["seen"].startswith("green chasuble")
    # a second identification of the same product keeps the description without
    # paying for the picture again
    asyncio.run(rt._remember_post_product(r, "facebook", "P1", prod, thumb="https://x/y.jpg"))
    assert calls == ["https://x/y.jpg"]
    assert json.loads(r.store[rt._post_product_key("facebook", "P1")])["seen"].startswith("green")
    # no thumb → identity still recorded, just without a look
    asyncio.run(rt._remember_post_product(_Redis(), "facebook", "P2", prod))


def test_describe_post_image_rejects_nonsense_and_never_raises(monkeypatch):
    class _LLM:
        def __init__(self, text): self.text = text
        async def complete(self, *, system, messages, tools):
            return types.SimpleNamespace(text=self.text)
    monkeypatch.setattr(rt.settings, "tier2_vision", True, raising=False)
    monkeypatch.setattr("app.agent.media.load_image_block", lambda url: {"type": "image"})
    monkeypatch.setattr(rt, "build_llm", lambda model=None: _LLM("NONE"))
    assert asyncio.run(rt._describe_post_image("https://x/y.jpg")) == ""
    monkeypatch.setattr(rt, "build_llm", lambda model=None: _LLM("Green chasuble with gold piping."))
    assert asyncio.run(rt._describe_post_image("https://x/y.jpg")) == "Green chasuble with gold piping"
    monkeypatch.setattr(rt, "build_llm", lambda model=None: (_ for _ in ()).throw(RuntimeError("down")))
    assert asyncio.run(rt._describe_post_image("https://x/y.jpg")) == ""
    assert asyncio.run(rt._describe_post_image("")) == ""


def test_the_model_is_told_how_the_post_product_looks():
    src = inspect.getsource(rt.run_turn)
    assert "as it appears in the post:" in src
    assert "never the catalogue label alone" in src
