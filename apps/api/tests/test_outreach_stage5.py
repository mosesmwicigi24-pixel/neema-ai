"""OUTBOUND COMMUNICATION, STAGE 5 — the rollout control: shadow or enforce,
and the contextual rules switched on one at a time from the dashboard. The
dispatcher reads it once per sweep; the environment is only the default."""
import asyncio
import json
import types
from datetime import datetime, timezone

from app.core.config import settings
from app.services import app_settings as aps


def run(coro):
    return asyncio.run(coro)


class _Redis:
    def __init__(self):
        self.store, self.hashes = {}, {}
    async def get(self, k): return self.store.get(k)
    async def set(self, k, v, ex=None, nx=False): self.store[k] = v
    async def delete(self, k): self.store.pop(k, None)
    async def hincrby(self, k, f, n):
        self.hashes.setdefault(k, {})[f] = self.hashes.get(k, {}).get(f, 0) + n
    async def expire(self, k, s): pass
    async def hgetall(self, k): return self.hashes.get(k, {})


class _DB:
    """A settings table of SimpleNamespace rows keyed by id."""
    def __init__(self, rows=None):
        self.rows, self.commits = dict(rows or {}), 0
    async def execute(self, q):
        key = None
        try:
            key = q.whereclause.right.value
        except Exception:
            pass
        row = self.rows.get(key)
        return types.SimpleNamespace(scalar_one_or_none=lambda: row)
    def add(self, row):
        self.rows[row.id] = row
    async def commit(self):
        self.commits += 1


def test_rules_parse_in_canonical_order_and_unknown_words_drop():
    assert aps.parse_outreach_rules("daily_cap, customer_replied; bogus") == ["customer_replied", "daily_cap"]
    assert aps.parse_outreach_rules("") == [] and aps.parse_outreach_rules(None) == []


def test_the_environment_is_only_the_default(monkeypatch):
    monkeypatch.setattr(settings, "outreach_mode", "shadow", raising=False)
    monkeypatch.setattr(settings, "outreach_enforce_rules", "colleague_replied", raising=False)
    ctrl = run(aps.get_outreach_control(_DB(), None))
    assert ctrl == {"mode": "shadow", "rules": ["colleague_replied"]}
    # the dashboard's rows override it, and "-" means "none, on purpose"
    db = _DB({"outreach_mode": types.SimpleNamespace(id="outreach_mode", value="enforce"),
              "outreach_enforce_rules": types.SimpleNamespace(id="outreach_enforce_rules", value="-")})
    assert run(aps.get_outreach_control(db, None)) == {"mode": "enforce", "rules": []}
    # a broken value falls back to the default, never to "enforce" by accident
    db = _DB({"outreach_mode": types.SimpleNamespace(id="outreach_mode", value="ENFORCE NOW")})
    assert run(aps.get_outreach_control(db, None))["mode"] == "shadow"


def test_set_writes_rows_refreshes_the_cache_and_rejects_nonsense(monkeypatch):
    monkeypatch.setattr(settings, "outreach_mode", "shadow", raising=False)
    monkeypatch.setattr(settings, "outreach_enforce_rules", "", raising=False)
    r, db = _Redis(), _DB()
    ctrl = run(aps.set_outreach_control(db, r, rules=["customer_replied"], updated_by="u1"))
    assert ctrl == {"mode": "shadow", "rules": ["customer_replied"]} and db.commits == 1
    assert json.loads(r.store["app:outreach_control"]) == ctrl
    assert db.rows["outreach_enforce_rules"].value == "customer_replied"
    ctrl = run(aps.set_outreach_control(db, r, mode="enforce"))
    assert ctrl["mode"] == "enforce" and json.loads(r.store["app:outreach_control"])["mode"] == "enforce"
    ctrl = run(aps.set_outreach_control(db, r, rules=[]))
    assert ctrl["rules"] == [] and db.rows["outreach_enforce_rules"].value == "-"
    for bad in (dict(mode="loud"), dict(rules=["nope"])):
        try:
            run(aps.set_outreach_control(db, r, **bad))
            raise AssertionError("accepted nonsense")
        except ValueError:
            pass
    # a cached value answers without the database, and any failure yields the default
    class _Dead:
        async def execute(self, *a, **k): raise RuntimeError("db down")
    assert run(aps.get_outreach_control(_Dead(), r))["mode"] == "enforce"      # from the cache
    assert run(aps.get_outreach_control(_Dead(), None)) == {"mode": "shadow", "rules": []}


def test_each_verdict_names_its_rule():
    from app.services.actions import rule_of
    assert rule_of("the customer wrote after this was planned — the live reply answered them") == "customer_replied"
    assert rule_of("a colleague replied after this was planned") == "colleague_replied"
    assert rule_of("one unprompted sales message a day") == "daily_cap"
    assert rule_of("") == "other"


def test_one_rule_can_be_enforced_while_the_others_stay_in_shadow(monkeypatch):
    from tests.test_outreach_stage2 import _dispatcher, _row
    now = datetime.now(timezone.utc)
    rows = [_row("quote_follow_up", id="a1", draft="Shall I reserve it?"),
            _row("buying_follow_up", id="a2", conversation_id="c2", draft="Still thinking about the tray?")]
    verdicts = {"quote_follow_up": ("suppress", "the customer wrote after this was planned"),
                "buying_follow_up": ("defer", "one unprompted sales message a day")}
    act, db, sent, _ = _dispatcher(monkeypatch, rows, verdicts=verdicts)
    monkeypatch.setattr(settings, "outreach_mode", "shadow", raising=False)
    async def control(db, redis): return {"mode": "shadow", "rules": ["customer_replied"]}
    monkeypatch.setattr(act, "_control", control)
    r = _Redis()
    assert run(act.process_due(db, r, now=now)) == 1
    assert rows[0].status == "vetoed" and "customer wrote" in rows[0].reason          # enforced
    assert [s[0] for s in sent] == ["buying_follow_up"] and sent[0][2] == ["defer: one unprompted sales message a day"]
    tally = r.hashes[next(iter(r.hashes))]
    assert tally == {"rule_customer_replied": 1, "enforced_suppress": 1, "rule_daily_cap": 1, "defer": 1}


def test_the_dispatcher_reads_the_control_once_per_sweep_and_falls_back_to_the_environment(monkeypatch):
    import inspect
    from app.services import actions as act
    src = inspect.getsource(act.process_due)
    assert src.count("await _control(db, redis)") == 1
    assert src.index("control = await _control(db, redis)") < src.index("for action in rows")
    class _Dead:
        async def execute(self, *a, **k): raise RuntimeError("no settings table")
    monkeypatch.setattr(settings, "outreach_mode", "enforce", raising=False)
    monkeypatch.setattr(settings, "outreach_enforce_rules", "", raising=False)
    assert run(act._control(_Dead(), None)) == {"mode": "enforce", "rules": []}


def test_the_health_view_and_the_standup_show_the_control(monkeypatch):
    from app.services import outreach_log as ol
    monkeypatch.setattr(settings, "outreach_mode", "shadow", raising=False)
    monkeypatch.setattr(settings, "outreach_enforce_rules", "", raising=False)
    r = _Redis()
    r.store["app:outreach_control"] = json.dumps({"mode": "shadow", "rules": ["customer_replied", "colleague_replied"]})
    class _NoDB:
        def __call__(self): raise RuntimeError("no db")
    view = run(ol.health_view(r, db_factory=_NoDB()))
    # without a database the view still reports the environment default honestly
    assert view["mode"] == "shadow" and view["enforced_rules"] == []
    assert "rule_customer_replied" in ol.TALLY_FIELDS and "rule_daily_cap" in ol.TALLY_FIELDS
    import inspect
    from app.jobs import self_qa
    assert "outreach_control_cached" in inspect.getsource(self_qa)


def test_the_routes_are_registered_and_admin_only_on_write():
    import inspect
    from app.routers import crm
    paths = {(rt.path, tuple(sorted(rt.methods or []))) for rt in crm.router.routes}
    assert ("/settings/outreach", ("GET",)) in paths and ("/settings/outreach", ("PUT",)) in paths
    assert "Admin only" in inspect.getsource(crm.put_outreach_setting)
