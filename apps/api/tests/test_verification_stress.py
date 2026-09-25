"""The stress battery for double verification (owner, 2026-09-25: "verify,
test it, stress test many scenarios"). Every scenario runs the REAL rules
(the model reviewer is off here: no key) and, where it matters, the real
gate with a scripted writer. Two failure modes are hunted: a FALSE HOLD (a
good reply strangled — the thing that answered "When am in Uganda" with a
holding line) and a FALSE PASS (a figure or item from nowhere let through).
"""
import asyncio
import inspect
import types

import pytest

import app.main  # noqa: F401
from app.agent import review as rv
from app.agent import runtime as rt
from app.core.config import settings
from app.routers import meta_webhook as mw


def _row(name, kes, usd, desc="", **kw):
    r = {"name": name, "slug": name.lower().replace(" ", "-"), "price": kes, "price_usd": usd,
         "aliases": [], "description": desc, "product_type": "simple", "category": "Communion Items"}
    r.update(kw)
    return r


ROWS = {
    "silver": _row("Silver Communion Tray", 18000, 180, "Silver-tone communion tray for 40 cups, complete with lid, holder and basin."),
    "golden": _row("Golden Communion Tray", 22000, 220, "Gold-plated communion cup tray holding 40 cups."),
    "goldbread": _row("Gold bread tray", 14000, 140, "Shallow gold-tone bread tray with a fitted lid."),
    "wooden": _row("Wooden tray", 5000, 50, "A wooden communion tray that holds 100 cups."),
    "alu": _row("Aluminium Tray", 7000, 70, "Light aluminium communion tray for 40 cups with its own lid."),
    "dss": _row("Double Stacked Silver Tray Set", 36000, 360, "Two stacked silver-tone cup trays with a lidded bread tray."),
    "plastic": _row("Plastic Communion Cups", 10, 10, "Light plastic cups made for communion trays."),
    "silvercups": _row("Silver Communion Cups", 100, 10, "Reusable silver communion cups, 10 ml each."),
    "glass": _row("Glass Cups", 100, 10, "Bevelled-glass communion cups."),
    "chalice": _row("Golden Chalice Cup with Paten Set", 65000, 650, "Chalice and paten in one radiant gold-tone set.", category="Chalice"),
    "brass": _row("Brass Chalice Cup", 40000, 400, "A brass chalice for Holy Communion.", category="Chalice"),
    "smallchalice": _row("Small Chalice Cup", 12000, 120, "A generously sized chalice in golden or silver finish.", category="Chalice"),
    "cassock": _row("Cassock", 13000, 120, "Made to your measurements.", product_type="variable", is_producible=True),
    "cassockset": _row("Cassock Set", 19500, 200, "Cassock, stole, belt, straight collar shirt and a 12 inch clergy collar."),
    "tallit": _row("Tallit (Prayer Shawl) - Medium", 6000, 60, "Tallit in royal blue, navy or purple."),
    "refiller": _row("Refiller Bottle 500ML", 1500, 20, "A squeeze bottle.", aliases=["communion cup filler"]),
}


def _seen(*keys):
    return [ROWS[k] for k in keys]


def _tool(name, out):
    return {"tool": name, "input": {}, "out": out}


def _msgs(*pairs):
    return [{"role": r, "content": c} for r, c in pairs]


@pytest.fixture(autouse=True)
def _rules_only(monkeypatch):
    async def none(*a, **k):
        return None
    monkeypatch.setattr(rv, "reviewer_verdict", none)


# (id, ask, reply, seen, tool_log, transcript, fx, expect) — expect: pass | hard | soft
S = [
    # ── the live threads: must PASS ──────────────────────────────────────────
    ("uganda", "When am in Uganda",
     "We ship to Kampala from our Nairobi workshop. The shipping cost will be confirmed once we finalise "
     "your order. What's your phone number so we can arrange delivery?", [], [], [], None, "pass"),
    ("wansapp", "My wansapp number", "Thank you — noted, that is your WhatsApp number. A colleague will reach out shortly.",
     [], [], [], None, "pass"),
    ("phone", "0779174313",
     "Thank you — noted. A colleague will reach out to you shortly, and if you need us sooner you may call "
     "or WhatsApp us on +254785490805. Ready to place your order for 1 Medium Tallit in navy at $60?",
     [], [], _msgs(("assistant", "The Medium Tallit in navy is $60."), ("user", "0779174313")), None, "pass"),
    ("rands-rate", "how much that in rands",
     "The Cassock is $120 — about R1,971.60 at today's rate; USD stays the order's currency.",
     _seen("cassock"), [], [], {"ZAR": 16.43}, "pass"),
    ("rands-norate", "how much that in rands",
     "The Cassock is $120 — it's charged in USD and converts at the day's rate when you pay.",
     _seen("cassock"), [], [], None, "pass"),
    ("ok", "I'm saying ok", "Wonderful 🙏 whenever you're ready, tell me which one and I'll take your order.",
     [], [], [], None, "pass"),
    # ── everyday DM arithmetic: must PASS ────────────────────────────────────
    ("cart-total", "go ahead with 2", "Your total is KES 39,350 for 2 sets, delivery included.",
     _seen("cassockset"), [_tool("update_cart", {"total": 39350, "lines": [{"qty": 2, "unit": 19500}]})], [], None, "pass"),
    ("deposit", "how much deposit?", "A 50% deposit is KES 11,000 on the KES 22,000 tray.",
     _seen("golden"), [], [], None, "pass"),
    ("qty-digits", "I need 100 cups", "100 Plastic Communion Cups at KES 10 each come to KES 1,000.",
     _seen("plastic"), [], [], None, "pass"),
    ("qty-words", "I want two trays", "Two Golden Communion Trays come to KES 44,000.",
     _seen("golden"), [], [], None, "pass"),
    ("qty-swahili", "nataka trei tatu", "Trei tatu za Golden Communion Tray ni KES 66,000.",
     _seen("golden"), [], [], None, "pass"),
    ("k-suffix", "how much", "The Golden Communion Tray is KES 22k.", _seen("golden"), [], [], None, "pass"),
    ("fee", "and delivery?", "KES 22,000 for the tray plus KES 350 delivery within Nairobi — KES 22,350 in all.",
     _seen("golden"), [], [], None, "pass"),
    ("two-rows", "the silver tray and the gold bread tray", "Silver Communion Tray $180 and Gold bread tray $140 — $320 together.",
     _seen("silver", "goldbread"), [], [], None, "pass"),
    ("range", "communion trays?", "From the Wooden tray at KES 5,000 to the Double Stacked Silver Tray Set at KES 36,000.",
     _seen("wooden", "alu", "silver", "golden", "dss"), [], [], None, "pass"),
    ("offer", "any discount?", "Today's offer: 10% off — KES 22,000, now KES 19,800.",
     _seen("golden"), [_tool("apply_offer", {"list_price": 22000, "offer_price": 19800, "percent": 10})], [], None, "pass"),
    ("order-link", "send the link", "Your order is ready: https://bethanyhouse.co.ke/o/123 — pay by M-Pesa till 123456.",
     _seen("golden"), [_tool("create_order", {"order_url": "https://bethanyhouse.co.ke/o/123", "total": 22000})], [], None, "pass"),
    ("status-ok", "where is my order?", "Your order has been shipped and is on its way — expect it Thursday.",
     [], [_tool("check_order_status", {"status": "shipped"})], [], None, "pass"),
    ("status-promise", "when do I get tracking?", "Once it ships you'll receive a tracking number here.",
     [], [], [], None, "pass"),
    ("shipping-guess", "delivery to Durban?", "We deliver to Durban by DHL — about USD 50.",
     _seen("golden"), [], [], None, "hard"),          # a courier cost from memory is a figure from nowhere
    ("shipping-honest", "delivery to Durban?", "We deliver to Durban by DHL — the cost is confirmed when we finalise your order.",
     _seen("golden"), [], [], None, "pass"),
    ("nairobi-fee", "and delivery in Nairobi?", "Delivery within Nairobi is KES 350.", _seen("golden"), [], [], None, "pass"),
    ("budget", "my budget is KES 15,000", "Within KES 15,000 the Cassock at KES 13,000 fits well.",
     _seen("cassock"), [], [], None, "pass"),
    ("sizes", "size?", "It's cut to your measurements — chest 42 inches, length 58 inches — no charge for size.",
     _seen("cassock"), [], [], None, "pass"),
    ("hours", "are you open?", "We're open 8am to 6pm, Monday to Saturday.", [], [], [], None, "pass"),
    ("date", "when?", "Ready by 3 October, 2 to 3 days to deliver.", [], [], [], None, "pass"),
    ("swahili-price", "bei ya tray ya dhahabu", "Golden Communion Tray ni KES 22,000 — inabeba vikombe 40. Unahitaji ngapi?",
     _seen("golden"), [], [], None, "pass"),
    ("substitute", "do you have a wooden chalice?", "We don't have a wooden chalice — the Brass Chalice Cup is $400.",
     _seen("brass"), [], [], None, "pass"),
    ("choose-gold", "the gold one please", "The Golden Communion Tray it is — $220. How many?",
     _seen("silver", "golden"), [], [], None, "pass"),
    ("both-finishes", "silver tray and the gold bread tray", "The Silver Communion Tray is $180 and the Gold bread tray $140.",
     _seen("silver", "goldbread"), [], [], None, "pass"),
    ("plastic-or-glass", "plastic or glass cups?", "Plastic Communion Cups are $10 and Glass Cups $10 — which do you prefer?",
     _seen("plastic", "glass"), [], [], None, "pass"),
    ("chalice-cup", "how much is the chalice cup?", "The Small Chalice Cup is $120.", _seen("smallchalice"), [], [], None, "pass"),
    ("set", "the silver set", "The Double Stacked Silver Tray Set is $360.", _seen("dss"), [], [], None, "pass"),
    ("no-finish", "I need a stole", "Our stoles are made to order — which colour?", [], [], [], None, "pass"),
    ("black", "black cassock", "The Cassock in black is $120, made to your measurements.", _seen("cassock"), [], [], None, "pass"),
    ("where-answered", "where are you located?", "We're in Nairobi, Kenya — and we deliver worldwide by DHL.", [], [], [], None, "pass"),
    ("where-can-i-get", "Where can I get it", "Order right here with me — tell me the colour and I'll reserve it.", [], [], [], None, "pass"),
    ("live-in", "I live in Kenya", "Lovely — then it's KES 13,000 for the Cassock.", _seen("cassock"), [], [], None, "pass"),
    ("filler", "communion cup filler", "The Refiller Bottle 500ML is $20.", _seen("refiller"), [], [], None, "pass"),
    ("earlier-price", "and the tallit?", "As I said, the Medium Tallit is $60.",
     [], [], _msgs(("assistant", "The Medium Tallit is $60."), ("user", "and the tallit?")), None, "pass"),
    ("usd-of-kes", "in dollars?", "That's $180.", _seen("silver"), [], [], None, "pass"),
    ("per-piece", "silver cups?", "Silver Communion Cups are KES 100 each — how many?", _seen("silvercups"), [], [], None, "pass"),
    # ── must be HARD (held unless rewritten) ─────────────────────────────────
    ("wrong-price", "how much is the gold tray?", "The Golden Communion Tray is $175.", _seen("golden"), [], [], None, "hard"),
    ("nowhere", "how much is a cope?", "The Cope is $450.", [], [], [], None, "hard"),
    ("chalice-for-cups", "do you have some holycommunion cups", "The Golden Chalice Cup with Paten Set is $650.",
     _seen("chalice", "plastic"), [], [], None, "hard"),
    ("silver-for-gold", "gold trays with holes to place tot glasses", "The Silver Communion Tray is $180.",
     _seen("silver"), [], [], None, "hard"),
    ("bad-link", "send the link", "Pay here: https://pay.example.com/x", [], [], [], None, "hard"),
    ("status-nowhere", "where is my order?", "Your order has been shipped and is on its way!", [], [], [], None, "hard"),
    ("rands-wrong", "how much that in rands", "The Cassock is $120 — about R2,300.", _seen("cassock"), [], [], {"ZAR": 16.43}, "hard"),
    ("rands-invented", "how much that in rands", "The Cassock is $120 — about R1,971.60.", _seen("cassock"), [], [], None, "hard"),
    ("loose-sum", "how much is the gold tray?", "The Golden Communion Tray is KES 20,000.", _seen("golden", "goldbread"), [], [], None, "hard"),
    ("own-discount", "any discount?", "I can do KES 19,800 for you.", _seen("golden"), [], [], None, "hard"),
    # ── round two: the odd shapes of real chats ──────────────────────────────
    ("both-offered", "gold tray?", "The Golden Communion Tray is $220 — or the Silver Communion Tray at $180 if you prefer.",
     _seen("silver", "golden"), [], [], None, "pass"),
    ("named-not-priced", "gold trays", "We also have the Silver Communion Tray, very popular.",
     _seen("silver"), [], [], None, "soft"),
    ("scripture", "blessings", "Rev. 2 Timothy 3:16 — thank you for your order of 2 stoles at $40 each, $80 in all.",
     [_row("Stole", 4000, 40)], [], [], None, "pass"),
    ("paybill", "how do I pay?", "Pay by M-Pesa: Paybill 123456, account 7890 — KES 22,000 for the tray.",
     _seen("golden"), [], [], None, "pass"),
    ("ksh-dot", "bei?", "Ni Ksh. 22,000/- kwa tray ya dhahabu.", _seen("golden"), [], [], None, "pass"),
    ("no-space", "price", "It is KES22000 or USD220.", _seen("golden"), [], [], None, "soft"),   # two currencies: soft
    ("shillings-word", "bei", "Ni shilingi 22,000 — elfu ishirini na mbili.", _seen("golden"), [], [], None, "pass"),
    ("half-then-fee", "deposit and delivery?", "A KES 11,000 deposit now, and KES 350 delivery on the day.",
     _seen("golden"), [], [], None, "pass"),
    ("three-rows-sum", "all three", "Wooden KES 5,000, Aluminium KES 7,000 and Silver KES 18,000 — KES 30,000 together.",
     _seen("wooden", "alu", "silver"), [_tool("update_cart", {"total": 30000})], [], None, "pass"),
    ("tool-subtotal", "and with 2 cups packs?", "Subtotal KES 22,020.", _seen("golden", "plastic"),
     [_tool("update_cart", {"subtotal": 22020, "total": 22370})], [], None, "pass"),
    ("earlier-user-figure", "can you do 20,000?", "I can't go to KES 20,000 — the Golden Communion Tray is KES 22,000.",
     _seen("golden"), [], _msgs(("user", "can you do KES 20,000?")), None, "pass"),
    ("bare-20000", "can you do 20,000?", "I can't go to KES 20,000 — it's KES 22,000.", _seen("golden"), [], [], None, "hard"),
    ("percent-only", "discount?", "There's 10% off this week on the Golden Communion Tray, KES 22,000 list.",
     _seen("golden"), [], [], None, "pass"),
    ("usd-rate-conv", "in dollars?", "KES 13,000 is $130 at our rate.", [_row("Alb", 13000, None)], [], [], None, "pass"),
    ("hub-usd-wins", "in dollars?", "KES 13,000 is $130.", _seen("cassock"), [], [], None, "hard"),   # the hub says $120
    ("zmw-customer", "how much in kwacha", "It is ZMW 2,600.", _seen("cassock"), [], [], None, "hard"),  # not a Zambian-market turn here
    ("naira", "in naira?", "The Cassock is $120 — about ₦159,348 at today's rate.", _seen("cassock"), [], [], {"NGN": 1327.9}, "pass"),
    ("pounds", "how much in pounds", "The Cassock is $120 — about £90.77 at today's rate.", _seen("cassock"), [], [], {"GBP": 0.7564}, "pass"),
    ("qty-word-rate", "two in rands", "Two cassocks come to about R3,943.20 at today's rate.", _seen("cassock"), [], [], {"ZAR": 16.43}, "pass"),
    ("link-in-prompt", "where do I order?", "Order on our website https://bethanyhouse.co.ke/product/cassock — ready in 5 days.",
     _seen("cassock"), [_tool("share_catalog", {"url": "https://bethanyhouse.co.ke/product/cassock"})], [], None, "pass"),
    ("tracking-given", "tracking?", "Your tracking number is DHL123456789.", [], [], [], None, "hard"),
    ("tracking-given-tool", "tracking?", "Your tracking number is DHL123456789.", [],
     [_tool("check_order_status", {"status": "shipped", "tracking": "DHL123456789"})], [], None, "pass"),
    ("kampala-days", "to Kampala?", "DHL to Kampala takes 2 to 4 days; the cost is confirmed when we finalise the order.",
     [], [], [], None, "pass"),
    ("greeting", "hi", "Hello and welcome to Bethany House 🙏 How can I help you today?", [], [], [], None, "pass"),
    ("thanks-line", "thanks", "You're most welcome 🙏", [], [], [], None, "pass"),
    ("emoji-only-reply", "👍", "🙏", [], [], [], None, "pass"),
    ("measure", "measurements?", "Chest, waist, hips, shoulder and length — in inches, please.", [], [], [], None, "pass"),
    ("kes-and-each", "cups?", "Plastic Communion Cups are KES 10 each; 500 come to KES 5,000.", _seen("plastic"), [], [], None, "pass"),
    ("dozen", "a dozen stoles", "A dozen stoles at $40 each come to $480.", [_row("Stole", 4000, 40)], [], [], None, "pass"),
    ("variant-price", "size L?", "Size L is KES 15,000.", [_row("Thurible", 12000, 120, variants=[{"name": "L", "price_kes": 15000, "price_usd": 150}])], [], [], None, "pass"),
    ("bundle-total", "the full outfit", "Cassock, shirt and stole together: KES 21,000.",
     [{"name": "Cassock + Shirt + Stole", "price": 21000, "price_usd": 210, "bundle": True,
       "bundle_rows": [_row("Cassock", 13000, 120), _row("Shirt", 4000, 40), _row("Stole", 4000, 40)]}], [], [], None, "pass"),
    # ── round three: what a careful human would still try ────────────────────
    ("kes-from-usd", "bei ya cassock?", "Cassock ni KES 12,000.", _seen("cassock"), [], [], None, "hard"),   # the hub's KES is 13,000
    ("delivered-before", "do you deliver to Uganda?", "Yes — we have delivered to Kampala many times, by DHL.",
     [], [], [], None, "pass"),
    ("it-was-delivered", "my order?", "It was delivered yesterday.", [], [], [], None, "hard"),
    ("order-shipped-tool", "my order?", "Your order has been shipped — DHL123 is the tracking number.",
     [], [_tool("check_order_status", {"status": "shipped", "tracking": "DHL123"})], [], None, "pass"),
    ("repeat-link", "the link again?", "Here it is again: https://bethanyhouse.co.ke/o/123",
     [], [], _msgs(("assistant", "Your order link: https://bethanyhouse.co.ke/o/123"), ("user", "the link again?")), None, "pass"),
    ("fresh-link", "the link?", "Here: https://bethanyhouse.co.ke/o/999", [], [], [], None, "hard"),
    ("times-three-fee", "3 trays delivered", "KES 22,000 × 3 = KES 66,000, plus KES 350 delivery — KES 66,350.",
     _seen("golden"), [], [], None, "pass"),
    ("two-with-delivery", "two with delivery", "Two trays with delivery come to KES 44,350.", _seen("golden"), [], [], None, "pass"),
    ("cards-price", "show me", "Sent you the card — the Golden Communion Tray at KES 22,000.",
     [], [_tool("send_product_cards", {"sent": [{"name": "Golden Communion Tray", "price": 22000}]})], [], None, "pass"),
    ("mpesa-charge", "how do I pay", "M-Pesa to the till; the transaction fee is KES 30.", [], [], [], None, "hard"),
    ("stainless-cups", "stainless steel cups", "The Silver Communion Cups are KES 100 each.", _seen("silvercups"), [], [], None, "pass"),
    ("silver-cross", "silver pectoral cross", "We don't have it in silver — the Pectoral Cross in gold finish is $40.",
     [_row("Pectoral Cross — Gold Finish", 4000, 40)], [], [], None, "pass"),
    ("silver-cross-priced", "silver pectoral cross", "The Pectoral Cross — Gold Finish is $40.",
     [_row("Pectoral Cross — Gold Finish", 4000, 40)], [], [], None, "hard"),
    ("gold-chalice", "gold chalice", "The Golden Chalice Cup with Paten Set is $650.", _seen("chalice"), [], [], None, "pass"),
    ("paren-message", "(2 pcs) how much", "Two Golden Communion Trays come to $440.", _seen("golden"), [], [], None, "pass"),
    # ── SOFT only (asks for a rewrite, never holds) ──────────────────────────
    ("two-ccy", "how much", "The Silver Communion Tray is $180 (KES 18,000).", _seen("silver"), [], [], None, "soft"),
    ("where-unanswered", "Do you have shops in South Africa?", "The Golden Communion Tray is $220. How many?",
     _seen("golden"), [], [], None, "soft"),
]


@pytest.mark.parametrize("sid,ask,reply,seen,log,transcript,fx,expect", S, ids=[s[0] for s in S])
def test_scenario(sid, ask, reply, seen, log, transcript, fx, expect):
    v = asyncio.run(rv.review_reply(ask, reply, seen, tool_results=log, transcript=transcript,
                                    mode="dm", fx=fx, known_figures=rv.prompt_figures("USD")))
    if expect == "pass":
        assert v["ok"], f"FALSE HOLD on {sid}: {v['issues']}"
    elif expect == "hard":
        assert v["hard"], f"FALSE PASS on {sid}: {v}"
    else:
        assert v["soft"] and not v["hard"], f"{sid}: {v}"


# ── the gate end to end, with a scripted writer ─────────────────────────────

class _Writer:
    def __init__(self, *texts):
        self.texts = list(texts)
        self.calls = 0

    async def complete(self, system, messages, tools=None):
        self.calls += 1
        return types.SimpleNamespace(text=self.texts.pop(0) if self.texts else "")


class _Ctx:
    def __init__(self, seen=None):
        self.seen_products = list(seen or [])
        self.read_only = True


def _run(reply, *, ask, seen=(), writer_texts=(), tool_log=None, transcript=None, public=False,
         closer=False, fx=None, redis=None, monkeypatch=None):
    if monkeypatch is not None:
        async def no_facts(ctx, user_text, tool_log):
            return []
        monkeypatch.setattr(rt, "_facts_for_ask", no_facts)

        async def no_flag(db, channel, key, issues, draft):
            return None
        monkeypatch.setattr(rt, "_flag_held_reply", no_flag)
    return asyncio.run(rt._gate_turn_reply(
        reply, user_text=ask, transcript=transcript or [{"role": "user", "content": ask}],
        tool_log=list(tool_log or []), ctx=_Ctx(seen), currency="USD",
        channel="facebook" if public else "messenger", public_comment=public,
        llm=_Writer(*writer_texts), sys_blocks=["SYSTEM"], redis=redis, db=None, key="K",
        fx=fx, closer=closer))


def test_the_live_uganda_thread_never_gets_a_holding_line(monkeypatch):
    out = _run("We ship to Kampala from our Nairobi workshop. What's your phone number?",
               ask="When am in Uganda", monkeypatch=monkeypatch)
    assert out[2] == "pass" and out[0].startswith("We ship to Kampala")
    out = _run("Thank you — noted.", ask="My wansapp number", monkeypatch=monkeypatch)
    assert out[2] == "pass"


def test_a_wrong_price_is_rewritten_from_the_rows_and_sent(monkeypatch):
    out = _run("The Golden Communion Tray is $175.", ask="how much is the gold tray?", seen=_seen("golden"),
               writer_texts=["The Golden Communion Tray is $220 — how many would you like?"], monkeypatch=monkeypatch)
    assert out == ("The Golden Communion Tray is $220 — how many would you like?", [], "rewritten")


def test_a_soft_finding_sends_the_better_draft_even_when_the_rewrite_is_worse(monkeypatch):
    # two currencies (soft) → rewrite comes back with a figure from nowhere (hard) → the original goes out
    out = _run("The Silver Communion Tray is $180 (KES 18,000).", ask="how much", seen=_seen("silver"),
               writer_texts=["The Silver Communion Tray is $175."], monkeypatch=monkeypatch)
    assert out[2] == "soft" and out[0] == "The Silver Communion Tray is $180 (KES 18,000)."
    # the rewrite fixed it → the rewrite goes out
    out = _run("The Silver Communion Tray is $180 (KES 18,000).", ask="how much", seen=_seen("silver"),
               writer_texts=["The Silver Communion Tray is $180."], monkeypatch=monkeypatch)
    assert out == ("The Silver Communion Tray is $180.", [], "rewritten")


def test_a_price_from_nowhere_twice_holds_with_the_price_line_once(monkeypatch):
    class _R:
        def __init__(self):
            self.s = {}

        async def set(self, k, v, nx=False, ex=None):
            if nx and k in self.s:
                return False
            self.s[k] = v
            return True

        async def hincrby(self, *a):
            return 1

        async def expire(self, *a):
            return True
    r = _R()
    out = _run("The Cope is $450.", ask="how much is a cope?", writer_texts=["The Cope is $450, sir."],
               redis=r, monkeypatch=monkeypatch)
    assert out[0] == rt._REVIEW_HOLD_DM_PRICE and out[2] == "held"
    out = _run("The Cope is $450.", ask="and the mitre?", writer_texts=["The Mitre is $80."],
               redis=r, monkeypatch=monkeypatch)
    assert out[0] == "" and out[2] == "held"               # never two holding lines in a row


def test_an_acknowledgement_is_never_answered_with_a_holding_line(monkeypatch):
    out = _run("Great, $450 it is!", ask="I'm saying ok", writer_texts=["$450 then!"], closer=True,
               monkeypatch=monkeypatch)
    assert out[0] == "" and out[2] == "held"


def test_a_public_comment_held_returns_nothing_for_the_engines_line(monkeypatch):
    out = _run("The Cope is $450.", ask="how much is a cope?", writer_texts=["Still $450."], public=True,
               monkeypatch=monkeypatch)
    assert out[0] == "" and out[2] == "held"


# ── the thumbs-up, end to end through the webhook ───────────────────────────

def test_messengers_like_sticker_schedules_a_silent_turn(monkeypatch):
    import test_meta_webhook as tmw
    calls = []

    async def fake_person(db, channel, external_id, **kw):
        return types.SimpleNamespace(person_id="p-" + external_id)

    async def fake_conv(db, channel, external_id, **kw):
        return tmw._FakeConv()

    async def fake_sched(redis, channel, external_id, text, dedup_id=None, page_id=None, media=None):
        calls.append((external_id, text, media))
    monkeypatch.setattr("app.services.identity.resolve_or_create_person", fake_person)
    monkeypatch.setattr("app.services.channel.get_or_create_conversation", fake_conv)
    monkeypatch.setattr("app.services.meta_media.schedule_media_rehost", lambda *a, **kw: None)
    monkeypatch.setattr(rt, "schedule_meta_reply", fake_sched)
    monkeypatch.setattr(settings, "meta_agent_reply", True, raising=False)
    like = "https://scontent.xx.fbcdn.net/v/t39.1997-6/39178562_1505197616293642.png?oh=x"
    payload = {"object": "page", "entry": [{"messaging": [
        {"sender": {"id": "PSID_L"}, "message": {"mid": "l1", "attachments": [
            {"type": "image", "payload": {"url": like, "sticker_id": 369239263222822}}]}},
        {"sender": {"id": "PSID_S"}, "message": {"mid": "s1", "attachments": [
            {"type": "image", "payload": {"url": like, "sticker_id": 1234}}]}},
        {"sender": {"id": "PSID_P"}, "message": {"mid": "p1", "attachments": [
            {"type": "image", "payload": {"url": "https://scontent.xx.fbcdn.net/v/t1/photo.jpg"}}]}},
    ]}]}
    db = tmw._FakeDB()
    asyncio.run(mw._capture_events(db, "messenger", payload))
    assert calls == [
        ("PSID_L", "👍", None),                       # the thumbs-up: text, no image
        ("PSID_S", "[sticker]", None),                # another sticker: a reaction, no image
        ("PSID_P", "", {"type": "image", "url": "https://scontent.xx.fbcdn.net/v/t1/photo.jpg", "caption": ""}),
    ]
    from app.models.message import Message
    texts = [o.text for o in db.added if isinstance(o, Message)]
    assert texts == ["👍", "[sticker]", "[image]"]
    # and the scheduled thumbs-up turn ends at the closer gate: no model, no reply
    assert asyncio.run(rt.closer_gate(None, "messenger", "PSID_L", "👍")) is True
    assert asyncio.run(rt.closer_gate(None, "messenger", "PSID_S", "[sticker]")) is True


def test_the_ok_ping_pong_still_ends_in_silence():
    class _R:
        def __init__(self):
            self.s = {}

        async def get(self, k):
            return self.s.get(k)

        async def set(self, k, v, ex=None, nx=False):
            self.s[k] = v
            return True

        async def delete(self, k):
            self.s.pop(k, None)

        async def expire(self, k, t):
            return True
    r = _R()
    assert asyncio.run(rt.closer_gate(r, "messenger", "P", "ok")) is False      # the first "ok": one warm line
    asyncio.run(rt.mark_closer_answered(r, "messenger", "P", "ok"))
    assert asyncio.run(rt.closer_gate(r, "messenger", "P", "I'm saying ok")) is True   # then silence
    assert asyncio.run(rt.closer_gate(r, "messenger", "P", "how much is the tray?")) is False  # substance clears it
    assert asyncio.run(rt.closer_gate(r, "messenger", "P", "👍")) is True         # a thumbs-up: always silence


def test_every_channel_shares_one_policy():
    src = inspect.getsource(rt.run_turn)
    assert "await _gate_turn_reply(" in src
    for fn in (rt._run_and_send, rt._run_and_send_meta):
        assert "run_turn(" in inspect.getsource(fn) and 'if not (reply or "").strip():' in inspect.getsource(fn)
    from app.routers import web_chat, manychat
    assert "run_turn(" in inspect.getsource(web_chat) and "run_turn(" in inspect.getsource(manychat)
