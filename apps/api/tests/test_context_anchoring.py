"""ANCHORED TO THE PRODUCT (owner, 2026-10-07).

Under a stole post — "Looking for a gift the pastor in your life will actually
treasure? … Single sided: $25, Double sided: $40" — "We need it on the Plateau.
How can we get supply?!" was answered with the shoe giveaway's lines ("our team
will be selecting one recipient for this gift — completely free") and a list
of communion trays. The campaign detector had read "gift the pastor" as a
giveaway; with no product anchored, the writer searched "supply" and sold
trays. The owner: keep every response anchored to the exact product the
customer is discussing; keep contexts separate; "a gift for your pastor" does
not mean the product is free or part of a giveaway.
"""
import inspect

import app.main  # noqa: F401
import app.agent.runtime as rt
from app.agent import review as rv
from app.agent.prompt import build_system_prompt

STOLE_CAPTION = ("Looking for a gift the pastor in your life will actually treasure? Whether it's your pastor, "
                 "reverend, evangelist, bishop or the woman of God who has prayed with you through every season, a "
                 "stole says \"we see your service, and we're grateful.\" Beautifully made, durable, and meaningful "
                 "every time it's worn. 🙏 ✨ Single sided: $25 ✨ Double sided: $40 Ordering from abroad? We deliver "
                 "worldwide via DHL Express 🌍 💬 WhatsApp us: +254785490805 #BethanyHouse #PastorAppreciation "
                 "#ClergyGifts #Ordination #WomenInMinistr#fyp #ChurchWear #southafrica #fyp #vestments #zimbabwe #kenya")
COMMENT = "We need it on the Plateau. How can we get supply?!"
BAD_REPLY = ("Hello Dangt, welcome to Bethany House! 🙏 We deliver worldwide via DHL from our Nairobi workshop. Our "
             "team will be selecting one recipient for this gift — completely free, you'd only cover the shipping. "
             "Follow us and watch for the details on who's been selected. For supply to the Plateau, we have several "
             "communion trays. The Wooden Tray holds 100 cups at USD 50, the Aluminium Tray holds 40 cups at USD 70, "
             "the Silver Communion Tray at USD 180, and the Golden Communion Tray at USD 220 — all come with their cups "
             "included. Which would serve your congregation? May we also have your church and town so we can reach you "
             "if you're selected for the gift?")
GOOD_REPLY = ("Hello Dangt, welcome to Bethany House! 🙏 Gladly — we supply stoles to the Plateau by DHL from our "
              "Nairobi workshop. The Single Sided Stole is $25 and the Double sided stole is $40. How many would you "
              "like, and which town should we deliver to?")
SINGLE = {"name": "Single Sided Stole", "slug": "single-sided-stole", "price": 2500, "price_kes": 2500, "price_usd": 25,
          "prices": {"KES": 2500, "USD": 25}, "category": "Vestments", "product_type": "simple"}
DOUBLE = {"name": "Double sided stole", "slug": "double-sided-stole", "price": 4000, "price_kes": 4000, "price_usd": 40,
          "prices": {"KES": 4000, "USD": 40}, "category": "Vestments", "product_type": "simple"}

# the trays part of the bad reply alone — no campaign line
TRAYS_TEXT = BAD_REPLY.split("For supply")[1].split("May we also")[0]

def _tray(name, slug, kes, usd):
    return {"name": name, "slug": slug, "price": kes, "price_kes": kes, "price_usd": usd,
            "prices": {"KES": kes, "USD": usd}, "category": "Communion Items", "product_type": "simple"}


TRAYS = [_tray("Wooden tray", "wooden-tray", 5000, 50), _tray("Aluminium Tray", "aluminium-tray", 7000, 70),
         _tray("Silver Communion Tray", "silver-communion-tray", 18000, 180),
         _tray("Golden Communion Tray", "golden-communion-tray", 22000, 220)]


# ── the detector: a gift SOLD is not a giveaway ──────────────────────────────
def test_a_product_sold_as_a_gift_is_not_a_campaign():
    assert not rt.is_campaign_post(STOLE_CAPTION)
    for c in ("Gift ideas for your pastor: stoles from $25", "The perfect gift for the bishop in your life — KES 4,000",
              "A gift for your pastor — order now", "Looking for a gift the pastor will treasure? WhatsApp us",
              "Gifting season: a cassock for your reverend, KES 13,000, order today",
              "#ClergyGifts Beautiful stoles, single sided $25, double sided $40"):
        assert not rt.is_campaign_post(c), c
    # the owner's campaign still reads as one
    for c in ("We are donating or gifting pastors, reverends and bishops a shoe this month. One selected recipient will "
              "receive the shoe completely free — the recipient only pays the shipping.",
              "Gifting pastors, reverends, bishops a shoe.",
              "We are gifting one pastor this shoe. Only shipping is paid by the winner.",
              "One selected recipient will receive this pair", "This pair will be gifted to one reverend"):
        assert rt.is_campaign_post(c), c


# ── the reviewer holds a mixed reply and passes the anchored one ─────────────
def test_the_reviewer_holds_the_giveaway_and_the_trays_under_the_stole_post():
    found = rv.context_issues(COMMENT, BAD_REPLY, TRAYS, post_product="Single Sided Stole")
    texts = " | ".join(f["text"] for f in found)
    assert len(found) == 2 and all(f["hard"] and f["kind"] == "context" for f in found)
    assert "giveaway" in texts and "trays the customer never asked for" in texts
    f = rv.rule_findings(COMMENT, BAD_REPLY, TRAYS, post_product="Single Sided Stole", campaign=False)
    assert sum(1 for x in f if x["kind"] == "context") == 2
    # the anchored reply carries no context finding
    assert rv.context_issues(COMMENT, GOOD_REPLY, [SINGLE, DOUBLE], post_product="Single Sided Stole") == []
    f2 = rv.rule_findings(COMMENT, GOOD_REPLY, [SINGLE, DOUBLE], post_product="Single Sided Stole")
    assert not any(x["kind"] == "context" for x in f2)
    # an explicit change from the customer wins: trays asked for are trays answered
    assert rv.context_issues("Do you also have communion trays? Prices please", TRAYS_TEXT,
                             TRAYS, post_product="Single Sided Stole") == []
    # under a real campaign the giveaway words are the host's own
    assert not any("giveaway" in f["text"] for f in
                   rv.context_issues("Size 42", "Our team will be selecting one recipient — completely free.", [],
                                     post_product="", campaign=True))
    # with no identity on record the caption still anchors the kind
    found_c = rv.context_issues(COMMENT, BAD_REPLY, TRAYS, post_caption=STOLE_CAPTION)
    assert any("trays the customer never asked for" in f["text"] for f in found_c)


def test_the_reviewers_kinds_read_hub_names_captions_and_comments_alike():
    assert rv.row_kind(SINGLE) == "stole" and rv.row_kind(DOUBLE) == "stole"
    assert {rv.row_kind(r) for r in TRAYS} == {"tray"}
    assert rv.row_kind({"name": "CINCTURE BELT"}) == "cincture"
    assert rv.row_kind({"name": "Chalice Cup -Medium"}) == "chalice"          # one thing, the review's own rule
    assert rv.row_kind({"name": "Tallit (Prayer Shawl) - Medium"}) == "tallit"
    assert rv.row_kind({"name": "Pectoral Cross with Chain"}) == "cross"
    assert rv.row_kind({"name": "Double Stacked Silver Tray Set"}) == "set"
    assert rv.row_kind({"name": "Bishopric Ring"}) == "ring"
    assert rv.row_kind({"name": "Thingamajig"}) == "" and rv.row_kind(None) == ""
    assert rv.goods_kinds_in(COMMENT) == set()                                  # "supply" is no kind
    assert rv.goods_kinds_in(STOLE_CAPTION) == {"stole"}
    assert rv.goods_kinds_in("Je, mna kasoki na sinia?") == {"cassock", "tray"}
    assert rv.goods_kinds_in("the one with 40 cups") == {"tray"}
    assert rv.goods_kinds_in("Size 42 please") == set()


def test_a_reply_that_keeps_the_stole_and_adds_a_tray_is_a_soft_finding():
    reply = GOOD_REPLY + " We also have the Wooden tray at USD 50 if you need communion ware."
    found = rv.context_issues(COMMENT, reply, [SINGLE, DOUBLE] + TRAYS, post_product="Single Sided Stole")
    assert len(found) == 1 and not found[0]["hard"] and "trays the customer never asked for" in found[0]["text"]
    # the post's kind spoken of by name, without its hub row in the tool results, still counts as covered
    reply2 = "We supply stoles to the Plateau. The Wooden tray is USD 50."
    found2 = rv.context_issues(COMMENT, reply2, TRAYS, post_product="Single Sided Stole")
    assert len(found2) == 1 and not found2[0]["hard"]
    # a set post is answered with any of its pieces
    assert rv.context_issues("how much", "The Wooden tray is USD 50 with its cups.", TRAYS,
                             post_product="Aluminium 4-Stack Communion Set") == []
    # a post whose caption names no kind anchors nothing
    assert rv.context_issues(COMMENT, TRAYS_TEXT, TRAYS,
                             post_caption="New arrivals this week! WhatsApp us") == []
    # the comment naming the post's own kind keeps the check on
    found3 = rv.context_issues("How much is the stole?", TRAYS_TEXT, TRAYS,
                               post_product="Single Sided Stole")
    assert len(found3) == 1 and found3[0]["hard"]


def test_the_reviewer_prompt_and_the_rewrite_name_the_posts_product():
    src = inspect.getsource(rv.reviewer_verdict)
    assert "8. CONTEXT MIXING" in src and "This post is NOT a campaign or giveaway" in src
    assert "post_product or (post_caption or '')[:200]" in src
    block = rv.rewrite_block(["x"], "draft", [], "USD", [], post_product="Single Sided Stole")
    assert "THE POST'S PRODUCT is Single Sided Stole" in block
    assert "THE POST'S PRODUCT" not in rv.rewrite_block(["x"], "draft", [], "USD", [], post_product="Ring", campaign=True)
    assert "post_caption=post_caption, campaign=campaign" in inspect.getsource(rv.review_reply)


# ── the owner's rules reach the writer ───────────────────────────────────────
def test_the_prompt_and_the_addendum_carry_the_owners_rules():
    p = " ".join(build_system_prompt(currency="USD").split())
    for s in ("ANCHORED TO THE PRODUCT (owner, 2026-10-07",
              "Identify the product before answering",
              "\"how can we get supply?\" refer to that post's product unless they explicitly indicate otherwise",
              "flag the discrepancy for confirmation instead of silently choosing a price",
              "\"a gift for your pastor\" does not mean the product is free or part of a giveaway",
              "never switch because a different item appears in search results",
              "ask ONE focused question",
              "Do the product, variant, price and campaign belong together?",
              "never communion trays, free shoes, winner selection or unrelated promotions",
              "briefly apologise, identify the correct item and answer the original question"):
        assert s in p, s
    add = " ".join(rt._public_comment_addendum("USD").split())
    assert "ANCHORED TO THIS POST (owner, 2026-10-07)" in add
    assert "'a gift for your pastor' is a product sold as a gift — never a giveaway" in add
    assert "apologise in a few words, name the right item and answer the original question" in add


# ── the system passes the post and the hub row, never another post ───────────
def test_a_public_comment_carries_its_own_post_and_a_dm_drops_an_unrelated_campaign():
    src = inspect.getsource(rt.run_turn)
    assert 'if public_comment and comment_post_id:' in src
    _tail = src.split('elif public_comment:', 1)[1].split('source_post = None', 1)[0]
    assert 'elif public_comment:' in src and all(ln.strip().startswith('#') for ln in _tail.strip().splitlines())
    assert 'public_comment or not _mentions_catalogue_item(user_text or ""))' in src
    assert "post_caption=_gate_post_caption, campaign=_campaign_post," in src
    assert "line += _post_row_context(_row, currency)" in src
    assert "await _flag_price_conflict(db, redis, channel, key," in src
    gate = inspect.getsource(rt._gate_turn_reply)
    assert "post_caption=post_caption, campaign=campaign)" in gate
    assert "post_product=post_product,\n                              campaign=campaign)" in gate


def test_the_hub_row_rides_with_the_post_and_a_caption_that_disagrees_is_flagged():
    assert rt._post_row({"slug": "single-sided-stole"}, [DOUBLE, SINGLE]) is SINGLE
    assert rt._post_row({"name": "double SIDED stole"}, [DOUBLE, SINGLE]) is DOUBLE
    assert rt._post_row({"name": "Mitre"}, [DOUBLE, SINGLE]) == {}
    assert rt._post_row_context(SINGLE, "USD") == ". Its hub row: Single Sided Stole — $25"
    assert rt._post_row_context(SINGLE, "KES") == ". Its hub row: Single Sided Stole — KES 2,500"
    assert rt._post_row_context({}, "USD") == ""
    ring = {"name": "Ring", "price": 1500, "price_usd": 20}                    # the stale hub dollar never rides
    assert rt._post_row_context(ring, "USD") == ". Its hub row: Ring — $15"
    # the stole caption's $25 / $40 agree with the hub: nothing to confirm
    assert rt._caption_price_conflict(STOLE_CAPTION, SINGLE, 100) == ""
    # a delivery fee in the caption is no product price; a contact line is no sale
    assert rt._caption_price_conflict("Single Sided Stole. Delivery within Nairobi KES 300. WhatsApp us",
                                      SINGLE, 100) == ""
    assert rt.is_campaign_post("Gifting pastors, reverends, bishops a shoe. WhatsApp us +254785490805 "
                               "to be considered. #BethanyHouse")
    # "completely free" delivery is no giveaway
    assert rv.context_issues("price?", "The Single Sided Stole is $25; pickup at our Nairobi workshop is "
                             "completely free.", [SINGLE], post_product="Single Sided Stole") == []
    assert rt._caption_price_conflict(STOLE_CAPTION, DOUBLE, 100) == ""
    assert rt._caption_price_conflict("New stoles in — which colour is yours?", SINGLE, 100) == ""
    assert rt._caption_price_conflict("Single sided stoles at KES 2,500", SINGLE, 100) == ""
    note = rt._caption_price_conflict("Stoles at $20 only this week!", SINGLE, 100)
    assert "PRICE TO CONFIRM" in note and "USD 20" in note and "Single Sided Stole at KES 2500 / USD 25" in note
    assert "confirm today's price with the team" in note
    assert rt._caption_price_conflict("", SINGLE, 100) == "" and rt._caption_price_conflict(STOLE_CAPTION, {}, 100) == ""
