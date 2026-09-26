"""TEN CYCLES — the closing battery (owner, 2026-09-26: "run 10 full
top-to-bottom cycles… refine every nuance so the app behaves like a highly
intelligent human salesperson"). Each check pins a nuance the cycles fixed:
a coherent prompt with no contradiction left in it, and an international
close that keeps Neema on the thread."""
import asyncio
import inspect
from types import SimpleNamespace

import app.main  # noqa: F401
import app.agent.runtime as rt
from app.agent import tools
from app.agent.prompt import build_system_prompt, customer_context

from tests.test_closing_carries_the_consultation import _DB, _R, _ctx, _wire  # noqa: F401


def _p(**kw):
    return build_system_prompt(**kw)


def test_the_prompt_reads_as_one_mind():
    p = _p(country_iso="", currency="USD", offer="Harvest Offer — 10% off")
    ke = _p(country_iso="KE", currency="KES")
    # the one-question rule names its two sanctioned shapes
    assert "The ONE sanctioned shape" in p and 'choices ("gold or silver?", "the 200 or the 500 pack?")' in p
    # two readings, one reply — never a silent pick
    assert "TWO READINGS, ONE REPLY" in p and "never a silent pick, least of all the dearer" in p
    # colour truth: sewn takes any colour; a stock line has its own
    assert "For a garment we sew, their colour is possible (COLOURS ARE\n  NEVER LIMITED)" in p
    assert "The two plain-truth exceptions" in p
    # the companion map and its timing
    assert "THE COMPANION\n  MAP" in p and "`goes_with`" in p
    assert "never before the price of what\n  they asked for" in p
    # the objection ladder, one rung per message; the offer rung only while one runs
    assert "THE OBJECTION LADDER" in p and "3. THE OFFER YOU ARE HOLDING (below)" in p
    assert "THE OFFER YOU ARE HOLDING" not in _p(offer="")
    assert "3. No offer is running today" in _p(offer="")
    # deferrals: three-part once, then one line, then silence
    assert 'A first "I\'ll get back to\n  you" with an item in play gets the three-part message' in p
    # one figure per item, beside the scope rule
    assert "ONE figure per item: a hub row has one price" in p
    # measurement timing, several wearers, the written quotation
    assert "WHEN TO MEASURE: after the yes" in p and "one list PER\n  WEARER" in p
    assert "A PARISH ORDER IN WRITING" in p and "`prepare_quotation`" in p
    # the international close keeps Neema on the thread
    assert "`create_order` has already told the team" in p and "you stay in the\n  conversation" in p
    assert "Do NOT present the KES payment link" in p
    # the payment block is labelled so every "see PAYMENT" lands
    assert "PAYMENT — for THEIR country" in p and "PAYMENT — for THEIR country" in ke
    # examples in the house style, no invented numbers, no real customers
    for bad in ("USD 50", "07xx", "Francis Xavier", "Apologies Simon", "your city or country",
                "about 5–7 days", "Live lesson", "how many exactly?", "Format for WhatsApp",
                "central-bank"):
        assert bad not in p and bad not in ke, bad
    assert "$50 to $45" in p and "typically 3–7 days" in p
    # the clock is in the tail, the shared block only points at it
    assert "THE CLOCK" in p and "in Nairobi right now" not in p
    assert "in Nairobi right now" in customer_context("", "", clock=True)
    # Kenya proved by evidence is a known country on every channel
    assert "You ALREADY know their country" in _p(country_iso="", currency="KES")
    assert "You do NOT know where this customer is" in _p(country_iso="", currency="USD")
    # the photo-reading rules sit with the photo cluster, not under STYLE
    assert p.index("READING A PHOTO — name only what is UNMISTAKABLE") < p.index("CLERGY WEAR EXPERTISE")
    assert p.index("METAL FINISH IS NOT THE PRODUCT LINE") < p.index("CLERGY WEAR EXPERTISE")
    # plain text everywhere, WhatsApp's single bold the one exception
    assert "PLAIN TEXT on every channel" in p and "On\n  WhatsApp alone a single *bold*" in p


def test_the_addenda_agree_with_the_shared_rules():
    meta = rt._meta_addendum("USD")
    assert "central-bank" not in meta and "TODAY'S RATE GIVEN IN YOUR CONTEXT" in meta
    assert "the team is told, you stay on" in meta
    assert "Francis Xavier" not in meta
    tiktok = rt._tiktok_addendum("USD")
    assert "till/paybill" not in tiktok and "order link create_order returns" in tiktok
    pub = " ".join(rt._public_comment_addendum("USD").split())
    assert "A SET IS PRICED AS ITS TOTAL (owner, 2026-09-21) and A PRICE CARRIES ITS SCOPE" in pub
    assert "ONE PIECE IS THE DEFAULT (owner rule) here too" in pub


def test_an_international_order_tells_the_team_and_keeps_neema_on(monkeypatch):
    items = [{"hub_product_id": 1, "name": "Cassock", "sku": "CAS", "qty": 1, "unit_price": 120,
              "made_to_order": True}]
    pushed = {"order_id": 78, "order_number": "WA-78", "total_amount": 13000, "currency_code": "KES",
              "public_url": "https://hub/order/tok78", "public_token": "tok78",
              "production_lines": [{"name": "Cassock"}], "unmatched": []}
    r = _R()
    db, calls = _wire(monkeypatch, items, pushed=pushed, redis=r, figures={})
    conv = SimpleNamespace(id="conv-1", channel="whatsapp", wa_id="254700111222", external_id=None,
                           person_id="p-1")
    db._r[1] = conv                          # the team-note lookup (the order's 2nd query) finds the thread
    published = []

    async def _publish(ch, payload):
        published.append((ch, payload))
    r.publish = _publish
    out = asyncio.run(_create_order_usd({"notes": "Johannesburg"}, _ctx(db, redis=r, currency="USD")))
    assert out["ok"] and out["team_told"] is True
    assert "transfer" in out["next_step"] and "never present the KES M-Pesa link" in out["next_step"]
    assert out["order_url"] == "https://neema.example/api/r/AB12CD"
    note = next(o for o in db.added if getattr(o, "media_type", "") == "note")
    assert "INTERNATIONAL ORDER #WA-78" in note.text and "Neema stays on the thread" in note.text
    assert published and published[0][1].count("international_order") == 1
    # a Kenyan order raises no such note
    db2, _ = _wire(monkeypatch, items, redis=_R(), figures={})
    out2 = asyncio.run(tools._create_order({}, _ctx(db2, redis=None)))
    assert out2["ok"] and "team_told" not in out2
    assert not any(getattr(o, "media_type", "") == "note" for o in db2.added)


async def _create_order_usd(args, ctx):
    return await tools._create_order(args, ctx)


def test_handoff_is_no_longer_the_international_payment_route():
    src = inspect.getsource(tools._create_order)
    assert 'if (ctx.currency or "KES") != "KES":' in src and "_team_note(" in src
    p = build_system_prompt(country_iso="ZA", currency="USD")
    intl = p[p.index("PAYMENT — for THEIR country"):p.index("ADDRESS THE PARCEL")]
    assert "then call `handoff_to_human` so a colleague confirms" not in intl
    assert "`handoff_to_human` only if they ask" in intl
