"""The cassock ladder (owner, 2026-10-30): "a clear indication of cassock set,
cassock, and complete cope and cassock set. We start for a cassock by saying
it's 13000, consider all other prices for different countries, then put a
follow-up post to say we have a cassock set which has a cassock, stole,
cincture belt, shirt and collar, and a cope cassock set which adds cope,
mitre and pectoral cross." The second message is priced from the hub rows,
in the customer's money, once a month per customer."""
import asyncio
import types

import app.main  # noqa: F401 — registers models before runtime import
import app.agent.runtime as runtime
from app.agent import prompt
from app.services import cassock_ladder as ladder

CASSOCK = {"name": "Cassock", "slug": "cassock", "price": 13000, "price_kes": 13000,
           "price_usd": 130, "prices": {"KES": 13000, "USD": 130, "ZMW": 2600}}
RED = {"name": "Red Apostolic Cassock", "slug": "red-apostolic-cassock", "price": 16400,
       "price_kes": 16400, "price_usd": 170, "prices": {"KES": 16400, "USD": 170, "ZMW": 3280}}
SET = {"name": "Cassock Set", "slug": "cassock-set", "price": 19500, "price_kes": 19500,
       "price_usd": 200, "prices": {"KES": 19500, "USD": 200, "ZMW": 3900}}
COPE = {"name": "Cope — Complete Set", "slug": "cope-complete-set", "price": 45000,
        "price_kes": 45000, "price_usd": 450, "prices": {"KES": 45000, "USD": 450, "ZMW": 9000}}
CATALOG = [CASSOCK, RED, SET, COPE]


def _ctx(currency="KES", seen=(CASSOCK,)):
    return types.SimpleNamespace(currency=currency, usd_rate=100, seen_products=list(seen))


class _Redis:
    def __init__(self):
        self.kv = {}

    async def get(self, k):
        return self.kv.get(k)

    async def set(self, k, v, nx=False, ex=None):
        if nx and k in self.kv:
            return False
        self.kv[k] = v
        return True

    def __getattr__(self, name):
        async def _noop(*a, **kw):
            return None
        return _noop


def test_a_priced_cassock_gets_the_ladder_and_a_set_never_does():
    assert ladder.applies([CASSOCK], "how much is a cassock?", "Our cassock is KES 13,000, made to measure.")
    assert ladder.applies([RED], "Can you check the price of a product?",
                          "The Red Apostolic Cassock is $170, made to order in Nairobi.")
    # Already about a set — the rules quote the set itself.
    assert not ladder.applies([SET], "how much is the cassock set?", "Our Cassock Set is KES 19,500.")
    assert not ladder.applies([CASSOCK], "I want the full set", "Our cassock is KES 13,000.")
    assert not ladder.applies([CASSOCK], "cassock?", "The cassock alone is KES 13,000; the set is KES 19,500.")
    # No price said, or no cassock this turn.
    assert not ladder.applies([CASSOCK], "cassock?", "Which colour would you like for the cassock?")
    assert not ladder.applies([SET, COPE], "cope?", "Our cope is $450.")


def test_the_sets_are_priced_from_the_hub_in_their_money():
    kes = ladder.message(CATALOG, _ctx("KES"))
    assert "Cassock Set" in kes and "KES 19,500" in kes
    assert "Cope & Cassock Set" in kes and "KES 45,000" in kes
    assert "stole, cincture belt, clergy shirt and collar" in kes
    assert "cope, mitre and pectoral cross" in kes
    # One question, at the end, asking for the order.
    assert kes.count("?") == 1 and kes.rstrip().endswith("I'll start your order.")
    assert kes.index("Cassock Set — KES 19,500") < kes.index("Cope & Cassock Set — KES 45,000")
    usd = ladder.message(CATALOG, _ctx("USD"))
    assert "$200" in usd and "$450" in usd and "KES" not in usd
    zmw = ladder.message(CATALOG, _ctx("ZMW"))
    assert "3,900" in zmw and "9,000" in zmw
    assert "*Cassock Set — KES 19,500:*" in kes                    # WhatsApp bold
    plain = ladder.message(CATALOG, _ctx("KES"), bold=False)         # Messenger / Instagram
    assert "*" not in plain and "Cassock Set — KES 19,500:" in plain
    sw = ladder.message(CATALOG, _ctx("KES"), swahili=True)
    assert "seti kamili" in sw and "KES 19,500" in sw and sw.count("?") == 1
    # A missing or unpriced row is no ladder — never one with a gap.
    assert ladder.message([CASSOCK, SET], _ctx()) is None
    assert ladder.message([CASSOCK, SET, dict(COPE, price=0, price_kes=0, prices={})], _ctx()) is None


def test_once_a_month_per_customer():
    r = _Redis()

    def go(contact="254700000001"):
        return asyncio.run(ladder.follow_up(r, channel="whatsapp", contact=contact, catalog=CATALOG,
                                            ctx=_ctx(), user_text="cassock price?",
                                            reply="Our cassock is KES 13,000."))
    assert go() and go() is None and go("254700000002")


def test_the_rules_name_the_three_steps_and_one_figure():
    rules = " ".join(prompt.build_system_prompt(country_iso="KE", currency="KES").split())
    assert "THE CASSOCK LADDER" in rules
    assert "Cope & Cassock Set (the Cassock Set" in rules and "pectoral cross" in rules
    assert "never two figures for one garment" in rules
    assert "End it WITHOUT a question" in rules


# ── the second message, sent as its own bubble ──────────────────────────────

def test_whatsapp_sends_the_ladder_as_a_second_message(monkeypatch):
    from app.services import n8n_bridge as svc
    sent, saved = [], []
    monkeypatch.setattr(runtime, "FOLLOW_UP_DELAY_S", 0)

    async def _turn(db, redis, wa_id, text, llm, media=None, deferred=False, turn_facts=None):
        turn_facts["follow_up"] = "We also have the Cassock Set — … at KES 19,500 …"
        return "Our cassock is KES 13,000, made to measure in your colour."

    async def _send(wa_id, text):
        sent.append(text)
        return f"wamid.{len(sent)}"

    async def _save(db, redis, wa_id, text, waba_msg_id=None, **kw):
        saved.append((text, waba_msg_id))

    async def _no(*a, **kw):
        return False

    class _Sess:
        async def __aenter__(self):
            return object()

        async def __aexit__(self, *a):
            return False
    monkeypatch.setattr("app.database.AsyncSessionLocal", _Sess)
    monkeypatch.setattr(runtime, "run_turn", _turn)
    monkeypatch.setattr(runtime, "build_llm", lambda **kw: object())
    monkeypatch.setattr(runtime, "_is_echo", _no)
    monkeypatch.setattr(svc, "_send_waba", _send)
    monkeypatch.setattr(svc, "save_outbound_message", _save)
    assert asyncio.run(runtime._run_and_send(_Redis(), "254700000001", "how much is a cassock?")) is True
    assert sent == ["Our cassock is KES 13,000, made to measure in your colour.",
                    "We also have the Cassock Set — … at KES 19,500 …"]
    assert [w for _t, w in saved] == ["wamid.1", "wamid.2"]


def test_a_turn_with_no_second_sender_gets_it_as_the_last_paragraph(monkeypatch):
    from tests.test_cost_circuit_breaker import _turn_db

    async def _cat(db, redis):
        return CATALOG
    monkeypatch.setattr("app.services.n8n_bridge.catalog_items", _cat)

    async def fake_run_tool(name, args, ctx):
        ctx.seen_products.append(CASSOCK)
        return {"count": 1, "results": [{"name": "Cassock", "price": 13000}]}
    monkeypatch.setattr(runtime, "run_tool", fake_run_tool)

    async def _pass(reply, **kw):
        return reply, [], "pass"
    monkeypatch.setattr(runtime, "_gate_turn_reply", _pass)
    from app.agent.llm import FakeLLM

    def llm():
        return FakeLLM([{"tools": [{"name": "search_catalog", "input": {"query": "cassock"}}]},
                        {"text": "Our cassock is KES 13,000, made to measure in your colour."}])
    facts: dict = {}
    out = asyncio.run(runtime.run_turn(_turn_db(), _Redis(), "254700000001", "how much is a cassock?",
                                       llm(), turn_facts=facts))
    assert out == "Our cassock is KES 13,000, made to measure in your colour."
    assert "Cassock Set — KES 19,500" in facts["follow_up"]
    out = asyncio.run(runtime.run_turn(_turn_db(), _Redis(), "254700000002", "how much is a cassock?",
                                       llm()))
    assert out.startswith("Our cassock is KES 13,000") and "\n\nYou can also take it as a complete set:" in out


def test_one_price_on_every_variant_is_the_product_s_price():
    """The Red Apostolic Cassock: KES 21,000 / $210 on the product, KES 16,400
    / $170 on all its variants — the variant is what an order is charged."""
    from app.core.hub_client import _apply_variant_pricing
    v = {"price_kes": 16400, "price_usd": 170, "prices": {"KES": 16400, "USD": 170, "ZMW": 3280}}
    prod = {"slug": "red-apostolic-cassock", "price": 21000, "price_kes": 21000, "price_usd": 210,
            "prices": {"KES": 21000, "USD": 210, "ZMW": 4200},
            "variants": [dict(v, is_default=True), dict(v), dict(v)]}
    _apply_variant_pricing(prod)
    assert (prod["price"], prod["price_kes"], prod["price_usd"]) == (16400, 16400, 170)
    assert prod["prices"]["ZMW"] == 3280
    # Variants that differ keep the product's own price and a range.
    mixed = {"slug": "cassock", "price": 12000, "price_kes": 12000, "price_usd": 120,
             "prices": {"KES": 12000, "USD": 120},
             "variants": [{"price_kes": 12000, "price_usd": 120, "prices": {"KES": 12000}},
                          {"price_kes": 13000, "price_usd": 130, "prices": {"KES": 13000}}]}
    _apply_variant_pricing(mixed)
    assert mixed["price_kes"] == 12000 and (mixed["price_min_kes"], mixed["price_max_kes"]) == (12000, 13000)
