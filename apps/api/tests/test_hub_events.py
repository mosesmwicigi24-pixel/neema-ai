"""Phase A — hub event agency: celebrations are Neema's, disappointments are
the human's; window/quiet-hour laws enforced; idempotent everywhere."""
import asyncio
import hashlib
import hmac
import json
import types
from datetime import datetime, timezone, timedelta

import pytest

from app.core.config import settings
from app.services import hub_events as he


@pytest.fixture(autouse=True)
def _secret(monkeypatch):
    monkeypatch.setattr(settings, "hub_events_secret", "topsecret", raising=False)


class _Redis:
    def __init__(self):
        self.store, self.published, self.z = {}, [], {}
    async def set(self, k, v, nx=False, ex=None):
        if nx and k in self.store: return False
        self.store[k] = v; return True
    async def publish(self, ch, msg): self.published.append((ch, json.loads(msg)))
    async def zadd(self, k, mapping): self.z.setdefault(k, {}).update(mapping)
    async def zrangebyscore(self, k, lo, hi):
        return [m for m, s in self.z.get(k, {}).items() if lo <= s <= hi]
    async def zrem(self, k, m): self.z.get(k, {}).pop(m, None)


def test_signature_verification():
    from app.routers.hub_events import _valid_signature
    body = b'{"id":"e1","type":"order.paid"}'
    good = "sha256=" + hmac.new(b"topsecret", body, hashlib.sha256).hexdigest()
    assert _valid_signature(body, good)
    assert not _valid_signature(body, "sha256=deadbeef")
    assert not _valid_signature(body, None)


def test_quiet_hours_and_next_morning():
    two_am = datetime(2026, 7, 30, 23, 0, tzinfo=timezone.utc)     # 02:00 NBO
    noon = datetime(2026, 7, 30, 9, 0, tzinfo=timezone.utc)        # 12:00 NBO
    nine_pm = datetime(2026, 7, 30, 18, 30, tzinfo=timezone.utc)   # 21:30 NBO
    assert he.is_quiet_hours(two_am) and he.is_quiet_hours(nine_pm)
    assert not he.is_quiet_hours(noon)
    m = he.next_morning_utc(two_am)
    assert (m + timedelta(hours=3)).hour == 8                      # 08:00 NBO


def test_briefs_are_specific():
    b = he.brief_for({"type": "order.paid", "order_number": "ORD-9",
                      "amount": 12000, "currency": "KES"})
    assert "ORD-9" in b and "KES 12,000" in b
    s = he.brief_for({"type": "order.shipped", "order_number": "ORD-9",
                      "tracking": "DHL123"})
    assert "DHL123" in s
    assert he.brief_for({"type": "bogus"}) is None


def test_unknown_and_duplicate_events_are_dropped():
    r = _Redis()
    out = asyncio.run(he.handle_event(None, r, {"id": "e1", "type": "weird.event"}))
    assert out == {"handled": False, "reason": "unknown_event"}
    # burn e2, then redeliver
    asyncio.run(r.set("hubevent:seen:e2", "1"))
    out = asyncio.run(he.handle_event(None, r, {"id": "e2", "type": "order.paid"}))
    assert out["reason"] == "duplicate"


def test_celebrate_routes_and_paid_guard(monkeypatch):
    r = _Redis()
    conv = types.SimpleNamespace(id="c1", channel="whatsapp", wa_id="254700000001",
                                 external_id=None, person_id="p1", contact_name="Moses")
    sent = []

    async def fake_within(db, c): return True
    async def fake_compose(db, redis, c, brief): return "Asante! Payment received 🙏"
    async def fake_send(to, text, context_wamid=None): sent.append(("wa", to, text))
    async def fake_save(db, redis, to, text): sent.append(("save", to, text))
    monkeypatch.setattr(he, "_within_window", fake_within)
    monkeypatch.setattr(he, "_compose_announcement", fake_compose)
    monkeypatch.setattr(he, "is_quiet_hours", lambda now=None: False)
    from app.services import n8n_bridge as svc
    monkeypatch.setattr(svc, "_send_waba", fake_send)
    monkeypatch.setattr(svc, "save_outbound_message", fake_save)

    ev = {"id": "e3", "type": "order.paid", "order_number": "ORD-1"}
    out = asyncio.run(he._celebrate(None, r, conv, ev))
    assert out == {"handled": True, "sent": "freeform"}
    assert sent[0][0] == "wa" and "Asante" in sent[0][2]

    # The SAME order paid again (hub + mpesa double-report) → guarded.
    out2 = asyncio.run(he._celebrate(None, r, conv, dict(ev, id="e4")))
    assert out2["reason"] == "already_celebrated"


def test_outside_window_uses_template_or_human(monkeypatch):
    r = _Redis()
    conv = types.SimpleNamespace(id="c1", channel="whatsapp", wa_id="254700000001",
                                 external_id=None, person_id="p1", contact_name="Moses M")
    async def fake_within(db, c): return False
    monkeypatch.setattr(he, "_within_window", fake_within)
    monkeypatch.setattr(he, "is_quiet_hours", lambda now=None: False)
    tsent = []
    from app.services import n8n_bridge as svc
    async def fake_tmpl(to, name, params, lang=None): tsent.append((to, name, params))
    async def fake_save(db, redis, to, text): tsent.append(("save", text))
    monkeypatch.setattr(svc, "send_wa_template", fake_tmpl, raising=False)
    monkeypatch.setattr(svc, "save_outbound_message", fake_save)

    monkeypatch.setattr(settings, "wa_event_template", "order_update", raising=False)
    out = asyncio.run(he._celebrate(None, r, conv,
                                    {"id": "e5", "type": "order.shipped",
                                     "order_number": "ORD-2"}))
    assert out["sent"] == "template"
    assert tsent[0][1] == "order_update" and tsent[0][2][0] == "Moses"

    # No template configured → dashboard notification, never a policy breach.
    monkeypatch.setattr(settings, "wa_event_template", "", raising=False)
    out2 = asyncio.run(he._celebrate(None, r, conv,
                                     {"id": "e6", "type": "order.shipped"}))
    assert out2["sent"] == "notified_human"
    assert any(p[1]["type"] == "hub_event" for p in r.published)


def test_quiet_hours_defers_and_drains(monkeypatch):
    r = _Redis()
    conv = types.SimpleNamespace(id="c1", channel="whatsapp", wa_id="254700000001",
                                 external_id=None, person_id="p1", contact_name=None)
    monkeypatch.setattr(he, "is_quiet_hours", lambda now=None: True)
    ev = {"id": "e7", "type": "order.paid", "order_number": "ORD-3",
          "customer_phone": "+254700000001"}
    out = asyncio.run(he._celebrate(None, r, conv, ev))
    assert out == {"handled": True, "deferred": "quiet_hours"}
    assert r.z[he.DEFER_ZSET]


def test_escalation_reasons_cover_all_disappointments():
    for t in he.ESCALATE:
        assert t in he._ESCALATE_REASON
