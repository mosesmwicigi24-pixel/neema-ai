"""A genuine question in ANY language must never be silently dropped.

The classifier's four buckets used to be: high = BUYING interest, low = "no
question", negative = complaint, spam = "unrelated". A real non-buying question
("Vous residez où", "Bethany House kenya je") fitted no bucket and fell into
`spam` by elimination — and spam means total silence with nothing recorded. These
tests pin the widened taxonomy, the language rule, and the visible-silence note.
"""
import asyncio
import types

import app.main  # noqa: F401 — registers models
import app.agent.runtime as rt


class _CapturingLLM:
    """Records the classifier prompt and returns a scripted label."""
    def __init__(self, label="high"):
        self.label, self.prompt, self.system = label, "", ""

    async def complete(self, *, system, messages, tools):
        self.system = system
        self.prompt = messages[0]["content"]
        return types.SimpleNamespace(text=self.label, tool_calls=[],
                                     assistant_content=[], usage={})


def _prompt_for(text, monkeypatch, label="high"):
    llm = _CapturingLLM(label)
    monkeypatch.setattr(rt, "build_llm", lambda model=None: llm)
    out = asyncio.run(rt.classify_comment_intent(text))
    return llm.prompt, out


# ── the taxonomy hole is closed ───────────────────────────────────────────────

def test_high_covers_any_genuine_question_not_only_price(monkeypatch):
    prompt, _ = _prompt_for("Vous residez où", monkeypatch)
    assert "any genuine question" in prompt
    # the non-buying questions that used to fall through must be named explicitly
    for cue in ("where you are located", "delivery", "opening hours"):
        assert cue in prompt


def test_spam_is_narrowed_to_actual_spam(monkeypatch):
    prompt, _ = _prompt_for("check my page", monkeypatch)
    assert "spam: ONLY bots, ads, promotional links, or abuse" in prompt
    assert "or unrelated" not in prompt        # the old catch-all is gone


def test_non_english_is_never_spam_by_language(monkeypatch):
    prompt, _ = _prompt_for("Bethany House kenya je", monkeypatch)
    assert "is NOT spam" in prompt
    assert "Never answer 'spam' merely because it isn't English" in prompt
    # the languages we actually receive are named so the light model anchors on them
    for lang in ("French", "Swahili", "Chinese"):
        assert lang in prompt


def test_scripted_labels_still_pass_through_and_empty_is_low(monkeypatch):
    _, out = _prompt_for("how much is the mitre?", monkeypatch, label="high")
    assert out == "high"
    _, out = _prompt_for("amen 🙏", monkeypatch, label="low")
    assert out == "low"
    # an unparseable answer still errs toward engaging, never silence
    _, out = _prompt_for("anything", monkeypatch, label="banana")
    assert out == "high"
    assert asyncio.run(rt.classify_comment_intent("   ")) == "low"   # no LLM call


# ── the public reply answers what was asked, in their language ────────────────

def test_public_comment_addendum_answers_the_real_question_in_their_language():
    add = rt._public_comment_addendum("KES")
    assert "ANSWER THE QUESTION THEY ACTUALLY ASKED" in add
    assert "SAME language" in add
    assert "Never answer a French or Swahili comment in English" in add


# ── deliberate silence is visible to the team ────────────────────────────────

def test_silent_decision_writes_an_internal_note(monkeypatch):
    from app.models.message import Message, MsgDirection

    added = []

    class _DB:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def execute(self, *a, **k):
            conv = types.SimpleNamespace(id="c1", person_id=None)
            return types.SimpleNamespace(scalar_one_or_none=lambda: conv)
        def add(self, o): added.append(o)
        async def commit(self): pass

    monkeypatch.setattr(rt, "AsyncSessionLocal", lambda: _DB(), raising=False)
    monkeypatch.setattr("app.database.AsyncSessionLocal", lambda: _DB())

    asyncio.run(rt._note_silent_decision("facebook", "FBID", "CID1", "spam"))

    assert len(added) == 1
    note = added[0]
    assert isinstance(note, Message)
    assert note.media_type == "note"                  # internal — not sent anywhere
    assert note.direction == MsgDirection.outbound
    assert "did not reply" in (note.text or "")
    assert "spam" in (note.text or "")                # the reason is visible


def test_note_helper_takes_no_redis():
    """It must not accept an unused redis arg (and must never broadcast — a pushed
    note would render as a real reply, since the socket payload has no isNote)."""
    import inspect
    params = list(inspect.signature(rt._note_silent_decision).parameters)
    assert params == ["channel", "ext", "cid", "intent"]
