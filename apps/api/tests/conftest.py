"""Shared test set-up."""
import pytest


@pytest.fixture(autouse=True)
def _no_hub_rates_carried_between_tests():
    """What a process remembers of the hub's catalogue (its currency rates,
    services/fx; its prices for the instruction examples,
    agent/prompt_prices) must not travel from one test to the next: a test
    that reads a catalogue would change what a later test's fallback is."""
    from app.agent import prompt_prices
    from app.services import fx
    fx._HUB_PER.update(rates={}, mark=None)
    prompt_prices._PRICES.update(by_slug={}, mark=None)
    yield
    fx._HUB_PER.update(rates={}, mark=None)
    prompt_prices._PRICES.update(by_slug={}, mark=None)


@pytest.fixture(autouse=True)
def _safeguards_as_the_older_tests_were_written(monkeypatch):
    """The safeguards the owner switched on (2026-11-23) change what a reply
    and an order step do: a line is added to a first greeting, an order step
    without the customer's yes is refused, a second deferral gets a line.
    Hundreds of older tests pin the behaviour BEFORE those switches and are
    about other things, so the suite runs with them off; the switched-on
    behaviour, and the deployed defaults themselves, are tested where they
    are named (tests/test_policy_layer.py, tests/test_safeguards_on.py)."""
    from app.core.config import settings
    for name, value in (("policy_mode", "shadow"), ("policy_guards_active", False),
                        ("official_numbers_by_code", False), ("offer_price_after_grant", False),
                        ("second_deferral_line", False)):
        monkeypatch.setattr(settings, name, value, raising=False)
    yield
