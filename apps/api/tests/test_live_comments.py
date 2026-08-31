"""When the shop is LIVE, welcome the room — don't sell at it.

The owner, mid-broadcast: "I am live on facebook, and I find the answers you
are giving is about the 102 bible stories. When I go live, I expect you to
welcome people in."

What actually happened: a viewer wrote "Watching from Liberia 🇱🇷" and got
"the 102 childrens stories is $15 — how many would you like?". Three faults
compounded:

  1. classify_comment_intent sends a greeting to `high` ON PURPOSE — under a
     product photo a hello IS a door opening. On a live stream it is someone
     arriving.
  2. With no product in the post, the agent read the VIDEO FRAME — a man in a
     shop full of stock — and matched a product at random.
  3. That guess was then recorded as the post's identity, so every later
     comment on the broadcast got the same wrong price. Two different viewers,
     same children's book.
"""
import pytest

from app.agent import runtime as rt


def test_a_live_greeting_is_not_a_sales_opportunity():
    # The exact comment from the broadcast.
    assert not rt._mentions_catalogue_item("Watching from Liberia 🇱🇷")
    assert not rt._looks_like_a_question("Watching from Liberia 🇱🇷")


def test_a_bare_price_ask_during_a_live_names_nothing():
    # Answerable under a photo; NOT answerable during a broadcast that has
    # shown twenty things.
    assert rt._looks_like_a_question("How much does it cost?")
    assert not rt._mentions_catalogue_item("How much does it cost?")


def test_a_named_product_during_a_live_is_still_answerable():
    # The other real comments on the same broadcast — these deserve a real price.
    assert rt._mentions_catalogue_item("How much is the Talliets?")
    assert rt._mentions_catalogue_item("How much is for the small size of the Talliets?")
    assert rt._mentions_catalogue_item("price of the cassock?")
    assert rt._mentions_catalogue_item("Do you have communion cups?")


def test_the_welcome_pool_sells_nothing():
    for line in rt._LIVE_WELCOME_POOL:
        low = line.lower()
        assert "$" not in line and "ksh" not in low and "kes" not in low
        assert "how many" not in low, "a welcome must not ask for an order"


def test_the_which_item_pool_never_quotes_a_price():
    for line in rt._LIVE_WHICH_POOL:
        assert "$" not in line
        assert "?" in line, "it must actually ask which item"


@pytest.mark.parametrize("text", [
    "Watching from Liberia 🇱🇷", "Hello", "Habari", "Amen", "Bonjour", "@top fans",
])
def test_arrivals_name_no_product(text):
    assert not rt._mentions_catalogue_item(text)
