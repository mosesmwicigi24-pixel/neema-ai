# Customer insights from evidence — slice 14 (2026-11-09)

The second implementation slice of the owner's directive "Unified Customer
Intelligence, Geographic Discovery & Commercial Profiling" (Phase 4,
Insights), following the audit (`CUSTOMER_INTELLIGENCE_AUDIT.md` §5, §8 item 2)
and slice 13 (`CUSTOMER_GEOGRAPHY.md`). No model call is added: every line
the Insights tab now shows is a rule over recorded facts. No migration.

## 1. What the audit found, and what changed

| Audit finding (§5) | Before | After |
|---|---|---|
| Paid and unpaid are the same | every `order_events` row counted as an order and its subtotal as spend; an unpaid order raised the score like a paid one | `services/insights.spend` separates them with the hub's paid states (the predicate the payment reminder and the performance view already use: `hub_payment_status`, else `payment_status`); the profile carries `paid_orders`, `paid_spent`, `unpaid_orders`, `unpaid_spent`, `orders_listed` and the `open_order` (the newest unpaid one within 30 days) |
| The scorer counted every order | "Orders" 10 pts each, "Spend level" on all subtotals | "Paid orders" and "Spend level" on PAID figures; a new row "Open order (unpaid)" (10 pts) so the breakdown says which is which |
| Two computations (panel vs list) | the list read orders and conversations by `wa_id` alone with a user-only phone check; the panel read person-wide with identity-aware phone proof | one builder, `insights.score_inputs`, called by both; the list now gathers orders, conversations, identities and persons in four bulk reads (by handle OR person), so a Messenger-linked customer ranks the same in both places |
| Stage from a prefix | "qualified" = a name + an email or `users.country` (the dialling prefix) | "qualified" = a name + an email or the customer's OWN location (`users.location`, or the geography record's stated/confirmed reading); the prefix qualifies nobody |
| Nothing from conversation evidence | no state, deal, commitment or quotation reached Insights | the commercial snapshot (§2) reads the deal, the customer-state floor, the hold, slice 12's commitment and the orders' payment status, and names one next best action |

`total_orders` and `total_spent` keep their meaning (everything listed; the
hub's lifetime figures when the customer is linked), so nothing that read
them changes. The leads list adds `paid_orders`, `paid_spent`,
`unpaid_orders`, `open_order`.

## 2. The snapshot and the next best action

`insights.snapshot()` returns, for the Insights tab's "Right now" section:
the stage and who set it (auto / manual), what the customer said last and
when (the floor's reading: asked for time, comparing, consulting, ready, says
they have paid, complaint…), an open hold with its end, the open commitment
(item, age, overdue, escalation stage), the open unpaid order, the interest
on the deal (its title or items), the cart, paid vs unpaid, days since
contact, and `next_best_action`.

The action is chosen by precedence, each with its reason, deterministically:

1. an opt-out or "stop" → nothing (final);
2. an overdue promised check → answer it (the customer is waiting on us);
   an open check not yet overdue → confirm it with the workshop;
3. "says they have paid" → verify in the hub;
4. a complaint → resolve it first;
5. a live hold → wait until its end, no outreach;
6. an unpaid order within 30 days → follow it up;
7. a cart and a conversation live within 7 days → close; "ready" → close;
8. a named interest this week → advance it;
9. a cart gone cold → a gentle nudge;
10. a past buyer past their usual gap → check in;
11. otherwise nothing due (with the reason: no live signal / recent contact).

Nothing is stored; the snapshot is recomputed on every read, like the score.

## 3. Writers and readers

| Path | Change |
|---|---|
| `routers/crm._lead_score_parts` | paid semantics, the `open_orders` row |
| `routers/crm._build_profile` | `insights.score_inputs`, the paid/unpaid fields, `snapshot`; new optional arguments `deal`, `commitment`, `opted_out` |
| `routers/crm.get_customer` | loads the open deal (by person, else by the customer's conversations) and `commitments.reading` for the snapshot |
| `routers/crm.list_leads` | four bulk reads; the shared inputs; paid/unpaid fields |
| `services/lead_signals.derive_lead_stage` | the customer's own details, not the prefix; `refresh_lead_signals` passes the person's state |
| `CustomerSidebar.tsx` | "Right now" section (action card + facts), "Paid (of N listed)" and "Unpaid / open" rows; types |

## 4. Behaviour changes a person should know about

- Lead scores move: an unpaid order now adds 10 points as its own row
  instead of 10 as an "order" plus spend points; a paid order scores as
  before. Customers whose only orders are unpaid rank lower than before,
  which is what the owner asked for.
- Leads with a name and a dialling-prefix country but no stated location or
  email are no longer auto-advanced to "qualified"; existing stages are not
  lowered (the advance is forward-only and manual stages are untouched).
- The Insights tab gains a "Right now" section; nothing was removed.

## 5. Tests

- `tests/test_insights.py` (15): the paid predicate (the hub's word first,
  never a guess), the split and the open order (local rows and the hub's
  dicts), the scorer's new row, the shared inputs, the panel and the list
  sharing them, the next-best-action precedence, the snapshot with a hold,
  a commitment, an expired hold, nothing known, and the profile end to end
  (local and hub-linked).
- **What the Postgres parity test found before it passed:** the panel mapped
  a local order without the hub's mirrored payment word
  (`crm._map_local_order` carried `payment_status` only), so a hub-paid order
  read as paid in the list and unpaid in the panel (55 vs 40 points). The
  mapping now carries `hub_payment_status` first, the same precedence as the
  insights module. This is exactly the drift the directive's "one source"
  rule is meant to catch.
- `tests/test_insights_db.py` (1, CI database job): two customers on
  Postgres, one with a hub-paid order and one with an unpaid order and a
  Messenger thread linked by person; the panel and the list give the same
  score for both, paid and unpaid are reported apart on both sides, the
  Messenger thread counts on both, and the snapshot names the unpaid order.
- `tests/test_lead_signals.py` updated to the new "qualified" rule (a prefix
  country alone → "contacted"; an email, a stated location or the geography
  record's reading → "qualified").
- Adjacent suites green: lead score, CRM intelligence, customer intel,
  geography, market evidence, currency gate. Web: `tsc --noEmit` clean.

## 6. Not done in this slice

Segmentation (country / language / channel aggregates); the Activity
timeline; the directive's "explainable lead scoring" beyond the itemised
breakdown that already exists; a stored score history; a currency
conversion for mixed-currency totals (summed as stored, the currencies
listed). The `total_spent` of a hub-linked customer stays the hub's lifetime
figure, which may include unpaid orders the hub lists; the paid figure is
computed only over the orders the hub returns.

## 7. Rollback

`git revert` of the squash commit. Nothing stored to unwind.
