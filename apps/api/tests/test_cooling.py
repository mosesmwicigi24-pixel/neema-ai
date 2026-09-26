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


def test_a_chatter_gets_briefer_then_one_warm_close_then_silence(monkeypatch):
    _not_in_play(monkeypatch)
    monkeypatch.setattr(settings, "cooling_economy_hour", 10)
    monkeypatch.setattr(settings, "cooling_cool_hour", 20)
    monkeypatch.setattr(settings, "cooling_drift_turns", 50)     # only the count matters here
    r = _R()
    out = []
    for i in range(24):
        v = asyncio.run(cl.decide(r, None, channel="whatsapp", key="254700", text=f"tell me story number {i} about yourself"))
        out.append(v["action"] if v else None)
    assert out[:2] == [None, None]                       # two full turns of pure chat
    assert out[2:20] == ["economy"] * 18                 # then briefer, on the light model
    assert out[20] == "cool"                             # past the hourly line: the one warm close
    assert out[21:] == ["silence"] * 3                   # then nothing
    v = asyncio.run(cl.decide(r, None, channel="whatsapp", key="254700", text="tell me story number 5 about yourself"))
    assert v["action"] == "silence"
    t = _tally(r)
    assert t["economy"] == 18 and t["cooled"] == 1 and t["silenced"] >= 3
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


def test_business_in_play_keeps_the_thread_warm_whatever_the_count(monkeypatch):
    _not_in_play(monkeypatch, True)
    monkeypatch.setattr(settings, "cooling_cool_hour", 3)
    monkeypatch.setattr(settings, "cooling_economy_hour", 2)
    r = _R()
    acts = [(asyncio.run(cl.decide(r, None, channel="messenger", key="P1", text=f"and another thing number {i}")) or {}).get("action")
            for i in range(8)]
    assert "cool" not in acts and "silence" not in acts
    assert acts[2:] == ["economy"] * 6                  # briefer, never cut off


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
    for i in range(6):
        v = asyncio.run(cl.decide(r, None, channel="instagram", key="U", text=f"do you like football number {i}"))
        acts.append((v or {}).get("action"))
    assert acts == [None, None, "economy", "economy", "cool", "silence"]
    # a product word resets the drift: the sale stays warm
    r2 = _R()
    for i in range(4):
        asyncio.run(cl.decide(r2, None, channel="instagram", key="U", text=f"blah blah number {i}"))
    assert asyncio.run(cl.decide(r2, None, channel="instagram", key="U", text="what about a stole then")) is None
    assert r2.store.get("cool:drift:instagram:U") is None


def test_the_same_words_within_minutes_are_not_a_new_turn(monkeypatch):
    _not_in_play(monkeypatch)
    r = _R()
    assert asyncio.run(cl.decide(r, None, channel="whatsapp", key="K", text="Did you get my message about the delivery")) is None
    v = asyncio.run(cl.decide(r, None, channel="whatsapp", key="K", text="did you get my message about the delivery"))
    assert v == {"action": "silence", "why": "duplicate"} and _tally(r)["duplicate"] == 1
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
    for i in range(30):
        assert asyncio.run(cl.decide(r, None, channel="whatsapp", key="C", text=f"story {i} of my life")) is None
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
        return {"action": "silence", "why": "cooled"}
    monkeypatch.setattr(cl, "decide", _silent)
    facts = {}
    assert asyncio.run(rt.run_turn(_db(), _R(), "254700000001", "another story", _LLM(), turn_facts=facts)) == ""
    assert not calls and facts["pacing"] == "cooled"


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
    assert "if not read_only and not scribe_only and not public_comment:" in src[i - 200:i]
    # read before any token is bought, after the church-goods guard
    assert src.index("_dom.guard_turn(") < i < src.index("for _ in range(_max_iter):")


# ── comments: a per-person daily budget beside the per-post one ─────────────

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
