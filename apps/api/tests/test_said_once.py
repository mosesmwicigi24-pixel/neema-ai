"""SAID ONCE (audit, 2026-11-05): a set's contents, a price, our address are
told to a customer once; from then on the next turn is reminded, and the
search row says "the set" instead of listing the pieces again."""
import asyncio

import app.main  # noqa: F401 — registers models
from app.agent import said_once as so

SET = {"slug": "cassock-set", "name": "Cassock Set", "price": 19500, "price_usd": 200,
       "description": "Complete cassock outfit in one order — cassock, stole, belt, "
                      "straight collar shirt and a 12 inch clergy collar."}
MITRE = {"slug": "mitre", "name": "Mitre", "price": 5500, "price_usd": 60, "description": "A bishop's mitre."}
CATALOG = [SET, MITRE, {"slug": "cassock", "name": "Cassock", "price": 13000, "price_usd": 120},
           {"slug": "stole", "name": "Single Sided Stole", "price": 2500, "price_usd": 25},
           {"slug": "belt", "name": "Cincture Belt", "price": 2200, "price_usd": 30},
           {"slug": "shirt", "name": "Straight Collar Shirt", "price": 2500, "price_usd": 30}]


class _Redis:
    def __init__(self):
        self.h, self.ttl = {}, {}

    async def hset(self, k, f, v):
        self.h.setdefault(k, {})[f] = v

    async def hgetall(self, k):
        return dict(self.h.get(k, {}))

    async def expire(self, k, s):
        self.ttl[k] = s


def test_the_set_contents_and_its_price_are_noticed_once_said():
    reply = ("This is our Cassock Set at KES 19,500, everything included: the cassock, a stole, "
             "a belt, a straight collar shirt and a 12 inch clergy collar. Which colour?")
    facts = dict(so.facts_in_reply(reply, [SET], CATALOG, currency="KES"))
    assert facts["set:cassock-set"].startswith("Cassock Set comes with cassock, stole")
    assert facts["price:cassock-set"] == "Cassock Set at 19,500"
    # naming the set without listing it is not "contents told"
    facts = dict(so.facts_in_reply("The Cassock Set is KES 19,500.", [SET], CATALOG, currency="KES"))
    assert "set:cassock-set" not in facts and "price:cassock-set" in facts
    # a plain row has no contents; its price is still noted
    facts = dict(so.facts_in_reply("The Mitre is KES 5,500.", [MITRE], CATALOG, currency="KES"))
    assert list(facts) == ["price:mitre"]


def test_our_address_and_payment_lines_are_noticed():
    assert dict(so.facts_in_reply("We're at Sonalux Building, Moi Avenue.", [], CATALOG)) == {"address": "our shop address"}
    assert "payment" in dict(so.facts_in_reply("Pay to M-Pesa 0727 891 989.", [], CATALOG))
    assert so.facts_in_reply("Thank you, God bless.", [], CATALOG) == []


def test_the_next_turn_is_reminded_and_the_row_says_the_set():
    r = _Redis()
    reply = ("Our Cassock Set is KES 19,500: the cassock, a stole, a belt, a straight collar shirt "
             "and a 12 inch clergy collar.")
    asyncio.run(so.remember(r, "whatsapp", "254700000001",
                            so.facts_in_reply(reply, [SET], CATALOG, currency="KES")))
    said = asyncio.run(so.told(r, "whatsapp", "254700000001"))
    assert set(said) == {"set:cassock-set", "price:cassock-set"}
    n = so.note(said)
    assert "ALREADY TOLD THIS CUSTOMER" in n and "say 'the set'" in n and "Cassock Set at 19,500" in n
    assert so.set_keys(said) == frozenset({"set:cassock-set"})
    assert r.ttl["said:whatsapp:254700000001"] == so.TTL
    assert so.note({}) == "" and asyncio.run(so.told(None, "whatsapp", "x")) == {}


def test_the_search_row_marks_a_set_already_told(monkeypatch):
    from app.agent.tools import ToolContext, _search_catalog

    async def _cat(db, redis):
        return CATALOG
    monkeypatch.setattr("app.services.messaging.catalog_items", _cat)
    ctx = ToolContext(db=None, redis=None, wa_id="254700000001", currency="KES",
                      said=frozenset({"set:cassock-set"}))
    out = asyncio.run(_search_catalog({"query": "cassock set"}, ctx))
    rows = {r["name"]: r for r in out.get("results", [])}
    assert rows["Cassock Set"]["set"]["already_told"] is True
    assert "do not list the pieces again" in rows["Cassock Set"]["set"]["note"]
    fresh = asyncio.run(_search_catalog({"query": "cassock set"},
                                        ToolContext(db=None, redis=None, wa_id="x", currency="KES")))
    assert "already_told" not in {r["name"]: r for r in fresh["results"]}["Cassock Set"]["set"]


def test_run_turn_reads_the_note_and_records_the_reply():
    import inspect
    from app.agent import runtime
    src = inspect.getsource(runtime.run_turn)
    assert src.index("_so.told(redis, channel, key)") < src.index("llm.complete(system=sys_blocks")
    assert "said=frozenset(k for k in _said" in src
    assert src.index("_so2.remember(redis, channel, key, _facts)") > src.index("_gate_turn_reply(")
