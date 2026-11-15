"""ORDER RECONSTRUCTION (owner, 2026-11-15 — the Melchizkek thread).

A customer chose three garments for two people by sending photos. The order
ended as two standard sets: one garment dropped, the style swapped. Pinned
here, without the model:

  * every photo of a burst reaches the turn; an album notice never says "we
    cannot see it";
  * photos keep a number; a message that points at them gets them back;
  * a cart line carries who each piece is for; an item with no hub price is
    held for a colleague and never replaced;
  * a removal needs the customer's own words, found in the record;
  * no order while a piece awaits a price or is unconfirmed;
  * a reply may not claim a cart change that did not happen.
"""
import asyncio
from datetime import datetime, timedelta, timezone

import app.main  # noqa: F401
from app.agent import cart as cartmod
from app.agent import order_sheet, review, tools
from app.agent.tools import ToolContext
from app.services import inbound_kinds, photo_memory, wa_native

NOW = datetime(2026, 11, 15, 12, 0, tzinfo=timezone.utc)

SET = {"hub_product_id": 7, "sku": "CAS-SET", "slug": "cassock-set", "name": "Cassock Set",
       "price": 19500, "price_usd": 195, "prices": {"KES": 19500, "USD": 195}, "aliases": [],
       "category": "Clergy Wear", "product_type": "simple", "is_producible": True,
       "in_stock": True, "variants": []}
CROSS = {"hub_product_id": 8, "sku": "EPC", "slug": "episcopal-cross", "name": "Episcopal Cross",
         "price": 20000, "price_usd": 200, "prices": {"KES": 20000, "USD": 200}, "aliases": [],
         "category": "Clergy Accessories", "product_type": "simple", "is_producible": False,
         "in_stock": True, "variants": []}


# ── photos ────────────────────────────────────────────────────────────────────

def test_an_album_notice_never_wakes_the_agent_or_says_we_cannot_see_it():
    d = inbound_kinds.describe({"type": "unsupported", "unsupported": {"type": "album"}})
    assert d["wake"] is False
    assert "cannot see" not in d["agent_text"] and "does not deliver" not in d["agent_text"]
    assert "album" in d["text"].lower() and "separately" in d["text"]


class _R:
    """The few redis calls the debounce buffer makes."""
    def __init__(self):
        self.kv, self.lists = {}, {}

    async def rpush(self, k, v):
        self.lists.setdefault(k, []).append(v)

    async def expire(self, k, s):
        return True

    async def incr(self, k):
        self.kv[k] = int(self.kv.get(k, 0)) + 1
        return self.kv[k]

    async def get(self, k):
        return self.kv.get(k)

    async def lrange(self, k, a, b):
        return list(self.lists.get(k, []))

    async def delete(self, k):
        self.lists.pop(k, None)


def test_every_photo_of_a_burst_reaches_the_turn_in_order():
    async def go():
        r = _R()
        await wa_native._enqueue(r, "1612", "", {"type": "image", "url": "/m/a.jpg"}, "1")
        await wa_native._enqueue(r, "1612", "", {"type": "image", "url": "/m/b.jpg"}, "2")
        await wa_native._enqueue(r, "1612", "", {"type": "image", "url": "/m/b.jpg"}, "3")   # a duplicate
        t = await wa_native._enqueue(r, "1612", "make these two for me", None, "4")
        return await wa_native._drain(r, "1612", t)
    text, media, ids = asyncio.run(go())
    assert text.strip() == "make these two for me"
    assert media["url"] == "/m/a.jpg" and [m["url"] for m in media["more"]] == ["/m/b.jpg"]
    assert ids == ["1", "2", "3", "4"]


def test_one_photo_is_still_one_photo():
    async def go():
        r = _R()
        t = await wa_native._enqueue(r, "1612", "", {"type": "image", "url": "/m/a.jpg"}, "1")
        return await wa_native._drain(r, "1612", t)
    _, media, _ = asyncio.run(go())
    assert media == {"type": "image", "url": "/m/a.jpg"}


def test_a_past_photo_reads_with_its_number_and_what_it_showed():
    assert photo_memory.history_line(None) == "[the customer sent a photo]"
    line = photo_memory.history_line(
        {"photo": {"n": 2, "h": 5, "seen": "our own photo of the Red Apostolic Cassock"}})
    assert line == "[the customer sent photo 2 — our own photo of the Red Apostolic Cassock]"


def test_words_that_point_at_photos_are_recognised():
    for t in ("make these two for me", "This one is his", "all as in the picture",
              "the purple one", "same as in the photo", "kama picha"):
        assert photo_memory.points_at_photos(t), t
    for t in ("How much is delivery to Minneapolis?", "My name is John and I pastor a church"):
        assert not photo_memory.points_at_photos(t), t


def _photos():
    return [{"n": 1, "label": "photo 1", "url": "/a", "at": NOW - timedelta(minutes=50), "seen": ""},
            {"n": 2, "label": "photo 2", "url": "/b", "at": NOW - timedelta(minutes=49), "seen": ""},
            {"n": 3, "label": "photo 3", "url": "/c", "at": NOW - timedelta(minutes=30), "seen": ""}]


def test_a_pointing_message_gets_the_recent_photos_back():
    got = photo_memory.to_attach(_photos(), "these two are mine, the purple one is his", now=NOW)
    assert [p["n"] for p in got] == [1, 2, 3]


def test_an_ordinary_message_and_an_old_photo_attach_nothing():
    assert photo_memory.to_attach(_photos(), "How long does shipping to the US take please?", now=NOW) == []
    late = NOW + timedelta(hours=6)
    assert photo_memory.to_attach(_photos(), "these two are mine", now=late) == []
    # a bare word earns the pictures only while they are fresh
    assert photo_memory.to_attach(_photos(), "Purple", now=NOW) == []
    assert photo_memory.to_attach(_photos(), "Purple", now=NOW - timedelta(minutes=20))


def test_the_same_picture_sent_again_is_the_same_photo():
    assert photo_memory.same_photo(0b1111, 0b1101)
    assert not photo_memory.same_photo(0, (1 << 40) - 1)
    assert not photo_memory.same_photo(None, 3)


# ── the cart as a record ─────────────────────────────────────────────────────

class _DB:
    async def commit(self):
        pass


def _rig(monkeypatch, start=None, said=()):
    store = {"items": list(start or []), "pending": []}
    asked = []

    async def fake_cart(db_, wa_id, channel="whatsapp"):
        return {"items": [dict(i) for i in store["items"]],
                "pending": [dict(p) for p in store["pending"]]}

    async def fake_save(db_, wa_id, cart, channel="whatsapp"):
        store["items"] = [dict(i) for i in cart["items"]]
        store["pending"] = [dict(p) for p in cart.get("pending") or []]
        return cart

    async def fake_clear(db_, wa_id, channel="whatsapp"):
        store["items"], store["pending"] = [], []
        return {"items": []}

    async def fake_catalog(db_, redis_):
        return [SET, CROSS]

    async def fake_check(args, ctx_):
        asked.append(dict(args))
        return {"ok": True, "team_check_open": True}
    monkeypatch.setattr(cartmod, "get_cart", fake_cart)
    monkeypatch.setattr(cartmod, "save_cart", fake_save)
    monkeypatch.setattr(cartmod, "clear_cart", fake_clear)
    monkeypatch.setattr(tools.svc, "catalog_items", fake_catalog)
    monkeypatch.setattr(tools, "_check_availability", fake_check)

    def call(said_now=said, **args):
        ctx = ToolContext(db=_DB(), redis=None, wa_id="16125550000", currency="USD",
                          channel="whatsapp", customer_words=tuple(said_now))
        return asyncio.run(tools._update_cart(args, ctx))
    return store, call, asked


TWO = [{"for": "himself", "colour": "black with red trim", "photo": "photo 1",
        "as_pictured": True, "status": "confirmed"},
       {"for": "his spiritual father", "colour": "purple", "photo": "photo 3",
        "as_pictured": True, "status": "tentative"}]


def test_a_line_carries_who_each_piece_is_for(monkeypatch):
    store, call, _ = _rig(monkeypatch)
    out = call(action="set", product="Cassock Set", quantity=2, details=TWO)
    assert out["ok"] and out["total"] == 390
    units = store["items"][0]["units"]
    assert [u["for"] for u in units] == ["himself", "his spiritual father"]
    assert units[0]["photo"] == "photo 1" and units[0]["as_pictured"] is True
    # a later change of number without details keeps what was known
    call(action="set", product="Cassock Set", quantity=3)
    assert len(store["items"][0]["units"]) == 2 and store["items"][0]["qty"] == 3


def test_a_repeat_add_with_details_updates_the_pieces_not_the_number(monkeypatch):
    store, call, _ = _rig(monkeypatch)
    call(action="add", product="Cassock Set", quantity=2)
    out = call(action="add", product="Cassock Set", quantity=2, details=TWO)
    assert out["ok"] and store["items"][0]["qty"] == 2
    assert len(store["items"][0]["units"]) == 2


def test_an_unpriced_item_is_held_for_a_colleague_and_never_replaced(monkeypatch):
    store, call, asked = _rig(monkeypatch)
    call(action="add", product="Cassock Set", quantity=1)
    out = call(action="hold", description="purple apostolic full set with stole and cross",
               details=[{"for": "his spiritual father", "photo": "photo 3", "as_pictured": True}])
    assert out["ok"] and out["team_asked"] is True
    assert asked and asked[0]["_unpriced"] is True and "photo 3" in asked[0]["item"]
    assert len(store["items"]) == 1                       # nothing took its place
    assert store["pending"][0]["for"] == "his spiritual father"
    assert out["total"] == 195 and "awaiting_price" in out
    assert "NOT in the total" in out["awaiting_price_note"]
    # held twice is held once, and the team is asked once
    call(action="hold", description="Purple apostolic full set with stole and cross",
         details=[{"for": "his spiritual father"}])
    assert len(store["pending"]) == 1 and len(asked) == 1


def test_the_unpriced_path_skips_the_near_name_catalogue_shortcut():
    import inspect
    src = inspect.getsource(tools._check_availability)
    assert 'args.get("_unpriced")' in src and "PRICE NEEDED" in src


def test_a_removal_needs_the_customers_own_words(monkeypatch):
    start = [{"hub_product_id": 7, "name": "Cassock Set", "sku": "CAS-SET", "variant_id": None,
              "qty": 2, "unit_price": 19500, "price_usd": 195, "prices": {"KES": 19500, "USD": 195}},
             {"hub_product_id": 8, "name": "Episcopal Cross", "sku": "EPC", "variant_id": None,
              "qty": 1, "unit_price": 20000, "price_usd": 200, "prices": {"KES": 20000, "USD": 200}}]
    store, call, _ = _rig(monkeypatch, start, said=("The purple one should have a stole",))
    for args in ({"action": "remove", "product": "Episcopal Cross"},
                 {"action": "clear"},
                 {"action": "set", "product": "Cassock Set", "quantity": 1},
                 {"action": "remove", "product": "Episcopal Cross", "customer_said": "remove the cross"},
                 {"action": "remove", "product": "Episcopal Cross", "customer_said": "ok"}):
        out = call(**args)
        assert out["ok"] is False and out["unchanged"] and "NOT CHANGED" in out["error"], args
    assert [(i["name"], i["qty"]) for i in store["items"]] == [("Cassock Set", 2), ("Episcopal Cross", 1)]
    # with their words in the record, it goes through (case and punctuation aside)
    out = call(said_now=("Please remove the cross, I already have one.",),
               action="remove", product="Episcopal Cross", customer_said="please remove the cross")
    assert out["ok"] and [i["name"] for i in store["items"]] == ["Cassock Set"]
    # raising a number was never a removal
    assert call(action="set", product="Cassock Set", quantity=3)["ok"]


def test_undoing_ones_own_addition_in_the_same_turn_needs_no_quote(monkeypatch):
    store, _, _ = _rig(monkeypatch)
    ctx = ToolContext(db=_DB(), redis=None, wa_id="16125550000", currency="USD", channel="whatsapp")
    asyncio.run(tools._update_cart({"action": "add", "product": "Episcopal Cross"}, ctx))
    out = asyncio.run(tools._update_cart({"action": "remove", "product": "Episcopal Cross"}, ctx))
    assert out["ok"] and store["items"] == []


def test_no_order_while_a_piece_awaits_a_price_or_is_unconfirmed(monkeypatch):
    store, call, _ = _rig(monkeypatch)
    call(action="set", product="Cassock Set", quantity=2, details=TWO)
    ctx = ToolContext(db=_DB(), redis=None, wa_id="16125550000", currency="USD", channel="whatsapp")
    out = asyncio.run(tools._create_order({}, ctx))
    assert "not yet confirmed" in out["error"] and "his spiritual father" in out["error"]
    call(action="hold", description="white and red apostolic cassock", details=[{"for": "himself"}])
    out = asyncio.run(tools._create_order({}, ctx))
    assert "awaiting a colleague's price" in out["error"] and out["awaiting_price"]


def test_the_order_so_far_is_written_for_the_model_and_for_the_workshop():
    items = [{"name": "Cassock Set", "qty": 2, "unit_price": 195, "units": order_sheet.clean_units(TWO)}]
    pending = [order_sheet.clean_pending("white and red apostolic cassock",
                                         [{"for": "himself", "photo": "photo 2", "as_pictured": True}])]
    note = order_sheet.sheet_note(items, 390, "USD", pending)
    assert "Cassock Set ×2 — USD 195 each" in note
    assert "for himself — black with red trim — as in photo 1 [confirmed]" in note
    assert "for his spiritual father — purple — as in photo 3 [tentative]" in note
    assert "AWAITING A COLLEAGUE'S PRICE" in note and "white and red apostolic cassock" in note
    assert "Total of the priced lines: USD 390" in note
    assert order_sheet.sheet_note([], 0, "USD", []) == ""
    # a line whose pieces do not add up says so
    short = order_sheet.sheet_note([dict(items[0], qty=3)], 585, "USD", [])
    assert "3 on the line but 2 described" in short
    assert "for himself" in order_sheet.for_order({"items": items})


def test_a_quote_must_really_be_in_the_record():
    said = ["Remove the cross please — I have one already."]
    assert order_sheet.quote_found("remove the cross, please", said)
    assert not order_sheet.quote_found("remove the stole", said)
    assert not order_sheet.quote_found("ok", ["ok"])
    assert not order_sheet.quote_found("", said)


def test_a_reply_may_not_claim_a_cart_change_that_did_not_happen():
    claim = "I've replaced the cassock in your order with the apostolic one."
    assert review.cart_claim_without_change(claim, [])
    assert review.cart_claim_without_change(
        claim, [{"tool": "update_cart", "out": {"ok": False, "unchanged": True, "error": "NOT CHANGED"}}])
    assert review.cart_claim_without_change(
        claim, [{"tool": "update_cart", "out": {"ok": True, "items": []}}]) is None
    assert review.cart_claim_without_change("The Cassock Set is USD 195.", []) is None
    kinds = [f["kind"] for f in review.rule_findings("change it", claim, [], tool_results=[])]
    assert "cart_claim" in kinds


def test_the_turn_is_wired():
    import inspect
    from app.agent import prompt, runtime
    src = inspect.getsource(runtime.run_turn)
    assert "_pm.index(db, redis, channel=channel, key=key, report=_pm_report)" in src
    assert "_pm.to_attach(_photos, user_text)" in src
    assert "_sheet.sheet_note(" in src and "customer_words=" in src
    assert "_more_imgs" in src
    assert "photo_memory import history_line" in inspect.getsource(runtime._history)
    psrc = inspect.getsource(prompt)
    assert "update_cart hold" in psrc and "NEVER put a listed product in its place" in psrc


# ── the permanent model test (app.jobs.eval_order_thread) ────────────────────

def test_the_thread_test_reads_the_order_record_not_the_wording():
    from app.jobs import eval_order_thread as ot
    ask3 = {"pieces": 3, "for_other": True, "no_loss": True, "closing": True}
    two = ot.order_state({"items": [{"name": "Cassock Set", "qty": 2}]})
    bad = ot.check_turn(ask3, "Your total is USD 390. Shall I start your order?", two,
                        {"garment_pieces": 3}, [])
    assert any("holds 2 garment" in b for b in bad) and any("garment was lost" in b for b in bad)
    assert any("spiritual father" in b for b in bad)
    full = ot.order_state({
        "items": [{"name": "Cassock Set", "qty": 2,
                   "units": [{"for": "himself"}, {"for": "himself"}]}],
        "pending": [{"description": "purple set with stole and cross", "for": "his spiritual father"}]})
    # a held stole or cross is not a garment
    assert ot.order_state({"items": [], "pending": [{"description": "stole and silver cross"}]})["garment_pieces"] == 0
    assert any("offered to place" in b for b in
               ot.check_turn({}, "It is USD 390; a colleague prices the rest. Shall I place it now?", full, None, []))
    assert full["garment_pieces"] == 3 and full["for_someone_else"]
    assert ot.check_turn(ask3, "Two sets are USD 390; a colleague will confirm the purple set's price.",
                         full, {"garment_pieces": 3}, []) == []
    # a closing total that hides the piece awaiting a price is a failure
    assert ot.check_turn(ask3, "The total is USD 390.", full, {"garment_pieces": 3}, [])
    # so is an order placed while it waits, asking again, or a blind reply
    placed = [{"tool": "create_order", "out": {"ok": True, "sandbox": True}}]
    assert any("order was placed" in b for b in ot.check_turn(ask3, "Done — colleague…", full, None, placed))
    assert ot.check_turn({}, "What would you like to order?", full, None, [])
    assert ot.check_turn({}, "I'm sorry, I can't see the photo.", full, None, [])
    # an accessory is not a garment
    assert ot.order_state({"items": [{"name": "Episcopal Cross", "qty": 1}]})["garment_pieces"] == 0


def test_the_thread_test_draws_its_own_pictures_and_stays_off_real_systems():
    import inspect
    from app.jobs import eval_order_thread as ot
    from app.services.post_catalog import dhash_bytes, hamming
    hashes = [dhash_bytes(ot.draw(k)) for k in (ot.BLACK, ot.WHITE, ot.PURPLE)]
    assert all(h is not None for h in hashes)
    assert hamming(hashes[0], hashes[2]) > 6          # told apart as different photos
    src = inspect.getsource(ot)
    assert "_local_db_only()" in inspect.getsource(ot.run)
    assert '"sandbox": True' in src and "_cleanup_contacts(redis, [CONTACT])" in src
    assert [len(t["photos"]) for t in ot.TURNS] == [2, 1, 0, 0, 0]


def test_an_offer_to_place_the_order_must_be_backed_by_the_record():
    offer = "The three cassocks come to $390. Shall I place it now?"
    held = [{"tool": "update_cart", "out": {"ok": True, "items": [{"name": "Cassock"}],
                                            "awaiting_price": ["stole and silver cross"]}}]
    assert "awaits a colleague" in review.order_offer_unready(offer, held)
    ready = [{"tool": "get_cart", "out": {"items": [{"name": "Cassock"}]}}]
    assert review.order_offer_unready(offer, ready) is None
    # a total over an empty record, with an offer to start
    tok = review.ORDER_STATE.set({"lines": 0, "awaiting": 0})
    try:
        multi = ("Everything comes to $455. Your cassocks are $130 each, the stole $25 and the cross $40. "
                 "Shall I start your two cassocks?")
        assert "nothing is on the order record" in review.order_offer_unready(multi, [])
        # the ordinary single-item sale is left alone
        assert review.order_offer_unready("The Cassock is $130. Shall I start your order?", []) is None
        assert review.order_offer_unready("Everything comes to $455.", []) is None
        kinds = [f["kind"] for f in review.rule_findings("how much", multi, [], tool_results=[])]
        assert "order_unready" in kinds
    finally:
        review.ORDER_STATE.reset(tok)
    # no state known: the rule stays out of the way
    assert review.order_offer_unready(offer, []) is None
