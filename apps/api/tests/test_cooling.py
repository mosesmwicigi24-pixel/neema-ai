"""PACING — cooling off without betraying the sale (owner, 2026-09-26: "some
people want to chat with neema non-stop… enhance cooling off without
betraying the quality of the sales and closing sales").

A buyer is never paced; a chatter gets briefer, then one warm close, then
silence until they ask for an item."""
import asyncio
import inspect
import types

import app.main  # noqa: F401
import app.agent.runtime as rt
from app.agent import cooling as cl
from app.agent.prompt import build_system_prompt
from app.core.config import settings


class _R:
    def __init__(self):
        self.store: dict = {}
        self.h: dict = {}

    async def get(self, k):
        return self.store.get(k)

    async def set(self, k, v, ex=None, nx=False):
        if nx and k in self.store:
            return False
        self.store[k] = v
        return True

    async def delete(self, *ks):
        for k in ks:
            self.store.pop(k, None)

    async def incr(self, k):
        self.store[k] = int(self.store.get(k, 0)) + 1
        return self.store[k]

    async def expire(self, k, ttl):
        return True

    async def hincrby(self, k, f, n):
        self.h.setdefault(k, {})
        self.h[k][f] = self.h[k].get(f, 0) + n

    async def hgetall(self, k):
        return dict(self.h.get(k, {}))


def _tally(r):
    return asyncio.run(cl.read_tally(r))


def _not_in_play(monkeypatch, value=False):
    async def _f(db, channel, key):
        return value
    monkeypatch.setattr(cl, "business_in_play", _f)


def test_a_buyer_is_read_as_a_buyer():
    yes = ["how much is the cassock?", "Bei ya kasoki?", "nataka kuagiza stola", "I want to order",
           "do you deliver to Kisumu", "what sizes do you have", "send me photos", "price?",
           "can I pay by mpesa", "2 silver trays please", "is the chalice available", "communion cups",
           "where are you located?", "what do you sell?", "I need help with a gown for my ordination",
           "mko wapi?", "do you have anything for ushers"]
    no = ["hi how are you today", "God is good all the time", "tell me about yourself",
          "what do you think of the weather", "haha you are funny", "are you a robot?",
          "I am from Nakuru", "we had a wonderful service yesterday"]
    for t in yes:
        assert cl.buying_signal(t), t
    for t in no:
        assert not cl.buying_signal(t), t
    assert cl.buying_signal("", has_media=True)              # a photo is an ask
    # a colour, a size, a figure — the sale's own answers
    for t in ("black please", "navy", "large", "2", "chest 42 length 58", "nyeusi moja"):
        assert cl.buying_signal(t), t


def test_a_chatter_gets_briefer_then_one_warm_close_then_silence(monkeypatch):
    _not_in_play(monkeypatch)
    monkeypatch.setattr(settings, "cooling_economy_hour", 10)
    monkeypatch.setattr(settings, "cooling_cool_hour", 20)
    monkeypatch.setattr(settings, "cooling_drift_turns", 50)     # only the count matters here
    r = _R()
    out = []
    for i in range(24):
        w = "story " + " ".join(["la"] * (i + 1))
        v = asyncio.run(cl.decide(r, None, channel="whatsapp", key="254700", text=f"tell me {w} about yourself"))
        out.append(v["action"] if v else None)
    assert out[:2] == [None, None]                       # two full turns of pure chat
    assert out[2:20] == ["economy"] * 18                 # then briefer, on the light model
    assert out[20] == "cool"                             # past the hourly line: the one warm close
    assert out[21:] == ["defer"] * 3                     # then the slow lane
    v = asyncio.run(cl.decide(r, None, channel="whatsapp", key="254700", text="tell me one more thing about yourself"))
    assert v["action"] == "defer"
    # a question during the cool-off is never left hanging: answered now, briefly
    v = asyncio.run(cl.decide(r, None, channel="whatsapp", key="254700", text="can you sing?"))
    assert v["action"] == "economy" and asyncio.run(cl.is_cooled(r, "whatsapp", "254700"))
    t = _tally(r)
    assert t["economy"] == 18 and t["cooled"] == 1 and t["silenced"] >= 3 and t["question"] == 1
    # the first buying signal lifts it, and that message is answered in full
    v = asyncio.run(cl.decide(r, None, channel="whatsapp", key="254700", text="how much is the cassock?"))
    assert v is None and _tally(r)["lifted"] == 1
    assert not asyncio.run(cl.is_cooled(r, "whatsapp", "254700"))


def test_the_cool_close_says_how_to_resume():
    en = cl.cool_line(False, "Pastor Moses Mwicigi")
    assert en.startswith("Thank you, Pastor Moses — ") and "just say which one" in en and "God bless" in en
    sw = cl.cool_line(True, "Grace")
    assert sw.startswith("Asante Grace — ") and "taja tu bidhaa" in sw
    assert cl.cool_line(False, "").startswith("Thank you — ")
    for bad in ("too much", "limit", "budget", "chatting"):
        assert bad not in en.lower() and bad not in sw.lower()


def test_business_in_play_is_never_paced_short_of_a_whole_day_of_chat(monkeypatch):
    _not_in_play(monkeypatch, True)
    monkeypatch.setattr(settings, "cooling_cool_hour", 3)
    monkeypatch.setattr(settings, "cooling_economy_hour", 2)
    monkeypatch.setattr(settings, "cooling_cool_day", 6)
    r = _R()
    acts = [(asyncio.run(cl.decide(r, None, channel="messenger", key="P1", text=f"and another thing about my day {w}")) or {}).get("action")
            for w in "abcdefgh"]
    assert "cool" not in acts and "silence" not in acts
    assert acts[:6] == [None] * 6                        # a sale in progress: full answers
    assert acts[6:] == ["economy", "economy"]            # a whole day of chat past the line: light


def test_an_answer_to_our_question_is_the_sale_talking(monkeypatch):
    _not_in_play(monkeypatch)
    monkeypatch.setattr(settings, "cooling_drift_turns", 3)
    r = _R()
    # "which colour would you like?" → "the dark one please" — no product word, still not drift
    for t in ("the dark one please", "the second option", "for my husband", "just the one"):
        assert asyncio.run(cl.decide(r, None, channel="whatsapp", key="A", text=t, answering=True)) is None
    assert "cool:drift:whatsapp:A" not in r.store


def test_a_buyer_is_never_paced_whatever_the_count(monkeypatch):
    _not_in_play(monkeypatch)
    monkeypatch.setattr(settings, "cooling_cool_hour", 3)
    monkeypatch.setattr(settings, "cooling_economy_hour", 1)
    r = _R()
    asks = ["how much is the cassock", "and the stole?", "do you deliver to Eldoret", "what about sizes",
            "can I pay in instalments", "send the photos", "I want two", "which colours do you have"]
    for t in asks:
        assert asyncio.run(cl.decide(r, None, channel="whatsapp", key="B", text=t)) is None, t
    assert _tally(r) == {}                              # not even an economy turn


def test_drifting_small_talk_cools_even_under_the_hourly_line(monkeypatch):
    _not_in_play(monkeypatch)
    monkeypatch.setattr(settings, "cooling_drift_turns", 5)
    monkeypatch.setattr(settings, "cooling_economy_hour", 100)
    monkeypatch.setattr(settings, "cooling_cool_hour", 100)
    r = _R()
    acts = []
    for w in "abcdef":
        v = asyncio.run(cl.decide(r, None, channel="instagram", key="U", text=f"I like football {w}"))
        acts.append((v or {}).get("action"))
    assert acts == [None, None, "economy", "economy", "cool", "defer"]
    # a product word resets the drift: the sale stays warm
    r2 = _R()
    for w in "abcd":
        asyncio.run(cl.decide(r2, None, channel="instagram", key="U", text=f"blah blah {w}"))
    assert asyncio.run(cl.decide(r2, None, channel="instagram", key="U", text="what about a stole then")) is None
    assert r2.store.get("cool:drift:instagram:U") is None


def test_the_same_words_within_minutes_are_not_a_new_turn(monkeypatch):
    _not_in_play(monkeypatch)
    r = _R()
    assert asyncio.run(cl.decide(r, None, channel="whatsapp", key="K", text="Did you get my message about the delivery")) is None
    v = asyncio.run(cl.decide(r, None, channel="whatsapp", key="K", text="did you get my message about the delivery"))
    assert v == {"action": "silence", "why": "duplicate"} and _tally(r)["duplicate"] == 1
    # a silenced ask repeated during a cool-off still lifts it: nothing was on their screen
    r3 = _R()
    asyncio.run(cl.cool(r3, "whatsapp", "K"))
    assert asyncio.run(cl.decide(r3, None, channel="whatsapp", key="K", text="hmm hmm hmm hmm")) == {"action": "defer", "why": "cooled"}
    assert asyncio.run(cl.decide(r3, None, channel="whatsapp", key="K", text="how much is the cassock please")) is None
    assert asyncio.run(cl.decide(r3, None, channel="whatsapp", key="K", text="how much is the cassock please")) == {"action": "silence", "why": "duplicate"}
    # short answers are never held: they may answer two different questions
    assert asyncio.run(cl.decide(r, None, channel="whatsapp", key="K", text="yes")) is None
    assert asyncio.run(cl.decide(r, None, channel="whatsapp", key="K", text="yes")) is None
    monkeypatch.setattr(settings, "cooling_dup_seconds", 0)
    assert asyncio.run(cl.decide(r, None, channel="whatsapp", key="K", text="Did you get my message about the delivery")) is None


def test_closers_and_the_switch_are_left_alone(monkeypatch):
    _not_in_play(monkeypatch)
    r = _R()
    for _ in range(30):
        assert asyncio.run(cl.decide(r, None, channel="whatsapp", key="C", text="thanks", closer=True)) is None
    assert "cool:h:whatsapp:C" not in r.store
    monkeypatch.setattr(settings, "cooling_enabled", False)
    for w in "abcdefghij":
        assert asyncio.run(cl.decide(r, None, channel="whatsapp", key="C", text=f"story {w} of my life")) is None
    assert asyncio.run(cl.decide(None, None, channel="whatsapp", key="C", text="story of my life")) is None


# ── run_turn wiring ──────────────────────────────────────────────────────────

class _Res:
    def __init__(self, one=None, many=None):
        self._one, self._many = one, many or []

    def scalar_one_or_none(self):
        return self._one

    def scalars(self):
        return types.SimpleNamespace(all=lambda: self._many, first=lambda: self._many[0] if self._many else None)

    def all(self):
        return self._many


class _FakeDB:
    def __init__(self, results):
        self._r, self._i = list(results), 0
        self.added = []

    async def execute(self, *a, **k):
        if self._i < len(self._r):
            r = self._r[self._i]
            self._i += 1
            return r
        return _Res()

    def add(self, o):
        self.added.append(o)

    async def commit(self):
        pass


def _db():
    user = types.SimpleNamespace(name="Zablon Wanjiru", wa_id="254700000001", person_id=None, country_iso="KE",
                                 country="Kenya", state={})
    return _FakeDB([_Res(one=user), _Res(one=None), _Res(one=None), _Res(one=None), _Res(many=[])])


def test_run_turn_sends_the_cool_close_and_then_nothing(monkeypatch):
    calls = []

    class _LLM:
        _model = settings.tier2_model
        purpose = "whatsapp"

        async def complete(self, *, system, messages, tools, **kw):
            calls.append(1)
            return types.SimpleNamespace(text="Karibu!", tool_calls=[], assistant_content=[], usage={})

    async def _cool(redis, db, **kw):
        return {"action": "cool", "reply": cl.cool_line(False, kw.get("customer_name", "")), "flag": "paced"}
    monkeypatch.setattr(cl, "decide", _cool)
    flagged = []

    async def _flag(db, channel, key, note):
        flagged.append(note)
    monkeypatch.setattr(rt, "_flag_guard", _flag)
    facts = {}
    out = asyncio.run(rt.run_turn(_db(), _R(), "254700000001", "tell me a story about Nairobi", _LLM(), turn_facts=facts))
    assert out.startswith("Thank you, Zablon — ") and "just say which one" in out
    assert not calls and flagged == ["paced"] and facts["pacing"] == "cool"

    async def _silent(redis, db, **kw):
        return {"action": "defer", "why": "cooled"}
    monkeypatch.setattr(cl, "decide", _silent)
    facts = {}
    assert asyncio.run(rt.run_turn(_db(), _R(), "254700000001", "another story", _LLM(), turn_facts=facts)) == ""
    assert not calls and facts["pacing"] == "cooled"


def test_system_composed_turns_are_never_paced(monkeypatch):
    called = []

    async def _spy(redis, db, **kw):
        called.append(kw.get("text"))
        return {"action": "defer", "why": "cooled"}
    monkeypatch.setattr(cl, "decide", _spy)

    class _LLM:
        _model = settings.tier2_model
        purpose = "job:cart-recovery"

        async def complete(self, *, system, messages, tools, **kw):
            return types.SimpleNamespace(text="Karibu tena!", tool_calls=[], assistant_content=[], usage={})
    out = asyncio.run(rt.run_turn(_db(), _R(), "254700000001",
                                  "(Internal: this customer built a cart and went quiet — write the nudge.)", _LLM()))
    assert out == "Karibu tena!" and called == []


def test_the_slow_lanes_own_turn_is_one_brief_answer(monkeypatch):
    _not_in_play(monkeypatch)
    r = _R()
    asyncio.run(cl.cool(r, "whatsapp", "L"))
    v = asyncio.run(cl.decide(r, None, channel="whatsapp", key="L", text="story one\nstory two", deferred=True))
    assert v["action"] == "economy" and "PACING" in v["note"]
    assert asyncio.run(cl.decide(r, None, channel="whatsapp", key="L", text="how much is a stole", deferred=True)) is None
    assert "cool:h:whatsapp:L" not in r.store                # the lane's turn is not counted


def test_run_turn_economy_swaps_to_the_light_model_with_a_pacing_note(monkeypatch):
    seen = []

    class _Main:
        _model = settings.tier2_model
        purpose = "whatsapp"

        async def complete(self, *, system, messages, tools, **kw):
            seen.append(("main", system))
            return types.SimpleNamespace(text="ok", tool_calls=[], assistant_content=[], usage={})

    class _Light:
        _model = settings.tier2_model_light
        purpose = "whatsapp"

        async def complete(self, *, system, messages, tools, **kw):
            seen.append(("light", system))
            return types.SimpleNamespace(text="Noted.", tool_calls=[], assistant_content=[], usage={})

    async def _econ(redis, db, **kw):
        return {"action": "economy", "note": cl.pacing_note(3), "hour": 11, "day": 11}
    monkeypatch.setattr(cl, "decide", _econ)
    monkeypatch.setattr(rt, "build_llm", lambda model=None, **kw: _Light())
    out = asyncio.run(rt.run_turn(_db(), _R(), "254700000001", "so what else do you do", _Main()))
    assert out == "Noted."
    assert seen and seen[0][0] == "light" and all(m != "main" for m, _ in seen)
    tail = seen[0][1][1]                                # the loop's call: [rules, this customer]
    assert "PACING: this person has been chatting a long while" in tail
    assert "`pause_conversation`" in tail and "A buyer is never paced" in tail


def test_pacing_never_touches_drafts_scribes_or_public_comments():
    src = inspect.getsource(rt.run_turn)
    i = src.index("from app.agent import cooling as _pace")
    assert "if not read_only and not scribe_only and not public_comment and _gate_applies(user_text):" in src[i - 260:i]
    # read before any token is bought, after the church-goods guard
    assert src.index("_dom.guard_turn(") < i < src.index("for _ in range(_max_iter):")


# ── comments: a per-person daily budget beside the per-post one ─────────────

class _LaneRedis(_R):
    def __init__(self):
        super().__init__()
        self.lists: dict = {}

    async def rpush(self, k, v):
        self.lists.setdefault(k, []).append(v)
        return len(self.lists[k])

    async def lrange(self, k, a, b):
        return list(self.lists.get(k, []))

    async def delete(self, *ks):
        for k in ks:
            self.store.pop(k, None)
            self.lists.pop(k, None)


def test_is_question_reads_marks_and_first_words():
    for t in ("can you sing?", "je mko wapi", "what time do you close", "Do you have a shop", "unafunga saa ngapi?"):
        assert cl.is_question(t), t
    for t in ("I like football", "nice one", "God bless you", "hmm hmm"):
        assert not cl.is_question(t), t


def test_should_defer_only_a_cooled_threads_non_question_chat():
    r = _R()
    assert asyncio.run(cl.should_defer(r, "whatsapp", "S", "hmm nice weather", False)) is False
    asyncio.run(cl.cool(r, "whatsapp", "S"))
    assert asyncio.run(cl.should_defer(r, "whatsapp", "S", "hmm nice weather", False)) is True
    assert asyncio.run(cl.should_defer(r, "whatsapp", "S", "ok thanks", False, closer=True)) is False  # the closer gate's
    assert asyncio.run(cl.should_defer(r, "whatsapp", "S", "how much is a stole", False)) is False   # an item
    assert asyncio.run(cl.should_defer(r, "whatsapp", "S", "can you sing?", False)) is False        # a question
    assert asyncio.run(cl.should_defer(r, "whatsapp", "S", "look", True)) is False                  # a photo
    assert asyncio.run(cl.should_defer(None, "whatsapp", "S", "hmm nice weather", False)) is False


def test_the_slow_lane_answers_everything_together_once(monkeypatch):
    import asyncio as _aio
    slept = []

    async def _sleep(s):
        slept.append(s)
    monkeypatch.setattr(_aio, "sleep", _sleep)
    monkeypatch.setattr(settings, "cooling_defer_minutes", 15)
    r = _LaneRedis()
    got = []

    async def runner(text, media):
        got.append((text, media))

    async def main():
        await cl.cool(r, "messenger", "P")                  # a lane only exists on a cooled thread
        assert await cl.slow_lane(r, "messenger", "P", "story one", None, runner)
        assert await cl.slow_lane(r, "messenger", "P", "story two", None, runner)
        assert await cl.slow_lane(r, "messenger", "P", "", {"type": "image", "url": "u"}, runner)
        assert len(cl._LANE_TASKS) == 1                     # one timer per thread
        await _aio.gather(*list(cl._LANE_TASKS))
    _aio.run(main())
    assert got == [("story one\nstory two", {"type": "image", "url": "u"})]
    assert slept == [15 * 60]
    assert not r.lists.get("cool:lane:messenger:P") and "cool:lanelock:messenger:P" not in r.store
    assert _tally(r)["deferred"] == 3
    # a lane whose thread was lifted meanwhile answers nothing twice
    r2 = _LaneRedis()
    got.clear()

    async def main2():
        await cl.slow_lane(r2, "messenger", "Q", "story", None, runner)      # thread not cooled: lifted
        await _aio.gather(*list(cl._LANE_TASKS))
    _aio.run(main2())
    assert got == []


def test_the_schedulers_put_cooled_chat_on_the_slow_lane(monkeypatch):
    import asyncio as _aio

    async def _sleep(s):
        pass
    monkeypatch.setattr(_aio, "sleep", _sleep)
    ran = []

    async def _run(redis, wa_id, text, media=None, *, deferred=False):
        ran.append(("wa", text, deferred))

    async def _run_meta(redis, channel, ext, text, page_id=None, media=None, *, deferred=False):
        ran.append((channel, text, deferred))
        return True

    async def _no(*a, **kw):
        return False
    monkeypatch.setattr(rt, "_run_and_send", _run)
    monkeypatch.setattr(rt, "_run_and_send_meta", _run_meta)
    monkeypatch.setattr(rt, "_is_paused", _no)
    monkeypatch.setattr(rt, "closer_gate", _no)
    r = _LaneRedis()
    asyncio.run(cl.cool(r, "whatsapp", "254700"))
    asyncio.run(cl.cool(r, "messenger", "PS"))

    async def main():
        assert await rt.schedule_reply(r, "254700", "just chatting along", "m1")
        assert await rt.schedule_reply(r, "254700", "and more chatting", "m2")
        assert await rt.schedule_meta_reply(r, "messenger", "PS", "hmm nothing much", "m3")
        assert ran == []                                     # nothing ran at once
        await _aio.gather(*list(cl._LANE_TASKS))
        # a question on a cooled thread goes straight through
        await rt.schedule_reply(r, "254700", "what time do you close?", "m4")
        await _aio.gather(*list(rt._bg_tasks))
    _aio.run(main())
    assert ("wa", "just chatting along\nand more chatting", True) in ran
    assert ("messenger", "hmm nothing much", True) in ran
    assert ("wa", "what time do you close?", False) in ran


def test_a_pleasantry_wearing_an_ask_is_never_a_closer():
    assert rt.is_closer("thanks") and rt.is_closer("God bless") and rt.is_closer("I'll get back to you")
    for t in ("God bless, how much is the stole?", "Welcome, I need a cassock", "thanks, send the link",
              "bye but first the price of the tray"):
        assert not rt.is_closer(t), t
    assert rt.is_closer("ok thanks 🙏")


def test_sheng_and_swahili_buyers_are_read_as_buyers():
    for t in ("nipe bei", "shilingi ngapi", "niko na order", "zawadi ya bishop", "hamper for my pastor",
              "nimetuma pesa", "the fee?"):
        assert cl.buying_signal(t), t


def test_reengage_leaves_a_paced_or_paused_thread_alone():
    import app.jobs.reengage as rj
    conv = types.SimpleNamespace(channel="messenger", wa_id=None, external_id="P1", id="c1")
    msg = types.SimpleNamespace(id="m1", text="hmm so anyway", direction=None)
    r = _R()
    asyncio.run(cl.cool(r, "messenger", "P1"))
    out = asyncio.run(rj._handle(r, conv, msg, send=False))
    assert out["skipped"] == "left alone (paced / paused)"
    r2 = _R()
    r2.store["agent:pause:messenger:P1"] = "1"
    assert asyncio.run(rj._handle(r2, conv, msg, send=False))["skipped"] == "left alone (paced / paused)"


def test_the_prompt_closes_when_they_ask_to_pay_and_serves_gift_buyers():
    p = build_system_prompt(currency="KES")
    assert "IS their yes: call `create_order` in\n  that same reply" in p
    assert 'never a second "are you ready?"' in p
    assert "A GIFT BUYER" in p and "leading with what needs no\n  size" in p


def test_the_agent_pause_lifts_on_a_buying_signal():
    r = _R()
    r.store["agent:pause:whatsapp:254700"] = "1"
    assert asyncio.run(rt._is_paused(r, "whatsapp", "254700")) is True                      # no text: paused
    assert asyncio.run(rt._is_paused(r, "whatsapp", "254700", "lol nice one")) is True       # chat: paused
    assert asyncio.run(rt._is_paused(r, "whatsapp", "254700", "how much is the cassock?")) is False
    assert "agent:pause:whatsapp:254700" not in r.store                                    # lifted for good
    src = inspect.getsource(rt.schedule_reply) + inspect.getsource(rt.schedule_meta_reply)
    assert 'await _is_paused(redis, "whatsapp", wa_id, text)' in src
    assert "await _is_paused(redis, channel, external_id, text)" in src


def test_a_messenger_voice_note_is_the_message(monkeypatch):
    import app.services.meta_media as mm

    async def _heard(url):
        return "nataka kasoki mbili nyeusi" if url == "https://cdn/v.mp4" else None
    monkeypatch.setattr(mm, "transcribe_audio_url", _heard)
    text, media = asyncio.run(rt._hear_voice_note("", {"type": "audio", "url": "https://cdn/v.mp4"}))
    assert text == "nataka kasoki mbili nyeusi" and media is None
    text, media = asyncio.run(rt._hear_voice_note("see", {"type": "audio", "url": "https://cdn/v.mp4"}))
    assert text == "see\nnataka kasoki mbili nyeusi"
    text, media = asyncio.run(rt._hear_voice_note("", {"type": "audio", "url": "https://cdn/none"}))
    assert text == "(the customer sent a voice note)" and media is None      # no backend: the attachment rule
    img = {"type": "image", "url": "u", "caption": ""}
    assert asyncio.run(rt._hear_voice_note("", img)) == ("", img)
    import app.routers.meta_webhook as wh
    assert 'turn_media = {"type": "audio", "url": media_url}' in inspect.getsource(wh)
    assert "text, media = await _hear_voice_note(text, media)" in inspect.getsource(rt._run_and_send_meta)


def test_the_guard_knows_the_hubs_names_and_urgent_buyers_get_a_date_led_reply():
    src = inspect.getsource(rt.run_turn)
    assert "names=_guard_names)" in src and "_svc_g.catalog_items(db, redis)" in src
    p = build_system_prompt(currency="USD")
    assert "A DATE ON THE TABLE (urgent buyers)" in p
    assert "fire `check_availability` for a READY piece in that same turn" in p
    assert "close TODAY" in p and 'Never say "that\'s not possible"' in p
    assert "`schedule_check_in` on the day before their date" in p


def test_a_person_commenting_non_stop_hits_a_daily_budget(monkeypatch):
    monkeypatch.setattr(settings, "meta_comment_person_cap", 3)
    r = _R()
    hits = [asyncio.run(rt._person_over_cap(r, "POST1", "U1")) for _ in range(5)]
    assert hits == [False, False, False, True, True]
    assert asyncio.run(rt._person_over_cap(r, "POST1", "U2")) is False      # another person keeps the model
    assert asyncio.run(rt._person_over_cap(r, "POST2", "U1")) is False      # another post too
    assert asyncio.run(rt._person_over_cap(None, "POST1", "U1")) is False
    src = inspect.getsource(rt)
    assert "or await _person_over_cap(redis, post_id, ext)" in src
    # the free priced path is decided BEFORE the caps, so it never spends them
    i = src.index("free_ask = _trusted and is_bare_price_ask(prompt_text)")
    assert i < src.index("_person_over_cap(redis, post_id, ext)")


# ── the prompt, the tool, health ─────────────────────────────────────────────

def test_the_prompt_paces_without_ever_pacing_a_buyer():
    p = build_system_prompt(currency="KES")
    assert "PACING (owner rule, 2026-09-26" in p
    assert "A buyer is never paced" in p and "never a\n  chase" in p
    assert 'never "you have been chatting too much"' in p
    from app.agent.tools import TOOLS
    pause = next(t for t in TOOLS if t["name"] == "pause_conversation")
    assert "PACING" in pause["description"] and "Never use it on a buying customer" in pause["description"]
    import app.routers.health as health
    assert 'out["cooling"]' in inspect.getsource(health)


def test_the_ladder_has_sensible_defaults():
    assert settings.cooling_enabled is True
    assert settings.cooling_economy_hour < settings.cooling_cool_hour
    assert settings.cooling_economy_day < settings.cooling_cool_day
    assert 1 <= settings.cooling_hours <= 12 and settings.cooling_drift_turns >= 4
    assert settings.meta_comment_person_cap >= 3
