"""CUSTOMER NAMES — one decision with its evidence (owner, 2026-11-09: a
customer showed as "John 14:14", a Facebook display name that is a verse).
Model-free: the classifier, the self-introduction reader, the precedence
rules and the writer's greeting."""
import pytest

from app.services import names


@pytest.mark.parametrize("value,kind", [
    ("John 14:14", "scripture"), ("Psalm 23", "scripture"), ("Phil 4:13", "scripture"),
    ("1 Cor 13", "scripture"), ("Jeremiah 29:11", "scripture"), ("Romans 8:28 🙏", "scripture"),
    ("Grace Ministries", "organization"), ("Bethel Church Nairobi", "organization"),
    ("Mama Shiro Boutique", "organization"),
    ("@peter_k", "handle"), ("peter.k99", "handle"), ("😀😀", "handle"), ("J", "handle"),
    ("Guest", "placeholder"), ("WhatsApp User", "placeholder"),
    ("Mary Wanjiru", "person"), ("John Kamau", "person"), ("Pastor Moses", "person"),
    ("Bishop Daniel Mwangi", "person"), ("Jean-Pierre N'Diaye", "person"), ("Amos", "person"),
    ("John Mark", "person"), ("", "empty"), (None, "empty"),
])
def test_classify(value, kind):
    assert names.classify(value) == kind


@pytest.mark.parametrize("text,name", [
    ("My name is Peter", "Peter"),
    ("my name is peter kamau and I need a robe", "Peter Kamau"),
    ("I'm Bishop Daniel", "Bishop Daniel"),
    ("This is Pastor James from Nairobi", "Pastor James"),
    ("Hi, I am Peter Kamau", "Peter Kamau"),
    ("Hello, I'm Grace.", "Grace"),
    ("Naitwa Wanjiru", "Wanjiru"),
    ("Jina langu ni Otieno", "Otieno"),
    ("Mimi ni Mchungaji Paul", "Mchungaji Paul"),
    ("Je m'appelle Jean", "Jean"),
    ("Meu nome é Ana", "Ana"),
    ("Call me Liz", "Liz"),
])
def test_self_introduction_reads_their_own_name(text, name):
    assert names.self_introduction(text) == name


@pytest.mark.parametrize("text", [
    "I am the way, the truth and the life",
    "I am Alpha and Omega",
    "John 3:16 says I am the light",
    'He said "my name is Legion"',
    "my pastor's name is John",
    "His name is Peter",
    "I'm fine thanks", "I'm interested in the cassock", "I'm in Nairobi", "I am Kenyan",
    "im looking for a robe", "I'm Peter's mother", "I am ready to pay",
    "Is this Bethany House?", "",
])
def test_self_introduction_leaves_everything_else(text):
    assert names.self_introduction(text) is None


def _with(*readings):
    st = {}
    for value, by, at in readings:
        st, _ = names.observe(st, value, by=by, at=at)
    return st


def test_a_verse_profile_never_wins_over_a_personal_name():
    st = _with(("John 14:14", "facebook", "2026-11-01T00:00:00+00:00"))
    d = names.decide(st)
    assert d["value"] == "John 14:14" and d["kind"] == "scripture"      # kept, not a person
    st, _ = names.observe(st, "Mary W", by="whatsapp", at="2026-11-02T00:00:00+00:00")
    assert names.decide(st)["value"] == "Mary W"
    # the verse stays on the record as the Facebook profile name
    assert st["name"]["readings"]["facebook"]["value"] == "John 14:14"
    assert st["name"]["history"][-1]["previous"]["value"] == "John 14:14"


def test_precedence_confirmed_stated_profile_platform():
    st = _with(("Pete K", "facebook", "2026-11-01T00:00:00+00:00"),
               ("Peter Kamau", "whatsapp", "2026-11-02T00:00:00+00:00"))
    assert names.decide(st)["by"] == "whatsapp"
    st, _ = names.observe(st, "Bishop Daniel", by="stated", at="2026-11-03T00:00:00+00:00")
    assert names.decide(st)["value"] == "Bishop Daniel"                  # their word beats the profile
    st, _ = names.observe(st, "Daniel Mwangi", by="operator", at="2026-11-04T00:00:00+00:00")
    assert names.decide(st)["value"] == "Daniel Mwangi"
    # a later profile name or self-introduction never silently replaces staff's
    st, _ = names.observe(st, "Danny", by="whatsapp", at="2026-11-05T00:00:00+00:00")
    st, _ = names.observe(st, "Dan", by="stated", at="2026-11-06T00:00:00+00:00")
    assert names.decide(st)["value"] == "Daniel Mwangi"
    st, _ = names.observe(st, "Daniel M. Mwangi", by="operator", at="2026-11-07T00:00:00+00:00")
    assert names.decide(st)["value"] == "Daniel M. Mwangi"               # staff can correct


def test_staff_word_stands_even_for_an_organization():
    st = _with(("Mary", "whatsapp", "2026-11-01T00:00:00+00:00"),
               ("Grace Ministries", "operator", "2026-11-02T00:00:00+00:00"))
    assert names.decide(st)["value"] == "Grace Ministries"


def test_fuller_name_for_the_same_person_wins_unless_confirmed():
    st = _with(("Meshack Munyao", "facebook", "2026-11-01T00:00:00+00:00"),
               ("Meshack", "stated", "2026-11-02T00:00:00+00:00"))
    assert names.decide(st)["value"] == "Meshack Munyao"
    st, _ = names.observe(st, "Meshack", by="operator", at="2026-11-03T00:00:00+00:00")
    assert names.decide(st)["value"] == "Meshack"


def test_same_reading_twice_is_not_a_change():
    st = _with(("Mary W", "whatsapp", "2026-11-01T00:00:00+00:00"))
    st2, changed = names.observe(st, "Mary W", by="whatsapp")
    assert changed is False and st2 == st


def test_history_is_capped():
    st = {}
    for i in range(40):
        st, _ = names.observe(st, f"Name {chr(65 + i % 26)}{i}x", by="operator",
                              at=f"2026-11-01T00:{i:02d}:00+00:00")
    assert len(st["name"]["history"]) == names.HISTORY_CAP


def test_seed_from_legacy_keeps_a_confirmed_name_and_the_channel_names():
    from types import SimpleNamespace as NS
    ids = [NS(channel="facebook", display_name="John 14:14"),
           NS(channel="whatsapp", display_name="John K")]
    st, seeded = names.seed_from_legacy({}, user_name="John Kariuki", user_confirmed=True,
                                        person_name="John 14:14", identities=ids,
                                        user_wa_id="254728000000")
    assert seeded
    r = st["name"]["readings"]
    assert r["facebook"]["value"] == "John 14:14" and r["whatsapp"]["value"] == "John K"
    assert r["legacy_confirmed"]["value"] == "John Kariuki"
    assert names.decide(st)["value"] == "John Kariuki"
    # seeding is once: a person already on the record is left alone
    st2, again = names.seed_from_legacy(st, user_name="X Y", user_confirmed=True,
                                        person_name=None, identities=[])
    assert again is False and st2 == st


def test_summary_says_where_the_name_came_from():
    s = names.summary({}, user_name=None, person_name="John 14:14",
                      identities=[type("I", (), {"channel": "facebook", "display_name": "John 14:14"})()])
    assert s["name"] == "John 14:14" and s["kind"] == "scripture" and s["addressable"] is False
    assert s["label"] == "Facebook profile"


def test_the_writer_never_greets_by_a_verse():
    from app.agent.prompt import customer_context
    greet, note = names.for_agent("John 14:14")
    assert greet == "" and "scripture" in note and "John 14:14" in note
    assert "speaking with" not in customer_context(greet, "Kenya")
    assert names.for_agent("Mary Wanjiru") == ("Mary Wanjiru", "")
    assert names.for_agent("Grace Ministries")[0] == ""
    assert names.for_agent("") == ("", "")


def test_web_form_is_not_the_customers_own_word():
    # the public form is unauthenticated: it never outranks a WhatsApp profile
    st = _with(("Mary W", "whatsapp", "2026-11-01T00:00:00+00:00"),
               ("Somebody Else", "web_form", "2026-11-02T00:00:00+00:00"))
    assert names.decide(st)["value"] == "Mary W"
