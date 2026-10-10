"""Re-engagement check-ins: the quality gate, the language, the parsing (no DB).

The 2026-10-10 preview showed the old sweep replaying interrupted turns —
"Thank you for your patience.", "I'm confirming the blue and red chasubles
with our team now…", a fresh currency conversion. A check-in is now composed
fresh and must pass a gate before it may go; skipping beats nonsense.
"""
import subprocess
import sys

from app.jobs import reengage as rj


def test_job_configures_mappers_in_a_fresh_interpreter():
    """On the box, `python -m app.jobs.reengage` starts a clean interpreter that
    imports ONLY what the job imports — so the job must pull in enough models to
    configure SQLAlchemy's mappers by itself. pytest loads every model via other
    test files, hiding this, so verify it in a subprocess with a fresh registry."""
    code = (
        "import app.jobs.reengage;"
        "from sqlalchemy.orm import configure_mappers; configure_mappers();"
        "print('MAPPERS_OK')"
    )
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert "MAPPERS_OK" in r.stdout


CHASUBLE = [
    ("customer", "Do you have the chasuble in blue and red?"),
    ("neema", "Yes 🙏 the Gothic Chasuble comes in blue and red — KES 18,000 each."),
    ("customer", "ok let me think"),
    ("neema", "Of course, take your time 🙏"),
]
TRAYS = [
    ("customer", "How much for 5 Aluminium Trays in dollars?"),
    ("neema", "The 5 Aluminium Trays come to $350 in total."),
    ("customer", "And in rand?"),
    ("neema", "Let me get that for you."),
]


def gate(text, item, transcript=CHASUBLE, name="Major", language="en"):
    return rj.quality_gate(text, item, transcript=transcript, name=name, language=language)


def test_the_gate_refuses_the_three_bad_lines_from_the_preview():
    assert gate("Thank you for your patience.", "Gothic Chasuble")
    assert gate("Thank you for waiting. I'm confirming the blue and red chasubles with our "
                "team now — they'll have the answer for you here in a moment…", "chasuble")
    assert gate("At today's rate, $350 is about R5,788.62 for the 5 Aluminium Trays… "
                "Shall I place the order now?", "Aluminium Trays", transcript=TRAYS, name=None)


def test_a_proper_check_in_passes():
    ok = ("Hello Major 🙏 just checking in — you were looking at the Gothic Chasuble in blue "
          "and red at KES 18,000 each. Shall I set them aside for you?")
    assert gate(ok, "Gothic Chasuble") is None


def test_the_gate_wants_an_item_from_the_thread_and_no_new_figures():
    assert gate("Hello Major 🙏 would you like to go ahead with your order?", "order") \
        == "names no item from the thread"
    assert gate("Hello Major 🙏 the Velvet Cope is lovely — shall I reserve it?", "Velvet Cope") \
        == "names no item from the thread"
    assert gate("Hello Major 🙏 the Gothic Chasuble is now KES 16,500 — shall I reserve it?",
                "Gothic Chasuble") == "a figure not already in the thread"


def test_the_gate_wants_a_question_the_name_and_a_fresh_line():
    assert gate("Hello Major 🙏 the Gothic Chasuble is still available.", "Gothic Chasuble") \
        == "asks no question"
    assert gate("Hello 🙏 shall I reserve the Gothic Chasuble for you?", "Gothic Chasuble") \
        == "does not greet them by name"
    assert gate("and the Gothic Chasuble, Major — shall I reserve it?", "Gothic Chasuble") \
        == "reads as the middle of a reply"
    assert gate("Of course, take your time 🙏", "Gothic Chasuble") == "replays an earlier line"


def test_the_gate_holds_the_thread_language():
    sw_thread = [("customer", "Nataka hii chasuble ya blue, bei gani?"),
                 ("neema", "Gothic Chasuble ni KES 18,000 🙏")]
    sw_ok = "Habari Major 🙏 bado unataka ile Gothic Chasuble ya KES 18,000? Nikuwekee moja?"
    assert gate(sw_ok, "Gothic Chasuble", transcript=sw_thread, language="sw") is None
    en = "Hello Major 🙏 would you still like the Gothic Chasuble at KES 18,000?"
    assert gate(en, "Gothic Chasuble", transcript=sw_thread, language="sw") \
        == "not in the thread's language (Swahili)"
    fr_ok = ("Bonjour Major 🙏 vous souhaitez toujours la Gothic Chasuble à KES 18,000 ? "
             "Je vous la réserve ?")
    assert gate(fr_ok, "Gothic Chasuble", transcript=sw_thread, language="fr") is None


def test_thread_language_follows_the_customers_own_words():
    assert rj.thread_language(["Do you have red stoles?"]) == "en"
    assert rj.thread_language(["Habari", "Nataka hii cassock, bei gani?"]) == "sw"
    assert rj.thread_language(["Bonjour, combien pour la chasuble avec étole ?"]) == "fr"
    assert rj.thread_language([]) == "en"


def test_hand_off_lines_are_recognised():
    for t in ("A colleague will confirm the colours and get back to you shortly 🙏",
              "I'm confirming that with our team now.",
              "Hello and welcome to Bethany House 🙏 We are so glad to have you here."):
        assert rj.is_handoff_line(t), t
    assert not rj.is_handoff_line("The Gothic Chasuble is KES 18,000. Would you like one?")


def test_parse_draft_reads_json_and_honours_a_skip():
    assert rj.parse_draft('{"item": "Red Stole", "text": "Hi 🙏 shall I reserve the Red Stole?"}') \
        == ("Red Stole", "Hi 🙏 shall I reserve the Red Stole?")
    assert rj.parse_draft('Sure: {"item": "Red Stole", "text": "x?"} done') == ("Red Stole", "x?")
    assert rj.parse_draft('{"skip": "nothing discussed"}') is None
    assert rj.parse_draft("Thank you for your patience.") is None
    assert rj.parse_draft('{"item": "", "text": "Hi?"}') is None


def test_the_prompt_is_a_fresh_brief_not_the_next_turn():
    system, user = rj.build_prompt(CHASUBLE, name="Major", language="sw")
    assert "FRESH" in system and "Swahili" in system and "Major" in system
    assert "never" in system.lower() and "patience" in system
    # the transcript is quoted reference text, never replayed as live turns
    assert user.startswith("The conversation so far")
    assert "Customer: Do you have the chasuble in blue and red?" in user
