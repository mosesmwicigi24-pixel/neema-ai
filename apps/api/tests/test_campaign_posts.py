"""CAMPAIGN POSTS (owner, 2026-09-26) — a visibility and mobilisation campaign
gifting ONE free pair of shoes to a Pastor, Reverend or Bishop. Not a voting or
competition campaign: one selected recipient receives the shoe completely
free and pays only the shipping. Never "sorry, something went wrong", never a
generic or irrelevant reply. And then: "stop saying we do not make shoes,
hatuuzi viatu. Go to the gift only. Do not digress. That shoe is a gift."

The owner's own reply is the shape: "Hello Pastor, welcome to Bethany House!
🙏 We're delighted to have you here. Our team will be selecting one recipient
for this gift — completely free, you'd only cover the shipping. Follow us and
watch for the details on who's been selected. May we have your name, church
and town so we can reach you if you're the one chosen?"

Live, the day it was built: Bishop John Tela's entry ("I love the shoe… my size
is no 41") got "we're sorry about the part that went wrong"; Pastor Stephen's
"I'm Pastor Stephen Tanui From Eldoret" got the canned "Bless you… so glad this
speaks to…"; and the church-goods guard, reading "shoes" as goods we do not
sell, had Neema say "hatuuzi viatu"."""
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
CASSOCK = {"name": "Purple Cassock", "slug": "purple-cassock", "price_kes": 12000, "product_type": "variable"}
OWNER_REPLY = ("Hello Pastor, welcome to Bethany House! 🙏 We're delighted to have you here. Our team will be "
               "selecting one recipient for this gift — completely free, you'd only cover the shipping. Follow "
               "us and watch for the details on who's been selected. May we have your name, church and town so "
               "we can reach you if you're the one chosen?")
CONTEST_RE = re.compile(r"\b(win|winner|winners|winning|lucky|vote|voting|contest|competition|"
                        r"entry|entries|good\s+luck|all\s+the\s+best|prize)\b", re.IGNORECASE)
DISCLAIM_RE = re.compile(r"hatuuzi|don'?t sell|do not sell|don'?t make|do not make|not ours|hub's price|search_catalog",
                         re.IGNORECASE)


def _no_contest_words(text: str) -> bool:
    """True when the text speaks of the campaign without contest language —
    the clauses that LIST the forbidden words, and the negation itself, are
    set aside."""
    t = re.sub(r"Never say win.*?'gift(?:ing)?'\.", " ", text, flags=re.DOTALL)
    t = re.sub(r"no 'win'.*?'gift(?:ing)?'\.", " ", t, flags=re.DOTALL)
    t = re.sub(r"not a competition(?:, a raffle)? or a vote", " ", t)
    return not CONTEST_RE.search(t)


def _gift_only(text: str) -> bool:
    """The brief never tells the host to disclaim, price or sell the gift —
    the one clause that forbids those words is set aside."""
    t = re.sub(r"never say we do not sell.*?not ours", " ", text, flags=re.DOTALL | re.IGNORECASE)
    t = re.sub(r"never 'we do not sell shoes', never 'hatuuzi viatu'", " ", t)
    t = re.sub(r"never disclaimed \(never 'we do not sell', never 'hatuuzi'\)", " ", t)
    return not DISCLAIM_RE.search(t)


# ── detection ────────────────────────────────────────────────────────────────
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
    assert "completely free" in facts and "only cover the shipping" in facts
    assert "A GIFT AND ONLY A GIFT" in facts and "'hatuuzi viatu'" in facts and "do not digress" in facts
    assert "follow us and watch for the details on who's been selected" in facts
    assert _no_contest_words(facts) and _gift_only(facts)
    draw = rt._campaign_facts("Raffle this Sunday — stand a chance to win")
    assert "RUNS A CAMPAIGN" in draw and "only the caption's words" in draw and "never disclaimed" in draw


# ── the host's reading ───────────────────────────────────────────────────────
def test_the_host_reads_every_entry():
    base = {"intent": "negative", "kind": "mixed", "severity": 1, "ask": "", "campaign": OWNER_CAPTION}
    r = rt._host_reading(base, "Lovely shoe but I wear size 44, do you have it?")
    assert (r["intent"], r["kind"], r["severity"]) == ("high", "other", 0) and r["hint"] == "displeasure"
    assert r["campaign"] == OWNER_CAPTION
    r = rt._host_reading(base, "Beautiful, but I never received my last order")
    assert r["intent"] == "negative" and r["kind"] == "mixed"
    r = rt._host_reading(dict(base, kind="complaint", severity=3), "This page is a scam")
    assert r["intent"] == "negative" and r["severity"] == 3
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


def test_buying_words_under_a_campaign():
    for t in (BISHOP, "How much is the cassock? Nataka kununua", "I want two pairs, size 44",
              "Can I buy one?", "Is it available in size 45?", "Do you have my size 40 in stock?",
              "How much?", "Bei ni ngapi?", "Inapatikana?"):
        assert rt._CAMPAIGN_BUY_RE.search(t), t
    for t in (PASTOR, "Size 42, Rev. Alice from Nakuru", "Amen", "I love this shoe", "Bless you for this"):
        assert not rt._CAMPAIGN_BUY_RE.search(t), t


# ── the host's brief ─────────────────────────────────────────────────────────
def test_the_host_context_carries_the_owners_reply_and_the_gift():
    ctx = rt._reading_context({"intent": "high", "kind": "other", "severity": 0, "ask": "", "campaign": OWNER_CAPTION})
    assert ctx.startswith("(THIS POST IS A CAMPAIGN")
    assert "the recipient only pays the shipping" in ctx                 # the caption, verbatim
    assert "HOST" in ctx and "not a shopkeeper at a stall" in ctx
    assert "A GIFT AND ONLY A GIFT" in ctx and "'hatuuzi viatu'" in ctx and "do not digress" in ctx
    # the owner's own reply is the shape
    assert "Hello Pastor, welcome to Bethany House!" in ctx
    assert "Follow us and watch for the details on who's been selected" in ctx
    assert "May we have your name, church and town so we can reach you if you're the one chosen?" in ctx
    assert "capture_contact" in ctx and "save_measurements" in ctx and "save_parish" in ctx
    assert "it is a gift — say so warmly" in ctx and "never a pivot from the gift" in ctx
    assert 'never "something went wrong"' in ctx and 'never "hold on"' in ctx
    assert _no_contest_words(ctx) and _gift_only(ctx)
    ctx2 = rt._reading_context({"kind": "question", "ask": "the size", "campaign": OWNER_CAPTION})
    assert "CAMPAIGN" in ctx2 and "this comment is a QUESTION — the size" in ctx2
    ctx3 = rt._reading_context({"kind": "other", "campaign": OWNER_CAPTION, "hint": "displeasure"})
    assert "sensed some displeasure" in ctx3
    assert rt._reading_context({"kind": "other"}) == ""
    cap = "x " * 200 + OWNER_CAPTION
    assert "the recipient only pays the shipping" in rt._reading_context({"kind": "other", "campaign": cap})


def test_the_addendum_and_the_turn_context_carry_the_framing():
    add = " ".join(rt._public_comment_addendum("USD").split())
    assert "CAMPAIGN / GIFTING POSTS (owner, 2026-09-26)" in add
    assert "HOSTED, not sold" in add and "not a competition or a vote" in add
    assert "never 'hatuuzi viatu'" in add and "speak of the gift only and do not digress" in add
    assert "invite them to follow us" in add and "'something went wrong' at someone joining in" in add
    line = rt._campaign_turn_context(OWNER_CAPTION, "My size is 41")
    assert line.startswith('(Context — this customer reached us from our Facebook/Instagram post "We are donating')
    assert 'their comment there was: "My size is 41"' in line
    assert "GIFTING CAMPAIGN" in line and "A GIFT AND ONLY A GIFT" in line
    assert "it is a gift — say so warmly" in line and "never a pivot from the gift" in line
    assert 'never "something went wrong"' in line and "never a generic hold" in line
    assert _no_contest_words(line) and _gift_only(line)


# ── the canned lines ─────────────────────────────────────────────────────────
def test_the_canned_lines_never_speak_of_a_contest_a_price_or_an_error():
    for pool in (rt._CAMPAIGN_ACK_POOL, rt._SW_CAMPAIGN_ACK_POOL, rt._CAMPAIGN_GIFT_POOL, rt._SW_CAMPAIGN_GIFT_POOL):
        for line in pool:
            assert not CONTEST_RE.search(line), line
            assert "went wrong" not in line and "hold on" not in line.lower() and "sorry" not in line.lower(), line
            assert "{name}" in line and not re.search(r"\d", line) and "sell" not in line.lower(), line
    for line in rt._CAMPAIGN_GIFT_POOL + rt._SW_CAMPAIGN_GIFT_POOL:
        assert "gift" in line.lower() or "zawadi" in line
    # the thread's line by what they wrote: a price or buying ask hears the gift, never a price
    t = rt._campaign_canned("How much is the shoe?", "question", "the price", " Bishop", "seed")
    assert t in [x.replace("{name}", " Bishop") for x in rt._CAMPAIGN_GIFT_POOL]
    t = rt._campaign_canned("Nataka kununua viatu hivi", "question", "", " Bishop", "seed", swahili=True)
    assert t in [x.replace("{name}", " Bishop") for x in rt._SW_CAMPAIGN_GIFT_POOL]
    t = rt._campaign_canned("When will the selection be made?", "question", "", " Bishop", "seed")
    assert t == rt._pick(rt._QUESTION_ACK_POOL, "seed").replace("{name}", " Bishop")
    t = rt._campaign_canned("Please post more photos", "request", "more photos", " Bishop", "seed")
    assert "more photos" in t
    t = rt._campaign_canned(PASTOR, "other", "", " Stephen", "seed")
    assert t in [x.replace("{name}", " Stephen") for x in rt._CAMPAIGN_ACK_POOL]
    # the base line never prices the post's item under a campaign, whatever it knows
    t = rt._comment_public_reply("", False, " Bishop", "seed", product_known=True,
                                 product_name="Clergy Oxford Shoe", price_text="KES 4,500", campaign=True)
    assert "4,500" not in t and "Oxford" not in t and t in [x.replace("{name}", " Bishop") for x in rt._CAMPAIGN_ACK_POOL]
    assert rt._comment_public_reply("Welcome, Bishop John!", False, " Bishop", "seed", campaign=True) == "Welcome, Bishop John!"


# ── the engine, end to end, with fakes ───────────────────────────────────────
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


def test_the_bishops_entry_is_hosted_and_the_gift_never_travels_as_order_here(monkeypatch):
    ans = ("Hello Bishop John, welcome to Bethany House! 🙏 Size 41 noted. Our team will be selecting "
           "one recipient for this gift — completely free, you'd only cover the shipping. Follow us and "
           "watch for the details on who's been selected. May we have your church and town so we can "
           "reach you if you're the one chosen?")
    out = _engage(monkeypatch, BISHOP, reading=MIXED, identity=SHOE, answer=ans)
    assert out["public"] == [ans] and out["human"] == []
    assert "went wrong" not in out["public"][0]
    r = out["turn"]["comment_reading"]
    assert r["intent"] == "high" and r["campaign"] == OWNER_CAPTION and r["hint"] == "displeasure"
    assert out["turn"]["media"] is None
    assert out["dm"] == [] and out["remembered"] == []
    # ANOTHER item he brought up, served by its hub name, opens the inbox with ITS link — never the shoe's
    ans2 = ans + " And the cassock you're planning — the Purple Cassock is KES 12,000; message us and we'll fit it."
    out = _engage(monkeypatch, BISHOP, reading=MIXED, identity=SHOE, answer=ans2, turn_rows=[CASSOCK])
    assert len(out["dm"]) == 1 and "purple-cassock" in out["dm"][0] and "clergy-oxford-shoe" not in out["dm"][0]
    assert out["remembered"] == []


def test_the_pastors_intro_is_welcomed_by_the_host_and_opens_no_inbox(monkeypatch):
    ans = OWNER_REPLY
    out = _engage(monkeypatch, PASTOR, reading=LOW, identity=SHOE, answer=ans, name="Stephen Tanui")
    assert out["public"] == [ans] and out["dm"] == [] and out["human"] == []
    assert out["turn"]["comment_reading"]["intent"] == "high"
    # "share your shoe size" in an answer never reads as naming the Clergy Oxford Shoe
    ans = "Welcome, Pastor Stephen! Share your church and shoe size as the post asks, and you're in."
    out = _engage(monkeypatch, PASTOR, reading=LOW, identity=SHOE, answer=ans, name="Stephen Tanui")
    assert out["dm"] == []


def test_a_size_alone_is_an_entry(monkeypatch):
    out = _engage(monkeypatch, "Size 42", reading=LOW, identity=SHOE, answer="Size 42 noted — and your name and church?")
    assert out["public"] == ["Size 42 noted — and your name and church?"] and out["dm"] == []


def test_how_much_is_answered_as_the_gift(monkeypatch):
    ans = ("It's a gift, John 🙏 Our team will be selecting one recipient — completely free, only the "
           "shipping to cover. Share your name, church and size as the post asks, so we can reach you.")
    out = _engage(monkeypatch, "How much?", reading=QUESTION, identity=SHOE, answer=ans)
    assert out["public"] == [ans]
    assert out["dm"] == [] and out["remembered"] == []   # never "Order here" for the gift


def test_over_the_cap_a_buying_ask_hears_the_gift_never_a_price(monkeypatch):
    out = _engage(monkeypatch, "How much is the shoe?", reading=QUESTION, identity=SHOE, over_cap=True)
    assert out["turn"] is None and len(out["public"]) == 1
    t = out["public"][0]
    assert t in [x.replace("{name}", " John") for x in rt._CAMPAIGN_GIFT_POOL]
    assert "4,500" not in t and "Oxford" not in t and not CONTEST_RE.search(t)
    assert out["human"] == [] and out["dm"] == []
    out = _engage(monkeypatch, "I want two pairs, size 44", reading=dict(QUESTION, ask="two pairs"),
                  identity=SHOE, over_cap=True)
    assert out["public"][0] in [x.replace("{name}", " John") for x in rt._CAMPAIGN_GIFT_POOL]
    assert out["human"] == []


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


def test_a_held_draft_hears_the_host_and_a_colleague_gets_the_reasons(monkeypatch):
    out = _engage(monkeypatch, PASTOR, reading=LOW, identity=SHOE, answer="A draft with an invented date",
                  held=["a date the caption does not give"], name="Stephen Tanui")
    assert out["public"][0] in [x.replace("{name}", " Stephen") for x in rt._CAMPAIGN_ACK_POOL]
    assert len(out["human"]) == 1 and out["human"][0]["issues"] == ["a date the caption does not give"]
    assert out["dm"] == []
    # a held draft at a price ask: the gift's line, and a colleague — never the disclaimer
    out = _engage(monkeypatch, "How much is the shoe?", reading=QUESTION, identity=SHOE,
                  answer="Samahani, viatu hatuuzi", held=["it says we do not sell the gift"])
    assert out["public"][0] in [x.replace("{name}", " John") for x in rt._CAMPAIGN_GIFT_POOL]
    assert "hatuuzi" not in out["public"][0] and len(out["human"]) == 1


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
    assert "4,500" not in t and "Which" not in t and t in [x.replace("{name}", " John") for x in rt._CAMPAIGN_GIFT_POOL]


def test_a_shop_post_still_sells_as_before(monkeypatch):
    """The campaign handling never touches a shop post: over the cap, a bare
    price ask on a trusted identity gets the priced line."""
    out = _engage(monkeypatch, "How much?", reading=QUESTION, identity=SHOE, over_cap=True,
                  caption="Clergy Oxford Shoe — in stock now, KES 4,500")
    t = out["public"][0]
    assert "KES 4,500" in t and "gift" not in t.lower()


# ── the wiring, pinned ───────────────────────────────────────────────────────
def test_the_engine_hands_entries_to_the_host():
    src = inspect.getsource(rt._run_comment_engage)
    assert "campaign = bool(_caption) and is_campaign_post(_caption)" in src
    assert "reading = _host_reading(dict(reading, campaign=_caption), comment_text)" in src
    assert "plan = dict(plan, dm=False)" in src
    assert "free_ask = _trusted and is_bare_price_ask(prompt_text) and not campaign" in src
    assert "if campaign:\n        media = None" in src
    assert "if is_live or campaign:" in src
    assert 'product_name, matched = "", {}' in src and "asks_it = True" not in src
    assert 'if campaign and not (product_link and _names_exactly(answer, matched.get("name") or "")):' in src
    assert "campaign=campaign," in src
    assert "public_text = _campaign_canned(comment_text, kind, ask, name_tag, ext, swahili)" in src
    assert 'if not campaign or held_issues or (kind in ("request", "question")' in src
    assert "pool = _SW_CAMPAIGN_ACK_POOL if swahili else _CAMPAIGN_ACK_POOL" in src
    add = " ".join(rt._public_comment_addendum("USD").split())
    assert "CAMPAIGN / GIFTING POSTS (owner, 2026-09-26)" in add
    src2 = inspect.getsource(rt.run_turn)
    assert "_campaign_post = bool(_campaign_cap) and is_campaign_post(_campaign_cap)" in src2
    assert "line = _campaign_turn_context(_campaign_cap, source_post.get(\"comment\") or \"\")" in src2
    assert "_known = {} if _campaign_post else await _post_identity(" in src2
    assert "and not identity_trusted_record(_known) and not _campaign_post" in src2
    # the gift's words are set aside for the guard and the reviewer before either reads
    assert "_campaign_allow = tuple(_dom0.gift_terms(_cap0))" in src2
    assert "allow=_campaign_allow, names=_guard_names)" in src2
    assert "allow=_campaign_allow)" in src2
    assert inspect.getsource(rt._gate_turn_reply).count("allow=allow") == 2
    assert "if is_campaign_post" not in inspect.getsource(rt._resolve_post_product)
    assert rt._names_exactly("the Purple Cassock is KES 12,000", "Purple Cassock")
    assert not rt._names_exactly("share your shoe size as the post asks", "Clergy Oxford Shoe")


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


# ── The gift is never "goods we do not sell" (owner, 2026-09-26) ─────────────
class _FakeRedis:
    def __init__(self):
        self.kv: dict = {}

    async def get(self, k):
        return self.kv.get(k)

    async def set(self, k, v, ex=None, nx=False):
        if nx and k in self.kv:
            return False
        self.kv[k] = v
        return True

    async def delete(self, k):
        self.kv.pop(k, None)

    async def incr(self, k):
        self.kv[k] = int(self.kv.get(k) or 0) + 1
        return self.kv[k]

    async def expire(self, k, ex):
        return True

    async def hincrby(self, k, f, n):
        return n

    async def hgetall(self, k):
        return {}


def test_the_guard_never_declines_the_gift(monkeypatch):
    """'Stop saying we do not make shoes, hatuuzi viatu — that shoe is a
    gift.' Under the campaign post the gift's words are never goods to
    decline, and a thread paused for them is lifted the moment they write."""
    from app.agent import domain as dm
    allow = dm.gift_terms(OWNER_CAPTION)
    assert {"shoes", "viatu", "sneakers", "sandals"} <= set(allow)
    assert "shoes" in dm.gift_terms("Kwa wachungaji wote: viatu hivi ni zawadi kwa mchungaji mmoja")
    assert dm.gift_terms("New cassocks for the season") == ()
    assert dm.off_domain_in("I love the shoes, size 41") == ["shoes"]
    assert dm.off_domain_in("I love the shoes, size 41", allow) == []
    assert dm.off_domain_in("Nataka viatu na simu", allow) == ["simu"]
    a = dm.assess("Size 42, I want the shoes", allow=allow)
    assert not a["off_only"] and not a["mixed"]
    assert dm.assess("Size 42, I want the shoes")["off_only"]
    monkeypatch.setattr(settings, "church_goods_guard", True, raising=False)
    r = _FakeRedis()
    v = asyncio.run(dm.guard_turn(r, channel="facebook", key="u1", text="Size 42, I want the shoes",
                                  transcript=[], public_comment=True, allow=allow))
    assert v is None
    # the same words on a shop post are declined and paused, as before
    v = asyncio.run(dm.guard_turn(r, channel="facebook", key="u2", text="Size 42, I want the shoes",
                                  transcript=[], public_comment=True))
    assert v and v["action"] == "decline" and "shoes" in v["reply"] and r.kv.get("guard:pause:facebook:u2")
    # a thread paused for the shoes is a guest again the moment they write under the gift
    v = asyncio.run(dm.guard_turn(r, channel="facebook", key="u2", text="Viatu size 42 tafadhali",
                                  transcript=[], public_comment=True, allow=allow))
    assert v is None and r.kv.get("guard:pause:facebook:u2") is None


def test_the_reviewer_never_holds_the_gift_and_holds_its_disclaimer():
    from app.agent import review as rv
    allow = ("shoes", "viatu", "sneakers", "sandals")
    gift_reply = ("Hello Pastor, welcome to Bethany House! These shoes are our gift to one selected "
                  "recipient — completely free, only the shipping to cover.")
    assert rv.domain_issues("I love the shoes, size 41", gift_reply) != []
    assert rv.domain_issues("I love the shoes, size 41", gift_reply, allow) == []
    assert rv.gift_issues(gift_reply, allow) == []
    bad = "Samahani, viatu hatuuzi — sisi ni mavazi ya kanisa na vifaa vya ushirika tu 🙏"
    iss = rv.gift_issues(bad, allow)
    assert iss and iss[0]["hard"] and "GIFT" in iss[0]["text"]
    assert rv.gift_issues("Sorry, we don't sell shoes — we make church vestments only", allow)
    assert rv.gift_issues(bad, ()) == []
    f = rv.rule_findings("Nataka viatu size 42", bad, [], allow=allow)
    assert any(x["kind"] == "gift" and x["hard"] for x in f)
    f2 = rv.rule_findings("Nataka viatu size 42", gift_reply, [], allow=allow)
    assert not any(x["kind"] == "gift" for x in f2)
    block = rv.rewrite_block(["x"], bad, [], "KES", [], allow=allow)
    assert "THE GIFT" in block and "never 'hatuuzi'" in block
    assert "THE GIFT" not in rv.rewrite_block(["x"], bad, [], "KES", [])
    src = inspect.getsource(rv.reviewer_verdict)
    assert "THE GIFT — under this post" in src and "allow=()" in src
    assert "allow=allow" in inspect.getsource(rv.review_reply)
