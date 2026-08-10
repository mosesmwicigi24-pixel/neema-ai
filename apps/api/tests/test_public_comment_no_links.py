"""The send-boundary guard: a PUBLIC comment reply can never carry a link.

Facebook cuts the reach of a post whose comments carry outbound links, so a link
in a comment buys one click at the cost of the whole post's audience. The rule
had lived only in the prompt and in the reply templates — and production showed
that was not enough: the over-cap template still pasted the storefront page.

So `meta_send.reply_to_comment` now sanitises at the wire. Everything private —
private replies, Messenger/Instagram DMs, WhatsApp — is deliberately untouched:
that is exactly where the link is supposed to go.
"""
import asyncio

from app.services import meta_send


# The line that actually went out on the Bethany House page, byte for byte.
_LEAKED = ("Karibu SelfieAnne 🙏 You can see it and order here 👉 "
           "https://bethanyhouse.co.ke/product/refiller?ref=E14E0D — "
           "we'll handle delivery from there 💛")


def _capture(monkeypatch) -> list:
    """Record what would have hit the Graph API instead of calling it."""
    posted: list = []

    async def fake_post(path, body, what, page_id=None):
        posted.append((path, body, what))
        return {}

    monkeypatch.setattr(meta_send, "_graph_post", fake_post)
    return posted


# ── the sanitiser itself ─────────────────────────────────────────────────────

def test_the_production_leak_is_cleaned_and_still_reads_well():
    out, removed = meta_send.sanitize_public_comment(_LEAKED)
    assert removed == ["https://bethanyhouse.co.ke/product/refiller?ref=E14E0D"]
    assert "http" not in out and "bethanyhouse" not in out
    assert "👉" not in out                     # the pointer aimed at nothing
    assert out.startswith("Karibu SelfieAnne")
    assert out.endswith("we'll handle delivery from there 💛")
    assert "  " not in out                     # no hole where the URL had been


def test_every_shape_of_link_is_caught():
    for bad in [
        "See https://bethanyhouse.co.ke/product/x it is lovely",
        "See http://example.com/a?b=c it is lovely",
        "Visit www.bethanyhouse.co.ke today please",
        "Our shop bethanyhouse.co.ke has it in stock",
        "The page is neema.bethanyhouse.co.ke/api/o/ABC for you",
        "Write to us at sales@bethanyhouse.co.ke any time",
        "Find us at bethanyhouse.com/shop right now",
    ]:
        out, removed = meta_send.sanitize_public_comment(bad)
        assert removed, f"missed the link in: {bad}"
        assert "http" not in out and "www." not in out
        assert "bethanyhouse.co" not in out and "bethanyhouse.com" not in out


def test_ordinary_sales_copy_is_left_exactly_alone():
    """The guard must be invisible on the 99.9% of replies that are already
    clean — no reformatting, no stripped punctuation, no lost emoji."""
    for good in [
        "Totally understand — the Silver Tray is beautiful but I hear you on the "
        "cost. We also have an Aluminium Tray at $70 💛",
        "Which one catches your eye, and how many trays would you need? Also, "
        "which city are you in?",
        "Thank you Grace 🙏 Yes, the Red Chasuble is available — send us a "
        "message and we'll share the price and get you sorted 💛",
        "Asante sana! 🙏",
    ]:
        out, removed = meta_send.sanitize_public_comment(good)
        assert removed == []
        assert out == good


def test_a_decapitated_cta_line_is_dropped_not_left_dangling():
    out, removed = meta_send.sanitize_public_comment(
        "That red chasuble is $150.\nOrder here 👉 https://bethanyhouse.co.ke/p/x\n"
        "Neema can help you right there 💬")
    assert removed
    assert "Order here" not in out             # two words pointing nowhere
    assert out.startswith("That red chasuble is $150.")
    assert "Neema can help you right there 💬" in out


def test_a_reply_that_was_nothing_but_a_link_falls_back_to_a_warm_line():
    out, removed = meta_send.sanitize_public_comment("https://bethanyhouse.co.ke/p/x")
    assert removed
    assert out == meta_send.LINK_FREE_FALLBACK
    assert "http" not in out                   # and the fallback is itself clean


def test_prices_and_decimals_are_not_mistaken_for_domains():
    for safe in ["It is KES 13,000.50 delivered", "Ratio 1.5 to 2.0", "e.g. two sizes"]:
        assert meta_send.sanitize_public_comment(safe) == (safe, [])


# ── the wire: public comments are cleaned, private messages are not ──────────

def test_reply_to_comment_strips_the_link_before_it_reaches_graph(monkeypatch):
    posted = _capture(monkeypatch)
    asyncio.run(meta_send.reply_to_comment("CID_1", _LEAKED, page_id="P1"))

    path, body, _what = posted[0]
    assert path == "CID_1/comments"
    assert "http" not in body["message"]
    assert "bethanyhouse" not in body["message"]
    assert body["message"].startswith("Karibu SelfieAnne")


def test_instagram_comment_replies_are_guarded_too(monkeypatch):
    posted = _capture(monkeypatch)
    asyncio.run(meta_send.reply_to_comment("IGC_1", _LEAKED, channel="instagram"))

    path, body, _what = posted[0]
    assert path == "IGC_1/replies"             # the IG edge, still guarded
    assert "http" not in body["message"]


def test_a_clean_comment_is_posted_verbatim(monkeypatch):
    posted = _capture(monkeypatch)
    clean = "The Aluminium Tray is $70 💛 Send us a message and we'll sort you out"
    asyncio.run(meta_send.reply_to_comment("CID_2", clean))
    assert posted[0][1]["message"] == clean


def test_the_private_reply_keeps_its_link(monkeypatch):
    """The whole point: the storefront link travels by DM. Guarding this path
    would break the sale it was moved here to protect."""
    posted = _capture(monkeypatch)
    dm = ("The Aluminium Tray is $70.\n\nOrder here 👉 "
          "https://bethanyhouse.co.ke/product/aluminium-tray?ref=AB12CD\n"
          "Reply here and I'll help you get yours 💛")
    asyncio.run(meta_send.send_private_reply("CID_3", dm))

    path, body, _what = posted[0]
    assert path == "me/messages"               # Send API — the edge 400s on v21
    assert body["recipient"] == {"comment_id": "CID_3"}
    assert body["message"] == {"text": dm}     # untouched, link and all


def test_messenger_and_instagram_dms_keep_their_links(monkeypatch):
    posted = _capture(monkeypatch)
    dm = "Order here 👉 https://bethanyhouse.co.ke/product/x?ref=AB12CD"
    asyncio.run(meta_send.send_meta_message("PSID_1", dm))
    asyncio.run(meta_send.send_private_reply("IGC_9", dm, channel="instagram"))

    assert posted[0][1]["message"]["text"] == dm
    assert posted[1][1]["message"]["text"] == dm


def test_whatsapp_is_not_touched_by_the_comment_guard(monkeypatch):
    sent = []

    async def fake_waba(num, text, context_wamid=None):
        sent.append(text)

    import app.services.n8n_bridge as nb
    monkeypatch.setattr(nb, "_send_waba", fake_waba)
    body = "Order here 👉 https://bethanyhouse.co.ke/product/x?ref=AB12CD"
    asyncio.run(meta_send.send_to_channel("whatsapp", "254712345678", body))
    assert sent == [body]
