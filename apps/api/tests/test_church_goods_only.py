"""WE SELL CHURCH GOODS ONLY (owner, 2026-09-25).

Live, Messenger (Jack): "Kasoki 2 na saples" — Neema did not know "saples"
(a surplice) and guessed "vikombe vya ushirika, au divai, au maharagwe?";
"Maharagwe" came back and she took beans as an order line: "pakiti gani
unahitaji?". In the same thread "Bule 1, na white 1" was confirmed as
"nyeusi na nyeupe" — blue became black. "Put guardrails against selling
things that are not church based… decline politely and stop for 12 hours."
"""
import asyncio
import inspect
import types

import pytest

import app.main  # noqa: F401
from app.agent import domain as d
from app.agent import review as rv
from app.agent import runtime as rt
from app.agent.prompt import build_system_prompt
from app.core.config import settings
from app.core.synonyms import canonical

_REAL_REVIEWER = rv.reviewer_verdict      # the module fixture below switches the model reviewer off


class _R:
    """The slice of redis the guard uses."""

    def __init__(self):
        self.store: dict = {}
        self.h: dict = {}

    async def get(self, k):
        return self.store.get(k)

    async def set(self, k, v, ex=None, nx=False):
        if nx and k in self.store:
            return False
        self.store[k] = v
        return True

    async def delete(self, *ks):
        for k in ks:
            self.store.pop(k, None)

    async def incr(self, k):
        self.store[k] = int(self.store.get(k, 0)) + 1
        return self.store[k]

    async def expire(self, k, ttl):
        return True

    async def hincrby(self, k, f, n):
        self.h.setdefault(k, {})
        self.h[k][f] = self.h[k].get(f, 0) + n

    async def hgetall(self, k):
        return dict(self.h.get(k, {}))


LIVE_REPLY = ("Sawa. Kasoki 2 (nyeusi na nyeupe), na maharagwe. Je, maharagwe ni kiasi gani — "
              "pakiti gani unahitaji? Na upo wapi (mji)?")
LIVE_GUESS = "Na saples — je, ni vikombe vya ushirika, au divai, au maharagwe, au kitu kingine?"
DECLINE = ("Samahani, maharagwe hatuuzi — sisi ni mavazi ya kanisa na vifaa vya ushirika tu. "
           "Tunaendelea na kasoki 2 (bluu na nyeupe) na surplice — upo mji gani?")


# ── the live thread ──────────────────────────────────────────────────────────

def test_the_live_beans_reply_is_held_and_the_decline_passes():
    assert d.treats_as_ours(LIVE_REPLY) == ["maharagwe"]
    assert d.treats_as_ours(LIVE_GUESS) == ["maharagwe"]          # a guess sells them too
    assert d.treats_as_ours(DECLINE) == []
    f = rv.domain_issues("Maharagwe", LIVE_REPLY)
    assert f and f[0]["kind"] == "domain" and f[0]["hard"]
    assert "we sell church vestments, communion ware and church supplies ONLY" in f[0]["text"]
    assert rv.domain_issues("Maharagwe", DECLINE) == []
    kinds = {x["kind"]: x["hard"] for x in rv.rule_findings("Maharagwe", LIVE_REPLY, [])}
    assert kinds.get("domain") is True
    assert "domain" in rv.HARD_KINDS and "colour" in rv.HARD_KINDS


def test_saples_is_a_surplice_not_a_guess(monkeypatch):
    assert canonical("Kasoki 2 na saples") == "Kasoki 2 na surplice"
    for w in ("saplis", "sapulisi", "saplice", "Saples", "surplise"):
        assert canonical(w) == "surplice", w
    for w in ("samples", "supplies", "sales", "surplus"):
        assert canonical(w) == w, w
    # the catalogue search lands on the hub row
    from app.agent import tools
    from app.services import promotions as promo

    async def items(db, redis):
        return [{"hub_product_id": 7, "sku": "SUR", "name": "Surplice", "slug": "surplice", "price": 4500,
                 "price_usd": 45, "aliases": [], "description": "White surplice.", "product_type": "simple",
                 "category": "Vestments"},
                {"hub_product_id": 8, "sku": "CAS", "name": "Cassock", "slug": "cassock", "price": 13000,
                 "price_usd": 120, "aliases": [], "description": "", "product_type": "simple",
                 "category": "Vestments"}]

    async def none(redis):
        return None
    monkeypatch.setattr(tools.svc, "catalog_items", items)
    monkeypatch.setattr(promo, "campaign_now", none)
    ctx = tools.ToolContext(db=None, redis=None, wa_id="PSID", channel="messenger", currency="USD", read_only=True)
    r = asyncio.run(tools._search_catalog({"query": "saples"}, ctx))
    assert r["results"] and r["results"][0]["name"] == "Surplice"
    # the prompt names it
    p = " ".join(build_system_prompt(currency="USD").split())
    assert '"saples" / "saplis" / "sapulisi" is a SURPLICE' in p
    assert "sapulisi / saples / saplis (surplice)" in p


def test_bule_is_blue_never_black():
    f = rv.colour_issues("Bule 1,na white 1", "Nzuri — kasoki moja nyeusi, moja nyeupe, zimechukuliwa.")
    assert f and f[0]["kind"] == "colour" and f[0]["hard"]
    assert "they said bule — the reply says nyeusi instead" in f[0]["text"]
    assert rv.colour_issues("Bule 1,na white 1", "Kasoki moja bluu (navy), moja nyeupe — zimechukuliwa.") == []
    assert rv.colour_issues("blue one", "We have navy — the closest to blue.") == []
    assert rv.colour_issues("not black, blue", "Blue it is.") == []            # nothing swapped
    assert rv.colour_issues("blue", "We have black, white, navy, red and green.") == []   # theirs is among them
    assert rv.colour_issues("white", "black and white as you said") == []      # an earlier colour carried
    assert rv.colour_issues("blue", "Which size?") == []                       # no colour said back
    assert rv.colour_issues("blue cassock", "We don't make blue — the closest we have is black.") == []   # theirs named, the nearest offered
    soft = rv.colour_issues("blue cassock", "We don't make that colour — the closest we have is black.")
    assert soft and not soft[0]["hard"]
    kinds = {x["kind"]: x["hard"] for x in rv.rule_findings("Bule 1,na white 1", "kasoki moja nyeusi, moja nyeupe", [])}
    assert kinds == {"colour": True}
    p = " ".join(build_system_prompt(currency="USD").split())
    assert "THEIR COLOUR IS THE COLOUR" in p and '"Bule", "bluu", "blu" is BLUE' in p


# ── reading a message ────────────────────────────────────────────────────────

OFF_ONLY = [
    "Maharagwe", "beans please", "mchele kilo 5", "Do you sell phones?", "Nataka mkopo", "unauza simu?",
    "nataka shamba", "any vacancy?", "I need a job", "natafuta kazi", "do you sell cakes", "sugar mummy",
    "sukari kilo 2", "Hi, I want to buy a laptop", "nataka kuku 10", "girlfriend", "dawa ya malaria",
    "shoes", "boda boda", "airtime please", "unga wa ugali", "do you have cooking oil", "nyama ya mbuzi",
    "I want to buy a car", "gari bei gani", "how much is a fridge", "tv 32 inch", "betting tips", "sportpesa",
    "insurance cover", "I need a loan", "nipe mkopo", "mbolea ya mahindi", "seedlings for sale?",
    "cosmetics and makeup", "wigs", "do you sell jeans", "condoms", "viagra", "bhang", "beer crate",
    "soda 24 pack", "chapati 20", "mandazi", "cake for a birthday", "iphone 13", "laptop charger",
    "sim card", "data bundles", "apartment to let", "bedsitter", "hostel rooms", "internship?", "hire me",
    "mayai 30", "milk 2 litres", "fish fresh", "githeri", "dengu", "tomatoes and onions", "viazi",
]
NEVER = [
    "Kasoki 2 na saples", "Bule 1,na white 1", "nataka kasoki na mkate wa ushirika", "divai ya ushirika bei gani",
    "do you have anointing oil", "candles?", "water bottle price", "Ladies dress price", "how much is the bag",
    "usher belt", "good job guys", "matunda ya roho", "chakula cha Bwana", "mwanakondoo", "where is your shop",
    "hello", "how much", "Nataka bible", "biblia bei", "graduation gowns for 40 students", "choir robes",
    "school uniforms", "mabati", "generator", "we need chairs for the church", "nataka pete", "ring size 8",
    "bread", "mkate", "wine", "oil", "bag", "bell", "viatu vya kanisa", "my phone is 0712345678",
    "phone: 0712 345 678", "0712345678", "whatsapp number?", "send me your phone number",
    "I will call you on phone", "nitumie namba ya simu", "call me on my phone", "kazi nzuri sana",
    "I saw your post while eating beans, nice", "kuku wa kanisa", "cake for church wedding",
    "kasoki 2 na maharagwe", "Communion wafer bread 500", "holy water bottle", "altar wine 2 bottles",
    "the collar size 15", "clergy shirt navy", "chalice gold", "trays for the cups", "kikombe cha Bwana",
    "mishumaa ya madhabahu", "ubani", "chetezo", "kengele", "msalaba wa kifuani", "pete ya askofu",
    "joho la kwaya", "gauni la harusi", "sadaka basket", "kitambaa cha meza ya Bwana", "hymn books",
    "tallit", "skull cap", "mitre for the bishop", "cope and mitre", "stole purple", "alb white",
    "how much is delivery to Kampala", "I am in Uganda", "where are you located", "asante sana",
    "my order status", "M-Pesa paid", "send photos", "size chart", "measurements", "Amen 🙏", "👍",
]


def test_goods_we_do_not_sell_are_read_in_both_languages():
    for t in OFF_ONLY:
        a = d.assess(t)
        assert a["off_only"], (t, a)


def test_church_goods_and_everyday_words_never_trigger_it():
    for t in NEVER:
        a = d.assess(t)
        assert not a["off_only"], (t, a)
    # what is mixed stays mixed: answered, the beans declined by the writer
    assert d.assess("kasoki 2 na maharagwe")["mixed"]
    assert d.assess("cake for church wedding")["mixed"]
    # a long message that merely mentions beans is not an ask
    assert not d.assess("I saw your post while eating beans, nice")["asks"]


# ── the turn ─────────────────────────────────────────────────────────────────

def _turn(r, text, transcript=None, **kw):
    return asyncio.run(d.guard_turn(r, channel="messenger", key="P1", text=text,
                                    transcript=transcript or [], **kw))


def test_a_cold_ask_is_declined_and_the_thread_pauses_twelve_hours():
    r = _R()
    v = _turn(r, "Nataka maharagwe kilo 2", swahili=True)
    assert v["action"] == "decline" and v["goods"] == ["maharagwe"]
    assert "maharagwe hatuuzi" in v["reply"] and "mavazi ya kanisa" in v["reply"]
    assert r.store["guard:pause:messenger:P1"] == "maharagwe"
    # silence for anything that is not church business
    for t in ("hello?", "are you there", "ok", "na mchele?", "😡"):
        assert _turn(r, t) == {"action": "silence", "why": "maharagwe"}, t
    # church goods lift it — a person asking for a cassock is a customer
    assert _turn(r, "sawa, nataka kasoki basi") is None
    assert "guard:pause:messenger:P1" not in r.store
    assert _turn(r, "kasoki 2, bluu na nyeupe") is None
    tally = asyncio.run(d.read_tally(r))
    assert tally["declined"] == 1 and tally["paused"] == 1 and tally["silenced"] == 5 and tally["lifted"] == 1
    assert tally["paused:messenger"] == 1
    assert d.pause_seconds() == 12 * 3600 and settings.offdomain_pause_hours == 12


def test_with_church_business_in_play_the_first_ask_is_declined_in_the_reply():
    r = _R()
    transcript = [{"role": "user", "content": "Kasoki 2 na saples"},
                  {"role": "assistant", "content": "Nzuri. Kasoki 2 na surplice — rangi gani?"},
                  {"role": "user", "content": "Bule 1, na white 1"}]
    v = _turn(r, "Maharagwe", transcript=transcript, swahili=True)
    assert v["action"] == "note" and v["goods"] == ["maharagwe"]
    assert "NOT OUR GOODS" in v["note"] and "carry on with the church items" in v["note"]
    assert "guard:pause:messenger:P1" not in r.store
    # a second ask on the same thread pauses it
    v = _turn(r, "na mchele pia", transcript=transcript, swahili=True)
    assert v["action"] == "decline" and r.store["guard:pause:messenger:P1"] == "mchele"
    # a mixed message is answered, the beans declined by the writer
    r2 = _R()
    v = _turn(r2, "kasoki 2 na maharagwe")
    assert v["action"] == "note" and "guard:pause:messenger:P1" not in r2.store
    # under a post there is no business in play: declined and paused at once, in one public line
    r3 = _R()
    v = asyncio.run(d.guard_turn(r3, channel="facebook", key="C1", text="do you sell phones?",
                                 transcript=[{"role": "user", "content": "how much is the cassock"}],
                                 public_comment=True))
    assert v["action"] == "decline" and v["reply"] == "Sorry, we don't sell phones — we make church vestments and communion ware only 🙏"
    assert r3.store["guard:pause:facebook:C1"] == "phones"


def test_an_ordinary_message_passes_the_guard_untouched():
    r = _R()
    for t in NEVER:
        if d.assess(t)["mixed"]:
            continue
        assert _turn(r, t) is None, t
    assert r.store == {}


def test_the_guard_can_be_switched_off(monkeypatch):
    monkeypatch.setattr(settings, "church_goods_guard", False, raising=False)
    assert _turn(_R(), "Nataka maharagwe") is None


def test_the_decline_fits_what_they_asked():
    assert d.category_of(["maharagwe"]) == "food" and d.category_of(["mkopo"]) == "money"
    assert d.category_of(["a job"]) == "jobs" and d.category_of(["girlfriend"]) == "other"
    lines = [d.decline_line(["beans"]), d.decline_line(["maharagwe"], swahili=True),
             d.decline_line(["mkopo"], swahili=True), d.decline_line(["a loan"]),
             d.decline_line(["a job"]), d.decline_line(["natafuta kazi"], swahili=True),
             d.decline_line(["girlfriend"]), d.decline_line(["girlfriend"], swahili=True, public=True),
             d.decline_line(["phones"], public=True), d.decline_line(["maharagwe"], swahili=True, public=True)]
    assert "we don't sell beans" in lines[0] and "Bethany House" in lines[0]
    assert "maharagwe hatuuzi" in lines[1] and "kasoki, sapulisi, majoho, kola" in lines[1]
    assert "mkopo hatutoi" in lines[2] and "we don't offer a loan" in lines[3]
    assert "no vacancies" in lines[4] and "hatuna nafasi za kazi" in lines[5]
    assert "can't help with that" in lines[6] and "hatuwezi kusaidia" in lines[7]
    assert lines[8] == "Sorry, we don't sell phones — we make church vestments and communion ware only 🙏"
    assert lines[9] == "Samahani, maharagwe hatuuzi — sisi ni mavazi ya kanisa na vifaa vya ushirika tu 🙏"
    # every line reads as a decline to the verifier, so none is ever held
    for ln in lines:
        assert d.declines(ln), ln
        assert rv.domain_issues("x", ln) == [], ln
    note = d.flag_note(["maharagwe"])
    assert "asked here for maharagwe" in note and "silent on this thread for 12 hours" in note
    assert "under our post" in d.flag_note(["phones"], public=True)


# ── the wiring: every channel, before the writer ─────────────────────────────

def test_run_turn_asks_the_guard_before_the_writer():
    src = inspect.getsource(rt.run_turn)
    i = src.index("_dom.guard_turn(")
    assert i < src.index("_fx_rates: dict = {}") < src.index("await llm.complete(")
    assert 'if not read_only and not scribe_only and _gate_applies(user_text):' in src[:i]
    assert 'if _verdict and _verdict.get("action") == "silence":' in src and 'return ""' in src
    assert 'if _verdict and _verdict.get("action") == "decline":' in src and 'return _verdict["reply"]' in src
    assert 'tail += _verdict["note"]' in src
    assert "_flag_guard(db, channel, key," in src
    assert '"guard": "silence"' in src and '"guard": "decline"' in src
    # no "typing…" on a paused Messenger thread; a paused commenter hears no canned line
    meta = inspect.getsource(rt._run_and_send_meta)
    assert "not await _guard_paused(redis, channel, external_id)" in meta
    engine = inspect.getsource(rt)
    assert 'if _facts.get("guard") == "silence":' in engine
    # the empty reply the guard returns is silence on every channel
    assert 'if not (reply or "").strip():' in inspect.getsource(rt._run_and_send)


def test_the_prompt_the_reviewer_and_the_rewrite_carry_the_rule(monkeypatch):
    p = " ".join(build_system_prompt(currency="USD").split())
    assert "WE SELL CHURCH GOODS ONLY" in p
    assert "ask NOTHING about it (no quantity, no packet, no price), never add it to an order" in p
    assert "NEVER guess at things we do not sell" in p
    llm = types.SimpleNamespace(calls=[])

    async def complete(system, messages, tools=None, **kw):
        llm.calls.append(messages[0]["content"])
        return types.SimpleNamespace(text="verdict=pass | issues=-")
    llm.complete = complete
    monkeypatch.setattr(rt, "build_llm", lambda model=None, **kw: llm)
    monkeypatch.setattr(rv, "reviewer_verdict", _REAL_REVIEWER)
    asyncio.run(rv.review_reply("Maharagwe", DECLINE, [], mode="dm"))
    sent = llm.calls[-1]
    assert "7. NOT OUR GOODS" in sent and "A one-line polite decline PASSES" in sent
    assert "a different colour (they said blue / 'bule' / 'bluu', it confirms black)" in sent
    block = rv.rewrite_block(["x"], LIVE_REPLY, [], "KES", [], mode="dm")
    assert "declined in ONE short line, asked nothing about, and never added to the order" in block
    assert "'bule' / 'bluu' is BLUE" in block
    assert "church goods only" in rv.review_notes(["x"])


def test_health_reports_what_the_guard_did_today():
    from app.routers import health
    src = inspect.getsource(health)
    assert 'out["guard"] = {"declined"' in src and "read_tally" in src
    r = _R()
    asyncio.run(d.record(r, "declined", "whatsapp"))
    asyncio.run(d.record(r, "nonsense"))
    assert asyncio.run(d.read_tally(r)) == {"declined": 1, "declined:whatsapp": 1}
    assert asyncio.run(d.read_tally(None)) == {}


# ── the gate end to end: the live thread, corrected before it is sent ───────


@pytest.fixture(autouse=True)
def _rules_only(monkeypatch):
    async def none(*a, **k):
        return None
    monkeypatch.setattr(rv, "reviewer_verdict", none)


class _Writer:
    def __init__(self, *texts):
        self.texts = list(texts)
        self.calls = 0

    async def complete(self, system, messages, tools=None, **kw):
        self.calls += 1
        return types.SimpleNamespace(text=self.texts.pop(0) if self.texts else "")


class _Ctx:
    def __init__(self, seen=None):
        self.seen_products = list(seen or [])
        self.read_only = True


CASSOCK = {"name": "Cassock", "slug": "cassock", "price": 13000, "price_usd": 120, "aliases": [],
           "description": "Made to your measurements.", "product_type": "variable", "is_producible": True,
           "variants": [{"name": "Black", "attributes": {"Colour": "Black"}, "price_kes": 13000, "price_usd": 130},
                        {"name": "White", "attributes": {"Colour": "White"}, "price_kes": 13000, "price_usd": 200},
                        {"name": "Navy", "attributes": {"Colour": "Navy"}, "price_kes": 12000, "price_usd": 120}]}
SURPLICE = {"name": "Surplice", "slug": "surplice", "price": 4500, "price_usd": 45, "aliases": [],
            "description": "White surplice.", "product_type": "simple"}


def _gate(reply, *, ask, seen=(), writer_texts=(), transcript=None, monkeypatch, redis=None, public=False):
    async def no_facts(ctx, user_text, tool_log):
        return []
    monkeypatch.setattr(rt, "_facts_for_ask", no_facts)

    async def no_flag(db, channel, key, issues, draft):
        return None
    monkeypatch.setattr(rt, "_flag_held_reply", no_flag)
    return asyncio.run(rt._gate_turn_reply(
        reply, user_text=ask, transcript=transcript or [{"role": "user", "content": ask}],
        tool_log=[], ctx=_Ctx(seen), currency="KES", channel="facebook" if public else "messenger",
        public_comment=public, llm=_Writer(*writer_texts), sys_blocks=["SYSTEM"], redis=redis, db=None,
        key="K", fx=None, closer=False))


def test_the_live_beans_reply_is_rewritten_into_a_decline_that_sells_on(monkeypatch):
    fixed = ("Samahani, maharagwe hatuuzi — sisi ni mavazi ya kanisa na vifaa vya ushirika tu 🙏 "
             "Tunaendelea na kasoki 2 (bluu na nyeupe) na surplice. Upo mji gani?")
    out = _gate(LIVE_REPLY, ask="Maharagwe", seen=[CASSOCK, SURPLICE], writer_texts=[fixed], monkeypatch=monkeypatch)
    assert out == (fixed, [], "rewritten")
    # the guess that put beans in the customer's mouth is caught the same way
    fixed2 = "Na surplice — vazi jeupe la juu ya kasoki, KES 4,500. Ni hiyo unayomaanisha kwa 'saples'?"
    out = _gate(LIVE_GUESS, ask="Kaski 2 na saples", seen=[CASSOCK, SURPLICE], writer_texts=[fixed2], monkeypatch=monkeypatch)
    assert out == (fixed2, [], "rewritten")
    # a writer that keeps selling beans is held: the customer gets the holding line, not the beans
    out = _gate(LIVE_REPLY, ask="Maharagwe", seen=[CASSOCK], writer_texts=[LIVE_REPLY], monkeypatch=monkeypatch)
    assert out[2] == "held" and "maharagwe" not in out[0].lower() and out[1]
    assert any("church supplies ONLY" in i for i in out[1])
    # the reply that declines and sells on passes untouched
    out = _gate(fixed, ask="Maharagwe", seen=[CASSOCK, SURPLICE], monkeypatch=monkeypatch)
    assert out == (fixed, [], "pass")


def test_bule_becomes_blue_before_it_is_sent(monkeypatch):
    wrong = "Nzuri — kasoki moja nyeusi, moja nyeupe, zimechukuliwa. Na surplice — je, unahitaji ngapi?"
    right = "Nzuri — kasoki moja bluu (navy yetu ndiyo ya karibu zaidi), moja nyeupe, zimechukuliwa. Na surplice — ngapi?"
    out = _gate(wrong, ask="Bule 1,na white 1", seen=[CASSOCK], writer_texts=[right], monkeypatch=monkeypatch)
    assert out == (right, [], "rewritten")
    out = _gate(right, ask="Bule 1,na white 1", seen=[CASSOCK], monkeypatch=monkeypatch)
    assert out == (right, [], "pass")


# (ask, reply, seen, expect) — expect: pass (never held: no hard finding; a soft
# note may still ask for a better draft) | hard (held unless rewritten)
BATTERY = [
    ("Maharagwe", LIVE_REPLY, [CASSOCK], "hard"),
    ("Maharagwe", DECLINE, [CASSOCK], "pass"),
    ("Kaski 2 na saples", LIVE_GUESS, [CASSOCK], "hard"),
    ("Bule 1,na white 1", "kasoki moja nyeusi, moja nyeupe", [CASSOCK], "hard"),
    ("Bule 1,na white 1", "kasoki moja bluu (navy), moja nyeupe", [CASSOCK], "pass"),
    ("nataka mchele", "Samahani, mchele hatuuzi — sisi ni mavazi ya kanisa na vifaa vya ushirika tu.", [], "pass"),
    ("do you sell phones", "Yes! Phones from KES 10,000 — which model?", [], "hard"),
    ("kuku wa kanisa", "Kuku 10 ni KES 5,000 — tuletee oda.", [], "hard"),
    ("beans and a cassock", "The Cassock is KES 13,000 — beans we don't sell, we're a church vestment maker. Colour?", [CASSOCK], "pass"),
    ("navy cassock", "The Cassock in navy is KES 12,000 — your measurements?", [CASSOCK], "pass"),
    ("do you have rice?", "We don't stock rice — we're a church supplies store. Anything for the altar?", [], "pass"),
    ("cooking oil", "Anointing oil we have — the Anointing oil, KES 500.", [{"name": "Anointing oil", "price": 500, "price_usd": 5}], "pass"),
    ("I need a loan", "Sorry, we don't offer loans — we make church vestments and communion ware only.", [], "pass"),
    ("I need a loan", "Sure — loans from KES 5,000, what amount?", [], "hard"),
    ("sugar 2kg and a stole", "Sugar KES 300 and the stole KES 3,000.", [{"name": "Single Sided Stole", "price": 3000, "price_usd": 30}], "hard"),
    ("communion bread 500", "Communion Wafer Bread 500PCS is KES 1,500.", [{"name": "Communion Wafer Bread 500PCS", "price": 1500, "price_usd": 15}], "pass"),
    ("altar wine", "Altar Wine is KES 1,200 a bottle.", [{"name": "Altar Wine", "price": 1200, "price_usd": 12}], "pass"),
    ("red stole", "The Single Sided Stole comes in red — KES 3,000.", [{"name": "Single Sided Stole", "price": 3000, "price_usd": 30}], "pass"),
    ("red stole", "The Single Sided Stole in green is KES 3,000.", [{"name": "Single Sided Stole", "price": 3000, "price_usd": 30}], "hard"),
    ("bluu cassock", "We don't make bluu — the closest is navy, KES 12,000.", [CASSOCK], "pass"),
    ("white cassock and a phone charger", "White Cassock KES 13,000. Chargers we don't sell.", [CASSOCK], "pass"),
    ("nataka kasoki nyeusi", "Kasoki nyeusi ni KES 13,000 — vipimo vyako?", [CASSOCK], "pass"),
    ("nataka kasoki nyeusi", "Kasoki nyeupe ni KES 13,000 — vipimo vyako?", [CASSOCK], "hard"),
]


def test_the_rules_battery_never_holds_a_good_reply_nor_passes_a_bad_one():
    for ask, reply, seen, expect in BATTERY:
        v = asyncio.run(rv.review_reply(ask, reply, seen, mode="dm", currency="KES"))
        if expect == "pass":
            assert not v["hard"], f"FALSE HOLD on {ask!r}: {v['hard']}"
        else:
            assert v["hard"], f"FALSE PASS on {ask!r}: {v}"
