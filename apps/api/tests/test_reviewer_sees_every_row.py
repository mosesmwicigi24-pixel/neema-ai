"""THE REVIEWER JUDGES AGAINST WHAT THE AGENT SAW (live, 2026-10-05).

A voice note, transcribed right: "Hi there, I need to buy a communion tray,
several cups and a chalice cup." The agent searched three times — "communion
tray" (6 rows), "communion cups" (4), "chalice" (5, the Chalice Cup -Medium
among them) — and drafted a reply. Two things then held it:

  1. the reviewer was shown only the FIRST 8 rows of the turn (six trays,
     two cups): every chalice the agent had found was missing, so it judged
     "WRONG ITEM — chalice cups … not in hub inventory", "WRONG FIGURE —
     prices for chalices … not from hub", "NOT OUR GOODS — chalices not
     listed"; the rewrite was given the same 8 rows;
  2. the rules read the three-item ask as a chalice ask alone: "they asked
     for a chalice; 'Silver Communion Tray' is not one" — a HARD finding, on
     both drafts, so nothing was sent but the holding line.

Pinned here: every row of the turn reaches the reviewer and the rewrite,
priced as the agent saw it (KES, USD and ZMW alike); a tray or cups the
customer asked for beside a chalice fits the ask; a "chalice cup" is still
one chalice; and the valid checks — one currency, the hub's own figures —
still stand.
"""
import asyncio
import types

import app.main  # noqa: F401
from app.agent import review as rv
from app.agent import runtime as rt
from app.agent import tools
from app.core.config import settings

ASK = "Hi there, I need to buy a communion tray, several cups and a chalice cup."


def _row(name, sku, kes, desc, prices=None):
    return {"name": name, "sku": sku, "slug": sku.lower(), "price": kes, "price_usd": None,
            "prices": prices or {}, "category": "Communion Items", "aliases": [],
            "description": desc}


# The live catalogue's rows (names, skus, KES prices, descriptions as the hub has them).
TRAYS = [
    _row("Wooden tray", "COM-WT-001", 5000, "A wooden communion tray that holds 100 cups."),
    _row("Small Wooden tray", "GEN-SWT-001", 3000, "carries 50 cups"),
    _row("Aluminium Tray", "COM-AT-001", 7000, "Aluminium communion tray for 40 cups with its own lid."),
    _row("Silver Communion Tray", "843GLV9RC-D69A", 18000, "Silver-tone communion tray for 40 cups."),
    _row("Golden Communion Tray", "XYULGK29K-5D98", 22000, "Gold-plated communion cup tray holding 40 cups."),
    _row("Double Stacked Silver Tray Set", "COM-DSS-001", 36000, "Two stacked silver-tone cup trays."),
]
CUPS = [
    _row("Plastic Communion Cups", "COM-PC-001", 10, "Light, hygienic plastic cups made for communion trays."),
    _row("Pre-Packed Communion Cups", "COM-PCC-001", 30, "Sealed single-serve communion."),
    _row("Glass Cups", "YX9PKFQQ5", 100, "Bevelled-glass communion cups."),
    _row("Silver Communion Cups", "COM-SCC-001", 100, "Reusable silver communion cups, 10 ml each."),
]
CHALICES = [
    _row("Chalice Cup -Medium", "7IM6K8KA4", 10000, "Hand-engraved gold-plated brass chalice, medium size."),
    _row("Small Chalice Cup", "COM-LC-001", 12000, "A generously sized chalice in golden or silver finish."),
    _row("Chalice Cup - Medium Sized Gold Coated Stainless Steel", "COM-CCG-001", 20000,
         "Medium chalice in gold-coated stainless steel."),
    _row("Brass Chalice Cup", "CHA-BCC-001", 40000, "A brass chalice for Holy Communion."),
    _row("Golden Chalice Cup with Paten Set", "SF-CHL-01", 65000, "Chalice and paten in one set."),
]
SEEN = TRAYS + CUPS + CHALICES          # ctx.seen_products after the three searches, in order
SILVER_TRAY, PREPACKED, CHALICE_MEDIUM = TRAYS[3], CUPS[1], CHALICES[0]

DRAFT = ("Welcome 🙏 Here is what we have: the Silver Communion Tray is KES 18,000 (holds 40 cups), "
         "Plastic Communion Cups are KES 10 each, and the Chalice Cup -Medium is KES 10,000. "
         "How many cups do you need?")


def _fake_reviewer(monkeypatch):
    """A reviewer that reads the facts it is GIVEN, as the live one did: a
    chalice missing from its rows is 'not in hub inventory'."""
    llm = types.SimpleNamespace(prompts=[])

    async def complete(system, messages, tools=None, **kw):
        prompt = messages[0]["content"]
        llm.prompts.append(prompt)
        if "Chalice Cup -Medium" not in prompt:
            return types.SimpleNamespace(
                text="verdict=fail | issues=NOT OUR GOODS — chalices not listed in hub inventory")
        return types.SimpleNamespace(text="verdict=pass | issues=-")
    llm.complete = complete
    monkeypatch.setattr(rt, "build_llm", lambda model=None, **kw: llm)
    monkeypatch.setattr(settings, "reply_review", True)
    return llm


# ── 1. every row of the turn reaches the reviewer and the rewrite ───────────

def test_the_reviewer_is_shown_every_row_the_agent_found(monkeypatch):
    llm = _fake_reviewer(monkeypatch)
    v = asyncio.run(rv.review_reply(ASK, DRAFT, SEEN, currency="KES", mode="dm"))
    prompt = llm.prompts[-1]
    for p in SEEN:                                       # all 15, the chalices included
        assert f"- {p['name']} — KES " in prompt, p["name"]
    assert "- Chalice Cup -Medium — KES 10000" in prompt
    assert not any("NOT OUR GOODS" in i or "WRONG ITEM" in i for i in v["issues"]), v["issues"]
    assert v["ok"] and v["hard"] == [] and v["soft"] == []


def test_the_rewrite_is_given_the_same_rows():
    block = rv.rewrite_block(["x"], DRAFT, SEEN, "KES", [], mode="dm", comment=ASK)
    for p in SEEN:
        assert f"- {p['name']} — KES " in block, p["name"]


def test_a_row_found_twice_is_listed_once_and_a_long_turn_says_the_list_is_partial():
    text = rv.rows_text(SEEN + [CHALICE_MEDIUM, SILVER_TRAY], "KES")
    assert text.count("- Chalice Cup -Medium — ") == 1
    assert text.count("- Silver Communion Tray — ") == 1
    many = [_row(f"Row {i}", f"SKU-{i}", 100 + i, "") for i in range(35)]
    text = rv.rows_text(many, "KES")
    assert text.count("\n- Row ") + text.startswith("- Row ") == 30
    assert "+5 more rows looked up and not listed" in text
    assert "NOT proof we do not stock it" in text


def test_the_rows_are_priced_as_the_agent_saw_them_in_every_currency():
    kes = rv.rows_text([CHALICE_MEDIUM], "KES")
    assert kes.startswith("- Chalice Cup -Medium — KES 10000")
    # USD: KES / the house rate, as tools._to_display gives it
    usd = rv.rows_text([CHALICE_MEDIUM], "USD")
    agent_usd = tools._to_display(10000, types.SimpleNamespace(currency="USD",
                                                                usd_rate=settings.usd_kes_rate))
    assert usd.startswith(f"- Chalice Cup -Medium — USD {agent_usd}")
    # ZMW (the sibling, same day: a Zambian reply was judged against KES rows
    # labelled KES): the ZMW figure the agent quoted, under ZMW
    zmw = rv.rows_text([CHALICE_MEDIUM], "ZMW")
    assert zmw.startswith(f"- Chalice Cup -Medium — ZMW {10000 / settings.zmw_kes_rate:g}")
    assert "KES" not in zmw
    own = dict(CHALICE_MEDIUM, prices={"ZMW": 800})
    assert rv.rows_text([own], "ZMW").startswith("- Chalice Cup -Medium — ZMW 800")
    # an unpriced row is never shown as 0
    unpriced = dict(CHALICE_MEDIUM, price=0)
    assert "no price set in the hub" in rv.rows_text([unpriced], "KES")


# ── 2. the rules: three things asked, three things fit ──────────────────────

def test_a_tray_or_cups_asked_beside_a_chalice_fit_the_ask():
    assert rv.kinds_of(ASK) == {"tray", "cup", "chalice"}
    assert rv.item_issues(ASK, SILVER_TRAY) == []
    assert rv.item_issues(ASK, PREPACKED) == []
    assert rv.item_issues(ASK, CHALICE_MEDIUM) == []
    # both live drafts: no item finding, so nothing is held for it
    for draft in (DRAFT, "Pre-Packed Communion Cups are KES 30 each, and the Wooden tray is KES 5,000."):
        findings = rv.rule_findings(ASK, draft, SEEN, currency="KES", mode="dm")
        assert not [f for f in findings if f["kind"] == "item"], findings


def test_a_chalice_cup_is_still_one_chalice_and_cups_are_still_not_a_chalice():
    assert rv.kinds_of("I want a chalice cup") == {"chalice"}
    assert rv.kinds_of("Chalice Cup -Medium") == {"chalice"}
    assert rv.item_issues("I want a chalice cup", CUPS[2]) == [
        "they asked for a chalice; 'Glass Cups' is not one"]
    assert rv.item_issues("how much is a chalice?", SILVER_TRAY) == [
        "they asked for a chalice; 'Silver Communion Tray' is not one"]
    bad = rv.item_issues("communion cups please", CHALICE_MEDIUM)
    assert len(bad) == 1 and "is a chalice" in bad[0]


# ── 3. the valid checks still stand ─────────────────────────────────────────

def test_one_currency_and_the_hubs_own_figures_still_hold():
    two = DRAFT + " That is about USD 280 for the set."
    findings = rv.rule_findings(ASK, two, SEEN, currency="KES", mode="dm")
    assert any(f["kind"] == "currency" for f in findings)
    wrong = DRAFT.replace("KES 10,000", "KES 9,500")
    findings = rv.rule_findings(ASK, wrong, SEEN, currency="KES", mode="dm")
    assert any(f["kind"] == "figure" and f["hard"] for f in findings)


# ── 4. the turn end to end: draft → rules + reviewer → what the customer gets ─
# (owner, 2026-10-05: "should have sold. fix the problem")

HAND_OFF = (rt._REVIEW_HOLD_DM_PRICE, rt._REVIEW_HOLD_DM)

# The live first draft's shape: the trays and cups by their hub names, the
# chalice described rather than named, and a dollar figure beside the shillings.
LIVE_FIRST = ("Welcome 🙏 Yes, we have all three: the Silver Communion Tray is KES 18,000 (USD 180) "
              "and the Golden Communion Tray KES 22,000, both for 40 cups; Plastic Communion Cups "
              "are KES 10 each and Pre-Packed Communion Cups KES 30; and a medium chalice cup is "
              "KES 10,000. How many cups do you need?")
# The sale: the stocked items, hub KES prices, one currency, a quantity question
# and the next step to buy.
SALE = ("Welcome 🙏 Yes, we have all three: the Silver Communion Tray (40 cups, with lid, holder and "
        "basin) is KES 18,000; Plastic Communion Cups are KES 10 each; and the Chalice Cup -Medium "
        "is KES 10,000. How many cups would you like? Tell me the quantities and your delivery "
        "town and I will put your order together with the payment details.")


class _Writer:
    def __init__(self, *texts):
        self.texts = list(texts)
        self.calls = 0

    async def complete(self, system, messages, tools=None, **kw):
        self.calls += 1
        return types.SimpleNamespace(text=self.texts.pop(0) if self.texts else "")


def _turn(draft, monkeypatch, *writer_texts):
    """The gate exactly as run_turn calls it for a Kenyan WhatsApp DM, with the
    turn's 15 rows in ctx.seen_products and a reviewer that judges the facts
    it is given (a chalice missing from them is 'not in hub inventory')."""
    reviewer = _fake_reviewer(monkeypatch)
    flagged = []

    async def no_facts(ctx, user_text, tool_log):
        return []

    async def flag(db, channel, key, issues, draft):
        flagged.append(issues)
    monkeypatch.setattr(rt, "_facts_for_ask", no_facts)
    monkeypatch.setattr(rt, "_flag_held_reply", flag)
    ctx = types.SimpleNamespace(seen_products=list(SEEN), read_only=True, currency="KES")
    writer = _Writer(*writer_texts)
    out = asyncio.run(rt._gate_turn_reply(
        draft, user_text=ASK, transcript=[{"role": "user", "content": ASK}], tool_log=[],
        ctx=ctx, currency="KES", channel="whatsapp", public_comment=False, llm=writer,
        sys_blocks=["SYSTEM"], redis=None, db=None, key="254700706875", fx=None, closer=False))
    return out, reviewer, writer, flagged


def test_the_live_turn_now_sells(monkeypatch):
    # the sale goes out as written: no rewrite, nothing held, nobody flagged
    (reply, held, outcome), reviewer, writer, flagged = _turn(SALE, monkeypatch)
    assert (reply, held, outcome) == (SALE, [], "pass")
    assert writer.calls == 0 and flagged == []
    assert "- Chalice Cup -Medium — KES 10000" in reviewer.prompts[-1]
    for item, price in (("Silver Communion Tray", "KES 18,000"), ("Plastic Communion Cups", "KES 10"),
                        ("Chalice Cup -Medium", "KES 10,000")):
        assert item in reply and price in reply
    assert "USD" not in reply and "$" not in reply and reply not in HAND_OFF
    # the live first draft (two currencies) is corrected into the sale, not held:
    # before the fix both of its drafts carried "they asked for a chalice;
    # 'Silver Communion Tray' is not one" and the customer got the hand-off
    (reply, held, outcome), _r, writer, flagged = _turn(LIVE_FIRST, monkeypatch, SALE)
    assert (reply, held, outcome) == (SALE, [], "rewritten")
    assert writer.calls == 1 and flagged == []


def test_the_valid_checks_still_bite_end_to_end(monkeypatch):
    # two currencies: the draft is never passed as it stands
    (reply, held, outcome), *_ = _turn(LIVE_FIRST, monkeypatch, LIVE_FIRST)
    assert outcome == "soft" and reply == LIVE_FIRST         # soft, by design: sent with notes
    v = rv.rule_findings(ASK, LIVE_FIRST, SEEN, currency="KES", mode="dm")
    assert any(f["kind"] == "currency" for f in v)
    # a made-up figure, twice: held, the team is flagged, the customer gets the hand-off
    made_up = SALE.replace("KES 10,000", "KES 9,500")
    (reply, held, outcome), _r, _w, flagged = _turn(made_up, monkeypatch, made_up)
    assert outcome == "held" and reply in HAND_OFF and flagged
    assert any("unverified figure(s) 9,500" in i for i in held)
    # an item that is not in this turn's results, at a price no row carries: held the same way
    # (one priced at ANOTHER row's figure passes the rules; the reviewer reads that one)
    not_found = SALE.replace("How many cups", "The Brass Candle Stand is KES 3,750. How many cups")
    (reply, held, outcome), _r, _w, flagged = _turn(not_found, monkeypatch, not_found)
    assert outcome == "held" and reply in HAND_OFF and flagged
    assert any("unverified figure(s) 3,750" in i for i in held)
