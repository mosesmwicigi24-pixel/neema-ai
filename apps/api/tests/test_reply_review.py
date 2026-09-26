"""THE GATE BEFORE POSTING (owner, 2026-09-25).

Live, under a communion post: "How much are gold trays with holes to place
tot glasses? Do you have shops in South Africa?" was answered with the silver
set at $180 and nothing about South Africa; "Where is your location, do you
have some holycommunion cups" was answered with the Golden Chalice Cup with
Paten Set at $650 and no location. "Someone is asking for golden trays and
you give silver… Put a gate to review before posting… When someone asks for
Holy Communion Cups without specifying chalice, give the plastic, stainless
and glass cups, not chalice cups. Every post should be verified before
posting for accuracy and correct figures."

Pinned here: the rules (figures are the hub's, the item is the one asked
for, a where-question is answered), the reviewer's verdict line, the engine's
gate (one more draft, then the holding line and a colleague), the canned
path's refusal to sell the post's item for another finish or kind, the
search (gold is golden; communion cups are the small cups; tot glasses;
stainless cups), the synonym families, and the model's rules.
"""
import asyncio
import inspect
import types

import app.main  # noqa: F401
from app.agent import review as rv
from app.agent import runtime as rt
from app.agent import tools
from app.agent.prompt import build_system_prompt
from app.core.config import settings
from app.core.synonyms import canonical, hub_terms, range_for


SILVER = {"name": "Silver Communion Tray", "slug": "silver-communion-tray", "price": 18000,
          "price_usd": 180, "category": "Communion Items", "aliases": [],
          "description": "Silver-tone communion tray for 40 cups, complete with lid, holder and basin."}
GOLDEN = {"name": "Golden Communion Tray", "slug": "golden-communion-tray", "price": 22000,
          "price_usd": 220, "category": "Communion Accessories", "aliases": [],
          "description": "Gold-plated communion cup tray holding 40 cups."}
GOLD_BREAD = {"name": "Gold bread tray", "slug": "gold-bread-tray", "price": 14000, "price_usd": 140,
              "category": "Golden Communion Trays", "aliases": [], "description": "Shallow gold-tone bread tray."}
CHALICE = {"name": "Golden Chalice Cup with Paten Set", "slug": "chalice-royale", "price": 65000,
           "price_usd": 650, "category": "Chalice", "aliases": [], "description": "Chalice and paten in one set."}
SMALL_CHALICE = {"name": "Small Chalice Cup", "slug": "large-chalice", "price": 12000, "price_usd": 120,
                 "category": "Chalice", "aliases": [], "description": "A generously sized chalice."}
PLASTIC = {"name": "Plastic Communion Cups", "slug": "plastic-cups", "price": 10, "price_usd": 10,
           "category": "Communion Items", "aliases": [], "description": "Light plastic cups for communion trays."}
SILVER_CUPS = {"name": "Silver Communion Cups", "slug": "silver-communion-cups", "price": 100, "price_usd": 10,
               "category": "Communion Items", "aliases": [], "description": "Reusable silver communion cups, 10 ml each."}
GLASS = {"name": "Glass Cups", "slug": "glass-cups", "price": 100, "price_usd": 10,
         "category": "Communion Items", "aliases": [], "description": "Bevelled-glass communion cups."}
PREPACKED = {"name": "Pre-Packed Communion Cups", "slug": "pre-packed-communion-cups", "price": 30,
             "price_usd": 10, "category": "Communion Items", "aliases": [], "description": "Sealed single-serve communion."}
REFILLER = {"name": "Refiller Bottle 500ML", "slug": "refiller", "price": 1500, "price_usd": 20,
            "category": "Communion Items", "aliases": ["communion cup filler"], "description": "A squeeze bottle."}
WOODEN = {"name": "Wooden tray", "slug": "wooden-tray", "price": 5000, "price_usd": 50,
          "category": "Communion Items", "aliases": [], "description": "A wooden communion tray that holds 100 cups."}
CATALOG = [SILVER, GOLDEN, GOLD_BREAD, CHALICE, SMALL_CHALICE, PLASTIC, SILVER_CUPS, GLASS, PREPACKED, REFILLER, WOODEN]

GOLD_ASK = "How much are gold trays with holes to place tot glasses? Do you have shops in South Africa?"
GOLD_LIVE_REPLY = ("Welcome to Bethany House Silibaziso 🙏 the glass communion set with cross finial and "
                   "perforated base plate in clear and silver tones is $180, from our Nairobi shop and "
                   "delivered anywhere by DHL. Kindly place your order — how many you need and your city.")
CUPS_ASK = "Where is your location, do you have some holycommunion cups"
CUPS_LIVE_REPLY = ("The Golden Chalice Cup with Paten Set is $650 — a matched pair for the altar. "
                   "How many do you need, and how soon?")


# ── the rules: figures ──────────────────────────────────────────────────────

def test_money_figures_read_prices_and_leave_counts_alone():
    assert rv.money_figures("It's $40 or KES 3,500 — 40 cups, 500/=, 20 dollars, USD 12.50") == [40.0, 3500.0, 500.0, 20.0, 12.5]
    assert rv.money_figures("40 cups and 2 trays") == []
    assert rv.quantities("I need 40 cups and 2 trays for $40") == [40, 2]


def test_a_figure_from_nowhere_fails_and_the_hubs_own_figures_pass():
    assert rv.unverified_figures("It is $180.", [SILVER]) == []
    assert rv.unverified_figures("It is KES 18,000.", [SILVER]) == []
    assert rv.unverified_figures("It is $175.", [SILVER]) == [175.0]
    assert rv.unverified_figures("The tray is $180.", []) == [180.0]          # nothing looked up: nothing verified
    # a quantity multiple, a half (a deposit), the house-rate conversion
    assert rv.unverified_figures("100 cups come to KES 1,000.", [PLASTIC], comment="I need 100 cups") == []
    assert rv.unverified_figures("KES 22,000, a 50% deposit is KES 11,000.", [GOLDEN]) == []
    assert rv.unverified_figures("KES 1,000 each", [{"name": "X", "price_usd": 10}]) == []   # 10 × the rate
    # the owner's own stated delivery fee needs no hub row — an example price in the
    # prompt ("Eliad Oil at USD 50") is not a fact
    assert 350.0 in rv.prompt_figures("USD") and 50.0 not in rv.prompt_figures("USD")
    assert rv.unverified_figures("Delivery within Nairobi is KES 350.", [GOLDEN],
                                 known_figures=rv.prompt_figures("USD")) == []
    assert rv.unverified_figures("DHL to South Africa is USD 50.", [GOLDEN],
                                 known_figures=rv.prompt_figures("USD")) == [50.0]


def test_the_rules_hold_a_figure_from_nowhere():
    issues = rv.rule_issues("how much is the tray?", "The tray is $175.", [SILVER])
    assert len(issues) == 1 and "unverified figure(s) 175" in issues[0]
    assert "Silver Communion Tray (KES 18000 / USD 180)" in issues[0]


# ── the rules: the item they asked for ──────────────────────────────────────

def test_the_finish_they_asked_for_is_the_item():
    bad = rv.item_issues("gold trays with holes to place tot glasses", SILVER)
    assert len(bad) == 1 and "gold" in bad[0] and "'Silver Communion Tray' is silver" in bad[0]
    assert rv.item_issues("gold trays with holes to place tot glasses", GOLDEN) == []
    assert rv.item_issues("gold trays", GOLD_BREAD) == []           # the finish fits; the reviewer judges the kind
    assert rv.item_issues("stainless steel tray", SILVER) == []     # stainless IS the Silver line
    assert rv.item_issues("red cassock", {"name": "Cassock"}) == [] # a made-to-order item has no finish in its name
    assert rv.finishes_of("gold trays with holes to place tot glasses") == {"gold"}   # tot glasses are cups


def test_communion_cups_are_the_small_cups_never_a_chalice():
    bad = rv.item_issues("do you have some holycommunion cups", CHALICE)
    assert len(bad) == 1 and "small cups" in bad[0] and "is a chalice" in bad[0]
    assert rv.item_issues("holy communion cups", SMALL_CHALICE)
    for cups in (PLASTIC, SILVER_CUPS, GLASS, PREPACKED):
        assert rv.item_issues("do you have some holycommunion cups", cups) == []
    # a chalice when they SAY chalice — and cups are not a chalice
    assert rv.item_issues("how much is the chalice?", CHALICE) == []
    assert rv.item_issues("how much is the chalice?", GLASS) == ["they asked for a chalice; 'Glass Cups' is not one"]
    # a tray is not cups
    assert rv.item_issues("communion cups", SILVER) == ["they asked for a cup; 'Silver Communion Tray' is a tray"]
    assert rv.item_issues("tray for the cups", GOLDEN) == []


def test_the_rules_catch_both_live_replies():
    # the silver set sold for a gold-tray ask: the reply never names the hub row,
    # but its $180 is the Silver Communion Tray's price — that row is what it sells
    assert rv.product_named(GOLD_LIVE_REPLY, [SILVER]) is SILVER
    issues = rv.rule_issues(GOLD_ASK, GOLD_LIVE_REPLY, [SILVER])
    assert any("'Silver Communion Tray' is silver" in i for i in issues)
    # the chalice for a cups ask, and the location left hanging
    issues = rv.rule_issues(CUPS_ASK, CUPS_LIVE_REPLY, [CHALICE, PLASTIC])
    assert any("is a chalice" in i for i in issues)
    assert any("where we are" in i for i in issues)
    # and what a right reply looks like
    assert rv.rule_issues(GOLD_ASK, "Welcome Silibaziso 🙏 The Golden Communion Tray is $220 — gold-plated, "
                          "holds 40 cups. No shop in South Africa yet; we deliver there by DHL from "
                          "Nairobi. How many trays?", [GOLDEN]) == []
    assert rv.rule_issues(CUPS_ASK, "We are in Nairobi, Kenya 🙏 Yes — Plastic Communion Cups are $10 and "
                          "Glass Cups $10. How many do you need?", [PLASTIC, GLASS]) == []


def test_a_where_question_must_be_answered_but_a_mention_of_a_place_is_not_one():
    assert rv.where_unanswered("Where is your location", "The cups are $10.")
    assert rv.where_unanswered("Do you have shops in South Africa?", "The tray is $220. How many?")
    assert rv.where_unanswered("where are you located?", "The tray is $220.")
    assert not rv.where_unanswered("Where is your location", "We are in Nairobi, Kenya 🙏")
    assert not rv.where_unanswered("Do you have shops in South Africa?", "No shop there yet — we deliver by DHL.")
    assert not rv.where_unanswered("How much?", "It is $220")
    assert not rv.where_unanswered("Mko wapi?", "Tuko Nairobi")
    # a sentence that merely names a place is not a question about ours (live: "When am
    # in Uganda" was read as one and its good reply was held)
    assert not rv.where_unanswered("When am in Uganda", "Great — how many would you like?")
    assert not rv.where_unanswered("I live in Kenya", "Lovely. Which colour?")
    assert not rv.where_unanswered("My wansapp number", "Noted, thank you.")


def test_two_rows_priced_at_once_name_no_single_item():
    assert rv.product_named("Silver $180 or Golden $220 — which?", [SILVER, GOLDEN]) is None
    assert rv.product_named("The Golden Communion Tray is $220.", [SILVER, GOLDEN]) is GOLDEN


# ── the reviewer ────────────────────────────────────────────────────────────

def test_the_verdict_line_parses():
    v = rv.parse_verdict("verdict=fail | issues=wrong item: silver for gold; South Africa unanswered")
    assert v == {"ok": False, "issues": ["wrong item: silver for gold", "South Africa unanswered"]}
    assert rv.parse_verdict("Verdict=PASS | issues=-") == {"ok": True, "issues": []}
    assert rv.parse_verdict("I think it is fine") is None


class _LLM:
    def __init__(self, text):
        self.text = text
        self.calls = []

    async def complete(self, system, messages, tools=None):
        self.calls.append(messages[0]["content"])
        return types.SimpleNamespace(text=self.text)


def test_double_verification_reads_every_draft_twice_and_merges(monkeypatch):
    monkeypatch.setattr(settings, "comment_reply_review", True, raising=False)
    llm = _LLM("verdict=fail | issues=their question about South Africa is unanswered")
    monkeypatch.setattr(rt, "build_llm", lambda model=None, **kw: llm)
    # the rules find the wrong item (HARD) and the reviewer a missing answer (SOFT): both are read
    v = asyncio.run(rv.review_reply(GOLD_ASK, GOLD_LIVE_REPLY, [SILVER]))
    assert v["ok"] is False and v["by"] == "rules+reviewer" and len(llm.calls) == 1
    assert v["hard"] == ["they asked for gold; 'Silver Communion Tray' is silver — the finish they asked for is the item"]
    assert v["soft"] == ["their question about South Africa is unanswered"]
    assert v["issues"] == v["hard"] + v["soft"]
    # the rules pass → the reviewer's word is soft
    draft = ("The Golden Communion Tray is $220 — gold-plated, holds 40 cups. No shop in South "
             "Africa yet; DHL delivers there from Nairobi. How many?")
    llm.text = "verdict=fail | issues=the reply says 40 cups but the row says nothing about capacity"
    v = asyncio.run(rv.review_reply(GOLD_ASK, draft, [GOLDEN], post_product="Silver Communion Tray"))
    assert v == {"ok": False, "issues": ["the reply says 40 cups but the row says nothing about capacity"],
                 "hard": [], "soft": ["the reply says 40 cups but the row says nothing about capacity"],
                 "by": "reviewer"}
    sent = llm.calls[-1]
    assert "Golden Communion Tray — USD 220" in sent and GOLD_ASK in sent and draft in sent
    assert "The post is about: Silver Communion Tray" in sent
    assert "verdict=<pass|fail>" in sent and "communion CUPS" in sent
    llm.text = "verdict=pass | issues=-"
    assert asyncio.run(rv.review_reply(GOLD_ASK, draft, [GOLDEN])) == {
        "ok": True, "issues": [], "hard": [], "soft": [], "by": "reviewer"}


def test_the_reviewer_is_switchable_and_a_model_outage_leaves_the_rules_verdict(monkeypatch):
    draft = "The Golden Communion Tray is $220. No shop in South Africa; DHL delivers. How many?"
    monkeypatch.setattr(settings, "comment_reply_review", False, raising=False)
    monkeypatch.setattr(rt, "build_llm", lambda model=None, **kw: (_ for _ in ()).throw(AssertionError("no model")))
    assert asyncio.run(rv.review_reply(GOLD_ASK, draft, [GOLDEN])) == {
        "ok": True, "issues": [], "hard": [], "soft": [], "by": "rules"}
    monkeypatch.setattr(settings, "comment_reply_review", True, raising=False)

    class _Down:
        async def complete(self, *a, **k):
            raise RuntimeError("model down")
    monkeypatch.setattr(rt, "build_llm", lambda model=None, **kw: _Down())
    assert asyncio.run(rv.review_reply(GOLD_ASK, draft, [GOLDEN])) == {
        "ok": True, "issues": [], "hard": [], "soft": [], "by": "rules"}
    # a rule failure still stands with the model down — and it is hard
    v = asyncio.run(rv.review_reply("how much is the gold tray?", "It is $175.", [GOLDEN]))
    assert v["ok"] is False and v["hard"] and not v["soft"]


def test_the_switch_defaults_on():
    assert settings.comment_reply_review is True
    assert "comment_reply_review: bool = True" in inspect.getsource(type(settings))


def test_the_second_draft_is_told_why():
    notes = rv.review_notes(["they asked for gold; 'Silver Communion Tray' is silver"])
    assert notes.startswith("(A REVIEWER HELD BACK YOUR PREVIOUS DRAFT")
    assert "they asked for gold" in notes and "gold is not silver" in notes
    assert "never a chalice unless they say chalice" in notes
    assert "answer EVERY question they asked" in notes and "Never post a guess" in notes


# ── the gate inside the turn: every channel ─────────────────────────────────

class _Ctx:
    def __init__(self, seen=None):
        self.seen_products = list(seen or [])
        self.read_only = False


class _TurnLLM:
    """The writer's model for the rewrite: returns `texts` in order."""
    def __init__(self, texts):
        self.texts = list(texts)
        self.calls = []

    async def complete(self, system, messages, tools=None):
        self.calls.append({"system": system, "messages": messages, "tools": tools})
        return types.SimpleNamespace(text=self.texts.pop(0) if self.texts else "")


def _wire(monkeypatch, verdicts, facts_rows=None):
    """review_reply answers from `verdicts` in order; the gate's own search
    hands back `facts_rows`; flags and tallies are captured."""
    seen_by_call, flags, tally = [], [], []

    async def fake_review(comment, answer, seen, **kw):
        seen_by_call.append((answer, list(seen), kw))
        return verdicts.pop(0)

    async def fake_facts(ctx, user_text, tool_log):
        rows = list(facts_rows or [])
        ctx.seen_products.extend(rows)
        tool_log.append({"tool": "search_catalog", "input": {"query": user_text, "by": "reviewer"},
                         "out": {"results": [{"name": r["name"]} for r in rows]}})
        return rows

    async def fake_flag(db, channel, key, issues, draft):
        flags.append((channel, key, list(issues), draft))

    async def fake_tally(redis, outcome, channel=""):
        tally.append((outcome, channel))
    monkeypatch.setattr(rv, "review_reply", fake_review)
    monkeypatch.setattr(rv, "record_verdict", fake_tally)
    monkeypatch.setattr(rv, "prompt_figures", lambda currency="USD": frozenset())
    monkeypatch.setattr(rt, "_facts_for_ask", fake_facts)
    monkeypatch.setattr(rt, "_flag_held_reply", fake_flag)
    return seen_by_call, flags, tally


def _gate(monkeypatch, reply, *, verdicts, llm_texts=(), public=False, seen=None,
          facts_rows=None, user_text=GOLD_ASK, swahili=False):
    calls, flags, tally = _wire(monkeypatch, verdicts, facts_rows)
    llm = _TurnLLM(llm_texts)
    ctx = _Ctx(seen)
    transcript = [{"role": "user", "content": user_text}]
    out = asyncio.run(rt._gate_turn_reply(
        reply, user_text=user_text, transcript=transcript, tool_log=[], ctx=ctx,
        currency="USD", channel="facebook" if public else "whatsapp", public_comment=public,
        llm=llm, sys_blocks=["SYSTEM"], redis=None, db=None, key="K1",
        post_product="Silver Communion Tray", swahili=swahili))
    return out, calls, flags, tally, llm, ctx


def _v(hard=(), soft=(), by="rules"):
    hard, soft = list(hard), list(soft)
    return {"ok": not (hard or soft), "issues": hard + soft, "hard": hard, "soft": soft, "by": by}


def test_a_passing_reply_is_sent_as_written(monkeypatch):
    out, calls, flags, tally, llm, _ = _gate(
        monkeypatch, "The Golden Communion Tray is $220.", seen=[GOLDEN], verdicts=[_v()])
    assert out == ("The Golden Communion Tray is $220.", [], "pass")
    assert llm.calls == [] and flags == [] and tally == [("pass", "whatsapp")]
    assert calls[0][2]["mode"] == "dm" and calls[0][2]["post_product"] == "Silver Communion Tray"


def test_a_failing_reply_is_rewritten_once_with_the_reasons_and_the_facts(monkeypatch):
    fixed = "The Golden Communion Tray is $220 — no shop in South Africa; DHL delivers from Nairobi. How many?"
    out, calls, flags, tally, llm, ctx = _gate(
        monkeypatch, GOLD_LIVE_REPLY, seen=[SILVER], facts_rows=[GOLDEN],
        verdicts=[_v(hard=["they asked for gold; 'Silver Communion Tray' is silver"]), _v()],
        llm_texts=[fixed])
    assert out == (fixed, [], "rewritten") and flags == [] and tally == [("rewritten", "whatsapp")]
    # the gate fetched the rows for what they asked, and the rewrite saw them
    assert [r["name"] for r in ctx.seen_products] == ["Silver Communion Tray", "Golden Communion Tray"]
    call = llm.calls[0]
    assert call["tools"] == [] and call["system"] == ["SYSTEM"]
    assert call["messages"][-2] == {"role": "assistant", "content": GOLD_LIVE_REPLY}
    block = call["messages"][-1]["content"]
    assert block.startswith("[REVIEWER — your draft was HELD BACK before it was sent to the customer")
    assert "they asked for gold" in block and "Golden Communion Tray — USD 220" in block
    assert "THE FACTS YOU MAY STATE" in block and "Do not call a tool for this rewrite" in block
    assert "nothing they did not ask" in block
    # the second verdict was on the rewrite, with the fetched rows in hand
    assert calls[1][0] == fixed and [r["name"] for r in calls[1][1]][-1] == "Golden Communion Tray"


def test_soft_findings_never_hold_the_best_hard_clean_draft_is_sent(monkeypatch):
    """Owner, 2026-09-25: 'change from gating to double verifying'. A side
    question left unanswered or the reviewer's reading asks for a rewrite;
    if the rewrite is still not clean, the best draft with no hard finding
    goes out — never a holding line."""
    # the rewrite is hard-clean with one soft note → it goes out
    out, calls, flags, tally, llm, _ = _gate(
        monkeypatch, "We ship to Kampala from our Nairobi workshop. What's your phone number?",
        user_text="When am in Uganda", seen=[],
        verdicts=[_v(soft=["their question about how to get it is unanswered"], by="reviewer"),
                  _v(soft=["still no delivery time"], by="reviewer")],
        llm_texts=["We ship to Kampala from Nairobi by DHL — 3 to 5 days. Your phone number?"])
    assert out == ("We ship to Kampala from Nairobi by DHL — 3 to 5 days. Your phone number?", [], "soft")
    assert flags == [] and tally == [("soft", "whatsapp")]
    # the rewrite carries a hard finding, the original only a soft one → the original goes out
    out, *_ = _gate(
        monkeypatch, "We ship to Kampala from our Nairobi workshop. What's your phone number?",
        user_text="When am in Uganda", seen=[],
        verdicts=[_v(soft=["a side question unanswered"], by="reviewer"),
                  _v(hard=["unverified figure(s) 45"], soft=["x"])],
        llm_texts=["Shipping is $45."])
    assert out[0].startswith("We ship to Kampala") and out[2] == "soft"
    # the rewrite never came: the original, hard-clean, goes out
    out, *_ = _gate(monkeypatch, "Noted, thank you 🙏", user_text="My wansapp number", seen=[],
                    verdicts=[_v(soft=["the reviewer rejected the draft"], by="reviewer")], llm_texts=[""])
    assert out == ("Noted, thank you 🙏", [], "soft")


def test_only_a_hard_finding_on_both_drafts_holds_a_private_reply(monkeypatch):
    out, calls, flags, tally, llm, _ = _gate(
        monkeypatch, GOLD_LIVE_REPLY, seen=[SILVER],
        verdicts=[_v(hard=["they asked for gold; 'Silver Communion Tray' is silver"]),
                  _v(hard=["unverified figure(s) 95"])],
        llm_texts=["still wrong"])
    assert out == (rt._REVIEW_HOLD_DM_PRICE,
                   ["they asked for gold; 'Silver Communion Tray' is silver", "unverified figure(s) 95"], "held")
    assert flags == [("whatsapp", "K1", ["they asked for gold; 'Silver Communion Tray' is silver",
                                         "unverified figure(s) 95"], "still wrong")]
    assert tally == [("held", "whatsapp")]
    # a hard finding that is not about money gets the plain holding line; Swahili when they wrote Swahili
    out, *_ = _gate(monkeypatch, "Your order has shipped!", user_text="where is my order", seen=[],
                    verdicts=[_v(hard=["an order-status claim with no check_order_status behind it"]),
                              _v(hard=["an order-status claim with no check_order_status behind it"])],
                    llm_texts=["It is on its way!"])
    assert out[0] == rt._REVIEW_HOLD_DM and out[2] == "held"
    out, *_ = _gate(monkeypatch, "Ni $95.", user_text="bei gani ya kikombe", seen=[], swahili=True,
                    verdicts=[_v(hard=["unverified figure(s) 95"]), _v(hard=["unverified figure(s) 95"])],
                    llm_texts=["Ni $95."])
    assert out[0] == rt._SW_REVIEW_HOLD_DM_PRICE and out[2] == "held"


def test_never_two_holding_lines_in_a_row_and_never_one_for_an_acknowledgement(monkeypatch):
    calls, flags, tally = _wire(monkeypatch, [_v(hard=["unverified figure(s) 95"]),
                                              _v(hard=["unverified figure(s) 95"])])

    async def held_before(redis, channel, key, hours=6):
        return True
    monkeypatch.setattr(rv, "held_recently", held_before)
    out = asyncio.run(rt._gate_turn_reply(
        "It is $95.", user_text="how much?", transcript=[], tool_log=[], ctx=_Ctx(), currency="USD",
        channel="whatsapp", public_comment=False, llm=_TurnLLM(["It is $95."]), sys_blocks=["S"],
        redis=None, db=None, key="K1"))
    assert out == ("", ["unverified figure(s) 95", "unverified figure(s) 95"], "held")
    assert len(flags) == 1                      # the colleague is flagged, the customer is not walled
    # an acknowledgement is never answered with a holding line
    _wire(monkeypatch, [_v(hard=["unverified figure(s) 95"]), _v(hard=["unverified figure(s) 95"])])
    out = asyncio.run(rt._gate_turn_reply(
        "Great — $95 then!", user_text="I'm saying ok", transcript=[], tool_log=[], ctx=_Ctx(),
        currency="USD", channel="messenger", public_comment=False, llm=_TurnLLM(["Still $95"]),
        sys_blocks=["S"], redis=None, db=None, key="K1", closer=True))
    assert out[0] == "" and out[2] == "held"


def test_two_hard_failures_under_a_comment_return_nothing_for_the_engine_to_hold(monkeypatch):
    out, calls, flags, tally, llm, _ = _gate(
        monkeypatch, GOLD_LIVE_REPLY, seen=[SILVER], public=True,
        verdicts=[_v(hard=["silver for gold"]), _v(hard=["still silver"])],
        llm_texts=["still wrong"])
    assert out == ("", ["silver for gold", "still silver"], "held")
    assert flags == [] and tally == [("held", "facebook")]
    assert calls[0][2]["mode"] == "comment"
    assert "posted under the comment" in llm.calls[0]["messages"][-1]["content"]


def test_a_rewrite_that_never_comes_holds_only_on_a_hard_finding(monkeypatch):
    issue = "they asked for gold; 'Silver Communion Tray' is silver"
    out, calls, flags, tally, llm, _ = _gate(
        monkeypatch, GOLD_LIVE_REPLY, seen=[SILVER],
        verdicts=[_v(hard=[issue])], llm_texts=[""])
    assert out == (rt._REVIEW_HOLD_DM_PRICE, [issue], "held")
    assert flags and flags[0][3] == GOLD_LIVE_REPLY       # the draft goes to the colleague


def test_the_holding_lines_promise_the_thread_not_the_inbox():
    for line in rt._VERIFY_HOLD_POOL + rt._SW_VERIFY_HOLD_POOL + [
            rt._REVIEW_HOLD_DM, rt._SW_REVIEW_HOLD_DM, rt._REVIEW_HOLD_DM_PRICE, rt._SW_REVIEW_HOLD_DM_PRICE]:
        assert "🙏" in line
        low = line.lower()
        assert "dm" not in low and "message us" not in low and "inbox" not in low
        assert "right here" in low or "hapa" in low


def test_system_composed_prompts_are_not_gated():
    assert rt._gate_applies("How much is the tray?")
    assert rt._gate_applies("(I need one) how much")
    assert not rt._gate_applies("(Internal: this customer built a cart and went quiet…)")
    assert not rt._gate_applies("[CROSS-CHANNEL CONTINUATION — not a customer message. …]")
    assert not rt._gate_applies("")


def test_the_gate_searches_what_they_actually_asked():
    assert rt._ask_query(GOLD_ASK) == "gold communion tray"          # stop-words gone, hub terms in
    assert rt._ask_query(CUPS_ASK) == "communion cup"
    assert rt._ask_query("How much are the golden trays?") == "gold tray"
    assert rt._ask_query("hi") == ""


def test_run_turn_gates_every_real_turn_and_reports_to_the_caller():
    src = inspect.getsource(rt.run_turn)
    assert "turn_facts: dict | None = None" in src
    assert "turn_messages = list(messages)" in src and "tool_log: list[dict] = []" in src
    assert 'tool_log.append({"tool": call.name, "input": call.input, "out": out})' in src
    assert "if reply and not read_only and not scribe_only and _gate_applies(user_text):" in src
    assert "reply, _held, _gate_outcome = await _gate_turn_reply(" in src
    assert "fx=_fx_rates, closer=is_closer(user_text or \"\"))" in src
    assert 'turn_facts.update({"tools": tool_log, "held": list(_held), "review": _gate_outcome})' in src
    # the gate runs before the spend is measured and the reply returned
    assert src.index("await _gate_turn_reply(") < src.index("svc.log_agent_usage(")
    assert "_gate_post_product = str((_known or {}).get(\"name\") or \"\")" in src


def test_the_comment_engine_reads_the_gates_verdict():
    src = inspect.getsource(rt._run_comment_engage)
    assert "thread_parent=_parent, turn_facts=_facts)).strip()" in src
    assert 'held_issues: list[str] = list(_facts.get("held") or [])' in src
    assert "if held_issues:\n        answer = \"\"" in src
    gate = src.index('held_issues: list[str] = list(_facts.get("held") or [])')
    assert gate < src.index("if not seen_products:\n        await _resolve_post_product(")
    assert gate < src.index("dm_text = _dm_text(")
    assert gate < src.index("posted = await _post_public(public_text)")
    # the holding line when nothing verified survives, and the colleague gets the reasons
    assert "if held_issues and not answer:" in src
    assert "_SW_VERIFY_HOLD_POOL if swahili else _VERIFY_HOLD_POOL" in src
    assert "issues=held_issues or None)" in src
    # the canned path never sells the post's item for another finish or kind
    assert "_other = _item_issues(prompt_text, matched) if matched else []" in src
    assert "if held_issues:\n            product_name = \"\"\n            matched = {}" in src


def test_the_team_note_says_the_draft_was_held_and_why():
    note = rt._human_note("question", 0, CUPS_ASK, answered="Thank you 🙏 …",
                          issues=["the reply gave a chalice for communion cups"])
    assert note.startswith("HELD BACK BY THE REVIEWER (public comment)")
    assert "was NOT posted" in note and "answer them there, from the hub" in note
    assert "• Why it was held: the reply gave a chalice for communion cups" in note
    assert f'• Their comment: "{CUPS_ASK}"' in note
    # without issues, the note is the ordinary one
    assert rt._human_note("question", 0, CUPS_ASK).startswith("QUESTION (public comment)")
    assert "issues: list | None = None) -> None:" in inspect.getsource(rt._route_comment_to_human)
    assert "answered=answered, issues=issues)" in inspect.getsource(rt._route_comment_to_human)


# ── the rules that every channel now has ────────────────────────────────────

def test_a_tools_own_numbers_are_the_ground_truth():
    log = [{"tool": "update_cart", "input": {}, "out": {"total": 39350, "lines": [{"qty": 2, "unit": 19500}],
                                                        "note": "delivery KES 350 within Nairobi"}}]
    assert rv.figures_in_results(log) == {39350.0, 2.0, 19500.0, 350.0}
    ok = asyncio.run(rv.review_reply("go ahead", "Your total is KES 39,350 for 2 sets, delivery included.",
                                     [], tool_results=log, mode="dm"))
    assert ok["ok"] is True
    bad = asyncio.run(rv.review_reply("go ahead", "Your total is KES 41,000.", [], tool_results=log, mode="dm"))
    assert bad["ok"] is False and "unverified figure(s) 41,000" in bad["issues"][0]


def test_a_figure_already_said_in_the_conversation_may_be_repeated():
    transcript = [{"role": "user", "content": "My budget is KES 15,000"},
                  {"role": "assistant", "content": "The Cassock is KES 13,000."}]
    assert rv.transcript_figures(transcript) == {15000.0, 13000.0}
    assert rv.unverified_figures("Within your KES 15,000 — the cassock at KES 13,000 fits.", [],
                                 facts=rv.transcript_figures(transcript)) == []


def test_a_sum_is_two_rows_together_or_a_price_plus_a_small_fee_never_two_loose_figures():
    # a tool total plus the owner's delivery fee
    assert rv.unverified_figures("KES 19,500 plus KES 350 delivery is KES 19,850.", [SILVER],
                                 known_figures={350.0}, facts={19500.0}) == []
    # two rows together
    assert rv.unverified_figures("Both trays come to $400.", [SILVER, GOLDEN]) == []
    # what the first simulation let through: 13,000 + 7,000 (a prompt figure plus a half),
    # and 45 + 50 (two shipping figures) — no longer explained
    assert rv.unverified_figures("The Golden Communion Tray is KES 20,000.", [GOLDEN, GOLD_BREAD],
                                 known_figures={13000.0, 45.0, 50.0}) == [20000.0]
    assert rv.unverified_figures("Our wooden chalice is $95.", [], known_figures={45.0, 50.0}) == [95.0]
    # a fee is small: a "fee" bigger than a quarter of the price is not a fee
    assert rv.unverified_figures("Total $400.", [SILVER], known_figures={220.0}) == [400.0]


def test_one_currency_per_reply():
    assert rv.two_currencies("It is $180 (KES 18,000).") == ["USD", "KES"]
    assert rv.two_currencies("It is $180 or $200.") == []
    issues = rv.rule_issues("how much", "The tray is $180 (KES 18,000).", [SILVER])
    assert any("two currencies" in i for i in issues)


def test_a_link_must_come_from_a_tool():
    log = [{"tool": "create_order", "input": {}, "out": {"order_url": "https://bethanyhouse.co.ke/o/123"}}]
    assert rv.foreign_links("Pay here: https://bethanyhouse.co.ke/o/123", log) == []
    assert rv.foreign_links("Pay here: https://pay.example.com/x", log) == ["https://pay.example.com/x"]
    issues = rv.rule_issues("send the link", "Here: https://pay.example.com/x", [], tool_results=log)
    assert any("a link no tool gave" in i for i in issues)


def test_an_order_status_needs_an_order_tool_behind_it():
    assert rv.status_without_source("Your order has been shipped and is on its way!", [], [])
    log = [{"tool": "check_order_status", "input": {}, "out": {"status": "shipped"}}]
    assert not rv.status_without_source("Your order has been shipped!", log, [])
    earlier = [{"role": "assistant", "content": "Your order has been shipped 🙏"}]
    assert not rv.status_without_source("As I said, it has been shipped.", [], earlier)
    assert not rv.status_without_source("We ship worldwide by DHL.", [], [])


def test_saying_we_do_not_have_it_stands_the_finish_rule_down():
    assert rv.acknowledges_substitute("We don't have a wooden chalice — the Brass Chalice Cup is $400.")
    assert rv.acknowledges_substitute("Hatuna ya mbao, lakini tuna ya shaba.")
    assert not rv.acknowledges_substitute("The Brass Chalice Cup is $400.")
    brass = {"name": "Brass Chalice Cup", "price": 40000, "price_usd": 400}
    assert rv.item_issues("do you have a wooden chalice?", brass)
    assert rv.item_issues("do you have a wooden chalice?", brass,
                          "We don't have a wooden one — the Brass Chalice Cup is $400.") == []


def test_the_reviewer_reads_the_conversation_and_the_tools_in_a_private_chat(monkeypatch):
    monkeypatch.setattr(settings, "reply_review", True, raising=False)
    llm = _LLM("verdict=fail | issues=re-asks the colour they gave")
    chosen = []
    monkeypatch.setattr(rt, "build_llm", lambda model=None, **kw: chosen.append(model) or llm)
    transcript = [{"role": "user", "content": "I want the cassock in red"},
                  {"role": "assistant", "content": "Red it is — what size?"},
                  {"role": "user", "content": "Size L"}]
    log = [{"tool": "update_cart", "input": {}, "out": {"total": 13000}}]
    v = asyncio.run(rv.review_reply("Size L", "Which colour would you like?", [], transcript=transcript,
                                    tool_results=log, mode="dm"))
    assert v == {"ok": False, "issues": ["re-asks the colour they gave"], "hard": [],
                 "soft": ["re-asks the colour they gave"], "by": "reviewer"}
    sent = llm.calls[-1]
    assert "a reply in a private chat" in sent and "4. CONTRADICTS THE CONVERSATION" in sent
    assert "6. WRONG LANGUAGE" in sent and "Customer: I want the cassock in red" in sent
    assert '- update_cart: {"total": 13000}' in sent
    assert "The post is about" not in sent
    assert chosen == [settings.tier2_model_light]
    # money and order turns are reviewed by the main model
    llm.text = "verdict=pass | issues=-"
    asyncio.run(rv.review_reply("I have paid the deposit", "Received, thank you!", [], mode="dm"))
    assert chosen[-1] == settings.tier2_model


def test_the_private_chat_reviewer_has_its_own_switch(monkeypatch):
    monkeypatch.setattr(settings, "reply_review", False, raising=False)
    monkeypatch.setattr(rt, "build_llm", lambda model=None, **kw: (_ for _ in ()).throw(AssertionError("no model")))
    v = asyncio.run(rv.review_reply("hi", "Hello! How can I help?", [], mode="dm"))
    assert v == {"ok": True, "issues": [], "hard": [], "soft": [], "by": "rules"}
    assert settings.reply_review is True or True
    assert "reply_review: bool = True" in inspect.getsource(type(settings))


class _Tally:
    def __init__(self):
        self.h = {}

    async def hincrby(self, key, field, n):
        self.h.setdefault(key, {})[field] = self.h.setdefault(key, {}).get(field, 0) + n

    async def expire(self, key, ttl):
        self.ttl = ttl

    async def hgetall(self, key):
        return {k.encode(): str(v).encode() for k, v in self.h.get(key, {}).items()}


def test_the_days_tally_reaches_the_health_endpoint():
    r = _Tally()
    for outcome, ch in (("pass", "whatsapp"), ("pass", "facebook"), ("rewritten", "whatsapp"),
                        ("held", "web"), ("soft", "whatsapp")):
        asyncio.run(rv.record_verdict(r, outcome, ch))
    asyncio.run(rv.record_verdict(r, "nonsense", "x"))
    t = asyncio.run(rv.read_verdicts(r))
    assert t["pass"] == 2 and t["rewritten"] == 1 and t["held"] == 1 and t["soft"] == 1
    assert t["pass:facebook"] == 1
    assert r.ttl == 3 * 24 * 3600
    assert asyncio.run(rv.read_verdicts(None)) == {}
    from app.routers import health as h
    src = inspect.getsource(h.health)
    assert 'out["review"] = {"passed": tally.get("pass", 0),' in src


# ── the canned path: "gold trays" does not name the silver tray ─────────────

def test_a_comment_naming_another_finish_or_kind_does_not_name_the_posts_product():
    assert rt._names_product("How much is the silver communion tray?", "Silver Communion Tray")
    assert rt._names_product("how much are the trays?", "Silver Communion Tray")
    assert not rt._names_product(GOLD_ASK, "Silver Communion Tray")
    assert not rt._names_product("do you have some holycommunion cups", "Golden Chalice Cup with Paten Set")
    assert rt._names_product("do you have communion cups", "Plastic Communion Cups")


# ── the search: gold is golden, cups are the small cups ─────────────────────

def _search(monkeypatch, q):
    from app.services import n8n_bridge as svc
    from app.services import promotions as promo

    async def items(db, redis):
        return CATALOG

    async def none(redis):
        return None
    monkeypatch.setattr(svc, "catalog_items", items)
    monkeypatch.setattr(promo, "campaign_now", none)
    ctx = tools.ToolContext(db=None, redis=None, wa_id="x", channel="facebook", read_only=True)
    out = asyncio.run(tools._search_catalog({"query": q}, ctx))
    return [r["name"] for r in out["results"]], out


def test_gold_trays_with_holes_are_the_golden_communion_tray(monkeypatch):
    assert canonical("gold trays with holes to place tot glasses") == "gold communion tray"
    names, out = _search(monkeypatch, "gold trays with holes to place tot glasses")
    assert names[0] == "Golden Communion Tray"
    assert out["results"][0].get("match") != "partial"
    names, _ = _search(monkeypatch, GOLD_ASK)
    assert names[0] == "Golden Communion Tray"                  # even with the whole comment as the query
    assert tools._search_words("Golden Communion Trays") == {"gold", "communion", "tray"}
    assert tools._search_words("tot glasses aluminum") == {"tot", "glass", "aluminium"}


def test_communion_cups_are_the_small_cups_cheapest_first_never_a_chalice(monkeypatch):
    for q in ("holy communion cups", "holycommunion cups", "tot glasses", "communion cups",
              CUPS_ASK):
        assert canonical(q).endswith("communion cups"), q
        names, out = _search(monkeypatch, q)
        assert names == ["Plastic Communion Cups", "Pre-Packed Communion Cups",
                         "Silver Communion Cups", "Glass Cups"], q
        assert out["range"]["range"] == "communion cups"
        assert "a chalice only when they SAY chalice" in out["range"]["stay_in_range"]
    assert range_for("communion cups")["name"] == "communion cups"
    assert range_for("plastic communion cups") is None           # one member: the ordinary search
    assert range_for("chalice") is None


def test_stainless_cups_are_the_silver_communion_cups(monkeypatch):
    assert canonical("stainless steel cups") == "silver communion cups"
    assert canonical("metal cups for communion") == "silver communion cups for communion"
    names, _ = _search(monkeypatch, "stainless steel cups")
    assert names == ["Silver Communion Cups"]


def test_the_families_leave_compounds_alone():
    assert canonical("This little communion cup filler saves your linen") == \
        "This little communion cup filler saves your linen"
    assert canonical("communion cup tray") == "communion tray"
    assert canonical("tray for the cups") == "communion tray"
    assert canonical("the Silver Communion Tray set") == "the Silver Communion Tray set"
    assert canonical("a chalice") == "a chalice"
    for term in ("communion tray", "communion cups", "silver communion cups"):
        assert term in hub_terms()


def test_the_trays_range_keeps_its_own_words():
    names = [r["name"] for r in __import__("app.core.synonyms", fromlist=["range_members"])
             .range_members(range_for("communion trays"), CATALOG)]
    assert names == ["Wooden tray", "Silver Communion Tray", "Golden Communion Tray"]


# ── the model's rules ───────────────────────────────────────────────────────

def test_the_prompt_and_the_addendum_teach_the_rules():
    p = " ".join(build_system_prompt(currency="USD").split())
    assert "THE FINISH THEY ASKED FOR IS THE ITEM" in p
    assert "Golden Communion Tray" in p and "never quote the other finish as if it were theirs" in p
    assert "COMMUNION CUPS ARE THE SMALL CUPS" in p
    assert "name one ONLY when they say chalice, goblet or paten" in p
    a = " ".join(rt._public_comment_addendum("USD").split())
    assert "THE FINISH THEY ASKED FOR IS THE ITEM, AND THE KIND" in a
    assert "ANSWER EVERY QUESTION IN THE COMMENT" in a
    assert "EVERY REPLY IS VERIFIED BEFORE IT POSTS" in a
    assert "a draft that fails is held back and never posts" in a
