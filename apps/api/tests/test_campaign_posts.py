"""CAMPAIGN POSTS and the grievance the words do not carry (owner, 2026-09-26).

Live, Facebook, a shoe giveaway for clergy ("one person will get the shoe
for free; the only cost is shipping"): Bishop John Tela wrote "I am bishop
John Tela. I love the shoe. That shoe can serve me well with the bishops
cassock that I am planning to buy at Bethany house. My size is no 41." and
was told "we're sorry about the part that went wrong. One of us will speak
with you personally to put it right." Pastor Stephen's "I'm Pastor Stephen
Tanui From Eldoret" got the canned "Bless you… so glad this speaks to…"."""
import asyncio
import inspect

import app.main  # noqa: F401
import app.agent.runtime as rt

BISHOP = ("I am bishop John Tela.I love the shoe.That shoe can serve me well with the bishops "
          "cassock that I am planning to buy at Bethany house.My size is no 41.")
PASTOR = "I'm Pastor Stephen Tanui From Eldoret"
CAPTION = ("Clergy shoe giveaway! One pastor, reverend or bishop will win this shoe for free — "
           "the only cost is shipping. Comment with your name and shoe size to enter.")


def test_a_grievance_the_words_do_not_carry_is_not_a_grievance():
    # the light model's misread, exactly as it must have come back
    for model_says in ({"intent": "negative", "kind": "mixed", "severity": 1, "ask": ""},
                       {"intent": "negative", "kind": "complaint", "severity": 2, "ask": ""},
                       {"intent": "high", "kind": "mixed", "severity": 1, "ask": ""}):
        r = rt._settle_reading(BISHOP, dict(model_says))
        assert (r["intent"], r["kind"], r["severity"]) == ("high", "other", 0), model_says
        r = rt._settle_reading(PASTOR, dict(model_says))
        assert (r["intent"], r["kind"]) == ("high", "other"), model_says
    # a real grievance keeps its reading — cue words, plain displeasure, "but"
    for text in ("Beautiful work but my order never came", "I am not happy with this",
                 "Still waiting since May", "Nilituma pesa zangu, sijapata kitu", "this is wrong"):
        r = rt._settle_reading(text, {"intent": "negative", "kind": "complaint", "severity": 1, "ask": ""})
        assert r["intent"] == "negative", text
    r = rt._settle_reading("Beautiful work but my order never came",
                           {"intent": "negative", "kind": "mixed", "severity": 1, "ask": ""})
    assert r["kind"] == "mixed"


def test_the_bishops_entry_never_reaches_the_complaint_line(monkeypatch):
    """Whatever the model says, the reading that reaches the plan is 'high':
    the host answers, no empathy line, no colleague."""
    class _LLM:
        async def complete(self, **kw):
            import types
            return types.SimpleNamespace(text="intent=negative | kind=mixed | severity=1 | ask=-")
    monkeypatch.setattr(rt, "build_llm", lambda model=None, **kw: _LLM())
    r = asyncio.run(rt.read_comment(BISHOP))
    assert r["intent"] == "high" and r["kind"] == "other"
    plan = rt.plan_comment_actions(r["intent"])
    assert plan["style"] == "answer" and plan["human"] is False


def test_a_campaign_post_is_read_from_its_caption():
    assert rt.is_campaign_post(CAPTION)
    for c in ("GIVEAWAY: stand a chance to win a Bible", "Shinda viatu hivi — andika jina lako",
              "Lucky draw this Sunday for one pastor", "Win a stole for your ordination"):
        assert rt.is_campaign_post(c), c
    for c in ("Silver Communion Tray in stock — 40 cups included free", "New cassocks for the season",
              "Gift set for your pastor: stole and collar", "", None):
        assert not rt.is_campaign_post(c), c


def test_the_host_context_carries_the_rule_and_saves_the_entry():
    ctx = rt._reading_context({"intent": "high", "kind": "other", "severity": 0, "ask": "", "campaign": CAPTION})
    assert ctx.startswith("(THIS POST IS A CAMPAIGN / GIVEAWAY")
    assert "the only cost is shipping" in ctx                     # the caption, verbatim
    assert "HOST of the campaign, not a shopkeeper" in ctx
    assert "capture_contact" in ctx and "save_measurements" in ctx
    assert "never a date, a count, a winner or a rule the caption does not" in ctx
    assert "never priced and never sold" in ctx
    assert "item they plan to buy" in ctx and 'never "something went wrong"' in ctx
    # the ordinary reading still follows the campaign block
    ctx2 = rt._reading_context({"kind": "question", "ask": "the size", "campaign": CAPTION})
    assert "CAMPAIGN" in ctx2 and "this comment is a QUESTION — the size" in ctx2
    assert rt._reading_context({"kind": "other"}) == ""


def test_the_engine_hands_entries_to_the_host():
    src = inspect.getsource(rt._run_comment_engage)
    assert "campaign = bool(_caption) and is_campaign_post(_caption)" in src
    assert "reading = _host_reading(dict(reading, campaign=_caption), comment_text)" in src
    add = " ".join(rt._public_comment_addendum("USD").split())
    assert "CAMPAIGN / GIVEAWAY POSTS (owner, 2026-09-26)" in add
    assert "hosted, not sold" in add and "Never a complaint line or an apology at an entry" in add


# ── Pass 6 (2026-09-26): the fix must FIRE on the owner's real post ──────────
OWNER_CAPTION = ("We are donating or gifting pastors, reverends and bishops a shoe this month. "
                 "This is for mobilisation and visibility. One person will get the shoe for free — "
                 "the only cost is for shipping. Comment your name, your church and your size below.")


def test_the_owners_own_words_read_as_a_campaign():
    assert rt.is_campaign_post(OWNER_CAPTION)
    for c in ("Gifting pastors, reverends, bishops a shoe.",
              "One person will get this shoe for free",
              "The only cost is shipping",
              "You only pay for delivery",
              "We are giving away a stole to one lucky pastor",
              "Tuna kampeni: mchungaji mmoja atapata viatu hivi bure",
              "Shindano la wiki hii — andika jina lako",
              "Comment below to enter — entries close Sunday",
              "Win a Bible for your church this Easter"):
        assert rt.is_campaign_post(c), c
    # shop posts stay shop posts — free delivery, a tag-a-friend, a SALES campaign
    for c in ("Free delivery within Nairobi on every cassock this week",
              "Tag a friend who needs this collar",
              "Easter sales campaign: cassocks at 10% off, order now",
              "Our price campaign — communion cups KES 350 each",
              "Take one home today: the Round Collar Shirt is KES 2,500",
              "Gift set for your pastor: stole and collar",
              "A win for your choir: robes from KES 3,500",
              "We offer free shipping on orders above KES 20,000",
              "Season's campaign: every cassock ordered this week comes with a free collar",
              "Our Christmas campaign is here — cassocks, shirts and stoles at 15% off",
              "We take part in the Nairobi church expo this weekend — visit our stand",
              "Give a pastor the gift of comfort — clergy shoes KES 4,500, order now"):
        assert not rt.is_campaign_post(c), c
    # the soft markers read as a giveaway only where nothing is sold
    for c in ("Blessing a pastor this month: we are giving one reverend this cassock. Tell us why yours deserves it.",
              "Our clergy shoe campaign: comment your name, church and size",
              "🎁 CLERGY SHOE CAMPAIGN 🎁 We are gifting one pastor, reverend or bishop this shoe. Only shipping is paid by the winner.",
              "As part of our mobilisation drive, one man of God will receive this pair at no cost. The only charge is delivery.",
              "Kwa wachungaji wote: mmoja wenu atapata viatu hivi BURE. Gharama ni ya usafirishaji tu."):
        assert rt.is_campaign_post(c), c


def test_the_host_reads_every_entry():
    base = {"intent": "negative", "kind": "mixed", "severity": 1, "ask": "", "campaign": CAPTION}
    r = rt._host_reading(base, "Lovely shoe but I wear size 44, do you have it?")
    assert (r["intent"], r["kind"], r["severity"]) == ("high", "other", 0)
    assert r["campaign"] == CAPTION
    # a real grievance under a giveaway is still one
    r = rt._host_reading(base, "Beautiful, but I never received my last order")
    assert r["intent"] == "negative" and r["kind"] == "mixed"
    r = rt._host_reading(dict(base, kind="complaint", severity=3), "This page is a scam")
    assert r["intent"] == "negative" and r["severity"] == 3
    # a size on its own is an entry, not a bare cheer; a bare emoji stays light
    r = rt._host_reading({"intent": "low", "kind": "other", "severity": 0, "ask": ""}, "Size 42")
    assert r["intent"] == "high"
    r = rt._host_reading({"intent": "low", "kind": "praise", "severity": 0, "ask": ""}, "🙏🙏")
    assert r["intent"] == "low"
    r = rt._host_reading({"intent": "goodwill", "kind": "question", "severity": 0, "ask": "the size"},
                         "which sizes are there?")
    assert r["intent"] == "high" and r["kind"] == "question"
    r = rt._host_reading({"intent": "spam", "kind": "other", "severity": 0, "ask": ""}, "buy followers here")
    assert r["intent"] == "spam"
    # the bishop's and the pastor's entries, whatever the model said
    for said in ({"intent": "negative", "kind": "mixed", "severity": 1, "ask": ""},
                 {"intent": "low", "kind": "praise", "severity": 0, "ask": ""},
                 {"intent": "goodwill", "kind": "other", "severity": 0, "ask": ""}):
        for t in (BISHOP, PASTOR):
            r = rt._host_reading(dict(said), t)
            assert r["intent"] == "high" and rt.plan_comment_actions(r["intent"])["style"] == "answer", (said, t)


def test_the_inbox_opens_only_for_an_entrant_who_speaks_of_buying():
    assert rt._CAMPAIGN_BUY_RE.search(BISHOP)                       # "planning to buy"
    assert not rt._CAMPAIGN_BUY_RE.search(PASTOR)
    assert not rt._CAMPAIGN_BUY_RE.search("Size 42, Rev. Alice from Nakuru")
    assert rt._CAMPAIGN_BUY_RE.search("How much is the cassock? Nataka kununua")


def test_over_the_cap_the_thread_hears_the_host_never_a_price():
    t = rt._comment_public_reply("", False, " Bishop", "seed", product_known=True,
                                 product_name="Clergy Oxford Shoe", price_text="KES 4,500", campaign=True)
    assert "4,500" not in t and "Oxford" not in t and "Bishop" in t
    assert t in [x.replace("{name}", " Bishop") for x in rt._CAMPAIGN_ACK_POOL]
    t = rt._comment_public_reply("", False, " Bishop", "seed", product_known=True, product_name="Clergy Oxford Shoe",
                                 price_text="KES 4,500", campaign=True, swahili=True)
    assert t in [x.replace("{name}", " Bishop") for x in rt._SW_CAMPAIGN_ACK_POOL]
    # a question or a request over the cap still promises a person
    t = rt._comment_public_reply("", False, " Bishop", "seed", kind="question", campaign=True)
    assert t == rt._pick(rt._QUESTION_ACK_POOL, "seed").replace("{name}", " Bishop")
    # the model's answer stands as it is
    assert rt._comment_public_reply("Welcome, Bishop John!", False, " Bishop", "seed", campaign=True) == "Welcome, Bishop John!"


def test_the_engine_never_sells_the_giveaway_item():
    src = inspect.getsource(rt._run_comment_engage)
    assert "free_ask = _trusted and is_bare_price_ask(prompt_text) and not campaign" in src
    assert "if is_campaign_post(post_caption(post_ctx)):" in inspect.getsource(rt._resolve_post_product)
    sink: list = []
    asyncio.run(rt._resolve_post_product(None, "facebook", "u1", {"title": CAPTION, "post_id": "p1"}, sink))
    assert sink == []
    assert "if is_live or campaign:" in src
    assert 'product_name, matched, ask_which = "", {}, False' in src
    assert "dm=bool(_CAMPAIGN_BUY_RE.search(comment_text))" in src
    assert "campaign=campaign," in src
    assert "if campaign:\n        media = None" in src
    assert 'if not campaign or kind in ("request", "question"):' in src
    src2 = inspect.getsource(rt.run_turn)
    assert "_campaign_post = bool(_campaign_cap) and is_campaign_post(_campaign_cap)" in src2
    assert "THIS POST IS A CAMPAIGN / GIVEAWAY: the item in it is given away" in src2
    assert "and not identity_trusted_record(_known) and not _campaign_post" in src2


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
    """The title the inbox card shows is 200 chars; the rule of a giveaway can
    sit past it — the caption now rides whole, and the engine reads THAT."""
    import httpx
    from app.core.config import settings
    from app.services import meta_send
    long = "Clergy shoes for the season. " * 10 + "One pastor will get this shoe for free — the only cost is shipping."
    monkeypatch.setattr(settings, "meta_page_token", "T", raising=False)
    monkeypatch.setattr(httpx, "AsyncClient", _fake_client(
        {"message": long, "permalink_url": "https://fb/p/1", "full_picture": "http://x/p.jpg",
         "attachments": {"data": [{"media_type": "photo"}]}}))
    ctx = asyncio.run(meta_send.fetch_post_context("POST9"))
    assert len(ctx["title"]) == 200 and ctx["caption"].endswith("the only cost is shipping.")
    assert not rt.is_campaign_post(ctx["title"]) and rt.is_campaign_post(rt.post_caption(ctx))
    # Instagram and a reel carry it too
    monkeypatch.setattr(httpx, "AsyncClient", _fake_client(
        {"caption": long, "permalink": "https://ig/p/1", "media_type": "IMAGE", "media_url": "http://x/i.jpg"}))
    ig = asyncio.run(meta_send.fetch_post_context("IG9", channel="instagram"))
    assert ig["caption"] == long[:1500] and len(ig["title"]) == 200
    monkeypatch.setattr(httpx, "AsyncClient", _fake_client({"description": long, "picture": "http://x/f.jpg"}))
    reel = asyncio.run(meta_send._video_post_context("REEL9"))
    assert reel["caption"] == long[:1500]
    # an older cached record (no caption) is left to expire: the key moved
    from app.routers import meta_webhook as mw
    assert "meta:postctx:v2:" in inspect.getsource(mw._post_context)
    assert rt.post_caption({"title": "Old record"}) == "Old record" and rt.post_caption(None) == ""


def test_the_host_context_shows_the_rule_however_long_the_caption():
    cap = "x " * 200 + OWNER_CAPTION
    ctx = rt._reading_context({"intent": "high", "kind": "other", "severity": 0, "ask": "", "campaign": cap})
    assert "the only cost is for shipping" in ctx
