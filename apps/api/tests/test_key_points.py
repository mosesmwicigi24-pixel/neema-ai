"""KEY POINTS, HIGHLY SUMMARISED (owner, 2026-11-03): "the internal memory
is too big, and that takes a lot of tokens … And also the call brief is too
big. I just need key points in that call, very highly summarized."

The call brief and the handoff briefing are held to a short shape whatever
the model writes — a card read at a glance, and small notes for every caller.
"""
import app.main  # noqa: F401 — registers models
from app.services import call_transcribe as ct
from app.services import copilot


def test_words_are_clipped_at_a_word():
    assert ct.clip_words("one two three", 5) == "one two three"
    assert ct.clip_words("one two three four, five", 4) == "one two three four…"
    assert ct.clip_words("  spaced   out \n text ", 9) == "spaced out text"


def test_a_long_brief_is_held_to_key_points():
    long_summary = ("Sue, who contacted us on WhatsApp, wants a gold communion set without the "
                    "incense, which she says costs about $300 of the $650 package price quoted to "
                    "her. She also asked for a clear glass communion cup (not silver) with a cross, "
                    "several shades of purple and gold bishop robes and a personalised Bible.")
    insights = {
        "products": ["Gold communion set without incense (tray and cup with cross; tray quantity "
                     "unconfirmed)", "Clear glass communion cup with cross (not silver)",
                     "Purple bishop robe, various shades", "Gold bishop robe", "Bible, personalised"],
        "objections": ["Does not want the incense and wants the price without it", "Cannot see "
                       "clearly", "Unsure how many trays", "Bible personalisation"],
        "commitments": ["Priscilla: send pictures"],
        "next_action": "Send Sue the pictures of the gold set and clear glass cup, and get a firm "
                       "price for the set without incense, then confirm Bible personalisation",
        "follow_up_message": " ".join(["word"] * 80),
    }
    summary, out = ct._sane_brief(long_summary, insights)
    assert len(summary.split()) <= ct.BRIEF_SUMMARY_WORDS and summary.endswith("…")
    assert summary.startswith("Sue, who contacted us")
    for k in ("products", "objections"):
        assert len(out[k]) <= ct.BRIEF_LIST_ITEMS
        assert all(len(x.split()) <= ct.BRIEF_ITEM_WORDS + 1 for x in out[k])
    assert len(out["next_action"].split()) <= 16 + 1
    assert len(out["follow_up_message"].split()) <= 40 + 1
    assert out["commitments"] == ["Priscilla: send pictures"]       # short items pass untouched


def test_the_brief_asks_for_key_points_only():
    p = ct._ANALYSE_SYSTEM
    assert "KEY POINTS ONLY" in p and "at most 25 words" in p and "at most 3" in p
    assert "action_items" not in p and "commitments" not in p      # no longer asked for


def test_the_handoff_briefing_is_four_short_labelled_lines():
    """Owner, 2026-11-04: can the internal note be more precise and brief?"""
    sprawl = """**Handoff briefing for the colleague taking over Sue (Canada):**
- **Where the sale stands:** Nothing is in the cart and nothing has been ordered.
Status: gold Chalice Cup with Paten Set without the thurible, plus clear glass cups with a cross; nothing ordered yet
Next: confirm the price without the thurible and send both photos on the other number today
Avoid: saying $650 is the price without the thurible
Say: Hi Sue, Priscilla here from Bethany House — confirming your set price now.
- Please also note the time-zone mistake and the robot question."""
    out = copilot.tight_briefing(sprawl)
    lines = out.splitlines()
    assert [ln.split(":")[0] for ln in lines] == ["Status", "Next", "Avoid", "Say"]
    assert all(len(ln.split()) <= copilot.BRIEF_LINE_WORDS + 1 for ln in lines)
    assert "**" not in out and "Handoff briefing" not in out
    assert len(out.split()) <= 4 * (copilot.BRIEF_LINE_WORDS + 1)


def test_an_unlabelled_briefing_still_comes_out_short():
    out = copilot.tight_briefing("\n".join(f"- point {i} " + "word " * 40 for i in range(9)))
    lines = out.splitlines()
    assert len(lines) == copilot.BRIEF_MAX_LINES
    assert all(len(ln.split()) <= copilot.BRIEF_LINE_WORDS + 1 for ln in lines)
    assert copilot.tight_briefing("") == ""


def test_the_briefing_ask_names_the_shape():
    assert "PRECISE AND BRIEF" in copilot.BRIEF_ASK and "at most 4 lines" in copilot.BRIEF_ASK
    assert "at most 12 words" in copilot.BRIEF_ASK
    for label in copilot.BRIEF_LABELS:
        assert f"{label}:" in copilot.BRIEF_ASK
