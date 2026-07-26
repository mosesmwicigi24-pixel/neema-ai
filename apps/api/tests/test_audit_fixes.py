"""Cross-tier audit regressions — the loopholes the system-wide audit confirmed.

Each test pins one seam where a new build had silently broken an older
assumption. If any of these regress, real customers get wrong messages.
"""
import asyncio
import types

import app.main  # noqa: F401 — registers models
from app.core.phone import is_plausible_phone
from app.models.person import Person
from app.models.user import User
import app.agent.cart as cartmod


# ── phones: a web session key is NEVER a phone ───────────────────────────────

def test_web_session_keys_are_not_phones():
    # sha1 hex fragments carry 7-15 digits — the old digits-only extraction
    # passed them and minted phantom (whatsapp, web_*) identities.
    assert is_plausible_phone("web_3fa47c19d2e8b105a44f") is False
    assert is_plausible_phone("web_0123456789abcdef0123") is False


def test_real_phones_still_pass_in_every_common_format():
    assert is_plausible_phone("254700706875") is True
    assert is_plausible_phone("+254 700 706 875") is True
    assert is_plausible_phone("+1 (555) 123-4567") is True
    assert is_plausible_phone("0700.706.875") is True
    # Meta PSIDs (16-17 digits) still rejected; junk still rejected
    assert is_plausible_phone("26414904614761138") is False
    assert is_plausible_phone("hello") is False
    assert is_plausible_phone(None) is False


# ── cart adoption is a MOVE — a bought basket can never resurrect ────────────

class _CartDB:
    def __init__(self, user, person):
        self.user, self.person, self.commits = user, person, 0
    async def execute(self, *a, **k):
        return types.SimpleNamespace(scalar_one_or_none=lambda: self.user)
    async def get(self, model, pk):
        return self.person
    async def commit(self):
        self.commits += 1


def test_adoption_moves_the_cart_off_the_user_row():
    person = Person(state={})
    user = User(wa_id="254700000001", phone="254700000001",
                state={"agent_cart": {"items": [{"name": "Mitre", "qty": 2}]}})
    user.person_id = "P1"
    db = _CartDB(user, person)

    store = asyncio.run(cartmod._load_store(db, "254700000001", "whatsapp"))
    assert store is person
    assert person.state["agent_cart"]["items"][0]["name"] == "Mitre"   # adopted
    assert "agent_cart" not in user.state                              # MOVED, not copied


def test_a_cleared_cart_stays_cleared():
    """The resurrection bug: buy → clear → the stale user-row copy re-adopted on
    the next read, re-nudging customers for baskets they already paid for."""
    person = Person(state={})
    user = User(wa_id="254700000001", phone="254700000001",
                state={"agent_cart": {"items": [{"name": "Mitre", "qty": 2}]}})
    user.person_id = "P1"
    db = _CartDB(user, person)

    asyncio.run(cartmod._load_store(db, "254700000001", "whatsapp"))   # adopt (move)
    asyncio.run(cartmod.save_cart(db, "254700000001", {"items": []}))  # ordered → cleared
    cart = asyncio.run(cartmod.get_cart(db, "254700000001"))
    assert cart["items"] == []                     # STAYS empty — no resurrection


def test_merged_person_reads_resolve_to_the_survivor():
    """A ref-linked web visitor pinned to a tombstoned person must still reach
    the ONE live cart store."""
    survivor = Person(state={"agent_cart": {"items": [{"name": "Alb"}]}})
    survivor.id, survivor.merged_into_id = "SURV", None
    ghost = Person(state={})
    ghost.id, ghost.merged_into_id = "GHOST", "SURV"

    class _DB(_CartDB):
        async def get(self, model, pk):
            return {"GHOST": ghost, "SURV": survivor}.get(pk)

    user = User(wa_id="254700000001", phone="254700000001", state={})
    user.person_id = "GHOST"
    store = asyncio.run(cartmod._load_store(_DB(user, None), "254700000001", "whatsapp"))
    assert store is survivor


# ── payment follow-up reaches Meta orders through the person ─────────────────

def test_meta_orders_resolve_conversation_via_person():
    import inspect
    import app.jobs.payment_followup as pf
    src = inspect.getsource(pf._conversation_for)
    assert "person_id" in src                 # phone-vs-PSID mismatch is bridged
    assert "external_id" in src               # and the recipient is the PSID


# ── sweeps must not treat internal notes as conversation turns ───────────────

def test_sweep_latest_message_queries_exclude_notes():
    import inspect
    import app.jobs.reengage as re_job
    import app.jobs.cart_recovery as cr
    for fn in (re_job._latest_message, cr._latest_message):
        assert '"note"' in inspect.getsource(fn)


def test_agent_history_excludes_notes():
    import inspect
    from app.agent.runtime import _history
    assert '"note"' in inspect.getsource(_history)   # operator-private, never model input


# ── previews are look-only ───────────────────────────────────────────────────

def test_dry_run_drafts_are_read_only():
    import inspect
    import app.jobs.reengage as re_job
    import app.jobs.cart_recovery as cr
    assert "read_only=not live" in inspect.getsource(re_job._draft)
    assert "read_only=True" in inspect.getsource(cr._draft)


def test_read_only_context_blocks_demand_writes(monkeypatch):
    import app.agent.tools as tools

    async def fake_catalog(db, redis):
        return []

    called = {"n": 0}

    async def fake_record(*a, **k):
        called["n"] += 1
        return True

    monkeypatch.setattr(tools.svc, "catalog_items", fake_catalog)
    from app.services import demand
    monkeypatch.setattr(demand, "record", fake_record)
    ctx = tools.ToolContext(db=object(), redis=None, wa_id="254700000001",
                            read_only=True)
    asyncio.run(tools._search_catalog({"query": "papal tiara"}, ctx))
    assert called["n"] == 0                    # a preview writes NOTHING


# ── honest channel labels for web traffic ────────────────────────────────────

def test_web_sessions_are_labelled_web_not_whatsapp():
    import app.agent.tools as tools
    web = tools.ToolContext(db=object(), redis=None, wa_id="web_abc", channel="whatsapp")
    wa = tools.ToolContext(db=object(), redis=None, wa_id="254700000001", channel="whatsapp")
    assert tools._channel_label(web) == "web"
    assert tools._channel_label(wa) == "whatsapp"


# ── lead stage ids match the Kanban ──────────────────────────────────────────

def test_lead_stage_is_negotiation_and_legacy_spelling_normalises():
    from app.services.lead_signals import derive_lead_stage, normalise_stage, _STAGE_RANK
    assert "negotiation" in _STAGE_RANK and "negotiating" not in _STAGE_RANK
    assert normalise_stage("negotiating") == "negotiation"   # legacy rows still render
    assert normalise_stage("won") == "won" and normalise_stage(None) == "new"


# ── web sessions cannot place phantom orders ─────────────────────────────────

def test_order_identity_never_bills_a_web_key(monkeypatch):
    import app.agent.tools as tools

    user = User(wa_id="web_abc", phone=None, name="Grace")

    class _DB:
        async def execute(self, *a, **k):
            return types.SimpleNamespace(scalar_one_or_none=lambda: user)

    ctx = tools.ToolContext(db=_DB(), redis=None, wa_id="web_abc", channel="whatsapp")
    phone, name, pid = asyncio.run(tools._order_identity(ctx))
    assert phone is None                       # no phone → the agent must ask
    # …but a captured real phone IS used
    user.phone = "+254700706875"
    phone2, _, _ = asyncio.run(tools._order_identity(ctx))
    assert phone2 == "254700706875"


# ── notes: the lost-update race is closed by a three-way merge ───────────────

def test_notes_merge_keeps_concurrent_appends_and_respects_deletions():
    from app.routers.crm import merge_notes
    base = "Prefers black.\n\nOld note."
    mine = "Prefers black cassocks."                      # edited + deleted "Old note."
    current = base + "\n\n📞 Call (27 Jul): wants 2 mitres."   # appended meanwhile
    merged = merge_notes(base, mine, current)
    assert "Prefers black cassocks." in merged            # operator's edit kept
    assert "📞 Call (27 Jul): wants 2 mitres." in merged  # concurrent append survives
    assert "Old note." not in merged                      # deliberate deletion respected


def test_notes_merge_plain_save_without_concurrency_is_identity():
    from app.routers.crm import merge_notes
    assert merge_notes("a", "a edited", "a") == "a edited"
    assert merge_notes(None, "first note", None) == "first note"
    assert merge_notes("", "", "") == ""


def test_notes_merge_without_a_base_still_never_loses_appends():
    from app.routers.crm import merge_notes
    # An old client that sends no base: current-only paragraphs still survive.
    merged = merge_notes(None, "my text", "📞 Call summary.")
    assert "my text" in merged and "📞 Call summary." in merged
