"""Close the loops that made a good agent feel careless.

The re-look at the whole system found the remaining quality not inside any
single reply, but BETWEEN them: promises that opened and never closed ("let me
confirm and come right back" → a flag nobody carried back), silence when a turn
died, the fit-check a tailor owes a customer after delivery, the questions that
stall orders (how long? how do I measure? can I have it in writing?), and a
returning customer greeted like a stranger.

A1  the team's answer is DELIVERED BY NEEMA (/conversations/{id}/answer)
A2  a failed turn sends an honest hold line instead of dead air
A3  order.delivered plans a fit-check six days out; outside the window it
    rides the approved utility template instead of dying in approvals
B4  a configured production window lets her answer "how long?" plainly
B5  a how-to-measure diagram tool (registered only when configured)
B6  a formal written quotation from the cart, composed in code
C7  RETURNING CUSTOMER leads the memory block — karibu tena
C8  two new nightly detectors: price answered with no number; selling into
    displeasure
C9  the standup shows the promise ledger
"""
import asyncio
import types
from datetime import datetime, timedelta, timezone

import pytest

import app.main  # noqa: F401 — registers all SQLAlchemy models
from app.core.config import settings


class _Res:
    def __init__(self, one=None, many=None):
        self._one, self._many = one, many or []
    def scalar_one_or_none(self): return self._one
    def scalars(self): return types.SimpleNamespace(all=lambda: self._many)


class _DB:
    def __init__(self, results=None):
        self._r = list(results or [])
        self._i = 0
        self.added, self.committed = [], False
    async def execute(self, *a, **k):
        r = self._r[self._i]; self._i += 1; return r
    def add(self, obj): self.added.append(obj)
    async def commit(self): self.committed = True
    async def refresh(self, obj): pass


class _Redis:
    def __init__(self): self.kv = {}
    async def set(self, k, v, nx=None, ex=None):
        if nx and k in self.kv:
            return None
        self.kv[k] = v
        return True
    async def get(self, k): return self.kv.get(k)


class _SessionCM:
    def __init__(self, db): self._db = db
    async def __aenter__(self): return self._db
    async def __aexit__(self, *a): return False


# ── A1: the team's answer travels back through Neema ─────────────────────────

def _req():
    return types.SimpleNamespace(app=types.SimpleNamespace(
        state=types.SimpleNamespace(redis=None)))


def _conv(channel="whatsapp"):
    return types.SimpleNamespace(id="c1", channel=channel,
                                 wa_id="254712345678", external_id=None,
                                 contact_name="Pastor Moses")


def test_team_answer_is_composed_and_sent_by_neema(monkeypatch):
    from app.routers import admin
    sent = {}

    async def _fake_turn(*a, **k):
        assert "TEAM ANSWER" in k["user_text"]
        assert "KES 3,500" in k["user_text"]        # the facts reach the composer
        assert k["read_only"] is True               # composing must write nothing
        return "Good news Pastor Moses — yes, we make it: KES 3,500, about 5 days. Shall I add it?"

    async def _fake_send(wa_id, text, *a, **k):
        sent["to"], sent["text"] = wa_id, text
        return "wamid.X"

    async def _fake_save(db, redis, wa_id, text, **k): pass
    async def _window_open(db, conv): return True

    monkeypatch.setattr("app.agent.runtime.run_turn", _fake_turn)
    monkeypatch.setattr("app.agent.runtime.build_llm", lambda *a, **k: None)
    monkeypatch.setattr("app.services.hub_events._within_window", _window_open)
    monkeypatch.setattr("app.services.n8n_bridge._send_waba", _fake_send)
    monkeypatch.setattr("app.services.n8n_bridge.save_outbound_message", _fake_save)

    db = _DB([_Res(one=_conv())])
    out = asyncio.run(admin.answer_through_neema(
        "c1", _req(), {"facts": "yes we can make it, KES 3,500, ~5 days"},
        db, types.SimpleNamespace(id="agent1")))
    assert out["ok"] and "KES 3,500" in out["sent"]
    assert sent["to"] == "254712345678"
    # The audit note is filed, internal-only.
    assert any(getattr(m, "media_type", "") == "note" for m in db.added)
    assert db.committed


def test_team_answer_refused_outside_the_window(monkeypatch):
    from fastapi import HTTPException
    from app.routers import admin

    async def _window_closed(db, conv): return False
    monkeypatch.setattr("app.services.hub_events._within_window", _window_closed)
    with pytest.raises(HTTPException) as e:
        asyncio.run(admin.answer_through_neema(
            "c1", _req(), {"facts": "confirmed"}, _DB([_Res(one=_conv())]),
            types.SimpleNamespace(id="a1")))
    assert e.value.status_code == 409


def test_team_answer_requires_facts():
    from fastapi import HTTPException
    from app.routers import admin
    with pytest.raises(HTTPException) as e:
        asyncio.run(admin.answer_through_neema(
            "c1", _req(), {}, _DB([]), types.SimpleNamespace(id="a1")))
    assert e.value.status_code == 422


# ── A2: a dead turn is never dead air ────────────────────────────────────────

def test_hold_line_sends_once_and_flags(monkeypatch):
    from app.agent import runtime
    sends = []

    async def _fake_send(wa_id, text, *a, **k):
        sends.append(text)
        return "wamid.H"
    async def _fake_save(db, redis, wa_id, text, **k): pass

    monkeypatch.setattr("app.services.n8n_bridge._send_waba", _fake_send)
    monkeypatch.setattr("app.services.n8n_bridge.save_outbound_message", _fake_save)
    monkeypatch.setattr("app.database.AsyncSessionLocal",
                        lambda: _SessionCM(_DB([_Res(one=None), _Res(one=None)])))
    r = _Redis()
    asyncio.run(runtime._send_hold_line(r, "whatsapp", "254712345678"))
    asyncio.run(runtime._send_hold_line(r, "whatsapp", "254712345678"))  # guarded
    assert len(sends) == 1
    assert "Samahani" in sends[0] and "colleague" in sends[0]


def test_hold_line_never_raises(monkeypatch):
    from app.agent import runtime

    async def _boom(*a, **k): raise RuntimeError("send path down too")
    monkeypatch.setattr("app.services.n8n_bridge._send_waba", _boom)
    asyncio.run(runtime._send_hold_line(_Redis(), "whatsapp", "254700000000"))


def test_failure_handlers_call_the_hold_line():
    import inspect
    from app.agent import runtime
    assert "_send_hold_line" in inspect.getsource(runtime._run_and_send)
    assert "_send_hold_line" in inspect.getsource(runtime._run_and_send_meta)


# ── A3: the tailor's call-back ───────────────────────────────────────────────

def test_delivery_plans_a_fit_check_six_days_out():
    from app.services import hub_events as he
    db, r = _DB(), _Redis()
    asyncio.run(he._plan_fit_check(db, r, _conv(), {"order_number": "BH-2417"}))
    assert db.committed and len(db.added) == 1
    action = db.added[0]
    assert action.kind == "fit_check"
    days = (action.due_at - datetime.now(timezone.utc)).total_seconds() / 86400
    assert 5.9 < days < 6.1
    assert "BH-2417" in action.reason and "adjustment" in action.reason
    # One per order — the guard swallows the hub's retry.
    db2 = _DB()
    asyncio.run(he._plan_fit_check(db2, r, _conv(), {"order_number": "BH-2417"}))
    assert db2.added == []


def test_fit_check_rides_the_utility_template(monkeypatch):
    from app.services import actions
    monkeypatch.setattr(settings, "wa_event_template", "order_update")
    monkeypatch.setattr(settings, "wa_event_lang", "en")
    tpl = {}

    async def _fake_tpl(wa_id, template, lang, params):
        tpl["to"], tpl["name"], tpl["params"] = wa_id, template, params
        return {"messages": [{"id": "wamid.T"}]}
    async def _fake_save(db, redis, wa_id, text, **k): pass

    monkeypatch.setattr("app.services.n8n_bridge.send_wa_template", _fake_tpl)
    monkeypatch.setattr("app.services.n8n_bridge.save_outbound_message", _fake_save)
    action = types.SimpleNamespace(reason="Order BH-2417 was delivered 6 days ago — ask...",
                                   status="planned", draft=None)
    ok = asyncio.run(actions._send_fit_check_template(_DB(), None, _conv(), action))
    assert ok and action.status == "sent"
    assert tpl["name"] == "order_update"
    assert tpl["params"][0] == "Pastor"            # first name into {{1}}
    assert tpl["params"][1] == "BH-2417"           # order into {{2}}
    assert "fitting" in tpl["params"][2]           # the fit-check phrase into {{3}}


def test_scheduler_routes_windowless_fit_checks_to_the_template():
    import inspect
    from app.services import actions
    src = inspect.getsource(actions.process_due)
    assert "fit_check" in src and "_send_fit_check_template" in src


# ── B4: "how long will it take?" gets a real answer ──────────────────────────

def test_lead_time_line_appears_only_when_configured(monkeypatch):
    from app.agent.prompt import build_system_prompt
    monkeypatch.setattr(settings, "production_lead_time",
                        "shirts about 24 hours; cassocks about 5 days")
    p = build_system_prompt(currency="KES")
    assert "HOW LONG DOES IT TAKE" in p and "cassocks about 5 days" in p
    assert "Never promise an exact calendar date" in p
    # The owner's queue caveat: an order ahead can shift the date; the team
    # confirms and she comes back to them (check_availability closes the loop).
    assert "an order ahead of theirs adds days" in p
    assert "staff member will confirm" in p
    monkeypatch.setattr(settings, "production_lead_time", "")
    assert "HOW LONG DOES IT TAKE" not in build_system_prompt(currency="KES")


def test_owner_stated_times_ship_as_the_default():
    assert "clerical shirts about 24 hours" in settings.production_lead_time
    assert "cassocks about 5 days" in settings.production_lead_time
    assert "copes about 4 days" in settings.production_lead_time


# ── B5 + B6: the guide and the quotation ─────────────────────────────────────

def _ctx(channel="whatsapp"):
    from app.agent.tools import ToolContext
    return ToolContext(db=None, redis=None, wa_id="254712345678", channel=channel)


def test_measurement_guide_tool_is_dark_until_configured():
    from app.agent import tools
    # Test env has no guide URL → the tool must NOT be in the schema list
    # (tool lists head the prompt-cache prefix and must be deploy-stable).
    assert not settings.measurement_guide_url
    assert all(t["name"] != "send_measurement_guide" for t in tools.TOOLS)
    assert "send_measurement_guide" in tools._HANDLERS      # handler always wired


def test_measurement_guide_sends_the_image_on_whatsapp(monkeypatch):
    from app.agent import tools
    monkeypatch.setattr(settings, "measurement_guide_url", "https://x.co/guide.jpg")
    sent = {}

    async def _fake_img(wa_id, url, caption=""):
        sent["to"], sent["url"], sent["caption"] = wa_id, url, caption
        return "wamid.I"
    async def _fake_save(db, redis, wa_id, text, **k): pass

    monkeypatch.setattr("app.services.n8n_bridge._send_waba_image", _fake_img)
    monkeypatch.setattr("app.services.n8n_bridge.save_outbound_message", _fake_save)
    out = asyncio.run(tools._send_measurement_guide({}, _ctx()))
    assert out["ok"] and sent["url"].endswith("guide.jpg")
    # Meta channels get the link to include instead.
    out2 = asyncio.run(tools._send_measurement_guide({}, _ctx(channel="messenger")))
    assert out2["ok"] and out2.get("guide_url", "").endswith("guide.jpg")


def test_quotation_is_composed_in_code_with_real_figures(monkeypatch):
    from app.agent import tools

    async def _fake_cart(db, key, channel):
        return {"items": [{"name": "Ladies Princess Cassock", "qty": 2, "unit_price": 7000},
                          {"name": "Clerical Shirt", "qty": 2, "unit_price": 2500}]}
    async def _fake_display(cart, ctx):
        return cart["items"], 19000

    monkeypatch.setattr(tools.cartmod, "get_cart", _fake_cart)
    monkeypatch.setattr(tools, "_cart_display", _fake_display)
    out = asyncio.run(tools._prepare_quotation(
        {"addressed_to": "St Mary's Parish, Nakuru"}, _ctx()))
    q = out["quotation"]
    assert "QUOTATION QT-" in q
    assert "Prepared for: St Mary's Parish, Nakuru" in q
    assert "Ladies Princess Cassock ×2 @ KES 7,000 = KES 14,000" in q
    assert "*TOTAL: KES 19,000*" in q
    assert "Valid until" in q


def test_quotation_refuses_an_empty_cart(monkeypatch):
    from app.agent import tools

    async def _empty(db, key, channel): return {"items": []}
    monkeypatch.setattr(tools.cartmod, "get_cart", _empty)
    out = asyncio.run(tools._prepare_quotation({}, _ctx()))
    assert "error" in out and "update_cart" in out["error"]


# ── C7: karibu tena ──────────────────────────────────────────────────────────

def test_returning_customer_leads_the_memory_block(monkeypatch):
    from app.agent import memory

    async def _orders(db, wa_id, limit=3, person_id=None):
        return ["BH-2401 — KES 12,000", "BH-2377 — KES 7,000"]
    monkeypatch.setattr(memory, "_recent_orders_summary", _orders)
    user = types.SimpleNamespace(state=None, person_id=None, id="u1")
    out = asyncio.run(memory.build_memory_context(None, None, "254712345678", user=user))
    assert out.startswith("RETURNING CUSTOMER — 2 past order(s)")
    assert "karibu tena" in out


# ── C8: the nightly mirror learns two new failures ───────────────────────────

def test_price_question_answered_without_a_number_is_caught():
    from app.jobs.self_qa import find_issues
    msgs = [{"direction": "inbound", "text": "how much is the cassock?"},
            {"direction": "outbound", "text": "Which colour would you like?"}]
    assert any(f["kind"] == "price_unanswered" for f in find_issues(msgs))
    # A priced answer is not a finding.
    ok = [{"direction": "inbound", "text": "how much is the cassock?"},
          {"direction": "outbound", "text": "It's KES 7,000 — which colour would you like?"}]
    assert not any(f["kind"] == "price_unanswered" for f in find_issues(ok))


def test_selling_into_displeasure_is_caught():
    from app.jobs.self_qa import find_issues
    msgs = [{"direction": "inbound", "text": "this is wrong"},
            {"direction": "outbound", "text": "It's KES 7,000 — would you like one?"}]
    assert any(f["kind"] == "sold_into_complaint" for f in find_issues(msgs))
    calm = [{"direction": "inbound", "text": "this is wrong"},
            {"direction": "outbound", "text": "I'm so sorry — tell me what happened and I'll check right away."}]
    assert not any(f["kind"] == "sold_into_complaint" for f in find_issues(calm))


# ── C9: the promise ledger reaches the standup ───────────────────────────────

def test_standup_shows_follow_ups_due():
    from app.jobs.self_qa import compose_standup

    class _R:
        def __init__(self, scalar=None, many=None, row=None):
            self._s, self._m, self._row = scalar, many or [], row
        def scalar_one(self): return self._s
        def scalars(self): return types.SimpleNamespace(all=lambda: self._m)
        def one(self): return self._row

    class _SeqDB(_DB):
        pass

    db = _SeqDB([_R(scalar=7), _R(scalar=2), _R(scalar=0), _R(many=[]),
                 _R(row=(1.0, 10)), _R(scalar=3), _R(scalar=1)])
    out = asyncio.run(compose_standup(db))
    assert "🤝 3 follow-up(s) due in the next 24h (1 already overdue)" in out


# ── the hub's own measurement specs drive the measuring ──────────────────────
# Every production item in the hub carries [{name, unit, required}] — verified
# live: clergy-cassock needs Neck/Shoulders/Sleeves/Chest/Full Length (+
# optional Waist/Hips); a clergy-shirt needs Wrist/Arm Hole/Upper Arm too.
# The spec now flows hub → search_catalog → the ask → the order push.

_HUB_SPECS = [{"name": "Neck", "unit": "in", "required": True},
              {"name": "Shoulders", "unit": "in", "required": True},
              {"name": "Chest", "unit": "in", "required": True},
              {"name": "Waist", "unit": "in", "required": False},
              {"name": "Full Length", "unit": "in", "required": True}]


def test_hub_mapping_carries_the_measurement_spec():
    from app.core.hub_client import _map_product
    p = _map_product({"id": 1, "slug": "clergy-cassock", "is_producible": True,
                      "measurements": _HUB_SPECS,
                      "translations": [{"language_code": "en", "name": "Clergy Cassock"}]})
    assert p["measurements"] == _HUB_SPECS
    assert _map_product({"id": 2, "translations": []})["measurements"] == []


def test_search_results_say_what_to_measure(monkeypatch):
    from app.agent import tools

    async def _catalog(db, redis):
        return [{"name": "Clergy Cassock", "sku": "CC-1", "category": "Cassocks",
                 "price": 7000, "price_usd": 55, "slug": "clergy-cassock",
                 "product_type": "simple", "is_producible": True,
                 "measurements": _HUB_SPECS, "description": "Fine poly-cotton."},
                {"name": "Anointing Oil", "sku": "AO-1", "category": "Communion",
                 "price": 500, "price_usd": 5, "slug": "anointing-oil",
                 "measurements": []}]
    monkeypatch.setattr(tools.svc, "catalog_items", _catalog)
    out = asyncio.run(tools._search_catalog({"query": ""}, _ctx()))
    by = {r["name"]: r for r in out["results"]}
    need = by["Clergy Cassock"]["measurements_needed"]
    assert need == ("Neck, Shoulders, Chest, Full Length "
                    "(+ optional: Waist) — in inches")
    assert "measurements_needed" not in by["Anointing Oil"]


def test_saved_figures_ride_the_production_order(monkeypatch):
    """The point of measuring in chat: the workshop receives the figures WITH
    the order, not a note telling them to start from zero."""
    from app.core import hub_client as hc
    captured = {}

    async def _fake_post_json(*a, **k):  # not used — we stop before HTTP
        raise AssertionError

    async def _no_customer(wa_id): return None
    monkeypatch.setattr(hc, "_find_customer_id", _no_customer)

    class _Resp:
        def __init__(self): self.status_code = 200
        def raise_for_status(self): pass
        def json(self): return {"data": {"id": 9, "order_number": "WA-9"}}
        @property
        def is_success(self): return True

    class _Client:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, url, **k):
            captured["payload"] = k.get("json")
            return _Resp()

    monkeypatch.setattr(hc.httpx, "AsyncClient", _Client)
    monkeypatch.setattr(settings, "hub_outlet_id", 1)
    catalog = [{"hub_product_id": 5, "name": "Clergy Cassock", "sku": "CC-1",
                "slug": "clergy-cassock", "price": 7000, "price_kes": 7000,
                "product_type": "variable", "is_producible": True,
                "in_stock": False, "aliases": [], "variants": []}]
    asyncio.run(hc.push_pending_order(
        catalog, wa_id="254712345678", first_name="Moses", country_iso="KE",
        items=[{"name": "Clergy Cassock", "qty": 1, "unit_price": 7000}],
        measurement_note="Measurements on file: chest 42in, full length 58in. "
                         "Confirm with the customer before production."))
    notes = captured["payload"]["production_items"][0]["production_notes"]
    assert "chest 42in" in notes and "Confirm with the customer" in notes
    # Order-level notes carry the figures too — most producible items are
    # 'simple' in the hub and route via items[], which has no per-line notes.
    assert "chest 42in" in captured["payload"]["notes"]


def test_figures_reach_the_workshop_even_via_the_stock_path(monkeypatch):
    """A 'simple' producible cassock routes via items[] (stock path) — the
    live hub has 15 of 23 production items shaped exactly like this. The
    order-level notes are the only channel that reaches the workshop there."""
    from app.core import hub_client as hc
    captured = {}

    async def _no_customer(wa_id): return None
    monkeypatch.setattr(hc, "_find_customer_id", _no_customer)

    class _Resp:
        status_code = 200
        is_success = True
        def raise_for_status(self): pass
        def json(self): return {"data": {"id": 9, "order_number": "WA-9"}}

    class _Client:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, url, **k):
            captured["payload"] = k.get("json")
            return _Resp()

    monkeypatch.setattr(hc.httpx, "AsyncClient", _Client)
    monkeypatch.setattr(settings, "hub_outlet_id", 1)
    catalog = [{"hub_product_id": 6, "name": "Surplice", "sku": "SP-1",
                "slug": "surplice", "price": 4000, "price_kes": 4000,
                "product_type": "simple", "is_producible": True,
                "in_stock": True, "aliases": [], "variants": []}]
    asyncio.run(hc.push_pending_order(
        catalog, wa_id="254712345678", first_name="Moses", country_iso="KE",
        items=[{"name": "Surplice", "qty": 1, "unit_price": 4000}],
        measurement_note="Measurements on file: chest 40in."))
    assert "production_items" not in captured["payload"]     # stock path, unchanged
    assert "chest 40in" in captured["payload"]["notes"]      # figures still arrive


def test_prompt_measures_from_the_hub_and_offers_ready_made_first():
    from app.agent.prompt import build_system_prompt
    p = build_system_prompt(currency="KES")
    assert "WHAT TO MEASURE comes from the catalogue" in p
    assert "`measurements_needed`" in p
    assert "never invent a list of your own" in p
    assert "READY-MADE FIRST, CUSTOM WHEN IT DIFFERS" in p
    flat = " ".join(p.split())
    # Audit F2: the ready check is async — the sale continues while the team
    # looks, and same-day collection is only promised once confirmed.
    assert "collect at the shop or have sent the same day" in flat
    assert "never a wait and never a downgrade" in flat
