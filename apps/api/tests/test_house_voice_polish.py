"""The Sunday house voice keeps re-learning from the team's replies, and now
corrects their grammar (owner, 2026-11-05) — every figure, name and the
length exactly as the team wrote them."""
import asyncio
import types

import app.main  # noqa: F401 — registers models
from app.tools import stylebook as sb

EX = [{"q": "how much is collar shirt", "a": "the roman collar shirt goes for 2500 and we have white n black", "kind": "price"},
      {"q": "mko wapi", "a": "Tuko Sonalux building 7th floor room 18 moi avenue", "kind": "location"},
      {"q": "do u deliver", "a": "yes we deliver countrywide via g4s at 350", "kind": "delivery"}]


class _LLM:
    def __init__(self, text):
        self.text, self.calls = text, 0

    async def complete(self, system, messages, tools=()):
        self.calls += 1
        assert "Correct ONLY spelling, grammar and punctuation" in messages[0]["content"]
        return types.SimpleNamespace(text=self.text)


def test_grammar_is_corrected_and_the_facts_kept():
    llm = _LLM("1. The Roman collar shirt goes for 2,500, and we have white and black.\n"
               "2. Tuko Sonalux Building, 7th floor, Room 18, Moi Avenue.\n"
               "3. Yes, we deliver countrywide via G4S at 350.")
    out = asyncio.run(sb.polish_exemplars(EX, llm=llm))
    assert llm.calls == 1
    assert out[0]["a"] == "The Roman collar shirt goes for 2,500, and we have white and black."
    assert out[1]["a"].startswith("Tuko Sonalux Building")
    assert [p["q"] for p in out] == [p["q"] for p in EX]          # the customers' words untouched


def test_a_polish_that_changes_a_figure_or_the_length_is_refused():
    llm = _LLM("1. The Roman collar shirt goes for 2,800, and we have white and black.\n"
               "2. Tuko Sonalux Building, 7th floor, Room 18, Moi Avenue, near Nairobi Sports House, "
               "opposite Family Bank, open Monday to Saturday from 8 to 5.\n"
               "3. ")
    out = asyncio.run(sb.polish_exemplars(EX, llm=llm))
    assert [p["a"] for p in out] == [p["a"] for p in EX]
    assert sb.polish_keeps_the_facts("goes for 2500", "goes for 2,500.")
    assert not sb.polish_keeps_the_facts("goes for 2500", "goes for 2600")


def test_no_key_no_model_the_raw_lines_stand(monkeypatch):
    monkeypatch.setattr("app.core.config.settings.anthropic_api_key", "", raising=False)
    assert asyncio.run(sb.polish_exemplars(EX)) == EX

    class _Boom:
        async def complete(self, **k):
            raise RuntimeError("down")
    assert asyncio.run(sb.polish_exemplars(EX, llm=_Boom())) == EX


def test_refresh_polishes_before_it_renders():
    import inspect
    src = inspect.getsource(sb.refresh)
    assert "await polish_exemplars(choose_exemplars(pairs))" in src
