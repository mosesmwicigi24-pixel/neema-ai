"""Double verification, a thumbs-up that ends it, and today's rate.

Owner, 2026-09-25, two Messenger threads after the gate went live:
- a customer's thumbs-up (Messenger's Like sticker) was answered with "I can
  see you've sent a thumbs-up, but I'm not able to open that image…"; "I'm
  saying ok" then got the holding line. "When a thumb up is done, which means
  satisfaction, you should not continue."
- "how much that in rands" got "let me confirm the exact rate with our team";
  "When am in Uganda" and "My wansapp number" got holding lines. "Change from
  gating to double verifying… make the logic consistent."
"""
import asyncio
import inspect
import json
import types

import app.main  # noqa: F401
from app.agent import review as rv
from app.agent import runtime as rt
from app.agent.prompt import build_system_prompt
from app.routers import meta_webhook as mw
from app.services import fx


# ── a thumbs-up is the end of the exchange ──────────────────────────────────

def test_messengers_like_sticker_is_a_thumbs_up_not_a_photo():
    like = {"mid": "m1", "attachments": [{"type": "image", "payload": {
        "url": "https://scontent.xx.fbcdn.net/v/t39.1997-6/39178562.png", "sticker_id": 369239263222822}}]}
    assert mw._sticker(like) == "👍"
    assert mw._sticker({"attachments": [{"type": "image", "payload": {
        "url": "https://x/y.png", "sticker_id": "369239383222810"}}]}) == "👍"
    assert mw._sticker({"attachments": [{"type": "image", "payload": {
        "url": "https://x/y.png", "sticker_id": 12345}}]}) == "[sticker]"
    assert mw._sticker({"attachments": [{"type": "image", "payload": {"url": "https://x/p.jpg"}}]}) is None
    assert mw._sticker({"text": "hi"}) is None
    src = inspect.getsource(mw)
    assert 'text, media_type, media_url = sticker, None, None' in src
    assert 'turn_text = (message.get("text") or "").strip() or (sticker or "")' in src


def test_a_thumbs_up_is_silence_always():
    for t in ("👍", "👍👍", "🙏", "❤️", "👌", "[sticker]", " 👍 "):
        assert rt.is_silent_ack(t), t
        assert asyncio.run(rt.closer_gate(None, "messenger", "P1", t)) is True, t
    for t in ("ok", "thanks", "how much?", "👍 how much is it?", ""):
        assert not rt.is_silent_ack(t), t
    # a typed closer still takes the old path (one warm line, then silence)
    assert asyncio.run(rt.closer_gate(None, "messenger", "P1", "thanks")) is False


def test_i_am_saying_ok_is_an_acknowledgement():
    for t in ("I'm saying ok", "im saying okay", "just saying ok", "I am saying ok 🙏",
              "noted", "alright", "ok ok", "kk", "sawa sawa", "cool 👍"):
        assert rt.is_closer(t), t
    for t in ("ok, I want the gold one", "ok how much", "yes", "sure", "fine, and delivery?"):
        assert not rt.is_closer(t), t


def test_nothing_is_ever_sent_for_an_empty_reply():
    src = inspect.getsource(rt._run_and_send)
    assert 'if not (reply or "").strip():' in src and src.index('if not (reply or "").strip():') < src.index("_send_waba(")
    src = inspect.getsource(rt._run_and_send_meta)
    assert 'if not (reply or "").strip():' in src and src.index('if not (reply or "").strip():') < src.index("send_to_channel(")


# ── today's rate: a fact for the writer and for the verifier ────────────────

def test_the_currency_they_asked_for_is_read():
    assert fx.currency_asked("how much that in rands") == "ZAR"
    assert fx.currency_asked("Price in Naira please") == "NGN"
    assert fx.currency_asked("in pounds?") == "GBP"
    assert fx.currency_asked("how much in ugandan shillings") == "UGX"
    assert fx.currency_asked("how much in shillings") is None          # Kenya's own, hub-priced
    assert fx.currency_asked("how much is the cassock") is None
    assert fx.currency_asked("Randall asked about the tray") is None    # no word inside a word
    assert fx.currency_asked("") is None


class _R:
    def __init__(self):
        self.store = {}

    async def get(self, k):
        return self.store.get(k)

    async def set(self, k, v, ex=None, nx=False):
        if nx and k in self.store:
            return False
        self.store[k] = v
        return True


def test_rates_are_fetched_once_a_day_and_a_stale_copy_survives_an_outage(monkeypatch):
    fx._mem.update(at=0.0, rates={})
    calls = []

    async def fake_fetch():
        calls.append(1)
        return {"ZAR": 16.43, "NGN": 1327.9}
    monkeypatch.setattr(fx, "fetch", fake_fetch)
    r = _R()
    assert asyncio.run(fx.rates(r)) == {"ZAR": 16.43, "NGN": 1327.9}
    assert json.loads(r.store["fx:usd"]) == {"ZAR": 16.43, "NGN": 1327.9}
    assert json.loads(r.store["fx:usd:stale"]) == {"ZAR": 16.43, "NGN": 1327.9}
    assert asyncio.run(fx.rates(r)) == {"ZAR": 16.43, "NGN": 1327.9} and calls == [1]   # cached
    # the source is down and the day's copy expired: the stale copy serves
    fx._mem.update(at=0.0, rates={})
    r.store.pop("fx:usd")

    async def down():
        return {}
    monkeypatch.setattr(fx, "fetch", down)
    assert asyncio.run(fx.rates(r)) == {"ZAR": 16.43, "NGN": 1327.9}
    # nothing anywhere: no rates, no conversion
    fx._mem.update(at=0.0, rates={})
    assert asyncio.run(fx.rates(_R())) == {}
    fx._mem.update(at=0.0, rates={})


def test_the_source_shape_is_read_and_the_house_currencies_left_alone():
    got = fx._pick({"result": "success", "rates": {"ZAR": 16.431387, "KES": 129.49, "USD": 1, "ZMW": 19.66,
                                                   "NGN": "1327.9", "GBP": 0.7564, "XXX": "bad"}})
    assert got["ZAR"] == 16.431387 and got["NGN"] == 1327.9 and got["GBP"] == 0.7564
    assert "KES" not in got and "USD" not in got and "XXX" not in got
    assert fx.convert_usd(120, 16.431387) == 1971.77
    line = fx.context_line("ZAR", 16.43)
    assert "TODAY'S RATE: 1 USD = 16.43 ZAR" in line and "$120 = 1,971.60 ZAR" in line
    assert "Never promise to 'confirm the rate'" in line
    assert "no rate is available today" in fx.no_rate_line("ZAR")


def test_the_turn_hands_the_writer_todays_rate_only_when_asked():
    src = inspect.getsource(rt.run_turn)
    assert '_fx_code = _fx.currency_asked(user_text) if currency == "USD" else None' in src
    assert "_fx_rates = await _fx.rates(redis)" in src
    assert "tail += (_fx.context_line(_fx_code, _fx_rates[_fx_code]) if _fx_rates.get(_fx_code)" in src
    assert "else _fx.no_rate_line(_fx_code))" in src
    p = " ".join(build_system_prompt(currency="USD").split())
    assert "TODAY'S RATE GIVEN IN YOUR CONTEXT" in p
    assert "never invent a rate from memory" in p and "never promise to 'confirm the rate with the team'" in p
    assert "central-bank" not in p


def test_the_verifier_reads_rands_and_allows_the_conversion_at_todays_rate():
    assert rv.money_with_currency("R2,200 or ZAR 2200 or 2,200 rands, $120, ₦5,000") == [
        ("ZAR", 2200.0), ("ZAR", 2200.0), ("ZAR", 2200.0), ("USD", 120.0), ("NGN", 5000.0)]
    assert rv.money_figures("Randall paid R500") == [500.0]
    cassock = {"name": "Cassock", "price": 13000, "price_usd": 120}
    rate = {"ZAR": 16.43}
    ok = "The Cassock is $120 — about R1,971.60 at today's rate."
    assert rv.unverified_figures(ok, [cassock], "how much that in rands", fx=rate) == []
    assert rv.unverified_figures("The Cassock is $120 — about R2,300.", [cassock], "in rands", fx=rate) == [2300.0]
    assert rv.unverified_figures("R1,971.60", [cassock], "in rands") == [1971.6]         # no rate: no conversion
    # the currency they asked for may stand beside the USD price it converts
    assert rv.two_currencies(ok, "how much that in rands") == []
    assert rv.two_currencies(ok, "how much is it") == ["USD", "ZAR"]
    assert rv.rule_issues("how much that in rands", ok, [cassock], fx=rate) == []
    block = rv.rewrite_block(["x"], "draft", [cassock], "USD", [], mode="dm", fx=rate, comment="in rands?")
    assert "Today's rate (a fact): 1 USD = 16.43 ZAR" in block and "an exchange rate" in block
    assert "never promise to 'confirm' a figure with the team" in block


# ── consistent: every channel, the same policy ──────────────────────────────

def test_the_reviewer_treats_ordinary_promises_as_promises(monkeypatch):
    llm = types.SimpleNamespace(calls=[])

    async def complete(system, messages, tools=None):
        llm.calls.append(messages[0]["content"])
        return types.SimpleNamespace(text="verdict=pass | issues=-")
    llm.complete = complete
    monkeypatch.setattr(rt, "build_llm", lambda model=None: llm)
    asyncio.run(rv.review_reply("my number", "Noted — a colleague will reach out shortly.", [], mode="dm"))
    sent = llm.calls[-1]
    assert "A colleague reaching out, a delivery being arranged, a price to be confirmed are ordinary promises" in sent


def test_hard_and_soft_are_named_in_one_place():
    assert rv.HARD_KINDS == ("figure", "item", "link", "status", "photos")
    f = rv.rule_findings("gold trays", "The Silver Communion Tray is $180 (KES 18,000).",
                         [{"name": "Silver Communion Tray", "price": 18000, "price_usd": 180}])
    kinds = {x["kind"]: x["hard"] for x in f}
    assert kinds == {"currency": False, "item": True}
    f = rv.rule_findings("where are you located?", "It is $99 — see https://pay.example.com/x",
                         [{"name": "Cassock", "price": 13000, "price_usd": 120}])
    kinds = {x["kind"]: x["hard"] for x in f}
    assert kinds == {"figure": True, "where": False, "link": True}


def test_the_hold_guard_marks_and_remembers():
    r = _R()
    assert asyncio.run(rv.held_recently(r, "whatsapp", "K")) is False     # first hold: marked
    assert asyncio.run(rv.held_recently(r, "whatsapp", "K")) is True      # within hours: already
    assert asyncio.run(rv.held_recently(None, "whatsapp", "K")) is False
