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
as seen; ONE currency — KES only when the evidence on the customer's record
says Kenya (a captured location, the profile's country, a Kenyan number linked
to the same person), USD otherwise, never two in one quote (owner, later the
same day); and "we ship worldwide by DHL", once.
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


# ── 2. the public price: ONE currency, the commenter's own ───────────────────

def test_public_price_text_is_one_currency(monkeypatch):
    monkeypatch.setattr(rt.settings, "usd_kes_rate", 100, raising=False)
    assert rt._public_price_text(13000, 140, "KES") == "KES 13,000"
    assert rt._public_price_text(13000, 140, "USD") == "$140"      # the hub's own USD
    assert rt._public_price_text(13000, None, "USD") == "$130"     # no hub USD → KES / rate
    assert rt._public_price_text(None, 140, "KES") == "KES 14,000"  # no hub KES → USD × rate
    assert rt._public_price_text(450, 4.5, "USD") == "$4.50"
    assert rt._public_price_text(None, None, "USD") == ""
    for args in ((13000, 140, "KES"), (13000, 140, "USD")):
        assert "outside Kenya" not in rt._public_price_text(*args)


def test_the_engine_prices_the_canned_line_in_the_commenters_money():
    src = inspect.getsource(rt._run_comment_engage)
    assert "price_text = _public_price_text(_kes, _usd, _ccy)" in src
    assert "_ccy = (await _meta_market(_db3, channel, ext))[0]" in src
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


def test_search_catalog_rows_carry_one_currency_only(monkeypatch):
    async def fake_catalog(db, redis):
        return _catalog()
    monkeypatch.setattr(tools.svc, "catalog_items", fake_catalog)
    kenyan = asyncio.run(_search_catalog({"query": "chasuble"},
                                         ToolContext(db=None, redis=None, wa_id="254700",
                                                     currency="KES")))
    row = kenyan["results"][0]
    assert row["price"] == 13000 and row["currency"] == "KES"
    assert "usd_outside_kenya" not in row and "quote_rule" not in kenyan
    assert "usd_outside_kenya" not in row["variants"][0]
    abroad = asyncio.run(_search_catalog({"query": "chasuble"},
                                         ToolContext(db=None, redis=None, wa_id="PSID",
                                                     currency="USD")))
    assert abroad["results"][0]["price"] == 140 and abroad["results"][0]["currency"] == "USD"
    assert not hasattr(ToolContext(db=None, redis=None, wa_id="x"), "placed")


# ── 4. the market: USD until the evidence on their record says Kenya ────────

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


def _person(name="Nicole Kioko", location=None):
    import uuid
    from app.models.person import Person
    p = Person(display_name=name, state={"location": location} if location else {})
    p.id = uuid.uuid4()
    return p


def _ident(p, channel="facebook"):
    return types.SimpleNamespace(person_id=p.id, channel=channel, external_id="PSID",
                                 display_name=None, raw_profile=None)


def _market(results, p):
    return asyncio.run(rt._meta_market(_FakeDB(results, p), "facebook", "PSID"))


def test_meta_market_is_usd_until_the_evidence_says_kenya():
    # A Kenyan-looking name is not evidence: nothing on the record → USD.
    p = _person()
    cur, loc, name, _ = _market([_ident(p), None, [], []], p)
    assert cur == "USD" and loc == {} and name == "Nicole Kioko"
    # Their own words: a captured location.
    q = _person("Amos", "Kampala, Uganda")
    cur, loc, _, _ = _market([_ident(q), None, [], []], q)
    assert cur == "USD" and loc["country_iso"] == "UG"
    k = _person("Grace", "Machakos, Kenya")
    cur, loc, _, _ = _market([_ident(k), None, [], []], k)
    assert cur == "KES" and loc["country_iso"] == "KE"


def test_meta_market_reads_the_merged_whatsapp_number():
    # The same person, merged: this Facebook identity and a WhatsApp identity
    # on a +254 number. The number is the evidence — KES.
    p = _person()
    wa = types.SimpleNamespace(person_id=p.id, channel="whatsapp", external_id="254712345678",
                               display_name=None, raw_profile=None)
    cur, loc, _, _ = _market([_ident(p), None, [_ident(p), wa], []], p)
    assert cur == "KES" and loc["country_iso"] == "KE"
    # A merged Ugandan number is evidence the other way.
    p2 = _person()
    wa2 = types.SimpleNamespace(person_id=p2.id, channel="whatsapp", external_id="256700111222",
                                display_name=None, raw_profile=None)
    cur, loc, _, _ = _market([_ident(p2), None, [wa2], []], p2)
    assert cur == "USD" and loc["country_iso"] == "UG"


def test_meta_market_reads_the_profile_and_a_phone_they_gave_us():
    # The profile's country (set by capture_contact from their words or number).
    p = _person()
    user = types.SimpleNamespace(location=None, name=None, country_iso="KE", country="Kenya",
                                 phone=None)
    cur, loc, _, _ = _market([_ident(p), user, [], []], p)
    assert cur == "KES" and loc == {"country_iso": "KE", "country": "Kenya"}
    # A phone they gave us, on the profile.
    p2 = _person()
    user2 = types.SimpleNamespace(location=None, name=None, country_iso=None, country=None,
                                  phone="+254722000111")
    cur, loc, _, _ = _market([_ident(p2), user2, [], []], p2)
    assert cur == "KES" and loc["country_iso"] == "KE"
    # A phone identifier attached to the person (a number matched or volunteered).
    p3 = _person()
    ph = types.SimpleNamespace(type="phone", value="+254733000111")
    cur, loc, _, _ = _market([_ident(p3), None, [], [ph]], p3)
    assert cur == "KES" and loc["country_iso"] == "KE"


def test_run_turn_and_the_tools_speak_one_currency():
    src = inspect.getsource(rt.run_turn)
    assert 'currency = market_currency(loc.get("country_iso"))' in src
    assert "placed" not in src
    assert "_public_comment_addendum(currency)" in src and "_meta_addendum(currency)" in src


# ── 5. the rules agree with each other ───────────────────────────────────────

def test_the_prompt_has_one_piece_as_the_default_everywhere():
    for p in (build_system_prompt(country_iso="", currency="KES"),
              build_system_prompt(country_iso="KE", currency="KES"),
              build_system_prompt(country_iso="US", currency="USD")):
        assert "ONE PIECE IS THE DEFAULT" in p
        assert '"Shall I reserve it for you?" is a sale' in p
        # a photo is priced AS SEEN, never by its catalogue label alone
        assert "naming it as THEY see it" in p


def test_the_unknown_country_prompt_is_one_currency():
    p = build_system_prompt(country_iso="", currency="USD")
    assert "ONE CURRENCY, NEVER TWO" in p
    assert "quote USD confidently" in p
    assert "we ship worldwide by DHL" in p
    assert 'NEVER ask "are you in Kenya?"' in p
    assert "a Kenyan number on their profile" in p
    assert "Never put two currencies in one quote" in p
    assert "usd_outside_kenya" not in p and "or $140 outside Kenya" not in p


def test_comment_rules_are_aligned_with_the_owner():
    a = rt._public_comment_addendum("KES")
    assert "ONE CURRENCY, NEVER TWO" in a and "Kenyan Shillings (KES)" in a
    assert "Never put two currencies in one reply" in a
    assert "Say once that we ship worldwide by DHL" in a
    assert "usd_outside_kenya" not in a and "outside Kenya" not in a
    assert "SAY WHAT THEY SEE" in a
    assert "never the bare catalogue label ('Ornate Chasuble — Embroidered')" in a
    assert "ONE PIECE IS THE DEFAULT" in a
    assert "'How many?' is a pull only for goods bought in numbers" in a
    assert "(shall I reserve it for you? which colour? which city for delivery?)" in a
    assert "which colour? how many? which country" not in a
    # the owner's first-contact welcome and the no-daypart rule no longer collide
    assert "FIRST CONTACT — THE WELCOME" in a and "never 'Good morning' under a comment" in a
    assert "the FIRST CONTACT greeting rules do not apply" not in a
    b = rt._public_comment_addendum("USD")
    assert "ONE CURRENCY, NEVER TWO" in b and "US Dollars (USD)" in b and "SAY WHAT THEY SEE" in b
    # the ZMW example the market tests pin still holds
    assert "ZMW 1,300" in rt._public_comment_addendum("ZMW")


def test_messenger_and_tiktok_rules_carry_the_same_default():
    for a in (rt._meta_addendum("USD"), rt._tiktok_addendum("USD")):
        assert "One currency at a time — never two in one reply" in a
        assert "convert" in a.lower()                                 # switch to KES on evidence
        assert "NOT YET PLACED" not in a and "usd_outside_kenya" not in a
    for a in (rt._meta_addendum("KES"), rt._tiktok_addendum("KES")):
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
