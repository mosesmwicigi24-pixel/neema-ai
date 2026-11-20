"""A NAME IS NOT A PREFIX (owner, 2026-11-20): "Neema was repeating the name
of a person after every message sent, e.g. Moses, … then Moses, …"."""
from app.agent.voice import drop_repeated_name as drn


def test_the_second_opening_name_is_dropped():
    earlier = ["Welcome to Bethany House, Moses. Which colour would you like?"]
    assert drn("Moses, the cassock is made to your measurements.", "Moses Mwicigi", earlier) \
        == "The cassock is made to your measurements."
    assert drn("Pastor Moses — it ships by DHL.", "Pastor Moses", earlier) == "It ships by DHL."
    assert drn("moses: yes, we have it.", "Moses", earlier) == "Yes, we have it."


def test_the_first_use_is_kept():
    assert drn("Moses, welcome back.", "Moses", []) == "Moses, welcome back."
    assert drn("Moses, welcome back.", "Moses", ["Which colour would you like?"]) == "Moses, welcome back."


def test_only_the_last_two_replies_count():
    earlier = ["Thank you, Moses.", "Which size?", "And the colour?"]
    assert drn("Moses, noted.", "Moses", earlier) == "Moses, noted."


def test_a_greeting_a_thank_you_and_a_close_are_left_alone():
    earlier = ["Moses, the stole is ready."]
    for line in ("Hello Moses, good to hear from you.", "Thank you, Moses.",
                 "It will be ready on Friday, Moses.", "Moses is the name on the parcel."):
        assert drn(line, "Moses", earlier) == line


def test_nothing_is_dropped_when_nothing_would_be_left_or_no_name_is_known():
    earlier = ["Moses, the stole is ready."]
    assert drn("Moses!", "Moses", earlier) == "Moses!"
    assert drn("Moses, yes.", "", earlier) == "Moses, yes."
    assert drn("", "Moses", earlier) == ""
    # a title alone, or a two-letter name, is not a name to match on
    assert drn("Pastor, yes we do.", "Pastor Jo", ["Pastor, welcome."]) == "Pastor, yes we do."


def test_the_turn_applies_it_and_public_comments_are_excluded():
    import inspect
    from app.agent import runtime
    src = inspect.getsource(runtime.run_turn)
    assert "drop_repeated_name" in src and "not public_comment" in src
