"""The inbox names the customer's weight: a repeat buyer wears their number.

Owner (2026-08-09): rows carry the country by NAME (bright orange chip) and,
for anyone who has completed orders before, a badge with the count beside the
name. "Completed" is strict: the hub says money landed (PAID_STATES) on a
hub-linked order — an abandoned cart or an unpaid order never earns the badge.
Counted person-first (a Messenger↔WhatsApp merge shows ONE history), wa_id as
the fallback view, and the row takes max() of the two — they are overlapping
views of the same rows, never disjoint halves, so max never double-counts.
"""
import inspect

import app.main  # noqa: F401 — registers all SQLAlchemy models


def test_inbox_rows_count_paid_hub_orders_only():
    from app.routers import admin
    src = inspect.getsource(admin.list_conversations)
    assert '"orders_count"' in src
    assert "PAID_STATES" in src                        # money landed, not "open"
    assert "hub_order_id.isnot(None)" in src           # real hub orders only
    assert "person_orders" in src and "wa_orders" in src
    assert "max(person_orders.get" in src              # person-first, never summed
    # Grouped queries keyed by person/wa — the list never queries per row.
    assert ".group_by(OrderEvent.person_id)" in src
    assert ".group_by(OrderEvent.wa_id)" in src


def test_paid_states_are_the_settled_ones():
    from app.jobs.payment_followup import PAID_STATES, is_paid
    assert "paid" in PAID_STATES and "completed" in PAID_STATES
    assert is_paid("PAID") and is_paid(" completed ")
    assert not is_paid("unpaid") and not is_paid("partial") and not is_paid(None)
