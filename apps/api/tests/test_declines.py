"""Owner review, 2026-10-29: the real replies after which a follow-up still
went out — and the ones that must NOT read as a no."""
import pytest

from app.services.declines import customer_declined


@pytest.mark.parametrize("text", [
    "NO", "No", "No, not now. Next time nlang po.", "Wag na muna po.",
    "I will not order hi- price we can't afford. Thank you.",
    "thank you i  cannot aford the prize🙏🏼",
    "no i have no enough cash for that sir/maam",
    "Entschuldigung, aber das ist mir leider zu teuer.",
    "Expenssiv for me", "Amount too expensive", "Oky,that expens to me",
])
def test_a_clear_no(text):
    assert customer_declined(text)


@pytest.mark.parametrize("text", [
    "But your price is quiet huge. Its very high",      # still bargaining — bought on
    "I can't afford the silver, how much is the aluminium?",
    "How much in Kenya shillings", "Not today next week", "Ok thanks we will arrange later",
    "No problem, send me 2", "👍", "", None,
])
def test_not_a_no(text):
    assert not customer_declined(text)
