"""The team's reading glass (owner, 2026-08-18): "Let's have a translated copy
just below the text, perhaps in gray … so the human who is following can track
the conversation" — plus the reply-box toggle: "when human types in English,
it translates to that language. Just like how the samsung keyboard does."

The thread with Христина Маркова showed both halves of the problem: she wrote
Bulgarian, Neema answered (sometimes in Bulgarian), and neither side was
readable to the human running the dashboard — nor could that human reply in
Bulgarian themselves.

These tests pin the design's load-bearing choices: heuristics keep
English/Swahili away from the model, one batched light-model call fills a
whole thread, the readable-marker means nothing is ever asked twice, the
daily budget stop silences it entirely, and every failure fails OPEN — a
human's reply is never blocked by the translator that exists to help it.
"""
import asyncio
import json
import types

import app.services.translate as tx
from app.core.config import settings


class _Res:
    def __init__(self, one=None, many=None):
        self._one, self._many = one, many or []

    def scalar_one_or_none(self):
        return self._one

    def scalars(self):
        return types.SimpleNamespace(all=lambda: self._many)

    def all(self):
        return self._many


class _FakeDB:
    def __init__(self, results):
        self._results, self._i = list(results), 0

    async def execute(self, *a, **k):
        r = self._results[self._i]
        self._i += 1
        return r

    async def commit(self):
        self.committed = True


class _Redis:
    def __init__(self, store=None):
        self.kv = dict(store or {})

    async def get(self, k):
        return self.kv.get(k)

    async def set(self, k, v, nx=False, ex=None):
        if nx and k in self.kv:
            return None
        self.kv[k] = v
        return True

    async def delete(self, k):
        self.kv.pop(k, None)

    async def incrbyfloat(self, k, v):
        self.kv[k] = float(self.kv.get(k, 0.0)) + float(v)
        return self.kv[k]

    async def expire(self, k, s):
        return True

    def __getattr__(self, name):
        async def _noop(*a, **kw):
            return None
        return _noop


def _msg(text, translated=None, media_type=None, mid="m1"):
    return types.SimpleNamespace(id=mid, text=text, translated_text=translated,
                                 translated_from=None, media_type=media_type,
                                 created_at=None)


# ── heuristics: what is offered to the translator ────────────────────────────

def test_non_latin_scripts_are_definite_candidates():
    assert tx.needs_translation("Каква е цената")            # Bulgarian
    assert tx.needs_translation("የዋጋውን ያሳውቁኝ")               # Amharic
    assert tx.needs_translation("多少钱")                      # Chinese


def test_english_and_swahili_are_never_offered():
    """The team reads both — translating them is pure noise and pure cost."""
    assert not tx.needs_translation("How much is the aluminium tray please?")
    assert not tx.needs_translation("Bei ngapi kwa sinia na vikombe?")
    assert not tx.needs_translation("Asante sana, Mungu awabariki")
    assert not tx.needs_translation("ok thanks")


def test_ambiguous_latin_text_goes_to_the_model():
    """French/Spanish/Portuguese fail the word lists — the model arbitrates
    (and its 'already readable' verdict is cached, so nothing is asked twice)."""
    assert tx.needs_translation("Quelle est la couleur disponible?")
    assert tx.needs_translation("Cuánto cuesta la bandeja?")


def test_placeholders_links_emoji_and_numbers_have_nothing_to_translate():
    assert not tx.needs_translation("[image]")
    assert not tx.needs_translation("🙏👍")
    assert not tx.needs_translation("https://bethanyhouse.co.ke/product/x")
    assert not tx.needs_translation("+254 785 490 805")
    assert not tx.needs_translation("")
    assert not tx.needs_translation(None)


def test_candidate_filter_excludes_notes_and_done_rows():
    assert tx.is_candidate(_msg("Каква е цената"))
    assert not tx.is_candidate(_msg("Каква е цената", media_type="note"))
    assert not tx.is_candidate(_msg("Каква е цената", translated="What is the price"))


def test_readable_marker_never_renders():
    """A row whose stored translation equals its own text is the 'nothing to
    do' marker — the dashboard must show no gray line for it."""
    assert tx.translation_for(_msg("hello there", translated="hello there")) is None
    assert tx.translation_for(_msg("Каква е цената",
                                   translated="What is the price")) == "What is the price"
    assert tx.translation_for(_msg("plain", translated=None)) is None


def test_model_output_parsing_survives_fences_and_garbage():
    good = [{"i": 0, "lang": "Bulgarian", "en": "How much"}]
    assert tx._parse_items(json.dumps(good)) == good
    assert tx._parse_items("```json\n" + json.dumps(good) + "\n```") == good
    assert tx._parse_items("Sure! Here you go: " + json.dumps(good)) == good
    assert tx._parse_items("I could not process that") == []
    assert tx._parse_items("") == []


# ── the batched thread worker ────────────────────────────────────────────────

def _worker_world(monkeypatch, *, reply_json, rows):
    import app.database as database
    import app.agent.runtime as runtime
    import app.services.n8n_bridge as bridge

    class _Sess:
        def __init__(self):
            self.db = _FakeDB([_Res(many=rows)])

        async def __aenter__(self):
            return self.db

        async def __aexit__(self, *a):
            return False
    monkeypatch.setattr(database, "AsyncSessionLocal", _Sess)

    calls = []

    class _LLM:
        _model = settings.tier2_model_light

        async def complete(self, **kw):
            calls.append(kw)
            return types.SimpleNamespace(
                text=reply_json,
                usage={"input_tokens": 300, "output_tokens": 60,
                       "cache_read_tokens": 0, "cache_write_tokens": 0,
                       "cache_write_1h_tokens": 0})
    monkeypatch.setattr(runtime, "build_llm", lambda model=None: _LLM())

    published = []

    async def _pub(redis, channel, payload):
        published.append((channel, payload))
    monkeypatch.setattr(bridge, "_broadcast", _pub)

    async def _log(db, wa_id, model, totals, node="run_turn"):
        published.append(("usage", node))
        return {"ok": True, "cost_usd": 0.0004}
    monkeypatch.setattr(bridge, "log_agent_usage", _log)
    return calls, published


def test_one_batched_call_fills_the_thread_and_pushes_live(monkeypatch):
    m1 = _msg("Каква е цената", mid="a1")
    m2 = _msg("Merci beaucoup mon frère", mid="a2")
    reply = json.dumps([
        {"i": 0, "lang": "Bulgarian", "en": "What is the price"},
        {"i": 1, "lang": "French", "en": "Thank you very much my brother"},
    ])
    calls, published = _worker_world(monkeypatch, reply_json=reply, rows=[m1, m2])
    r = _Redis()
    n = asyncio.run(tx._translate_thread(r, "conv9", ["a1", "a2"]))
    assert n == 2 and len(calls) == 1, "must be ONE model call for the whole batch"
    assert m1.translated_text == "What is the price"
    assert m1.translated_from == "Bulgarian"
    ws = [p for p in published if p[0] == "conv9"]
    assert ws and ws[0][1]["type"] == "translations"
    assert {i["id"] for i in ws[0][1]["items"]} == {"a1", "a2"}
    assert ("usage", "translate") in published          # metered under its own node
    assert "translate:lock:conv9" not in r.kv           # lock released


def test_already_readable_verdict_is_cached_as_the_marker(monkeypatch):
    """en:"" from the model = readable as-is → the row stores its own text so
    it is NEVER offered again, and no gray line ever renders for it."""
    m = _msg("Bruno Nion", mid="b1")
    reply = json.dumps([{"i": 0, "lang": "English", "en": ""}])
    _worker_world(monkeypatch, reply_json=reply, rows=[m])
    n = asyncio.run(tx._translate_thread(_Redis(), "conv1", ["b1"]))
    assert n == 0
    assert m.translated_text == m.text
    assert not tx.is_candidate(m)
    assert tx.translation_for(m) is None


def test_the_daily_budget_stop_silences_the_translator(monkeypatch):
    from app.services import ai_budget
    m = _msg("Каква е цената", mid="c1")
    calls, _ = _worker_world(monkeypatch, reply_json="[]", rows=[m])
    r = _Redis({ai_budget._day_key(): "99.0"})
    assert asyncio.run(tx._translate_thread(r, "conv2", ["c1"])) == 0
    assert not calls, "translation bought tokens past the daily stop"


def test_a_broken_answer_cools_down_instead_of_re_burning(monkeypatch):
    m = _msg("Каква е цената", mid="d1")
    calls, _ = _worker_world(monkeypatch, reply_json="not json at all", rows=[m])
    r = _Redis()
    assert asyncio.run(tx._translate_thread(r, "conv3", ["d1"])) == 0
    assert m.translated_text is None
    assert "translate:cool:conv3" in r.kv, "no cooldown — every re-open would re-buy the miss"
    # and while cooling, nothing is attempted at all
    assert asyncio.run(tx._translate_thread(r, "conv3", ["d1"])) == 0
    assert len(calls) == 1


# ── the reply box's outbound direction ───────────────────────────────────────

def test_target_language_prefers_the_threads_cached_detection():
    db = _FakeDB([_Res(many=[(None, "ok thanks"), ("Bulgarian", "Каква е цената")])])
    lang, sample = asyncio.run(tx.target_language(db, "conv"))
    assert lang == "Bulgarian" and sample is None


def test_target_language_falls_back_to_a_foreign_sample():
    db = _FakeDB([_Res(many=[(None, "Каква е цената"), (None, "[image]")])])
    lang, sample = asyncio.run(tx.target_language(db, "conv"))
    assert lang is None and sample == "Каква е цената"


def test_reply_is_translated_into_the_customers_language(monkeypatch):
    import app.agent.runtime as runtime

    class _LLM:
        _model = settings.tier2_model_light

        async def complete(self, **kw):
            return types.SimpleNamespace(
                text=json.dumps({"lang": "Bulgarian",
                                 "text": "Благодарим ви — подносът е $70."}),
                usage={})
    monkeypatch.setattr(runtime, "build_llm", lambda model=None: _LLM())
    db = _FakeDB([_Res(many=[("Bulgarian", "Каква е цената")])])
    out = asyncio.run(tx.translate_reply(db, _Redis(), "conv",
                                         "Thank you — the tray is $70."))
    assert out["text"].startswith("Благодарим") and out["lang"] == "Bulgarian"


def test_an_english_thread_sends_english_untouched(monkeypatch):
    import app.agent.runtime as runtime
    monkeypatch.setattr(runtime, "build_llm",
                        lambda model=None: (_ for _ in ()).throw(AssertionError("model called")))
    db = _FakeDB([_Res(many=[(None, "how much is it"), (None, "ok thanks")])])
    out = asyncio.run(tx.translate_reply(db, _Redis(), "conv", "It is $70."))
    assert out == {"text": "It is $70.", "lang": None}


def test_reply_translation_fails_open_never_blocking_the_human(monkeypatch):
    import app.agent.runtime as runtime

    class _Boom:
        _model = settings.tier2_model_light

        async def complete(self, **kw):
            raise RuntimeError("model down")
    monkeypatch.setattr(runtime, "build_llm", lambda model=None: _Boom())
    db = _FakeDB([_Res(many=[("Bulgarian", "Каква е цената")])])
    out = asyncio.run(tx.translate_reply(db, _Redis(), "conv", "It is $70."))
    assert out["text"] == "It is $70."      # the English still goes out
    # and past the daily stop it doesn't even try
    from app.services import ai_budget
    out2 = asyncio.run(tx.translate_reply(_FakeDB([]), _Redis({ai_budget._day_key(): "99"}),
                                          "conv", "It is $70."))
    assert out2["text"] == "It is $70."


def test_the_thread_serializer_would_show_the_sent_reply_in_reverse():
    """Toggle path: `text` = Bulgarian actually sent, translated_text = the
    human's English — the same gray line then reads the sale back later."""
    m = _msg("Благодарим ви — подносът е $70.",
             translated="Thank you — the tray is $70.")
    assert tx.translation_for(m) == "Thank you — the tray is $70."
