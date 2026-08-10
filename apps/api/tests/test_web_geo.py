"""Website location comes from the IP (owner rule) — resolved once, cached,
stamped on the profile, and used for the first quote. Never asked."""
import asyncio

import app.main  # noqa: F401
from app.routers import web_chat as wc


class _Redis:
    def __init__(self): self.store = {}
    async def get(self, k): return self.store.get(k)
    async def setex(self, k, ttl, v): self.store[k] = v


def _fake_httpx(monkeypatch, payload, status=200):
    class _Resp:
        status_code = status
        def json(self): return payload

    class _Client:
        def __init__(self, *a, **k): ...
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, url, headers=None): return _Resp()
    import httpx
    monkeypatch.setattr(httpx, "AsyncClient", _Client)


def test_ip_resolves_and_caches(monkeypatch):
    _fake_httpx(monkeypatch, {"country_code": "ke", "country_name": "Kenya"})
    r = _Redis()
    assert asyncio.run(wc._country_from_ip(r, "105.161.1.2")) == ("KE", "Kenya")
    assert r.store["ipgeo:105.161.1.2"] == "KE|Kenya"
    # Second call is served from cache — break httpx to prove it isn't touched.
    _fake_httpx(monkeypatch, {}, status=500)
    assert asyncio.run(wc._country_from_ip(r, "105.161.1.2")) == ("KE", "Kenya")


def test_private_and_missing_ips_resolve_to_nothing(monkeypatch):
    r = _Redis()
    for ip in (None, "", "127.0.0.1", "::1", "10.0.0.5", "192.168.1.4", "172.19.0.1"):
        assert asyncio.run(wc._country_from_ip(r, ip)) is None
    assert r.store == {}                 # nothing cached, nothing queried


def test_lookup_failure_never_raises(monkeypatch):
    class _Boom:
        def __init__(self, *a, **k): ...
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, url, headers=None): raise RuntimeError("down")
    import httpx
    monkeypatch.setattr(httpx, "AsyncClient", _Boom)
    assert asyncio.run(wc._country_from_ip(None, "8.8.8.8")) is None


def test_web_turn_uses_the_stamped_country():
    """run_turn's web branch must read User.country_iso — that's the whole
    point of geolocating: KES for a Nairobi visitor, never a question."""
    import inspect
    from app.agent import runtime
    src = inspect.getsource(runtime.run_turn)
    assert "user.country_iso" in src or 'getattr(user, "country_iso"' in src
