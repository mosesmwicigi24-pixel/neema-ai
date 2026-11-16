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
