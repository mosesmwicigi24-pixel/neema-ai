"""READ THE INTENT, GRADE IT, ROUTE IT (owner, 2026-09-22).

"The agent should read the intent, grade the intent — is it a request, a
complaint, a commendation? If a complaint, graded on severity and referred to
a human agent. If a compliment, handled by Neema. If a statement that looks
like all three, resolve it wisely, in the best interest of the business and
the client."

The live miss: "Please more designs for ladies" (Queen Gili, 2026-09-21,
during the credit stop) was answered with "Send us a message and we'll help
however we can" — the neutral signpost that every unreadable comment got
when no model could answer. The residues, closed here: the one-size complaint
line and the one-size "COMPLAINT" note to the team; the request that was
never a kind of its own; the signpost pools ("send us a message", "tell us a
little more") and the two retired pools nothing read.

Repo fake style (no DB fixture). Requires Python 3.11 (SQLAlchemy models).
"""
import asyncio
import inspect
import types

import app.main  # noqa: F401 — registers all SQLAlchemy models
import app.agent.runtime as rt


class _LLM:
    def __init__(self, text="high"):
        self.text, self.prompt = text, ""

    async def complete(self, *, system, messages, tools, **kw):
        self.prompt = messages[0]["content"]
        return types.SimpleNamespace(text=self.text, tool_calls=[], assistant_content=[], usage={})


class _Down:
    async def complete(self, *, system, messages, tools, **kw):
        raise RuntimeError("credit balance is too low")


def _read(text, monkeypatch, answer="high"):
    llm = _LLM(answer)
    monkeypatch.setattr(rt, "build_llm", lambda model=None, **kw: llm)
    return asyncio.run(rt.read_comment(text)), llm


# ── 1. the deterministic readers ─────────────────────────────────────────────

def test_a_request_is_read_from_its_shape():
    for text in ("Share more designs for ladies, interested.", "Please more designs for ladies",
                 "send the catalogue", "post prices please", "more photos please",
                 "Tuma picha zaidi", "show us the options for men"):
        assert rt.looks_request(text), text
    for text in ("how much?", "this is wrong", "Amen 🙏", "where are you located?",
                 "beautiful work", "I want this"):
        assert not rt.looks_request(text), text


def test_the_ask_is_their_own_words_trimmed():
    assert rt.request_ask("Share more designs for ladies, interested.") == "more designs for ladies"
    assert rt.request_ask("Please more designs for ladies") == "more designs for ladies"
    assert rt.request_ask("anything", "designs for ladies") == "designs for ladies"
    assert rt.request_ask("Please", "-") == "what you asked for"


def test_a_grievance_is_graded_by_its_own_words():
    assert rt.grade_complaint("this is wrong") == 1
    assert rt.grade_complaint("very disappointed") == 1
    assert rt.grade_complaint("still waiting for my order") == 2
    assert rt.grade_complaint("I paid and nothing came, I want a refund") == 2
    assert rt.grade_complaint("poor quality, the stole was torn") == 2
    assert rt.grade_complaint("this is a scam, you people lied") == 3
    assert rt.grade_complaint("the stole was stolen from the parcel") == 3   # stolen, not the stole
    assert rt.grade_complaint("I will report you to the police") == 3
    assert rt.grade_complaint("hii ni wizi") == 3


# ── 2. the reading: one call, four fields ────────────────────────────────────

def test_the_model_line_is_parsed_and_a_bare_word_still_works():
    r = rt.parse_comment_reading("intent=high | kind=request | severity=0 | ask=more designs for ladies")
    assert r == {"intent": "high", "kind": "request", "severity": 0, "ask": "more designs for ladies"}
    assert rt.parse_comment_reading("negative") == {"intent": "negative", "kind": "other", "severity": 0, "ask": ""}
    assert rt.parse_comment_reading("intent=negative | kind=mixed | severity=2 | ask=-")["ask"] == ""
    assert rt.parse_comment_reading("banana") is None
    assert rt.parse_comment_reading("intent=purple | kind=request") is None
    assert rt.parse_comment_reading("") is None


def test_queen_gilis_comment_reads_as_a_request(monkeypatch):
    r, llm = _read("Please more designs for ladies", monkeypatch,
                   "intent=high | kind=request | severity=0 | ask=more designs for ladies")
    assert r["intent"] == "high" and r["kind"] == "request" and r["ask"] == "more designs for ladies"
    assert "kind=<request|question|complaint|praise|mixed|greeting|other>" in llm.prompt
    # …and still when the model is down (the credit stop that produced the miss)
    monkeypatch.setattr(rt, "build_llm", lambda model=None, **kw: _Down())
    r2 = asyncio.run(rt.read_comment("Please more designs for ladies"))
    assert r2["intent"] == "high" and r2["kind"] == "request" and r2["ask"] == "more designs for ladies"
    # …and when the model called it a question
    r3, _ = _read("Share more designs for ladies, interested.", monkeypatch,
                  "intent=high | kind=question | severity=0 | ask=-")
    assert r3["kind"] == "request" and r3["ask"] == "more designs for ladies"


def test_complaints_are_graded_and_never_below_their_words(monkeypatch):
    r, _ = _read("this is a scam", monkeypatch)                # deterministic: no model
    assert r["intent"] == "negative" and r["kind"] == "complaint" and r["severity"] == 3
    r, _ = _read("still waiting for my order", monkeypatch)
    assert r["kind"] == "complaint" and r["severity"] == 2
    r, _ = _read("this is wrong", monkeypatch)
    assert r["kind"] == "complaint" and r["severity"] == 1
    # the model's grade counts upward, never downward
    r, _ = _read("the collar came a size too small", monkeypatch,
                 "intent=negative | kind=complaint | severity=2 | ask=-")
    assert r["intent"] == "negative" and r["severity"] == 2
    r, _ = _read("the cassock is fine but delivery took a month", monkeypatch,
                 "intent=negative | kind=complaint | severity=1 | ask=-")
    assert r["kind"] == "complaint" and r["severity"] == 1


def test_kind_words_beside_a_grievance_are_mixed(monkeypatch):
    r, _ = _read("Beautiful work, but my order never came", monkeypatch)   # negative by words
    assert r["intent"] == "negative" and r["kind"] == "mixed" and r["severity"] == 2
    r, _ = _read("lovely stoles but the colour was wrong", monkeypatch,
                 "intent=negative | kind=mixed | severity=1 | ask=-")
    assert r["kind"] == "mixed" and r["intent"] == "negative"


def test_praise_greetings_and_the_old_labels_still_read_as_before(monkeypatch):
    r, _ = _read("We can't wait to have you in Zambia", monkeypatch)
    assert r["intent"] == "goodwill" and r["kind"] == "praise"
    r, _ = _read("How are you", monkeypatch)
    assert r["intent"] == "high" and r["kind"] == "greeting"
    r, _ = _read("amen 🙏", monkeypatch, "low")
    assert r["intent"] == "low"
    assert asyncio.run(rt.read_comment("   ")) == {"intent": "low", "kind": "other", "severity": 0, "ask": ""}
    # the old name is the reading's intent
    monkeypatch.setattr(rt, "build_llm", lambda model=None, **kw: _LLM("intent=high | kind=question | severity=0 | ask=delivery to Uganda"))
    assert asyncio.run(rt.classify_comment_intent("do you ship to Uganda?")) == "high"
    # a short cheer is praise even with no model to say so — thanked, never handed to a person
    monkeypatch.setattr(rt, "build_llm", lambda model=None, **kw: _Down())
    for text in ("Awesome 👍", "beautiful work", "❤️", "🙏🙏", "Nice one", "Thank you"):
        r = asyncio.run(rt.read_comment(text))
        assert r["intent"] == "low" and r["kind"] == "praise", text
    for text in ("Do you do for lay leaders", "How much?", "Nice, how much is it?", "where are you located"):
        r = asyncio.run(rt.read_comment(text))
        assert r["intent"] == "high" and r["kind"] != "praise", text
    # a request is answered, never thanked away
    r, _ = _read("more photos please", monkeypatch, "intent=low | kind=request | severity=0 | ask=more photos")
    assert r["intent"] == "high" and r["kind"] == "request"


# ── 3. the lines: by weight, never a signpost ────────────────────────────────

def test_the_empathy_line_follows_the_weight():
    mild = rt.empathy_text("complaint", 1).replace("{name}", " Florence")
    assert mild == rt._PUBLIC_EMPATHY.replace("{name}", " Florence")
    serious = rt.empathy_text("complaint", 2, private_sent=True).replace("{name}", " Grace")
    assert serious.startswith("We're sorry Grace 🙏") and "private message" in serious
    assert "{private}" not in serious and "💛" not in serious
    serious_no_dm = rt.empathy_text("complaint", 2, private_sent=False)
    assert "private message" not in serious_no_dm and serious_no_dm.endswith("now.")
    grave = rt.empathy_text("complaint", 3, private_sent=True)
    assert grave.startswith("We're truly sorry") and "today" in grave and "private message" in grave
    mixed = rt.empathy_text("mixed", 1)
    assert mixed.startswith("Thank you for the kind words") and "sorry" in mixed
    assert rt.empathy_text("mixed", 2, private_sent=True).startswith("We're sorry")
    sw = rt.empathy_text("complaint", 2, swahili=True, private_sent=True)
    assert sw.startswith("Samahani") and "ujumbe wa faragha" in sw
    for line in (rt._EMPATHY_SERIOUS, rt._EMPATHY_GRAVE, rt._EMPATHY_MIXED, rt._PRIVATE_COMPLAINT,
                 rt._SW_EMPATHY_SERIOUS, rt._SW_EMPATHY_GRAVE, rt._SW_EMPATHY_MIXED, rt._SW_PRIVATE_COMPLAINT):
        low = line.lower()
        assert "price" not in low and "order now" not in low and "💛" not in line and "http" not in low


def test_a_request_or_question_we_cannot_answer_promises_a_person_not_a_signpost():
    out = rt._comment_public_reply("", dm_sent=False, name_tag=" Queen", seed="q",
                                   kind="request", ask="more designs for ladies")
    assert "more designs for ladies" in out and "Queen" in out
    assert "send us a message" not in out.lower() and "dm us" not in out.lower()
    assert "team" in out.lower() and "here" in out.lower()
    q = rt._comment_public_reply("", dm_sent=False, name_tag=" Sam", seed="s", kind="question")
    assert "send us a message" not in q.lower() and "here" in q.lower()
    sw = rt._comment_public_reply("", dm_sent=False, name_tag="", seed="s", kind="request",
                                  ask="picha zaidi", swahili=True)
    assert "picha zaidi" in sw and "hapa" in sw
    # a trusted, priced product still sells to a bare price ask, kind or no kind
    sell = rt._comment_public_reply("", dm_sent=False, name_tag="", seed="s", product_known=True,
                                    product_name="Silver Communion Tray", price_text="$180",
                                    kind="question")
    assert "$180" in sell
    # the neutral line itself never sends anyone away any more
    for line in rt._NEUTRAL_ACK_POOL + rt._SW_NEUTRAL_ACK_POOL:
        low = line.lower()
        assert "send us a message" not in low and "tell us a little more" not in low
        assert "tutumie ujumbe" not in low and "tuambie zaidi" not in low
        assert "here" in low or "hapa" in low


# ── 4. the team's note: typed and graded ─────────────────────────────────────

def test_the_team_note_says_what_it_is_and_how_heavy():
    n1 = rt._human_note("complaint", 1, "this is wrong")
    assert n1.startswith("COMPLAINT (public comment) — severity 1/3 (mild)")
    n2 = rt._human_note("complaint", 2, "still waiting for my order")
    assert "severity 2/3 (serious)" in n2 and "TODAY" in n2 and "private message was opened" in n2
    n3 = rt._human_note("mixed", 3, "beautiful but this is a scam")
    assert n3.startswith("MIXED — kind words and a grievance") and "GRAVE / URGENT" in n3
    nr = rt._human_note("request", 0, "Please more designs for ladies", ask="more designs for ladies",
                        answered="Thank you Queen 🙏 Noted: more designs for ladies.")
    assert nr.startswith("REQUEST (public comment)") and "They want: more designs for ladies" in nr
    assert "RIGHT THERE in the thread" in nr and "Neema said:" in nr
    nq = rt._human_note("question", 0, "do you ship to Uganda?")
    assert nq.startswith("QUESTION (public comment)")
    assert rt._human_note("other", 0, "??").startswith("PUBLIC COMMENT Neema could not read")


def test_a_serious_complaint_is_an_escalation_the_bell_hears():
    src = inspect.getsource(rt._route_comment_to_human)
    assert 'if kind in ("complaint", "mixed") and int(severity or 1) >= 2:' in src
    assert "record_escalation(db, conv.id, note, redis=redis)" in src
    assert "InterceptAction.flag" in src


# ── 5. the engine acts on the reading ────────────────────────────────────────

def test_the_engine_reads_grades_and_routes():
    src = inspect.getsource(rt._run_comment_engage)
    assert "reading = await read_comment(comment_text, redis=redis)" in src
    # a serious or grave grievance: the private message first, then the line by weight
    assert "if severity >= 2:" in src and "private_sent = await _private_complaint_message(" in src
    assert "_PRIVATE_COMPLAINT" in inspect.getsource(rt._private_complaint_message)
    assert "text = empathy_text(kind, severity, swahili, private_sent=private_sent)" in src
    assert "await _route_comment_to_human(channel, ext, comment_text, kind=kind," in src
    # the model is handed the reading; the composer too
    assert "comment_reading=reading" in src
    assert "bundle=is_bundle, kind=kind, ask=ask)" in src
    # no answer and nothing sold → the team answers in the thread
    assert 'if not answer and intent != "goodwill" and not ask_which and not (product_name and price_text):' in src
    assert 'kind=(kind if kind in ("request", "question") else "other")' in src


def test_the_model_is_told_what_the_comment_is():
    assert "comment_reading: dict | None = None" in inspect.getsource(rt.run_turn)
    assert "_reading_context(comment_reading)" in inspect.getsource(rt.run_turn)
    req = rt._reading_context({"kind": "request", "ask": "more designs for ladies"})
    assert "REQUEST" in req and "more designs for ladies" in req and "search_catalog" in req
    assert "Never a bare 'send us a message'" in req
    assert "QUESTION" in rt._reading_context({"kind": "question", "ask": "delivery to Uganda"})
    assert "PRAISE" in rt._reading_context({"kind": "praise"})
    assert "GREETING" in rt._reading_context({"kind": "greeting"})
    assert "MIXED" in rt._reading_context({"kind": "mixed", "severity": 2})
    assert rt._reading_context({"kind": "other"}) == "" and rt._reading_context(None) == ""
    add = rt._public_comment_addendum("USD")
    assert "READ THE INTENT, THEN ANSWER IT (owner, 2026-09-22)" in add
    assert "answered WITH THE SHELF" in add and "never a bare 'send us a message'" in add
    assert "MIXED comment" in add and "READ THE MOOD BEFORE YOU SELL" in add
