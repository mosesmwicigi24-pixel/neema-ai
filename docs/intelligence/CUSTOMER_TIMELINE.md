# The customer timeline — slice 15 (2026-11-09)

The third implementation slice of the owner's directive "Unified Customer
Intelligence, Geographic Discovery & Commercial Profiling" (Phase 5,
Activity), following the audit (`CUSTOMER_INTELLIGENCE_AUDIT.md` §6, §8 item 3),
slice 13 (geography) and slice 14 (insights). No model call, no migration;
the events ride the existing `agent_activities` table.

## 1. What the audit found, and what changed

| Audit finding (§6) | Before | After |
|---|---|---|
| The panel's Activity tab is not an activity log | the first five orders and the per-channel counts | a **Timeline** section first: the customer-level events newest first, from the same ledger the conversation view reads; orders and channels below it, unchanged |
| One ledger, one level | eleven "Searched the catalogue" rows beside the order they led to; every event the same weight | every event carries a `level`: **customer** (what happened to or for them) or **technical** (how Neema got there); `services/timeline.py` |
| No filtering, grouping or deduplication | — | runs of the same technical step within 10 minutes fold into one row with a count and the first three details ("Searched the catalogue ×4"); the endpoint takes `?level=customer|technical` and `fold=`; the conversation view's Activity log keeps every step (the owner's 2026-08-19 rule) with a "Show Neema's steps" toggle; the panel shows the customer level with the toggle the other way |
| Nothing written for a discovery, a stage change, a commitment, a hold | — | new customer-level rows through the trail: **Placed the customer** (slice 13), **Stage moved to …** (`lead_signals.refresh_lead_signals`, only when the stage actually moves), **Promised check escalated to the team/supervisor** (`commitments.escalate`, once per stage), **Promised check answered** with the time it took (`deals.clear_team_check`), **Asked for time / Comparing prices / Consulting someone / Says they have paid / Has a complaint / Asked us to stop** (`customer_state.apply`, only on a change of state) |
| Rows with a null conversation never shown | unchanged in this slice (the trail resolves the conversation by handle; a row with none is rare) | recorded in UNFINISHED |

The labels of the new rows are the plain-words lines the trail already uses;
each carries the facts in its detail ("'the cope' — answered by Ann after
42 min"; "on hold until 2026-11-12"; "from contacted, by Neema's read of the
signals").

## 2. Levels

Customer: pickups, escalations, releases, transfers, pauses, flags, a
check-in **sent**, deals and promises, orders, calls, and the trail's
customer-facing tools (an order created or not placed, details or
measurements saved, a hand-over, an escalation, a pause, a team check asked,
a video or checkout link sent) plus the state-change rows above.

Technical: a catalogue search, cards shown, a cart edit, a catalogue link,
a calendar read, a remembered fact, a lead source recorded, an unrecognised
tool step, and a check-in **planned**, **vetoed**, **awaiting approval** or
**failed** (planning is Neema's work; the send is the customer's event).

## 3. Tests

- `tests/test_timeline.py` (9): the level of every kind and label, folding
  with the count, the window and the untouched customer rows, the counts and
  the filter, the trail's labels for the new rows, the endpoint folding and
  keeping the new kinds, the endpoint's filter, and the stage change writing
  one line (and not writing it again for the same signals).
- `tests/test_timeline_db.py` (1, CI database job): on Postgres, three
  searches fold into one technical row; a promised check answered after 42
  minutes, and a hold the customer asked for, each write exactly one
  customer-level row (the same reading again writes none); the ledger returns
  them with their levels and the customer filter leaves no tool rows.
- `tests/test_activity_trail.py` source pin updated (a tool call stays kind
  "tool"; the state-change rows keep their own kind). Existing activity,
  commitment, deal, lead-signal and customer-state suites green.
- Web: `tsc --noEmit` clean; the build result is in the regression report.

## 4. Not done in this slice

The conversation view's dividers (in-thread system events) are untouched.
Rows with no resolvable conversation are still not shown. No stored
"timeline" beyond the trail rows; no per-day grouping headers (the panel
shows "x minutes ago"). Segmentation (audit §8 item 5) is next.

## 5. Rollback

`git revert` of the squash commit. The new trail rows are ordinary
`agent_activities` rows; the previous ledger renders them as plain lines.
