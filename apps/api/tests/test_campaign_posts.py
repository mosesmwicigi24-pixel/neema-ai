"""CAMPAIGN POSTS (owner, 2026-09-26) — a visibility and mobilisation campaign
gifting ONE free pair of shoes to a Pastor, Reverend or Bishop. Not a voting or
competition campaign: one selected recipient receives the shoe completely
free and pays only the shipping. Never "sorry, something went wrong", never a
generic or irrelevant reply; understand the campaign, answer naturally and
confidently, build genuine conversation, encourage participation, and convert
a wish to buy into a sale without misrepresenting the gift.

Live, the day it was built: Bishop John Tela's entry ("I love the shoe… my size
is no 41") got "we're sorry about the part that went wrong"; Pastor Stephen's
"I'm Pastor Stephen Tanui From Eldoret" got the canned "Bless you… so glad this
speaks to…"."""
import asyncio
import inspect
import re

import app.main  # noqa: F401
import app.agent.runtime as rt
from app.core.config import settings

BISHOP = ("I am bishop John Tela.I love the shoe.That shoe can serve me well with the bishops "
          "cassock that I am planning to buy at Bethany house.My size is no 41.")
PASTOR = "I'm Pastor Stephen Tanui From Eldoret"
CAPTION = ("Clergy shoe giveaway! One pastor, reverend or bishop will win this shoe for free — "
           "the only cost is shipping. Comment with your name and shoe size to enter.")
OWNER_CAPTION = ("We are donating or gifting pastors, reverends and bishops a shoe this month. "
                 "This is for mobilisation and visibility. One selected recipient will receive the shoe "
                 "completely free — the recipient only pays the shipping. Comment your name, your church "
                 "and your size below.")
SHOE = {"name": "Clergy Oxford Shoe", "source": "caption", "confidence": 1.0,
        "price_kes": 4500, "price_usd": 35, "slug": "clergy-oxford-shoe", "product_type": "simple"}
CONTEST_RE = re.compile(r"\b(win|winner|winners|winning|lucky|vote|voting|contest|competition|"
                        r"entry|entries|good\s+luck|all\s+the\s+best|prize)\b", re.IGNORECASE)


def _no_contest_words(text: str) -> bool:
    """True when the text speaks of the campaign without contest language —
    the one clause that LISTS the forbidden words is set aside."""
    t = re.sub(r"Never say win.*?'gifting'\.", " ", text, flags=re.DOTALL)
    t = re.sub(r"no 'win'.*?'gifting'\.", " ", t, flags=re.DOTALL)
    t = re.sub(r"not a competition(?:, a raffle)? or a vote", " ", t)      # the negation itself
    return not CONTEST_RE.search(t)


# ── Cycle 1: detection ───────────────────────────────────────────────────────
def test_a_grievance_the_words_do_not_carry_is_not_a_grievance():
    for model_says in ({"intent": "negative", "kind": "mixed", "severity": 1, "ask": ""},
                       {"intent": "negative", "kind": "complaint", "severity": 2, "ask": ""},
                       {"intent": "high", "kind": "mixed", "severity": 1, "ask": ""}):
        r = rt._settle_reading(BISHOP, dict(model_says))
        assert (r["intent"], r["kind"], r["severity"]) == ("high", "other", 0), model_says
        r = rt._settle_reading(PASTOR, dict(model_says))
        assert (r["intent"], r["kind"]) == ("high", "other"), model_says
    for text in ("Beautiful work but my order never came", "I am not happy with this",
                 "Still waiting since May", "Nilituma pesa zangu, sijapata kitu", "this is wrong"):
        r = rt._settle_reading(text, {"intent": "negative", "kind": "complaint", "severity": 1, "ask": ""})
        assert r["intent"] == "negative", text
    r = rt._settle_reading("Beautiful work but my order never came",
                           {"intent": "negative", "kind": "mixed", "severity": 1, "ask": ""})
    assert r["kind"] == "mixed"


def test_a_campaign_post_is_read_from_its_caption():
    assert rt.is_campaign_post(CAPTION) and rt.is_campaign_post(OWNER_CAPTION)
    for c in ("GIVEAWAY: stand a chance to win a Bible", "Shinda viatu hivi — andika jina lako",
              "Lucky draw this Sunday for one pastor", "Win a stole for your ordination",
              "Gifting pastors, reverends, bishops a shoe.", "One person will get this shoe for free",
              "The only cost is shipping", "You only pay for delivery", "The recipient only pays the shipping",
              "One selected pastor will receive this pair", "We will select one bishop to gift this pair",
              "This pair will be gifted to one reverend", "A visibility and mobilisation campaign for clergy",
              "We are giving away a stole to one lucky pastor",
              "Tuna kampeni: mchungaji mmoja atapata viatu hivi bure",
              "Shindano la wiki hii — andika jina lako", "Comment below to enter — entries close Sunday"):
        assert rt.is_campaign_post(c), c
    for c in ("Silver Communion Tray in stock — 40 cups included free", "New cassocks for the season",
              "Gift set for your pastor: stole and collar", "", None,
              "Free delivery within Nairobi on every cassock this week", "Tag a friend who needs this collar",
              "Easter sales campaign: cassocks at 10% off, order now",
              "Our price campaign — communion cups KES 350 each",
              "Take one home today: the Round Collar Shirt is KES 2,500",
              "A win for your choir: robes from KES 3,500",
              "We offer free shipping on orders above KES 20,000",
              "Delivery completely free this week on all cassocks",
              "Season's campaign: every cassock ordered this week comes with a free collar",
              "Our Christmas campaign is here — cassocks, shirts and stoles at 15% off",
              "We take part in the Nairobi church expo this weekend — visit our stand",
              "Give a pastor the gift of comfort — clergy shoes KES 4,500, order now"):
        assert not rt.is_campaign_post(c), c
    for c in ("Blessing a pastor this month: we are giving one reverend this cassock. Tell us why yours deserves it.",
              "Our clergy shoe campaign: comment your name, church and size",
              "🎁 CLERGY SHOE CAMPAIGN 🎁 We are gifting one pastor, reverend or bishop this shoe. Only shipping is paid by the winner.",
              "As part of our mobilisation drive, one man of God will receive this pair at no cost. The only charge is delivery.",
              "Kwa wachungaji wote: mmoja wenu atapata viatu hivi BURE. Gharama ni ya usafirishaji tu."):
        assert rt.is_campaign_post(c), c


def test_a_gifting_campaign_is_not_a_draw_unless_its_caption_runs_one():
    assert not rt.campaign_is_draw(OWNER_CAPTION)
    assert rt.campaign_is_draw("Raffle this Sunday — stand a chance to win")
    assert rt.campaign_is_draw("Vote for your pastor to receive this pair")
    assert rt.campaign_is_draw(CAPTION)                        # "to enter"
    facts = rt._campaign_facts(OWNER_CAPTION)
    assert "GIFTING CAMPAIGN" in facts and "not a competition, a raffle or a vote" in facts
    assert "completely free" in facts and "paying only the shipping" in facts
    assert "our team makes the selection" in facts and "no date" in facts
    assert _no_contest_words(facts)
    draw = rt._campaign_facts("Raffle this Sunday — stand a chance to win")
    assert "RUNS A CAMPAIGN" in draw and "only the caption's words" in draw


# ── Cycle 2: the host's reading ──────────────────────────────────────────────
def test_the_host_reads_every_entry():
    base = {"intent": "negative", "kind": "mixed", "severity": 1, "ask": "", "campaign": OWNER_CAPTION}
    r = rt._host_reading(base, "Lovely shoe but I wear size 44, do you have it?")
    assert (r["intent"], r["kind"], r["severity"]) == ("high", "other", 0) and r["hint"] == "displeasure"
    assert r["campaign"] == OWNER_CAPTION
    r = rt._host_reading(base, "Beautiful, but I never received my last order")
    assert r["intent"] == "negative" and r["kind"] == "mixed"
    r = rt._host_reading(dict(base, kind="complaint", severity=3), "This page is a scam")
    assert r["intent"] == "negative" and r["severity"] == 3
    # checking before joining in is a question, never a grievance
    for t in ("Is this real or a scam?", "Hope this is not a scam", "Ni kweli hii?", "Is this genuine?", "Is this fake?"):
        r = rt._host_reading(dict(base, kind="complaint", severity=2), t)
        assert (r["intent"], r["kind"]) == ("high", "question"), t
    for t in ("So this is a scam.", "You people are fake", "Scam! I paid and got nothing"):
        r = rt._host_reading(dict(base, kind="complaint", severity=2), t)
        assert r["intent"] == "negative", t
    r = rt._host_reading({"intent": "low", "kind": "other", "severity": 0, "ask": ""}, "Size 42")
    assert r["intent"] == "high"
    r = rt._host_reading({"intent": "low", "kind": "praise", "severity": 0, "ask": ""}, "🙏🙏")
    assert r["intent"] == "low"
    for t in ("Amen", "Interested", "Me", "Rev. Alice Wanjiru"):
        r = rt._host_reading({"intent": "low", "kind": "other", "severity": 0, "ask": ""}, t)
        assert r["intent"] == "high", t
    r = rt._host_reading({"intent": "goodwill", "kind": "question", "severity": 0, "ask": "the size"},
                         "which sizes are there?")
    assert r["intent"] == "high" and r["kind"] == "question"
    r = rt._host_reading({"intent": "spam", "kind": "other", "severity": 0, "ask": ""}, "buy followers here")
    assert r["intent"] == "spam"
    for said in ({"intent": "negative", "kind": "mixed", "severity": 1, "ask": ""},
                 {"intent": "low", "kind": "praise", "severity": 0, "ask": ""},
                 {"intent": "goodwill", "kind": "other", "severity": 0, "ask": ""}):
        for t in (BISHOP, PASTOR):
            r = rt._host_reading(dict(said), t)
            assert r["intent"] == "high" and rt.plan_comment_actions(r["intent"])["style"] == "answer", (said, t)


def test_buying_intent_under_a_campaign():
    for t in (BISHOP, "How much is the cassock? Nataka kununua", "I want two pairs, size 44",
              "Can I buy one?", "Is it available in size 45?", "Do you have my size 40 in stock?",
              "How much?", "Bei ni ngapi?", "Inapatikana?"):
        assert rt._CAMPAIGN_BUY_RE.search(t), t
    for t in (PASTOR, "Size 42, Rev. Alice from Nakuru", "Amen", "I love this shoe", "Bless you for this"):
        assert not rt._CAMPAIGN_BUY_RE.search(t), t


# ── Cycle 3: the host's brief ────────────────────────────────────────────────
def test_the_host_context_carries_the_facts_the_rule_and_the_sale():
    ctx = rt._reading_context({"intent": "high", "kind": "other", "severity": 0, "ask": "", "campaign": OWNER_CAPTION})
    assert ctx.startswith("(THIS POST IS A CAMPAIGN")
    assert "the recipient only pays the shipping" in ctx                 # the caption, verbatim
    assert "HOST" in ctx and "not a shopkeeper at a stall" in ctx
    assert "GIFTING CAMPAIGN" in ctx and "not a competition, a raffle or a vote" in ctx
    assert "capture_contact" in ctx and "save_measurements" in ctx and "save_parish" in ctx
    assert "say the rule in ONE line exactly as the caption gives it" in ctx
    assert "invite them to, warmly" in ctx
    assert "never a date, a count, a criterion or a mechanism the caption does not state" in ctx.lower()
    assert 'never "something went wrong"' in ctx and 'never "hold on"' in ctx
    assert "A SALE, WITHOUT MISREPRESENTING THE GIFT" in ctx and "the gift is separate" in ctx
    assert "search_catalog it, give the hub's price" in ctx and "Never push a purchase on someone simply joining in" in ctx
    assert _no_contest_words(ctx)
    # the ordinary reading still follows the campaign block; the hint rides along
    ctx2 = rt._reading_context({"kind": "question", "ask": "the size", "campaign": OWNER_CAPTION})
    assert "CAMPAIGN" in ctx2 and "this comment is a QUESTION — the size" in ctx2
    ctx3 = rt._reading_context({"kind": "other", "campaign": OWNER_CAPTION, "hint": "displeasure"})
    assert "sensed some displeasure" in ctx3
    assert rt._reading_context({"kind": "other"}) == ""
    # however long the caption, the rule stays in view
    cap = "x " * 200 + OWNER_CAPTION
    assert "the recipient only pays the shipping" in rt._reading_context({"kind": "other", "campaign": cap})


def test_the_addendum_and_the_turn_context_carry_the_framing():
    add = " ".join(rt._public_comment_addendum("USD").split())
    assert "CAMPAIGN / GIFTING POSTS (owner, 2026-09-26)" in add
    assert "HOSTED, not sold" in add and "not a competition or a vote" in add
    assert "with the gift stated as separate" in add and "'something went wrong' at someone joining in" in add
    line = rt._campaign_turn_context(OWNER_CAPTION, "My size is 41", SHOE)
    assert line.startswith('(Context — this customer reached us from our Facebook/Instagram post "We are donating')
    assert 'their comment there was: "My size is 41"' in line
    assert "GIFTING CAMPAIGN" in line and "our Clergy Oxford Shoe" in line
    assert "only when they want one of their own; never as the gift" in line
    assert "saying plainly the gift is separate" in line and 'never "something went wrong"' in line
    assert _no_contest_words(line)
    assert "Clergy Oxford Shoe" not in rt._campaign_turn_context(OWNER_CAPTION, "", {})


# ── Cycle 6: the canned lines ────────────────────────────────────────────────
def test_the_canned_lines_never_speak_of_a_contest_or_an_error():
    for pool in (rt._CAMPAIGN_ACK_POOL, rt._SW_CAMPAIGN_ACK_POOL, rt._CAMPAIGN_SELL_POOL, rt._SW_CAMPAIGN_SELL_POOL):
        for line in pool:
            assert not CONTEST_RE.search(line), line
            assert "went wrong" not in line and "hold on" not in line.lower() and "sorry" not in line.lower(), line
            assert "{name}" in line
    for line in rt._CAMPAIGN_SELL_POOL + rt._SW_CAMPAIGN_SELL_POOL:
        assert "{product}" in line and "{price}" in line and "gift" in line.lower() or "zawadi" in line
    # the no-answer line: a buying ask on a trusted identity is served, the gift stated as separate
    t = rt._comment_public_reply("", False, " Bishop", "seed", product_known=True,
                                 product_name="Clergy Oxford Shoe", price_text="KES 4,500", campaign=True)
    assert "KES 4,500" in t and "Clergy Oxford Shoe" in t and "gift" in t
    assert t in [x.replace("{name}", " Bishop").replace("{product}", "the Clergy Oxford Shoe").replace("{price}", "KES 4,500")
                 for x in rt._CAMPAIGN_SELL_POOL]
    # an entry over the cap: the host's thanks
    t = rt._comment_public_reply("", False, " Bishop", "seed", campaign=True)
    assert t in [x.replace("{name}", " Bishop") for x in rt._CAMPAIGN_ACK_POOL]
    t = rt._comment_public_reply("", False, " Bishop", "seed", campaign=True, swahili=True)
    assert t in [x.replace("{name}", " Bishop") for x in rt._SW_CAMPAIGN_ACK_POOL]
    t = rt._comment_public_reply("", False, " Bishop", "seed", kind="question", campaign=True)
    assert t == rt._pick(rt._QUESTION_ACK_POOL, "seed").replace("{name}", " Bishop")
    assert rt._comment_public_reply("Welcome, Bishop John!", False, " Bishop", "seed", campaign=True) == "Welcome, Bishop John!"


# ── Cycle 7: the engine, end to end, with fakes ──────────────────────────────
class _DB:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


def _engage(monkeypatch, text, *, reading, caption=OWNER_CAPTION, identity=None, answer="",
            fail_turn=False, over_cap=False, held=None, name="John Tela", turn_rows=None,
            thumb="http://x/shoe.jpg"):
    """Run _run_comment_engage with every collaborator faked. Returns what left
    the building: the public text, the DM, the human hand-off, the like, what
    run_turn was handed, and what was recorded as the post's identity."""
    import app.database as dbmod
    from app.services import meta_send, n8n_bridge, post_catalog
    out = {"public": [], "dm": [], "human": [], "liked": [], "noted": [], "turn": None,
           "remembered": [], "saved": []}
    ident = dict(identity) if identity else {}

    async def read_comment(t, redis=None):
        return dict(reading)

    async def run_turn(db, redis, **kw):
        out["turn"] = kw
        if fail_turn:
            raise RuntimeError("model down")
        if turn_rows:
            kw["product_sink"].extend(turn_rows)
        if held:
            kw["turn_facts"]["held"] = list(held)
        return answer

    async def reply_to_comment(cid, t, page_id=None, channel=None):
        out["public"].append(t)

    async def send_private_reply(cid, t, page_id=None, channel=None):
        out["dm"].append(t)

    async def like_comment(cid, page_id=None, channel=None):
        out["liked"].append(cid)
        return True

    async def save_outbound(db, redis, channel, ext, t, reply_to_comment_id=None):
        out["saved"].append(t)

    async def route_human(channel, ext, t, **kw):
        out["human"].append(dict(kw, text=t))

    async def note_silent(channel, ext, cid, intent):
        out["noted"].append(intent)

    async def recall(redis, channel, post_id):
        return dict(ident)

    async def resolve(redis, channel, ext, post_ctx, sink):
        if ident:
            sink.append(dict(ident))

    async def remember(redis, channel, post_id, product, thumb=None):
        out["remembered"].append(product.get("name"))

    async def link(redis, channel, ext, product):
        return f"https://bethanyhouse.co.ke/product/{product.get('slug') or 'x'}?ref=abc" if product.get("name") else ""

    async def over(redis, post_id):
        return over_cap

    async def person_over(redis, post_id, ext):
        return False

    async def first_contact(channel, ext):
        return False

    async def market(db, channel, key):
        return ("KES", {}, "", None)

    async def thread_parent(pid):
        return {}

    async def private_complaint(cid, page_id, channel, name_tag, swahili):
        return False

    monkeypatch.setattr(settings, "meta_comment_like", False, raising=False)
    monkeypatch.setattr(dbmod, "AsyncSessionLocal", lambda: _DB())
    monkeypatch.setattr(meta_send, "reply_to_comment", reply_to_comment)
    monkeypatch.setattr(meta_send, "send_private_reply", send_private_reply)
    monkeypatch.setattr(meta_send, "like_comment", like_comment)
    monkeypatch.setattr(n8n_bridge, "save_outbound_channel_message", save_outbound)
    monkeypatch.setattr(post_catalog, "identity_trusted",
                        lambda rec: bool((rec or {}).get("name")) and (rec or {}).get("source") == "caption")
    for n, f in (("read_comment", read_comment), ("run_turn", run_turn), ("_route_comment_to_human", route_human),
                 ("_note_silent_decision", note_silent), ("_recall_post_product", recall),
                 ("_resolve_post_product", resolve), ("_remember_post_product", remember),
                 ("_storefront_product_link", link), ("_post_over_cap", over), ("_person_over_cap", person_over),
                 ("_first_contact", first_contact), ("_meta_market", market), ("_thread_parent", thread_parent),
                 ("_private_complaint_message", private_complaint)):
        monkeypatch.setattr(rt, n, f)
    monkeypatch.setattr(rt, "build_llm", lambda model=None, **kw: object())
    comment = {"comment_id": "c1", "from_id": "u1", "from_name": name, "text": text, "post_id": "p1",
               "page_id": "PAGE", "post_context": {"post_id": "p1", "title": caption[:200], "caption": caption,
                                                   "thumb": thumb}}
    asyncio.run(rt._run_comment_engage(None, "facebook", comment, {"PAGE"}))
    return out


MIXED = {"intent": "negative", "kind": "mixed", "severity": 1, "ask": ""}
LOW = {"intent": "low", "kind": "praise", "severity": 0, "ask": ""}
QUESTION = {"intent": "high", "kind": "question", "severity": 0, "ask": "the price"}


def test_the_bishops_entry_is_hosted_and_his_cassock_wish_opens_the_inbox(monkeypatch):
    ans = ("Welcome, Bishop John! Size 41 noted. This pair is our gift to one selected minister, "
           "who pays only the shipping. And the bishop's cassock you're planning — message us "
           "whenever you're ready and we'll fit it for you.")
    out = _engage(monkeypatch, BISHOP, reading=MIXED, identity=SHOE, answer=ans)
    assert out["public"] == [ans] and out["human"] == []
    assert "went wrong" not in out["public"][0]
    # the model was briefed as the host; the frame was not read for a product
    r = out["turn"]["comment_reading"]
    assert r["intent"] == "high" and r["campaign"] == OWNER_CAPTION and r["hint"] == "displeasure"
    assert out["turn"]["media"] is None
    # he spoke of buying → the inbox opens with the answer; the SHOE's link does not ride
    # (his wish is a cassock, and the answer never names the shoe by its hub name)
    assert out["dm"] == [ans]
    assert out["remembered"] == []


def test_the_pastors_intro_is_welcomed_by_the_host_and_opens_no_inbox(monkeypatch):
    ans = "Welcome, Pastor Stephen from Eldoret! Lovely to have you here — share your church and shoe size as the post asks, and you're in."
    out = _engage(monkeypatch, PASTOR, reading=LOW, identity=SHOE, answer=ans, name="Stephen Tanui")
    assert out["public"] == [ans] and out["dm"] == [] and out["human"] == []
    assert out["turn"]["comment_reading"]["intent"] == "high"


def test_a_size_alone_is_an_entry(monkeypatch):
    out = _engage(monkeypatch, "Size 42", reading=LOW, identity=SHOE, answer="Size 42 noted — and your name and church?")
    assert out["public"] == ["Size 42 noted — and your name and church?"] and out["dm"] == []


def test_how_much_is_answered_by_the_host_and_the_shoe_link_rides_the_inbox(monkeypatch):
    ans = ("This pair is our gift to one selected minister, who pays only the shipping. If you'd like "
           "a pair of your own now, the Clergy Oxford Shoe is KES 4,500 — message us with your size.")
    out = _engage(monkeypatch, "How much?", reading=QUESTION, identity=SHOE, answer=ans)
    assert out["public"] == [ans]
    assert len(out["dm"]) == 1 and out["dm"][0].startswith(ans) and "clergy-oxford-shoe" in out["dm"][0]
    assert out["remembered"] == []                       # a host's reply never becomes the post's identity
    # "two pairs" — the answer sells the pair by its hub name, so the link rides
    ans2 = "Two pairs in 44 — gladly. The Clergy Oxford Shoe is KES 4,500 a pair; message us and we'll take the order."
    out = _engage(monkeypatch, "I want two pairs, size 44", reading=dict(QUESTION, ask="two pairs"), identity=SHOE, answer=ans2)
    assert len(out["dm"]) == 1 and "clergy-oxford-shoe" in out["dm"][0]
    # the same words with an answer that names no product: the inbox opens, no link
    out = _engage(monkeypatch, "I want two pairs, size 44", reading=dict(QUESTION, ask="two pairs"), identity=SHOE,
                  answer="Gladly — message us with your size and we'll sort two pairs for you.")
    assert out["dm"] == ["Gladly — message us with your size and we'll sort two pairs for you."]


def test_over_the_cap_a_buying_ask_is_served_with_the_gift_stated_as_separate(monkeypatch):
    out = _engage(monkeypatch, "How much is the shoe?", reading=QUESTION, identity=SHOE, over_cap=True)
    assert out["turn"] is None and len(out["public"]) == 1
    t = out["public"][0]
    assert "KES 4,500" in t and "Clergy Oxford Shoe" in t and "gift" in t and not CONTEST_RE.search(t)
    assert out["human"] == [] and out["dm"] == []
    out = _engage(monkeypatch, "I want two pairs, size 44", reading=dict(QUESTION, ask="two pairs"),
                  identity=SHOE, over_cap=True)
    assert "KES 4,500" in out["public"][0]


def test_over_the_cap_an_entry_hears_the_host_and_a_question_promises_a_person(monkeypatch):
    out = _engage(monkeypatch, "I'm Rev Alice Wanjiru from Nakuru, size 39", reading=LOW, identity=SHOE,
                  over_cap=True, name="Alice Wanjiru")
    t = out["public"][0]
    assert t in [x.replace("{name}", " Alice") for x in rt._CAMPAIGN_ACK_POOL]
    assert out["human"] == [] and out["dm"] == []
    out = _engage(monkeypatch, "When will the selection be made?", identity=SHOE, over_cap=True,
                  reading={"intent": "high", "kind": "question", "severity": 0, "ask": "when the selection is made"})
    assert out["public"][0] == rt._pick(rt._QUESTION_ACK_POOL, "u1").replace("{name}", " John")
    assert len(out["human"]) == 1 and out["human"][0]["kind"] == "question"


def test_a_held_draft_at_an_entry_hears_the_host_and_a_colleague_gets_the_reasons(monkeypatch):
    out = _engage(monkeypatch, PASTOR, reading=LOW, identity=SHOE, answer="A draft with an invented date",
                  held=["a date the caption does not give"], name="Stephen Tanui")
    assert out["public"][0] in [x.replace("{name}", " Stephen") for x in rt._CAMPAIGN_ACK_POOL]
    assert len(out["human"]) == 1 and out["human"][0]["issues"] == ["a date the caption does not give"]
    assert out["dm"] == []


def test_a_failed_turn_at_an_entry_never_says_something_went_wrong(monkeypatch):
    out = _engage(monkeypatch, PASTOR, reading=LOW, identity=SHOE, fail_turn=True, name="Stephen Tanui")
    t = out["public"][0]
    assert t in [x.replace("{name}", " Stephen") for x in rt._CAMPAIGN_ACK_POOL]
    assert "went wrong" not in t and "sorry" not in t.lower()
    assert out["human"] == [] and out["dm"] == []


def test_a_real_grievance_under_the_campaign_is_still_a_grievance(monkeypatch):
    out = _engage(monkeypatch, "I entered last time and never received anything from you people",
                  reading={"intent": "negative", "kind": "complaint", "severity": 2, "ask": ""}, identity=SHOE)
    assert out["turn"] is None and "sorry" in out["public"][0].lower()
    assert len(out["human"]) == 1 and out["human"][0]["severity"] == 2 and out["dm"] == []


def test_is_this_real_is_a_question_for_the_host(monkeypatch):
    ans = "It's real, John — Bethany House is gifting this pair to one selected minister, who pays only the shipping."
    out = _engage(monkeypatch, "Is this real or a scam?",
                  reading={"intent": "negative", "kind": "complaint", "severity": 2, "ask": ""}, identity=SHOE, answer=ans)
    assert out["public"] == [ans] and out["human"] == [] and out["dm"] == []
    assert out["turn"]["comment_reading"]["kind"] == "question"


def test_a_bare_emoji_hears_the_hosts_thanks_and_spam_hears_nothing(monkeypatch):
    out = _engage(monkeypatch, "🙏🙏", reading={"intent": "low", "kind": "praise", "severity": 0, "ask": ""}, identity=SHOE)
    assert out["turn"] is None and out["public"][0] in [x.replace("{name}", " John") for x in rt._CAMPAIGN_ACK_POOL]
    out = _engage(monkeypatch, "Buy followers at cheap.example", reading={"intent": "spam", "kind": "other", "severity": 0, "ask": ""},
                  identity=SHOE)
    assert out["public"] == [] and out["noted"] == ["spam"]


def test_a_swahili_entry_over_the_cap_hears_the_host_in_swahili(monkeypatch):
    out = _engage(monkeypatch, "Mimi ni Mchungaji Otieno kutoka Kisumu, size yangu ni 43", reading=LOW, identity=SHOE,
                  over_cap=True, name="Otieno")
    assert out["public"][0] in [x.replace("{name}", " Otieno") for x in rt._SW_CAMPAIGN_ACK_POOL]


def test_without_a_trusted_identity_no_canned_line_ever_prices(monkeypatch):
    lead = dict(SHOE, source="model", confidence=0.4)
    out = _engage(monkeypatch, "How much is the shoe?", reading=QUESTION, identity=lead, over_cap=True)
    t = out["public"][0]
    assert "4,500" not in t and "Which" not in t and t == rt._pick(rt._QUESTION_ACK_POOL, "u1").replace("{name}", " John")


def test_a_shop_post_still_sells_as_before(monkeypatch):
    """The campaign handling never touches a shop post: over the cap, a bare
    price ask on a trusted identity gets the priced line, and the DM the link."""
    out = _engage(monkeypatch, "How much?", reading=QUESTION, identity=SHOE, over_cap=True,
                  caption="Clergy Oxford Shoe — in stock now, KES 4,500")
    t = out["public"][0]
    assert "KES 4,500" in t and "gift" not in t.lower()


# ── Cycle 8: the wiring, pinned ──────────────────────────────────────────────
def test_the_engine_hands_entries_to_the_host():
    src = inspect.getsource(rt._run_comment_engage)
    assert "campaign = bool(_caption) and is_campaign_post(_caption)" in src
    assert "reading = _host_reading(dict(reading, campaign=_caption), comment_text)" in src
    assert "dm=bool(_CAMPAIGN_BUY_RE.search(comment_text))" in src
    assert "free_ask = _trusted and is_bare_price_ask(prompt_text) and not campaign" in src
    assert "if campaign:\n        media = None" in src
    assert "if is_live or campaign:" in src
    assert "if campaign and _CAMPAIGN_BUY_RE.search(prompt_text):\n            asks_it = True" in src
    assert "if not (_trusted and asks_it and product_name and not held_issues):" in src
    assert "if campaign and not plan[\"dm\"]:\n        product_link = \"\"" in src
    assert "campaign=campaign," in src
    assert 'if not campaign or held_issues or kind in ("request", "question"):' in src
    assert "pool = _SW_CAMPAIGN_ACK_POOL if swahili else _CAMPAIGN_ACK_POOL" in src
    src2 = inspect.getsource(rt.run_turn)
    assert "_campaign_post = bool(_campaign_cap) and is_campaign_post(_campaign_cap)" in src2
    assert "line = _campaign_turn_context(_campaign_cap, source_post.get(\"comment\") or \"\", _known)" in src2
    assert "and not identity_trusted_record(_known) and not _campaign_post" in src2
    assert "if is_campaign_post" not in inspect.getsource(rt._resolve_post_product)


def _fake_client(payload):
    class _R:
        is_success = True
        status_code = 200

        def json(self):
            return payload

    class _C:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, **kw):
            return _R()
    return lambda *a, **k: _C()


def test_the_whole_caption_rides_with_the_post(monkeypatch):
    """The title the inbox card shows is 200 chars; the rule of a campaign can
    sit past it — the caption now rides whole, and the engine reads THAT."""
    import httpx
    from app.services import meta_send
    long = "Clergy shoes for the season. " * 10 + "One pastor will get this shoe for free — the only cost is shipping."
    monkeypatch.setattr(settings, "meta_page_token", "T", raising=False)
    monkeypatch.setattr(httpx, "AsyncClient", _fake_client(
        {"message": long, "permalink_url": "https://fb/p/1", "full_picture": "http://x/p.jpg",
         "attachments": {"data": [{"media_type": "photo"}]}}))
    ctx = asyncio.run(meta_send.fetch_post_context("POST9"))
    assert len(ctx["title"]) == 200 and ctx["caption"].endswith("the only cost is shipping.")
    assert not rt.is_campaign_post(ctx["title"]) and rt.is_campaign_post(rt.post_caption(ctx))
    monkeypatch.setattr(httpx, "AsyncClient", _fake_client(
        {"caption": long, "permalink": "https://ig/p/1", "media_type": "IMAGE", "media_url": "http://x/i.jpg"}))
    ig = asyncio.run(meta_send.fetch_post_context("IG9", channel="instagram"))
    assert ig["caption"] == long[:1500] and len(ig["title"]) == 200
    monkeypatch.setattr(httpx, "AsyncClient", _fake_client({"description": long, "picture": "http://x/f.jpg"}))
    reel = asyncio.run(meta_send._video_post_context("REEL9"))
    assert reel["caption"] == long[:1500]
    from app.routers import meta_webhook as mw
    assert "meta:postctx:v2:" in inspect.getsource(mw._post_context)
    assert rt.post_caption({"title": "Old record"}) == "Old record" and rt.post_caption(None) == ""
