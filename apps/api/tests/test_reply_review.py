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
    # the owner's own stated figures (shipping) need no hub row
    assert rv.unverified_figures("DHL to South Africa is USD 50.", [GOLDEN],
                                 known_figures=rv.prompt_figures("USD")) == []


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


def test_a_where_question_must_be_answered():
    assert rv.where_unanswered("Where is your location", "The cups are $10.")
    assert rv.where_unanswered("Do you have shops in South Africa?", "The tray is $220. How many?")
    assert not rv.where_unanswered("Where is your location", "We are in Nairobi, Kenya 🙏")
    assert not rv.where_unanswered("Do you have shops in South Africa?", "No shop there yet — we deliver by DHL.")
    assert not rv.where_unanswered("How much?", "It is $220")
    assert not rv.where_unanswered("Mko wapi?", "Tuko Nairobi")


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


def test_review_reply_rules_first_then_the_reviewer(monkeypatch):
    monkeypatch.setattr(settings, "comment_reply_review", True, raising=False)
    llm = _LLM("verdict=fail | issues=their question about South Africa is unanswered")
    monkeypatch.setattr(rt, "build_llm", lambda model=None: llm)
    # a rule failure is final — the reviewer is not even asked
    v = asyncio.run(rv.review_reply(GOLD_ASK, GOLD_LIVE_REPLY, [SILVER]))
    assert v["ok"] is False and v["by"] == "rules" and llm.calls == []
    # the rules pass → the reviewer decides
    draft = ("The Golden Communion Tray is $220 — gold-plated, holds 40 cups. No shop in South "
             "Africa yet; DHL delivers there from Nairobi. How many?")
    llm.text = "verdict=fail | issues=the reply says 40 cups but the row says nothing about capacity"
    v = asyncio.run(rv.review_reply(GOLD_ASK, draft, [GOLDEN], post_product="Silver Communion Tray"))
    assert v == {"ok": False, "issues": ["the reply says 40 cups but the row says nothing about capacity"],
                 "by": "reviewer"}
    sent = llm.calls[-1]
    assert "Golden Communion Tray — USD 220" in sent and GOLD_ASK in sent and draft in sent
    assert "The post is about: Silver Communion Tray" in sent
    assert "verdict=<pass|fail>" in sent and "communion CUPS" in sent
    llm.text = "verdict=pass | issues=-"
    assert asyncio.run(rv.review_reply(GOLD_ASK, draft, [GOLDEN])) == {"ok": True, "issues": [], "by": "reviewer"}


def test_the_reviewer_is_switchable_and_a_model_outage_leaves_the_rules_verdict(monkeypatch):
    draft = "The Golden Communion Tray is $220. No shop in South Africa; DHL delivers. How many?"
    monkeypatch.setattr(settings, "comment_reply_review", False, raising=False)
    monkeypatch.setattr(rt, "build_llm", lambda model=None: (_ for _ in ()).throw(AssertionError("no model")))
    assert asyncio.run(rv.review_reply(GOLD_ASK, draft, [GOLDEN])) == {"ok": True, "issues": [], "by": "rules"}
    monkeypatch.setattr(settings, "comment_reply_review", True, raising=False)

    class _Down:
        async def complete(self, *a, **k):
            raise RuntimeError("model down")
    monkeypatch.setattr(rt, "build_llm", lambda model=None: _Down())
    assert asyncio.run(rv.review_reply(GOLD_ASK, draft, [GOLDEN])) == {"ok": True, "issues": [], "by": "rules"}
    # a rule failure still holds with the model down
    assert asyncio.run(rv.review_reply(GOLD_ASK, "It is $175.", [GOLDEN]))["ok"] is False


def test_the_switch_defaults_on():
    assert settings.comment_reply_review is True
    assert "comment_reply_review: bool = True" in inspect.getsource(type(settings))


def test_the_second_draft_is_told_why():
    notes = rv.review_notes(["they asked for gold; 'Silver Communion Tray' is silver"])
    assert notes.startswith("(A REVIEWER HELD BACK YOUR PREVIOUS DRAFT")
    assert "they asked for gold" in notes and "gold is not silver" in notes
    assert "never a chalice unless they say chalice" in notes
    assert "answer EVERY question they asked" in notes and "Never post a guess" in notes


# ── the engine's gate ───────────────────────────────────────────────────────

def _gate(monkeypatch, verdicts):
    """review_reply answers from `verdicts` in order."""
    calls = []

    async def fake_review(comment, answer, seen, **kw):
        calls.append(answer)
        return verdicts.pop(0)
    monkeypatch.setattr(rv, "review_reply", fake_review)
    monkeypatch.setattr(rv, "prompt_figures", lambda currency="USD": frozenset())
    return calls


def test_a_passing_draft_posts_as_written(monkeypatch):
    calls = _gate(monkeypatch, [{"ok": True, "issues": [], "by": "reviewer"}])
    drafts = []

    async def regen(notes):
        drafts.append(notes)
        return "second"
    out = asyncio.run(rt._gate_public_answer(
        "The Golden Communion Tray is $220.", comment_text=GOLD_ASK, seen_products=[GOLDEN],
        post_product="", currency="USD", redis=None, regenerate=regen))
    assert out == ("The Golden Communion Tray is $220.", []) and drafts == [] and len(calls) == 1


def test_a_failing_draft_is_written_once_more_with_the_reasons(monkeypatch):
    _gate(monkeypatch, [{"ok": False, "issues": ["silver for gold"], "by": "rules"},
                        {"ok": True, "issues": [], "by": "reviewer"}])
    drafts = []

    async def regen(notes):
        drafts.append(notes)
        return "The Golden Communion Tray is $220. No shop in South Africa; DHL delivers."
    out = asyncio.run(rt._gate_public_answer(
        GOLD_LIVE_REPLY, comment_text=GOLD_ASK, seen_products=[SILVER, GOLDEN],
        post_product="Silver Communion Tray", currency="USD", redis=None, regenerate=regen))
    assert out[0].startswith("The Golden Communion Tray is $220.") and out[1] == []
    assert len(drafts) == 1 and "silver for gold" in drafts[0] and "HELD BACK" in drafts[0]


def test_two_failures_post_nothing_and_carry_both_reasons(monkeypatch):
    _gate(monkeypatch, [{"ok": False, "issues": ["silver for gold"], "by": "rules"},
                        {"ok": False, "issues": ["South Africa unanswered"], "by": "reviewer"}])

    async def regen(notes):
        return "still wrong"
    out = asyncio.run(rt._gate_public_answer(
        GOLD_LIVE_REPLY, comment_text=GOLD_ASK, seen_products=[SILVER],
        post_product="", currency="USD", redis=None, regenerate=regen))
    assert out == ("", ["silver for gold", "South Africa unanswered"])


def test_a_second_draft_that_fails_to_come_holds_with_the_first_reasons(monkeypatch):
    _gate(monkeypatch, [{"ok": False, "issues": ["silver for gold"], "by": "rules"}])

    async def regen(notes):
        raise RuntimeError("model down")
    out = asyncio.run(rt._gate_public_answer(
        GOLD_LIVE_REPLY, comment_text=GOLD_ASK, seen_products=[SILVER],
        post_product="", currency="USD", redis=None, regenerate=regen))
    assert out == ("", ["silver for gold"])
    assert asyncio.run(rt._noop_draft("x")) == ""


def test_the_engine_gates_the_answer_before_the_dm_and_the_post():
    src = inspect.getsource(rt._run_comment_engage)
    assert "async def _draft(notes: str | None = None) -> str:" in src
    assert "thread_parent=_parent, review_notes=notes)).strip()" in src
    assert "answer = await _draft()" in src
    gate = src.index("answer, held_issues = await _gate_public_answer(")
    assert src.index("answer = await _draft()") < gate
    assert gate < src.index("if not seen_products:\n        await _resolve_post_product(")
    assert gate < src.index("dm_text = _dm_text(")
    assert gate < src.index("posted = await _post_public(public_text)")
    assert "regenerate=(_draft if not skip_model else _noop_draft)" in src
    # the holding line when nothing verified survives, and the colleague gets the reasons
    assert "if held_issues and not answer:" in src
    assert "_SW_VERIFY_HOLD_POOL if swahili else _VERIFY_HOLD_POOL" in src
    assert "issues=held_issues or None)" in src
    # the canned path never sells the post's item for another finish or kind
    assert "_other = _item_issues(prompt_text, matched) if matched else []" in src
    assert "if held_issues:\n            product_name = \"\"\n            matched = {}" in src


def test_run_turn_carries_the_reviewers_notes_into_the_second_draft():
    src = inspect.getsource(rt.run_turn)
    assert "review_notes: str | None = None" in src
    assert "if public_comment and review_notes:\n        lead_ctx.append(review_notes)" in src


def test_the_holding_line_promises_the_thread_not_the_inbox():
    for line in rt._VERIFY_HOLD_POOL + rt._SW_VERIFY_HOLD_POOL:
        assert "{name}" in line and "🙏" in line
        low = line.lower()
        assert "dm" not in low and "message us" not in low and "inbox" not in low
        assert "right here" in low or "hapa" in low


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
