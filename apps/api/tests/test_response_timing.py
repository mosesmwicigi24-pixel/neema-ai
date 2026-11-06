"""Every response carries its own server time.

"The dashboard is slow" was unanswerable from outside: the box's other sites
were healthy, /api/health was fast, and the endpoints that actually matter
(conversations, threads, orders) need a login to measure — so server time,
network time and render time were indistinguishable.

Now the API times itself: a Server-Timing header on every response (visible in
any browser's Network tab, per request) and a WARNING log for anything slow, so
a regression shows up in `docker compose logs api` without anyone watching.

TestClient is used WITHOUT its context manager on purpose — entering it runs
the lifespan, which wants Redis and Postgres. The middleware under test needs
neither.
"""
import logging

import pytest
from fastapi.testclient import TestClient

import app.main as main_mod
from app.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def _no_hub(monkeypatch):
    """/api/health runs the price audit, which with no Redis cache fetches the
    hub catalogue over the network (15 s timeout). On a CI runner where the
    hub host drops packets that is 15,025 ms of "server time" and the quiet
    test fails. The middleware under test does not need the hub: fail the
    fetch at once so the route falls back to the local table."""
    from app.core import hub_client

    async def _unreachable(redis):
        raise RuntimeError("no hub in this test")
    monkeypatch.setattr(hub_client, "fetch_hub_catalog", _unreachable)


def test_every_response_reports_its_server_time():
    r = client.get("/api/health")
    assert r.status_code == 200
    timing = r.headers.get("Server-Timing")
    assert timing, "Server-Timing missing — a browser cannot separate server from network"
    assert timing.startswith("app;dur=")
    assert float(timing.split("=", 1)[1]) >= 0        # real, parseable ms


def test_a_slow_request_is_logged_loudly(monkeypatch, caplog):
    """The log line is what makes a regression visible without devtools open."""
    monkeypatch.setattr(main_mod, "SLOW_REQUEST_MS", 0)      # everything is "slow"
    with caplog.at_level(logging.WARNING, logger="neema.slow"):
        client.get("/api/health")
    lines = [r.getMessage() for r in caplog.records if r.name == "neema.slow"]
    assert any("slow GET /api/health" in ln for ln in lines), lines


def test_a_fast_request_stays_quiet(monkeypatch, caplog):
    monkeypatch.setattr(main_mod, "SLOW_REQUEST_MS", 10_000)
    with caplog.at_level(logging.WARNING, logger="neema.slow"):
        client.get("/api/health")
    assert not [r for r in caplog.records if r.name == "neema.slow"]


def test_the_log_line_carries_no_query_string():
    """Query strings can carry customer handles — the path alone is enough."""
    import inspect
    src = inspect.getsource(main_mod._timing)
    assert "request.url.path" in src
    assert "str(request.url" not in src
