"""AI lead-stage derivation + forward-only advance (pure, no DB)."""
import types

from app.services.lead_signals import derive_lead_stage, apply_signals


class _U:
    def __init__(self, name=None, email=None, country=None, last=None):
        self.name, self.email, self.country, self.last_message_at = name, email, country, last


def _order(hub=None):
    return types.SimpleNamespace(hub_order_id=hub)


def test_derive_lead_stage_from_signals():
    assert derive_lead_stage(_U(), []) == "new"
    assert derive_lead_stage(_U(last=object()), []) == "contacted"
    assert derive_lead_stage(_U(name="Moses", country="Kenya"), []) == "qualified"
    assert derive_lead_stage(_U(name="Moses", country="Kenya"), [_order(hub=92)]) == "negotiating"


def test_apply_advances_forward_only():
    s, ch = apply_signals({"lead_stage": "new"}, "qualified", None)
    assert ch and s["lead_stage"] == "qualified" and s["lead_stage_source"] == "auto"
    # never downgrade
    s, ch = apply_signals({"lead_stage": "negotiating"}, "qualified", None)
    assert not ch and s["lead_stage"] == "negotiating"


def test_apply_respects_manual_and_terminal():
    s, ch = apply_signals({"lead_stage": "contacted", "lead_stage_source": "manual"}, "negotiating", None)
    assert not ch and s["lead_stage"] == "contacted"
    s, ch = apply_signals({"lead_stage": "won"}, "negotiating", None)
    assert not ch and s["lead_stage"] == "won"


def test_apply_adds_country_tag_deduped():
    s, ch = apply_signals({"tags": ["vestments"]}, "new", "Kenya")
    assert ch and "Kenya" in s["tags"]
    s2, ch2 = apply_signals(s, "new", "kenya")  # case-insensitive, no dup
    assert ch2 is False
    assert sum(t.lower() == "kenya" for t in s2["tags"]) == 1
