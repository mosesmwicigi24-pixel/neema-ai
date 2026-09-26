"""COST CYCLE (owner, 2026-09-26: "heightened expenditure for a few days").

Every cut here removes a model call, a cache write or a re-read that bought
nothing — never a check that protects the customer. Each test pins the
mechanism, so a refactor that quietly re-inflates the bill fails here."""
import asyncio
import inspect
import json
import types
from datetime import datetime, timedelta, timezone

import app.agent.runtime as runtime
import app.agent.review as review
import app.agent.llm as llm_mod
from app.agent.prompt import build_system_prompt, customer_context
from app.core.config import settings


class _Redis:
    """Enough of redis for the paths under test — strings, counters, lists."""
    def __init__(self, kv=None):
        self.kv = dict(kv or {})
        self.lists: dict[str, list] = {}

    async def get(self, k):
        return self.kv.get(k)

    async def set(self, k, v, ex=None, nx=False):
        if nx and k in self.kv:
            return False
        self.kv[k] = v
        return True

    async def incr(self, k):
        self.kv[k] = int(self.kv.get(k, 0)) + 1
        return self.kv[k]

    async def expire(self, k, s):
        return True

    async def delete(self, k):
        self.kv.pop(k, None)
        self.lists.pop(k, None)
        return 1

    async def rpush(self, k, v):
        self.lists.setdefault(k, []).append(v)
        return len(self.lists[k])

    async def lrange(self, k, a, b):
        return list(self.lists.get(k, []))

    async def hincrby(self, k, f, n):
        return n


class _Resp:
    def __init__(self, text="", usage=None):
        self.text, self.tool_calls, self.assistant_content = text, [], []
        self.usage = usage or {}


# ── C1: the rewrite rides the loop's own cache ──────────────────────────────

def test_rewrite_is_sent_with_the_loops_tools_and_no_tool_choice(monkeypatch):
    """The gate's rewrite used to go out with `tools=[]`: a different prefix
    from the loop's, so the whole rules block was written cold again for one
    call. Now it carries the SAME tools (prefix identical → read, not
    written), `tool_choice="none"` keeps the answer in words, and the call is
    metered as its own purpose."""
    calls = []

    class _LLM:
        purpose = "whatsapp"

        async def complete(self, *, system, messages, tools, tool_choice=None):
            calls.append({"tools": tools, "tool_choice": tool_choice,
                          "purpose": self.purpose, "messages": messages})
            return _Resp("The cassock is $120 — shall I take your order?")

    verdicts = iter([
        {"ok": False, "issues": ["the reviewer rejected the draft"], "hard": [],
         "soft": ["the reviewer rejected the draft"], "by": "reviewer"},
        {"ok": True, "issues": [], "hard": [], "soft": [], "by": "reviewer"},
    ])

    async def _review(*a, **kw):
        return next(verdicts)

    async def _facts(*a, **kw):
        return []
    monkeypatch.setattr(review, "review_reply", _review)
    monkeypatch.setattr(runtime, "_facts_for_ask", _facts)
    tools = [{"name": "search_catalog", "input_schema": {}}, {"name": "create_order", "input_schema": {}}]
    ctx = types.SimpleNamespace(seen_products=[{"name": "Cassock", "price": 120}])
    llm = _LLM()
    out, held, outcome = asyncio.run(runtime._gate_turn_reply(
        "The cassock is 120.", user_text="how much is the cassock?", transcript=[
            {"role": "user", "content": "how much is the cassock?"}],
        tool_log=[], ctx=ctx, currency="USD", channel="whatsapp", public_comment=False,
        llm=llm, sys_blocks=["RULES", "THIS CUSTOMER"], redis=None, db=None, key="k",
        tools=tools))
    assert outcome == "rewritten" and out.startswith("The cassock is $120")
    assert len(calls) == 1
    assert calls[0]["tools"] == tools                 # the loop's list, verbatim
    assert calls[0]["tool_choice"] == "none"
    assert calls[0]["purpose"] == "rewrite"           # metered on its own line
    assert llm.purpose == "whatsapp"                  # and restored after
    # the transcript the writer saw, then the draft, then the reviewer's block
    roles = [m["role"] for m in calls[0]["messages"]]
    assert roles == ["user", "assistant", "user"]


def test_rewrite_without_tools_sends_no_tool_choice(monkeypatch):
    """A caller with no tools (tests, a scribe) gets the old shape: no
    tool_choice keyword at all, so simple doubles keep working."""
    calls = []

    class _LLM:
        async def complete(self, *, system, messages, tools, **kw):
            calls.append(dict(kw, tools=tools))
            return _Resp("Karibu sana.")

    verdicts = iter([
        {"ok": False, "issues": ["x"], "hard": [], "soft": ["x"], "by": "reviewer"},
        {"ok": True, "issues": [], "hard": [], "soft": [], "by": "reviewer"},
    ])

    async def _review(*a, **kw):
        return next(verdicts)

    async def _facts(*a, **kw):
        return []
    monkeypatch.setattr(review, "review_reply", _review)
    monkeypatch.setattr(runtime, "_facts_for_ask", _facts)
    ctx = types.SimpleNamespace(seen_products=[])
    asyncio.run(runtime._gate_turn_reply(
        "Karibu.", user_text="habari", transcript=[], tool_log=[], ctx=ctx, currency="KES",
        channel="whatsapp", public_comment=False, llm=_LLM(), sys_blocks="RULES",
        redis=None, db=None, key="k"))
    assert calls and calls[0]["tools"] == [] and "tool_choice" not in calls[0]


def test_run_turn_hands_the_gate_its_tools():
    src = inspect.getsource(runtime.run_turn)
    assert "tools=tools," in src.split("_gate_turn_reply(")[1][:900]
    assert 'greeting=bool(_GREETING_RE.match(' in src


def test_anthropic_client_sends_tool_choice_none_only_when_tools_are_present():
    sent = []

    class _Msgs:
        async def create(self, **kw):
            sent.append(kw)
            return types.SimpleNamespace(content=[], stop_reason="end_turn",
                                         usage=types.SimpleNamespace(
                                             input_tokens=1, output_tokens=1,
                                             cache_read_input_tokens=0,
                                             cache_creation_input_tokens=0,
                                             cache_creation=None))
    llm = object.__new__(llm_mod.AnthropicLLM)
    llm._client = types.SimpleNamespace(messages=_Msgs())
    llm._model, llm._max_tokens, llm._cache, llm.purpose = "claude-sonnet-5", 64, True, "t"
    tools = [{"name": "search_catalog", "input_schema": {"type": "object"}}]
    asyncio.run(llm.complete(system=["RULES", "TAIL"], messages=[{"role": "user", "content": "hi"}],
                             tools=tools, tool_choice="none"))
    assert sent[0]["tool_choice"] == {"type": "none"} and sent[0]["tools"] == tools
    asyncio.run(llm.complete(system="S", messages=[{"role": "user", "content": "hi"}],
                             tools=[], tool_choice="none"))
    assert "tool_choice" not in sent[1]               # nothing to forbid
    asyncio.run(llm.complete(system="S", messages=[{"role": "user", "content": "hi"}],
                             tools=tools))
    assert "tool_choice" not in sent[2]               # the loop's calls are untouched


# ── C4: one-off prompts carry no cache breakpoint; plain turns skip the model ─

def test_one_off_calls_go_out_uncached(monkeypatch):
    monkeypatch.setattr(settings, "tier2_prompt_cache", True)
    assert runtime.build_llm()._cache is True
    assert runtime.build_llm(cache=False)._cache is False
    assert runtime.build_llm(cache=True)._cache is True
    monkeypatch.setattr(settings, "tier2_prompt_cache", False)
    assert runtime.build_llm(cache=True)._cache is False   # the master switch still wins
    # every prompt nothing will read again
    import app.services.translate as translate
    import app.services.post_catalog as post_catalog
    import app.jobs.self_qa as self_qa
    import app.services.call_transcribe as calls
    assert 'purpose="reviewer", cache=False' in inspect.getsource(review.reviewer_verdict)
    assert 'purpose="comment-read", cache=False' in inspect.getsource(runtime.read_comment)
    assert 'purpose="vision", cache=False' in inspect.getsource(runtime._describe_post_image)
    assert 'purpose="vision", cache=False' in inspect.getsource(post_catalog.product_from_vision)
    assert inspect.getsource(translate).count('purpose="translate", cache=False') == 2
    assert 'purpose="job:self-qa", cache=False' in inspect.getsource(self_qa.distill_weekly)
    assert 'purpose="calls", cache=False' in inspect.getsource(calls)


def test_plain_draft_is_words_alone():
    assert review.plain_draft("You're welcome, Pastor. God bless!", [])
    assert review.plain_draft("Karibu sana — tuko hapa kukuhudumia.", [])
    assert not review.plain_draft("The cassock is $120.", [])          # a figure
    assert not review.plain_draft("It goes for 4500.", [])             # a bare number
    assert not review.plain_draft("Here: https://neema.example/o/AB12", [])
    assert not review.plain_draft("Your order is on its way.", [])     # a status word
    assert not review.plain_draft("Pay by M-Pesa.", [])                # payment words
    assert not review.plain_draft("You're welcome!", [{"name": "Cassock"}])   # a row in hand


def test_review_reply_can_run_the_rules_alone(monkeypatch):
    called = []

    async def _rv(*a, **kw):
        called.append(1)
        return {"ok": False, "issues": ["model said no"]}
    monkeypatch.setattr(review, "reviewer_verdict", _rv)
    v = asyncio.run(review.review_reply("thanks", "You're welcome!", [], model_review=False,
                                        mode="dm"))
    assert v["ok"] and not called
    v = asyncio.run(review.review_reply("thanks", "You're welcome!", [], mode="dm"))
    assert called and not v["ok"]                       # the default still asks the model


def test_gate_skips_the_model_reviewer_on_a_plain_greeting_or_closer(monkeypatch):
    seen_kw = []

    async def _review(*a, **kw):
        seen_kw.append(kw)
        return {"ok": True, "issues": [], "hard": [], "soft": [], "by": "rules"}
    monkeypatch.setattr(review, "review_reply", _review)
    ctx = types.SimpleNamespace(seen_products=[])
    base = dict(transcript=[], tool_log=[], ctx=ctx, currency="KES", channel="whatsapp",
                public_comment=False, llm=None, sys_blocks="R", redis=None, db=None, key="k")
    asyncio.run(runtime._gate_turn_reply("Good morning! Welcome to Bethany House — what may I "
                                         "help you with today?", user_text="Hi",
                                         greeting=True, **base))
    assert seen_kw[-1]["model_review"] is False
    asyncio.run(runtime._gate_turn_reply("You're most welcome, Pastor. God bless.",
                                         user_text="thanks", closer=True, **base))
    assert seen_kw[-1]["model_review"] is False
    # a greeting answered WITH a figure is a money turn: the reviewer reads it
    asyncio.run(runtime._gate_turn_reply("Good morning! Cassocks start at KES 4,500.",
                                         user_text="Hi", greeting=True, **base))
    assert seen_kw[-1]["model_review"] is True
    # an ordinary question is always read twice
    asyncio.run(runtime._gate_turn_reply("We are in Nairobi, along Tom Mboya Street.",
                                         user_text="where are you located?", **base))
    assert seen_kw[-1]["model_review"] is True


# ── C5: deliberate silence is not a missed reply ─────────────────────────────

def test_silence_is_marked_and_read_back():
    r = _Redis()
    before = datetime.now(timezone.utc) - timedelta(seconds=1)
    asyncio.run(runtime._mark_silenced(r, "messenger", "P1"))
    t = asyncio.run(runtime.silenced_since(r, "messenger", "P1"))
    assert t is not None and t.tzinfo is not None and t >= before
    assert asyncio.run(runtime.silenced_since(r, "messenger", "P2")) is None
    r.kv["agent:missed:silenced:messenger:P3"] = b"2026-09-26T10:00:00+00:00"
    assert asyncio.run(runtime.silenced_since(r, "messenger", "P3")).hour == 10
    assert asyncio.run(runtime.silenced_since(None, "messenger", "P1")) is None
    for fn in (runtime._run_and_send_meta,):
        src = inspect.getsource(fn)
        assert src.count("await _mark_silenced(redis, channel, external_id)") == 2


def _sweep_sessions(created_at):
    from app.models.message import MsgDirection
    msg = types.SimpleNamespace(id=7, text="is the cassock still available?", media_type=None, media_url=None,
                                external_id="psid1", created_at=created_at)
    conv = types.SimpleNamespace(channel="messenger", wa_id=None, external_id="psid1",
                                 person_id=None)

    class _Res:
        def __init__(self, one=None, many=None):
            self._one, self._many = one, many or []

        def all(self):
            return self._many

        def scalar_one_or_none(self):
            return self._one

    class _DB:
        def __init__(self, results):
            self._r = list(results)

        async def execute(self, *a, **k):
            return self._r.pop(0)

    sessions = [_DB([_Res(many=[(msg, conv)])]),
                _DB([_Res(one=MsgDirection.inbound), _Res(one=None)])]

    class _Sess:
        def __init__(self):
            self.db = sessions.pop(0)

        async def __aenter__(self):
            return self.db

        async def __aexit__(self, *a):
            return False
    return _Sess


def test_sweeper_leaves_a_thread_that_was_silenced_on_purpose(monkeypatch):
    import app.services.reply_sweeper as sweeper
    ran = []

    async def _run(*a, **kw):
        ran.append(a)
        return True

    async def _not_paused(*a, **kw):
        return False
    monkeypatch.setattr(runtime, "_run_and_send_meta", _run)
    monkeypatch.setattr(runtime, "_is_paused", _not_paused)
    inbound_at = datetime.now(timezone.utc) - timedelta(minutes=10)
    # silenced AFTER the inbound arrived → the turn ran and chose silence
    monkeypatch.setattr(sweeper, "AsyncSessionLocal", _sweep_sessions(inbound_at))
    r = _Redis({"agent:missed:silenced:messenger:psid1":
                (inbound_at + timedelta(seconds=20)).isoformat()})
    assert asyncio.run(sweeper.sweep_missed_replies(r)) == 0 and not ran
    assert "agent:missed:tries:7" not in r.kv        # no strike burned either
    # silenced BEFORE this inbound → a new message, a real miss: answered
    monkeypatch.setattr(sweeper, "AsyncSessionLocal", _sweep_sessions(inbound_at))
    r = _Redis({"agent:missed:silenced:messenger:psid1":
                (inbound_at - timedelta(minutes=5)).isoformat()})
    assert asyncio.run(sweeper.sweep_missed_replies(r)) == 1 and len(ran) == 1
    # a naive DB timestamp is read as UTC
    monkeypatch.setattr(sweeper, "AsyncSessionLocal",
                        _sweep_sessions(inbound_at.replace(tzinfo=None)))
    r = _Redis({"agent:missed:silenced:messenger:psid1":
                (inbound_at + timedelta(seconds=20)).isoformat()})
    assert asyncio.run(sweeper.sweep_missed_replies(r)) == 0 and len(ran) == 1


# ── C6: a post's photo is described once, identified posts send no image ─────

def test_post_photo_is_described_once_a_day(monkeypatch):
    r = _Redis()
    assert asyncio.run(runtime._may_describe(r, "facebook", "P1")) is True
    assert asyncio.run(runtime._may_describe(r, "facebook", "P1")) is False
    assert asyncio.run(runtime._may_describe(r, "facebook", "P2")) is True
    assert asyncio.run(runtime._may_describe(None, "facebook", "P1")) is True
    looks = []

    async def _describe(thumb):
        looks.append(thumb)
        return ""                                   # the model could not say

    async def _recall(redis, channel, post_id):
        return {}
    monkeypatch.setattr(runtime, "_describe_post_image", _describe)
    monkeypatch.setattr(runtime, "_recall_post_product", _recall)
    r = _Redis()
    for _ in range(3):
        asyncio.run(runtime._remember_post_product(r, "facebook", "P9",
                                                   {"name": "Cassock", "slug": "cassock"},
                                                   thumb="https://cdn/x.jpg"))
    assert len(looks) == 1, "three comments under one post bought three failed looks"
    rec = json.loads(r.kv[runtime._post_product_key("facebook", "P9")])
    assert rec["name"] == "Cassock"


def test_identified_post_sends_no_image_and_ladder_retries_four_times_a_day():
    src = inspect.getsource(runtime.run_turn)
    attach = src.split('if (settings.tier2_vision and not img_block and pctx.get("thumb")')[1][:400]
    assert "and not identity_trusted_record(_known)" in attach
    assert "ex=6 * 3600" in inspect.getsource(runtime._post_identity)


# ── C2: a burst of Meta DMs is one turn ─────────────────────────────────────

def test_meta_burst_is_answered_once_together(monkeypatch):
    import app.services.meta_send as meta_send
    ran, slept, typed = [], [], []

    async def _run(redis, channel, ext, text, page_id=None, media=None):
        ran.append((channel, ext, text, media))
        return True

    async def _sleep(s):
        slept.append(s)

    async def _typing(ext, page_id=None):
        typed.append(ext)

    async def _no(*a, **kw):
        return False
    monkeypatch.setattr(runtime, "_run_and_send_meta", _run)
    monkeypatch.setattr(runtime.asyncio, "sleep", _sleep)
    monkeypatch.setattr(meta_send, "send_typing_on", _typing)
    monkeypatch.setattr(runtime, "_is_paused", _no)
    monkeypatch.setattr(runtime, "closer_gate", _no)
    monkeypatch.setattr(settings, "meta_debounce_seconds", 12)
    r = _Redis()

    async def main():
        ok1 = await runtime.schedule_meta_reply(r, "messenger", "PSID", "Hi", "m1", page_id="pg")
        ok2 = await runtime.schedule_meta_reply(r, "messenger", "PSID", "I want a cassock", "m2",
                                                page_id="pg")
        ok3 = await runtime.schedule_meta_reply(r, "messenger", "PSID", "black", "m3", page_id="pg")
        await asyncio.gather(*list(runtime._bg_tasks))
        return ok1, ok2, ok3
    assert asyncio.run(main()) == (True, True, True)
    assert len(ran) == 1, "three messages in a burst became %d turns" % len(ran)
    assert ran[0][2] == "Hi\nI want a cassock\nblack" and ran[0][0] == "messenger"
    assert slept and all(s == 12 for s in slept)     # the window, per message
    assert typed == ["PSID"] * 3                      # "typing…" from the first second
    assert not r.lists.get("agent:burst:buf:messenger:PSID")   # drained


def test_meta_burst_prefers_the_photo_and_survives_no_redis(monkeypatch):
    ran = []

    async def _run(redis, channel, ext, text, page_id=None, media=None):
        ran.append((text, media))
        return True

    async def _sleep(s):
        pass
    monkeypatch.setattr(runtime, "_run_and_send_meta", _run)
    monkeypatch.setattr(runtime.asyncio, "sleep", _sleep)
    monkeypatch.setattr(settings, "meta_debounce_seconds", 12)
    r = _Redis()
    img = {"type": "image", "url": "https://cdn/p.jpg", "caption": ""}
    asyncio.run(runtime._meta_enqueue(r, "instagram", "U", "this one", None))
    tok = asyncio.run(runtime._meta_enqueue(r, "instagram", "U", "", img))
    assert asyncio.run(runtime._run_meta_after_burst(r, "instagram", "U", "", "pg", img, 1)) is False
    assert not ran                                     # superseded flush stays quiet
    assert asyncio.run(runtime._run_meta_after_burst(r, "instagram", "U", "", "pg", img, tok)) is True
    assert ran == [("this one", img)]
    # no redis → no buffer → answered now, unchanged
    assert asyncio.run(runtime._meta_enqueue(None, "instagram", "U", "x", None)) is None
    assert asyncio.run(runtime._run_meta_after_burst(None, "instagram", "U", "x", None, None, None)) is True
    assert ran[-1] == ("x", None)
    # the window can be switched off
    monkeypatch.setattr(settings, "meta_debounce_seconds", 0)
    assert asyncio.run(runtime._meta_enqueue(r, "instagram", "U", "x", None)) is None


# ── the comment reader, the clock, the comment's post, compact tool rows ─────

def test_bare_price_ask_is_read_without_a_model(monkeypatch):
    def _no_build(model=None, **kw):
        raise AssertionError("a bare price ask reached the model")
    monkeypatch.setattr(runtime, "build_llm", _no_build)
    for t in ("How much?", "how much is it", "Bei?", "bei gani", "Price please", "ngapi?"):
        r = asyncio.run(runtime.read_comment(t))
        assert (r["intent"], r["kind"], r["ask"]) == ("high", "question", "price"), t


def test_the_clock_lives_in_the_tail_not_the_shared_block(monkeypatch):
    import app.agent.prompt as prompt
    monkeypatch.setattr(prompt, "_nairobi_daypart", lambda: "morning")
    a = build_system_prompt(currency="KES")
    monkeypatch.setattr(prompt, "_nairobi_daypart", lambda: "evening")
    b = build_system_prompt(currency="KES")
    assert a == b, "the shared block still changes with the time of day"
    assert "THE CLOCK" in a and "under\n  THIS CUSTOMER" in a
    assert "TIME MATHS FROM TODAY" in a
    tail = customer_context("Pastor Moses", "Kenya", clock=True)
    assert "It is evening in Nairobi right now — today is" in tail
    assert tail.index("You are speaking with") < tail.index("It is evening")
    assert customer_context("", "") == ""              # unchanged for callers without the clock
    assert customer_context("", "", clock=True).startswith("THIS CUSTOMER\n- It is ")
    assert "clock=True" in inspect.getsource(runtime.run_turn)


def test_a_comment_turn_is_about_the_post_it_is_under_and_tool_rows_are_compact():
    src = inspect.getsource(runtime.run_turn)
    assert 'if public_comment and comment_post_id:' in src
    assert 'source_post = {"post_id": str(comment_post_id), "comment": ""}' in src
    assert 'json.dumps(out, ensure_ascii=False, separators=(",", ":"))' in src
    assert json.dumps({"name": "Cassock — Black", "price": 4500}, ensure_ascii=False,
                      separators=(",", ":")) == '{"name":"Cassock — Black","price":4500}'


def test_meta_debounce_setting_exists_with_a_short_window():
    assert 0 < settings.meta_debounce_seconds < settings.whatsapp_debounce_seconds
