"""The five items left from the enforcement list (owner, 2026-11-23):
photos after the check, the repair window from the record, a private message
spoken of only when one went, prices without a currency and "free", the
language check in both directions — and the conflicts fixed with them."""
import asyncio
from datetime import datetime, timedelta, timezone

import app.main  # noqa: F401 — registers all SQLAlchemy models
import app.agent.tools as tools
import app.services.messaging as svc
from app.agent import policy as pol
from app.agent import review as rv
from app.agent import runtime as rt
from app.agent.tools import ToolContext
from app.agent.voice import honest_inbox_claims
from app.core.config import settings
from app.services import repair_window as rw

CATALOG = [
    {"name": "Pectoral Cross — Gold Finish", "sku": "PC-GOLD", "slug": "pectoral-cross-gold",
     "price": 4000, "price_usd": 40, "thumbnail_url": "https://img/pc.jpg"},
    {"name": "Ring", "sku": "RING-1", "slug": "ring", "price": 1500, "price_usd": 15,
     "thumbnail_url": "https://img/ring.jpg"},
]


def _acoro(value):
    async def f(*a, **k):
        return value
    return f


def _cards_ctx(monkeypatch, outbox):
    monkeypatch.setattr(settings, "media_public_url", "https://shop.example", raising=False)
    monkeypatch.setattr(tools, "_customer_currency", _acoro("KES"))
    monkeypatch.setattr(svc, "catalog_items", _acoro(CATALOG))
    monkeypatch.setattr(tools, "_record_shared_media", _acoro(None))
    sent = []

    async def fake_card(wa_id, *, image_url, title, body, url, button="View"):
        sent.append(title)
        return "wamid.1"

    monkeypatch.setattr(svc, "_send_waba_product_card", fake_card)
    ctx = ToolContext(db=object(), redis=None, wa_id="254712345678", channel="whatsapp",
                      currency="KES", outbox=outbox)
    return ctx, sent


# ── 2. photos and cards go out with a reply that passed ──────────────────────

def test_cards_wait_in_the_outbox_and_the_writer_is_told_the_same(monkeypatch):
    ctx, sent = _cards_ctx(monkeypatch, [])
    out = asyncio.run(tools._send_product_cards({"products": ["Ring", "Pectoral Cross — Gold Finish"]}, ctx))
    assert sent == []                                  # nothing has left yet
    assert out["ok"] and out["sent_cards"] == 2
    assert "delivered" in out["note"]                  # the writer's note is unchanged
    assert len(ctx.outbox) == 1
    # the same cards asked for twice in one turn go out once
    asyncio.run(tools._send_product_cards({"products": ["Ring", "Pectoral Cross — Gold Finish"]}, ctx))
    assert len(ctx.outbox) == 1


def test_a_passed_reply_delivers_the_queue(monkeypatch):
    ctx, sent = _cards_ctx(monkeypatch, [])
    asyncio.run(tools._send_product_cards({"products": ["Ring"]}, ctx))
    reply = asyncio.run(rt._flush_outbox(ctx, "Which would you like?", held=False,
                                         redis=None, channel="whatsapp", key="254712345678"))
    assert sent == ["Ring"] and reply == "Which would you like?" and ctx.outbox == []


def test_a_held_reply_withholds_the_queue(monkeypatch):
    ctx, sent = _cards_ctx(monkeypatch, [])
    asyncio.run(tools._send_product_cards({"products": ["Ring"]}, ctx))
    reply = asyncio.run(rt._flush_outbox(ctx, "hold line", held=True,
                                         redis=None, channel="whatsapp", key="254712345678"))
    assert sent == [] and reply == "hold line" and ctx.outbox == []


def test_cards_that_cannot_be_delivered_become_the_hubs_own_text(monkeypatch):
    ctx, sent = _cards_ctx(monkeypatch, [])

    async def broken(*a, **k):
        raise RuntimeError("graph down")

    monkeypatch.setattr(svc, "_send_waba_product_card", broken)
    asyncio.run(tools._send_product_cards({"products": ["Ring"]}, ctx))
    reply = asyncio.run(rt._flush_outbox(ctx, "Here it is.", held=False,
                                         redis=None, channel="whatsapp", key="254712345678"))
    assert reply.startswith("Here it is.")
    assert "Ring" in reply and "KES 1,500" in reply and "/product/ring" in reply


def test_a_direct_call_still_sends_at_once(monkeypatch):
    ctx, sent = _cards_ctx(monkeypatch, None)
    out = asyncio.run(tools._send_product_cards({"products": ["Ring"]}, ctx))
    assert sent == ["Ring"] and out["sent_cards"] == 1


# ── 6. the repair window, from the record ────────────────────────────────────

NOW = datetime(2026, 11, 23, tzinfo=timezone.utc)


def test_the_window_is_counted_from_the_delivery_we_recorded():
    assert rw.reading(delivered_at="2026-11-15T10:00:00+00:00", now=NOW)["window"] == "inside"
    assert rw.reading(delivered_at="2026-10-01T10:00:00+00:00", now=NOW)["window"] == "outside"


def test_an_older_order_proves_only_what_its_last_status_time_proves():
    old = rw.reading(hub_fulfillment="delivered", hub_status_at=NOW - timedelta(days=40), now=NOW)
    assert old["window"] == "outside" and not old["exact"]
    assert rw.reading(hub_fulfillment="delivered", hub_status_at=NOW - timedelta(days=3),
                      now=NOW)["window"] == "unknown"
    assert rw.reading(hub_status="processing", now=NOW)["window"] == "not_delivered"


def test_the_note_says_only_what_the_record_proves():
    outside = [dict(rw.reading(delivered_at="2026-10-01T10:00:00+00:00", now=NOW),
                    number="BH-1", items="Cassock")]
    assert "OUTSIDE the 14-day window" in rw.note(outside) and "1 Oct 2026" in rw.note(outside)
    unknown = [dict(rw.reading(hub_fulfillment="delivered", hub_status_at=NOW, now=NOW), number="BH-2")]
    assert "date is not on our record" in rw.note(unknown)
    assert "does not mean they have none" in rw.note([])
    assert rw.worst(outside) == "outside" and rw.worst(unknown) is None and rw.worst([]) is None


def test_a_sizing_question_before_a_sale_is_not_a_repair():
    assert rw.asks_about_repair("Can you alter it?") == "strong"
    assert rw.asks_about_repair("Nataka kurekebisha kanzu") == "strong"
    assert rw.asks_about_repair("is 42 too big for me?") == "weak"
    assert rw.asks_about_repair("How much is a cassock?") == ""
    assert not rw.has_delivery([{"window": "not_delivered"}])


def test_an_outright_repair_offer_is_read_and_a_deferral_is_not():
    assert pol.repair_offered("Of course, we can alter it for you — bring it to the shop.")
    assert not pol.repair_offered("Our repair window is 14 days from delivery, so a colleague will decide.")
    assert not pol.repair_offered("We will not be able to repair it.")


# ── 5. a private message is spoken of only when one went ─────────────────────

def test_a_private_message_claim_is_dropped_when_none_went():
    t = "The Clergy Shirt is $25. I've also sent you a private message — drop your number there."
    assert honest_inbox_claims(t, dm_sent=False) == "The Clergy Shirt is $25."
    assert honest_inbox_claims(t, dm_sent=True) == t


def test_photos_are_never_claimed_the_true_line_is_said():
    t = "We have the Chasuble at $80. I've sent photos to your inbox!"
    assert honest_inbox_claims(t, dm_sent=True, link_sent=True) == \
        "We have the Chasuble at $80. I've sent you a private message with the link."
    assert honest_inbox_claims(t, dm_sent=False) == "We have the Chasuble at $80."


def test_an_invitation_is_not_a_claim():
    for t in ("Send us a message and we'll help.", "DM us for details."):
        assert honest_inbox_claims(t, dm_sent=False) == t


def test_the_comment_instructions_no_longer_tell_her_to_claim_photos():
    import inspect
    src = inspect.getsource(rt)
    assert "sent photos to their inbox" not in src


# ── 7. a price without a currency, and "free" ────────────────────────────────

def test_a_price_without_a_currency_is_read():
    assert pol.bare_price_numbers("The cassock is 4,200 each.") == [4200.0]
    assert pol.bare_price_numbers("Bei ni 4500 tu.") == [4500.0]


def test_counts_years_sizes_and_marked_money_are_not_bare_prices():
    for t in ("It is KES 4,200.", "The set is $360.", "For 500 people you need 13 trays.",
              "We were founded in 2019.", "Size is 42", "it is 100% cotton", "ready at 10:30",
              "Total is 12,000/=", "We are at 1500 Moi Avenue", "There are 250 members"):
        assert pol.bare_price_numbers(t) == [], t


def test_free_needs_a_source():
    src = ["Every communion tray comes with 40 free plastic cups."]
    assert pol.unsourced_free("It comes with 40 free cups.", src) == ""
    assert pol.unsourced_free("I'll add a free stole for you.", src)
    assert pol.unsourced_free("Feel free to ask.", src) == ""
    assert pol.unsourced_free("Whenever you are free, let me know.", src) == ""


# ── 9. the language, both ways ───────────────────────────────────────────────

FRENCH = "Bonjour ! Le prix de la chasuble est de $80. Merci pour votre intérêt, nous livrons partout."


def test_a_french_reply_to_someone_who_wrote_no_french_is_found():
    assert rv.language_unasked("Prize?", FRENCH) == "fr"
    assert rv.language_unasked("Bonjour, le prix?", FRENCH) is None


def test_their_earlier_messages_count_as_their_language():
    assert rv.language_unasked("Ok thanks", FRENCH) == "fr"
    assert rv.language_unasked("Ok thanks", FRENCH, [{"role": "user", "content": "Bonjour, je cherche une chasuble"}]) is None


def test_a_swahili_answer_to_a_terse_message_is_never_a_finding():
    # one Swahili word the floor cannot place is still a Swahili speaker
    sw = "Samahani, maharagwe hatuuzi — sisi ni mavazi ya kanisa na vifaa vya ushirika tu."
    for ask in ("Maharagwe", "Bule 1,na white 1", "Price?"):
        assert rv.language_unasked(ask, sw) is None


def test_an_english_reply_and_a_wordless_customer_are_left_alone():
    assert rv.language_unasked("How much?", "The Clergy Shirt is KES 2,500 each.") is None
    assert rv.language_unasked("", FRENCH) is None


def test_the_reverse_language_finding_is_soft_and_runs_under_comments():
    for mode in ("dm", "comment"):
        f = [x for x in rv.rule_findings("Prize?", FRENCH, [], mode=mode) if x["kind"] == "language"]
        assert f and f[0]["hard"] is False


def test_a_swahili_comment_answered_in_english_is_corrected_not_held():
    en = "The Clergy Shirt is KES 2,500 each and we are in Nairobi. Would you like one for your church?"
    f = [x for x in rv.rule_findings("Bei ya shati ni ngapi tafadhali?", en, [], mode="comment")
         if x["kind"] == "language"]
    assert f and f[0]["hard"] is False


# ── 11. conflicts ────────────────────────────────────────────────────────────

def test_a_three_piece_total_is_a_verified_figure():
    seen = [{"name": "Clergy Shirt", "price": 2500, "price_usd": 25},
            {"name": "Cassock", "price": 8000, "price_usd": 80},
            {"name": "Stole", "price": 3000, "price_usd": 30}]
    a = "The Clergy Shirt is KES 2,500, the Cassock KES 8,000 and the Stole KES 3,000 — KES 13,500 in all."
    assert rv.unverified_figures(a, seen, "how much for all three", frozenset(), facts=set(),
                                 currency="KES") == []
    assert rv.unverified_figures(a.replace("13,500", "14,500"), seen, "how much for all three",
                                 frozenset(), facts=set(), currency="KES") == [14500.0]


def test_the_correction_texts_agree_with_the_instructions():
    import inspect
    src = inspect.getsource(rv)
    assert "no shop there" not in src                   # X11: reach, never the absence
    assert "at today's rate above" not in src           # X9: the rate given, by its own name
    assert "Western Union, Mukuru or" not in src        # X10: only the rails for their country


# ── 12. conversational quality, in context ───────────────────────────────────

def _ids(**kw):
    return [f["policy"] for f in pol.quality_findings(**kw)]


def test_a_welcome_is_fine_first_and_found_fifth():
    w = "Hello! Welcome to Bethany House. The cassock is KES 8,000."
    assert "CNV-01" not in _ids(reply=w, user_text="How much is a cassock?", earlier_replies=[])
    assert "CNV-01" in _ids(reply=w, user_text="How much is a cassock?", earlier_replies=["The stole is KES 3,000."])
    assert "CNV-01" not in _ids(reply=w, user_text="Good morning", earlier_replies=["The stole is KES 3,000."])


def test_a_list_is_fine_when_a_list_was_asked_for():
    lst = "Here they are:\n- Cassock\n- Stole\n- Cope\n- Chasuble"
    assert "CNV-05" in _ids(reply=lst, user_text="How much is a cassock?")
    assert "CNV-05" not in _ids(reply=lst, user_text="Send me the list of all your vestments")


def test_a_price_in_a_complaint_and_two_questions_are_read():
    log = [{"tool": "raise_complaint", "out": {"ok": True}}]
    assert "CNV-03" in _ids(reply="I am sorry. Our new stole is KES 3,000.", tool_log=log)
    assert "CNV-03" not in _ids(reply="I am sorry. A colleague is on it.", tool_log=log)
    assert "CNV-04" in _ids(reply="Which colour? And what size?")


def test_quality_findings_never_hold_a_reply(monkeypatch):
    monkeypatch.setattr(settings, "policy_mode", "enforce", raising=False)
    monkeypatch.setattr(settings, "policy_enforce", "*", raising=False)
    found = pol.quality_findings(reply="Which colour? And what size?")
    assert found and pol.enforced(found) == []


# ── the official-numbers line on a first reply that used a tool ──────────────

def test_the_first_reply_is_judged_from_the_conversation_before_the_turn():
    # found by the model run of 2026-11-23: the turn's own tool calls sit in
    # `messages` as assistant entries, so a first reply that looked something
    # up was read as a later reply and got no official-numbers line
    import inspect
    src = inspect.getsource(rt.run_turn)
    i = src.index("_first_reply = not any(")
    assert "for _m in turn_messages)" in src[i:i + 200]


def test_a_second_mention_of_our_numbers_gives_way_on_the_first_reply(monkeypatch):
    from app.agent.voice import strip_numbers_line
    monkeypatch.setattr(settings, "whatsapp_handoff_number", "+254727891989", raising=False)
    monkeypatch.setattr(settings, "whatsapp_handoff_alt", "+254785490805", raising=False)
    t = "Our Cassock is KES 13,000. Which colour would you like?\n\nYou can reach us on +254727891989 or +254785490805."
    assert strip_numbers_line(t, every_mention=True) == "Our Cassock is KES 13,000. Which colour would you like?"
    assert strip_numbers_line(t) == " ".join(t.split()) or strip_numbers_line(t) == t   # later replies are left alone


# ── who was served: one contact against their hub record ─────────────────────

def test_an_order_counts_as_served_only_from_the_day_they_first_wrote():
    from app.routers.ops_read import served_reading
    summ = {"orders": [
        {"order_type": "pos", "payment_status": "paid", "total": 5000, "currency_code": "KES",
         "created_at": "2026-10-01T09:00:00Z"},
        {"order_type": "whatsapp", "payment_status": "paid", "total": 13000, "currency_code": "KES",
         "created_at": "2026-11-20T15:00:00Z"},
        {"order_type": "invoice", "payment_status": "unpaid", "total": 2500, "currency_code": "KES",
         "created_at": "2026-11-21T10:00:00Z"}]}
    r = served_reading("2026-11-20T08:00:00+00:00", summ)
    assert r["in_hub"] and r["orders"] == 3 and r["before"] == 1
    assert [(o["type"], o["paid"]) for o in r["after"]] == [("whatsapp", True), ("invoice", False)]
    assert [o["days"] for o in r["after"]] == [0, 1]          # same day, then the next day
    assert served_reading("2026-11-20T08:00:00+00:00", None) == {"in_hub": False, "orders": 0, "after": [], "before": 0}


def test_the_served_report_returns_no_name_and_no_number():
    import inspect
    from app.routers import ops_read
    src = inspect.getsource(ops_read.served)
    ret = src[src.rindex("return {"):]
    assert "wa_id" not in ret and "name" not in ret and "phone" not in ret


def test_a_hub_record_with_orders_counted_but_none_listed_is_seen():
    from app.routers.ops_read import record_shape
    into: dict = {}
    record_shape({"customer": {"id": 7, "name": "X", "sales": [{"id": 1}]},
                  "stats": {"total_orders": "3"}}, into)
    record_shape({"customer": {"orders": [{"id": 2}]}, "stats": {"total_orders": 1}}, into)
    record_shape(None, into)
    assert into["records"] == 3
    assert into["stats_say_orders"] == 2 and into["orders_listed"] == 1
    assert into["stats_say_orders_but_none_listed"] == 1
    assert into["lists_of_records"] == {"customer.sales": 1, "customer.orders": 1}
    assert "X" not in str(into) and "name" in into["customer_keys"]


# ── a total is never given without what it is made of (owner, 2026-11-23) ────

_ORDER = [{"name": "Refiller Bottle 500ML", "qty": 2, "unit_price": 300},
          {"name": "Episcopal Cross", "qty": 1, "unit_price": 2800},
          {"name": "Cream Gold Cassock", "qty": 2, "unit_price": 2100}]


def test_a_bare_total_gets_the_lines_it_is_made_of():
    from app.agent.order_sheet import total_breakdown
    said = ("Noted, 2 Cream Gold Cassocks, one for her and one for you. The order totals "
            "ZMW 7,600, and your delivery address is saved.\n\nAre you ready to proceed with the order?")
    out = total_breakdown(said, _ORDER, 7600, "ZMW")
    first, second = out.split("\n\n")
    assert "2 × Refiller Bottle 500ML = ZMW 600" in first
    assert "1 × Episcopal Cross = ZMW 2,800" in first
    assert "2 × Cream Gold Cassock = ZMW 4,200" in first
    assert second == "Are you ready to proceed with the order?"


def test_a_reply_that_names_every_line_or_gives_no_total_is_left_alone():
    from app.agent.order_sheet import total_breakdown
    full = ("2 refiller bottles ZMW 600, the Episcopal Cross ZMW 2,800 and 2 Cream Gold "
            "Cassocks ZMW 4,200: ZMW 7,600 in all.")
    assert total_breakdown(full, _ORDER, 7600, "ZMW") == full
    no_total = "The Cream Gold Cassock is ZMW 2,100 each. How many do you need?"
    assert total_breakdown(no_total, _ORDER, 7600, "ZMW") == no_total
    one_line = "Your total is ZMW 4,200."
    assert total_breakdown(one_line, _ORDER[2:], 4200, "ZMW") == one_line
    # a line with no price yet: nothing is written that cannot be stood behind
    unpriced = _ORDER[:2] + [{"name": "Robe", "qty": 1, "unit_price": None}]
    assert total_breakdown("Total ZMW 3,400.", unpriced, 3400, "ZMW") == "Total ZMW 3,400."


def test_the_order_note_asks_for_the_lines_with_the_total():
    from app.agent.order_sheet import sheet_note
    assert "WHEN YOU GIVE THE TOTAL" in sheet_note(_ORDER, 7600, "ZMW", [])
    assert "WHEN YOU GIVE THE TOTAL" not in sheet_note(_ORDER[:1], 600, "ZMW", [])


def test_the_hubs_channel_names_the_kind_of_sale():
    from app.routers.ops_read import order_kind, served_reading
    assert order_kind({"channel": "till", "order_type": "pos"}) == "till"
    assert order_kind({"channel": "quoted", "invoice_number": "INV-1"}) == "invoice"
    assert order_kind({"channel": "quoted", "invoice_number": None}) == "quote"
    assert order_kind({"order_type": "POS"}) == "pos"
    # a till sale typed with a phone and no customer record still counts,
    # and Nairobi time is compared as an instant with the first chat (UTC)
    r = served_reading("2026-11-10T09:00:00+00:00", {"orders": [
        {"order_type": "till", "payment_status": "paid", "total": 800, "currency_code": "KES",
         "created_at": "2026-11-10T17:45:00+03:00"},
        {"order_type": "web", "payment_status": "paid", "total": 500, "currency_code": "KES",
         "created_at": "2026-11-09T23:30:00+03:00"}]})
    assert [o["type"] for o in r["after"]] == ["till"] and r["before"] == 1


# ── where an unpaid order stopped (owner, 2026-11-24) ────────────────────────

def test_where_an_unpaid_order_stopped():
    from app.routers.ops_read import stall_reading
    t = "2026-11-20T10:%02d:00+00:00"
    assert stall_reading(t % 0, [])["reason"] == "customer_silent_since_order"
    # what was said BEFORE the order, and internal notes, are not read
    r = stall_reading(t % 10, [(t % 5, "user", "I have paid", False),
                               (t % 12, "human_agent", "note: call him", True),
                               (t % 13, "ai", "Here is your order.", False)])
    assert r["reason"] == "customer_silent_since_order" and not r["staff_replied_after"]
    assert stall_reading(t % 0, [(t % 1, "ai", "Order made.", False),
                                 (t % 2, "user", "Nimetuma pesa", False),
                                 (t % 3, "ai", "Thank you.", False)])["reason"] \
        == "customer_says_paid_order_still_unpaid"
    assert stall_reading(t % 0, [(t % 1, "ai", "Order made.", False),
                                 (t % 2, "user", "ok and delivery?", False)])["reason"] \
        == "customer_wrote_last_no_reply"
    promised = [(t % 1, "ai", "A colleague will send you the payment number.", False)]
    assert stall_reading(t % 0, promised)["reason"] == "colleague_promised_none_came"
    assert stall_reading(t % 0, promised + [(t % 4, "human_agent", "Here it is", False)])["reason"] \
        == "customer_silent_since_order"
    assert stall_reading(t % 0, [(t % 1, "user", "what is your till number", False),
                                 (t % 2, "ai", "Use the link above.", False)])["reason"] \
        == "asked_how_to_pay_then_stopped"


def test_the_stalled_report_returns_no_name_no_number_no_text():
    import inspect
    from app.routers import ops_read
    src = inspect.getsource(ops_read.orders_stalled)
    ret = src[src.index("out = {"):]
    for word in ('"name"', '"text"', '"wa_id"', '"phone"', '"contact"'):
        assert word not in ret


# ── both numbers are ours (owner, 2026-11-28) ────────────────────────────────
A, B = "+254727891989", "+254785490805"


def test_a_reply_never_says_we_have_only_one_number():
    from app.agent.voice import both_official_numbers as fix
    out = fix(f"Yes, that is us. Our only number is {A}. How can I help?")
    assert "only number" not in out and A in out and B in out
    out = fix(f"You can reach us on {B}. We do not have another number.")
    assert "another number" not in out and A in out and B in out
    out = fix(f"Namba yetu ni {A}. Hatuna namba nyingine.", swahili=True)
    assert "Hatuna namba nyingine" not in out and B in out and "rasmi" in out
    out = fix("We only have one official line, the one you are writing to.")
    assert "only have one" not in out and A in out and B in out


def test_one_of_our_two_numbers_is_never_disowned():
    from app.agent.voice import both_official_numbers as fix
    out = fix(f"Please be careful: 0785490805 is not our number. Ours is {A}.")
    assert "not our number" not in out and A in out and B in out
    out = fix("Our official number is 0727 891 989. Any other number is not from Bethany House.")
    assert out.count("Any other number") == 1 and A in out and B in out      # only beside BOTH
    # a stranger's number may still be called not ours
    stranger = f"0700111222 is not our number. Our official numbers are {A} and {B}."
    assert fix(stranger) == stranger


def test_one_number_given_as_how_to_reach_us_comes_with_the_other():
    from app.agent.voice import both_official_numbers as fix
    out = fix(f"You can WhatsApp us on {B} and we will finish your order there.")
    assert out.endswith(f"Our other official number is {A}.")
    assert fix("Tupigie kwa 0727891989.", swahili=True).endswith(f"Namba yetu nyingine rasmi ni {B}.")
    both = f"Our official numbers are {A} and {B}. Any other number is not from Bethany House."
    assert fix(both) == both                                                 # already right: untouched
    plain = "The Clergy Shirt is KES 4,500. How many would you like?"
    assert fix(plain) == plain                                               # nothing about numbers
    # a payment instruction names the ONE line that takes that payment
    pay = "Please pay KES 4,500 by M-Pesa to 0727891989 and send me the confirmation message."
    assert fix(pay) == pay
    assert fix("") == "" and fix(None) == ""


def test_the_prompt_says_it_strictly_and_the_turn_checks_it():
    import inspect
    from app.agent import prompt, runtime
    src = inspect.getsource(prompt)
    assert "WE HAVE TWO OFFICIAL NUMBERS, AND BOTH ARE OURS" in src and "NEVER say we have only one" in src
    assert "both_official_numbers" in inspect.getsource(runtime.run_turn)
