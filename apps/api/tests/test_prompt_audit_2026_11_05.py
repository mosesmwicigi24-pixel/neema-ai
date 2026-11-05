"""The five prompt edits from the audit of 2026-11-05 (Mama Beth's chat):
brevity ranks second, the long worked examples match the contract, the
customer never hears of our systems or a 'hold', and the church year is our
planning calendar, not a claim about their church."""
import app.main  # noqa: F401 — registers models
from app.agent.prompt import build_system_prompt

P = build_system_prompt(country_iso="KE", currency="KES")
FLAT = " ".join(P.split())


def test_brevity_ranks_second_only_to_money_and_truth():
    i = P.index("WHEN RULES COLLIDE")
    block = P[i: i + 1200]
    assert block.index("1. Money & truth safety") < block.index("2. The BREVITY CONTRACT (STYLE)") \
        < block.index("3. A complaint or grief") < block.index("4. Answer what they actually asked")
    assert "never permission to say more than the ask needs" in " ".join(block.split())


def test_the_worked_examples_are_as_short_as_the_contract_asks():
    for example in ("Our Cassock Set is $210, everything included — the cassock, stole, belt, shirt and collar. Which colour would you like?",
                    "This is our Silver Communion Tray at $180 — lid, holder, basin and 40 cups included. How many do you need?"):
        assert " ".join(example.split()) in " ".join(P.split())
        assert len(example.split()) <= 25
    assert "Two or three flowing sentences" not in P
    assert "40 cups are included in the package for free" not in P
    assert "Its contents are said ONCE in a conversation" in FLAT
    # the owner's welcome keeps its voice (pinned elsewhere) but is shorter
    flat = " ".join(P.split())
    assert "Welcome to Bethany House, Malakhi" in flat and "excited to have you" in flat
    assert "customized to your preference" not in flat


def test_the_customer_sees_a_shop_not_a_system():
    assert "THE CUSTOMER SEES A SHOP, NOT A SYSTEM" in P
    assert "shall I reserve it for you?" not in P
    assert "Shall I hold these while you confirm the colours?" not in P
    assert "by a word: never offer it" in FLAT


def test_the_church_year_is_our_calendar_not_their_churchs_colour():
    i = P.index("THE CHURCH YEAR")
    block = P[i: i + 1500]
    fb = " ".join(block.split())
    assert "THIS IS OUR PLANNING CALENDAR, NOT A CLAIM ABOUT THEIR CHURCH" in fb
    assert "are DENOMINATIONS" in fb and "Never tell a customer what their church" in fb
