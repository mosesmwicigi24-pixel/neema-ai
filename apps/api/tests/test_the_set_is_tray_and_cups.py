"""THE SET IS THE TRAY WITH ITS CUPS (owner, 2026-10-05: "Tray + cups together").

In one week the item rule held nine replies to "how much is the set?" — "they
asked for a set; 'Golden Communion Tray' is a tray" — a HARD finding, so each
customer got a holding line instead of a price. A communion set is the cup
tray with its cups: a reply offering the tray with the cups fits the ask; a
tray offered alone is told to add the cups and is never held for it; a bread
tray or a chalice alone is still not the set. The same week also held a
Swahili tray ask ("siniya ya kubebea vikombe") and "the one with 40cups" as
cups. Fixtures are the held asks of that week, anonymised (no names, no
numbers); drafts are the held drafts where they were stored, else what the
hold's reasons describe.
"""
import asyncio
import types

import app.main  # noqa: F401
from app.agent import review as rv
from app.agent import runtime as rt


def _row(name, sku, kes, usd, desc):
    return {"name": name, "sku": sku, "slug": sku.lower(), "price": kes, "price_usd": usd,
            "prices": {}, "category": "Communion Items", "aliases": [], "description": desc}


GOLDEN = _row("Golden Communion Tray", "XYULGK29K-5D98", 22000, 220, "Gold-plated communion cup tray holding 40 cups.")
SILVER = _row("Silver Communion Tray", "843GLV9RC-D69A", 18000, 180, "Silver-tone communion tray for 40 cups.")
ALU = _row("Aluminium Tray", "COM-AT-001", 7000, 70, "Aluminium communion tray for 40 cups with its own lid.")
GOLD_BREAD = _row("Gold bread tray", "COL-GBT-001", 14000, 140, "Shallow gold-tone bread tray with a fitted lid.")
SILVER_BREAD = _row("Silver Bread Tray", "ML8FMKZQL-7661", 13000, 130, "Silver-tone bread plate with matching lid.")
PLASTIC = _row("Plastic Communion Cups", "COM-PC-001", 10, 0.1, "Light, hygienic plastic cups made for communion trays.")
CHALICE = _row("Chalice Cup -Medium", "7IM6K8KA4", 10000, 100, "Hand-engraved gold-plated brass chalice, medium size.")
SEEN = [GOLDEN, SILVER, ALU, GOLD_BREAD, SILVER_BREAD, PLASTIC, CHALICE]

# The week's "set" asks (2026-10-01 → 04), as the customers wrote them.
SET_ASKS = ["How to order Sir and how much is the price of this Communion Set? PM Please Please",
            "How much set", "how much is full set", "How much the one set sir?", "I need 1 set.",
            "How much is the set? and how much is it please", "I need one set",
            "How much is the set", "I need a set"]

TRAY_AND_CUPS = ("The Golden Communion Tray is $220 — gold-plated, for 40 cups — and Plastic Communion "
                 "Cups are $0.10 each to fill it. How many cups would you like?")
TRAY_CUPS_INCLUDED = "The Golden Communion Tray is $220 — gold-plated, and it comes with cups included."
TRAY_ALONE = "The Golden Communion Tray is $220 and holds 40 cups — that's the full set as shown."


def _item(ask, draft):
    return [f for f in rv.rule_findings(ask, draft, SEEN, currency="USD", mode="dm") if f["kind"] == "item"]


def test_the_weeks_set_asks_are_no_longer_held_for_the_item():
    for ask in SET_ASKS:
        assert "set" in rv.kinds_of(ask), ask
        # the tray WITH its cups fits the set — no item finding at all
        assert _item(ask, TRAY_AND_CUPS) == [], ask
        assert _item(ask, TRAY_CUPS_INCLUDED) == [], ask
        # the tray alone: the rewrite is told to add the cups — and it never holds the reply
        alone = _item(ask, TRAY_ALONE)
        assert len(alone) == 1 and not alone[0]["hard"], ask
        assert alone[0]["text"].startswith(rv.SET_NEEDS_CUPS)


def test_a_bread_tray_or_a_chalice_alone_is_still_not_the_set():
    bread = _item("How much is the set", "The Gold bread tray is $140 — shallow, with a fitted lid.")
    assert len(bread) == 1 and bread[0]["hard"]
    assert bread[0]["text"] == "they asked for a set; 'Gold bread tray' is a tray"
    chalice = _item("How much is the set", "The Chalice Cup -Medium is $100 — hand-engraved.")
    assert len(chalice) == 1 and chalice[0]["hard"]
    # cups alone are not the set either
    cups = _item("How much is the set", "Plastic Communion Cups are $0.10 each.")
    assert len(cups) == 1 and cups[0]["hard"]
    # and a real set row fits as it always did
    stacked = _row("Double Stacked Silver Tray Set", "COM-DSS-001", 36000, 360, "Two stacked trays.")
    assert rv.item_issues("How much is the set", stacked, "The Double Stacked Silver Tray Set is $360.") == []


def test_swahili_trays_and_trays_named_by_their_cups():
    swahili = ("Natak siniy ya kubebea vikomb ila vikombe sitaki alafu unipe na siniya ya kubebea "
               "mikat na bila mikat")
    assert rv.kinds_of(swahili) == {"tray", "cup"}
    for word in ("sinia", "siniya", "masinia"):
        assert rv.kinds_of(f"bei ya {word}?") == {"tray"}
    held_draft = ("Kwa sinia ya vikombe: Silver Communion Tray ni USD 180.0. Kwa sinia ya mkate: "
                  "Silver Bread Tray – USD 130.0, au Gold bread tray – USD 140.0. Ungependa ipi?")
    assert _item(swahili, held_draft) == []
    # "the one with 40cups" is the tray that holds them
    assert rv.kinds_of("The one with 40cups") == {"tray"}
    assert _item("The one with 40cups", "The Silver Communion Tray is $180 — it holds 40 cups.") == []
    # …but cups wanted BY number are still cups, never a tray
    assert rv.kinds_of("I want 40 cups") == {"cup"}
    assert rv.kinds_of("how much for 100 cups") == {"cup"}


# ── the gate end to end ─────────────────────────────────────────────────────

class _Writer:
    def __init__(self, *texts):
        self.texts = list(texts)

    async def complete(self, system, messages, tools=None, **kw):
        return types.SimpleNamespace(text=self.texts.pop(0) if self.texts else "")


def _gate(monkeypatch, draft, *rewrites, ask="How much is the set"):
    async def none(*a, **k):
        return None

    async def no_facts(ctx, user_text, tool_log):
        return []

    async def no_flag(db, channel, key, issues, draft, redis=None):
        return None
    monkeypatch.setattr(rv, "reviewer_verdict", none)
    monkeypatch.setattr(rt, "_facts_for_ask", no_facts)
    monkeypatch.setattr(rt, "_flag_held_reply", no_flag)
    ctx = types.SimpleNamespace(seen_products=list(SEEN), read_only=True, currency="USD")
    return asyncio.run(rt._gate_turn_reply(
        draft, user_text=ask, transcript=[{"role": "user", "content": ask}], tool_log=[], ctx=ctx,
        currency="USD", channel="messenger", public_comment=False, llm=_Writer(*rewrites),
        sys_blocks=["SYSTEM"], redis=None, db=None, key="K", fx=None, closer=False))


HAND_OFF = (rt._REVIEW_HOLD_DM_PRICE, rt._REVIEW_HOLD_DM)


def test_the_set_sells_end_to_end(monkeypatch):
    assert _gate(monkeypatch, TRAY_AND_CUPS) == (TRAY_AND_CUPS, [], "pass")
    # the tray alone is rewritten with its cups…
    assert _gate(monkeypatch, TRAY_ALONE, TRAY_AND_CUPS) == (TRAY_AND_CUPS, [], "rewritten")
    # …and when the rewrite still leaves them out, the tray is sold, never held
    reply, held, outcome = _gate(monkeypatch, TRAY_ALONE, TRAY_ALONE)
    assert outcome == "soft" and reply == TRAY_ALONE and reply not in HAND_OFF
    # a bread tray offered for the set, twice: held as before
    bread = "The Gold bread tray is $140 — shallow, with a fitted lid."
    reply, held, outcome = _gate(monkeypatch, bread, bread)
    assert outcome == "held" and reply in HAND_OFF


def test_the_valid_checks_still_bite_on_a_set(monkeypatch):
    two = TRAY_AND_CUPS.replace("$220", "$220 (KES 22,000)")
    assert any(f["kind"] == "currency" for f in rv.rule_findings("How much is the set", two, SEEN,
                                                                  currency="USD", mode="dm"))
    made_up = TRAY_AND_CUPS.replace("$220", "$199")
    reply, held, outcome = _gate(monkeypatch, made_up, made_up)
    assert outcome == "held" and reply in HAND_OFF and any("unverified figure(s) 199" in i for i in held)
    off_list = TRAY_AND_CUPS.replace("to fill it.", "to fill it, and the Brass Candle Stand is $37.")
    reply, held, outcome = _gate(monkeypatch, off_list, off_list)
    assert outcome == "held" and any("unverified figure(s) 37" in i for i in held)
