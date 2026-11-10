# Final Release Readiness Report — slices 1–4 (2026-11-06)

**Operational note (2026-11-07): the Anthropic API balance ran out at ~06:30 UTC and was topped up at ~08:00; the live agent recovered at 08:04 UTC and the missed-reply sweep cleared the five hanging threads by 08:09 (OWNER_ACTIONS §0, REGRESSION_SAFETY_REPORT). Evaluation runs stay stopped on the owner's word.**

**Status: slices 1–10, both eval fixes and the evidence dossier are LIVE (box on `78535d8` at 12:41 UTC on 7 Nov: slice 10 = PR #342, the inbound heartbeat in `/api/health`; before that `b0e9eec` at 06:48 UTC: slice 9c = PR #338, the `availability_claim` soft finding and the availability tool's two-sided note; before that `19e4952` at 06:09 UTC: slice 9b = PR #336, the evaluation runner's opt-out door made faithful to the live one, no live-path change; before that `420b5fc` at 05:13 UTC: slice 9 = PR #334, the approved `interceptaction` enum migration, applied by the container at start; before that `b6cae00` at 02:10 UTC; slice 8 R1 = PR #328: the "turn raised" root cause proven and fixed; 8b = PR #329: the judge aligned with the gate, the `payment_method` soft finding, six sales labels; 8c = PR #330 merged as 369e4b6, on the box at 02:18 UTC; 7c = PR #326: the runner stages the hub outage its tool-failure cases ask for, seven safety labels corrected; slice 7 = PR #324: the language metric and figure judge corrected, a lone "Sawa" no longer flips a customer's stored language, the eval workflow takes a case file; 7b = PR #325: enum-label drift check, second engine removed; earlier: slice 6 = PR #323: runner repairs and the deterministic silence for bare closers, measured on the blind floor 0.887 → 0.956)** — slice 1 (PR #316) squash-merged as `c8c3356` at 17:18 UTC
on the owner's word ("merge and deploy when green"), after the full suite
(3,294 passed, 0 failed) and CI were green on its head. The box reported
`version = c8c3356…` at ~17:52 UTC with `agent.replies = ok`, outreach still
in shadow mode with no enforced rules. The first main build hung 24 minutes
on the runner's apt step before any test ran; it was cancelled and re-run.
The verification pass's S1/S2 findings are fixed or recorded
(VERIFICATION_PASS_1 response table). Slices 2–3 (PR #317) merged as `34d371e` at 18:53 UTC after verification
passes 2 and 2b (every S1/S2 fixed) and green CI; **live on the box at
~19:22 UTC** (replies ok, outreach still shadow; the first main build hung
on the runner's apt step and was re-run). Slice 4
(PR #318: durable opt-out without a person, an unowned hold left to the
sweep, dated facts, Meta receipts, figure facts, rule-proposals card, the
one-step real-model run) merged as `d084e91` at 19:44 UTC after
verification passes 3 and 3b (every S1/S2 fixed, two test gaps closed) and
green CI; **live on the box at ~19:55 UTC** (replies ok, outreach still shadow;
the bounded apt step in CI held this time). Full suite on the merged main:
3,313 passed, 0 failed. Verification pass 4 (an audit of every VERIFIED
COMPLETE row against the merged code) is running.

## Measured improvement

| What | Before | After | Where |
|---|---|---|---|
| Customer-state floor (blind set, never read) | 0.725 | 0.780 (intervals overlap) | BENCHMARK_RESULTS |
| Language guess (blind set) | 0.528 | 0.930 (separated) | same |
| Opt-out recognition (blind set, n=34) | 0.912 | 0.971 (overlap) | same |
| False opt-out on "stop sending the trays" | yes | no | same |
| 100-point Excellence Score | NOT MEASURED | NOT MEASURED | model-dependent dimensions blocked |

The 10-point aggregate improvement is **not demonstrated**: the dimensions
that carry most of the weight (reliability on transcripts, task success,
emotional and consultative judgment) need the real-model run and human
raters. What is demonstrated is a large, interval-separated gain on the
deterministic layer that gates holds, paid-claim notes, opt-outs and closer
silence, plus fail-closed safeguards that had been fail-open.

## Remaining risks

1. Production behaviour of the fail-closed gate: more held replies if the
   reviewer model is unreachable (by design); watch `held/gate_error`.
2. Wider floor readings → more holds; a false "needs time" delays a sale by
   up to 7 days (the hold) — mitigated by W2-3 (a question or buying signal
   lifts it).
3. One-time prompt cache rewrite (cost blip on first turn per conversation).
4. The Meta door now returns 502 on a capture failure: a persistent bug would
   make Meta retry repeatedly (same posture as WhatsApp today).

## Items requiring owner approval

- ~~Merge and deploy PR #316 (production deployment).~~ Done, c8c3356 live.
- **Database migration a9c1e3f5b7d9** (the `interceptaction` enum gains `flag` and `escalated`) ships with the slice-9 image on the owner's approval of 2026-11-07; the container runs `alembic upgrade head` before uvicorn, the statement is `ADD VALUE IF NOT EXISTS` (idempotent, no table rewrite, no row lock).
- The `/api/health` hub wait (UNFINISHED_REGISTER): a one-function change to serve only the cached price audit — production behaviour, waits for the owner's word.
- ~~A model key on the box or as the repository secret~~ — the secret exists; the first run crashed in the runner (fixed in PR #319); the run on the fixed branch is in progress.
- Saving the dashboard credential from a browser (for production-derived cases).
- Naming human raters and native speakers.
- A post-conversation rating ask (an unprompted message).
- Retiring the legacy bridge order path and the expiring shortener (W9-4).
- A DB idempotency key for orders (migration).

Slices 1–18 are live on the box at b5dda19 (14:27 UTC, 9 Nov) — every implementation slice of the Customer Intelligence directive and the validation run's one fix. The owner's later word (13:0x UTC) allowed one validation run: 10/11 turns, the Bahrain/Kenya case 3/3, one model-free defect found and fixed in slice 18 (`BENCHMARK_RESULTS.md`).

## Slice 19 (2026-11-10) — merged as 68da764, live (on the box 07:28 UTC)

Intent discernment and graceful close (`INTENT_DISCERNMENT.md`): one kind boundary for a request for goods without payment, one brief line on a repeat, then no automatic reply to that same request; buyers, negotiators, credit, samples, promotions, donors, complaints, payment claims and requests for a person are never part of it. Sales follow-ups and the seasonal campaign wait while a boundary stands, with no time expiry. No migration. One model pass read (12/14); the corrections after the owner's four-risk review are tested but not seen with the model.

## Slice 18 (2026-11-09) — merged as b5dda19, live (on the box 14:27 UTC)

The directive's Phase 9 run (`customer_intelligence.jsonl` × 1, run 42624670362): 10/11 turns. The failure — a Kenyan number saying "Dubai, UAE" placed in Kenya and quoted in shillings — was in `iso_from_text`, which knew only the formal country names and the Kenyan towns. Country aliases and well-known cities now name their country (`CUSTOMER_GEOGRAPHY.md` §5c). No migration; no API change; the resolver's other callers (operator country, shipping destination, Meta evidence, Swahili guard) widen in the same direction.

## Slice 17 (2026-11-09) — merged as 4bd5ac9, live

Verify / correct on the Profile tab (web only; `CUSTOMER_GEOGRAPHY.md` §5b): a "Placement" row appears only while the current placement is unconfirmed, with its confidence, the earlier readings on hover, and a one-click Confirm that records the operator's confirmation through the existing PATCH (no API change). One Postgres test added for the ISO-only confirmation. Rollback: revert the squash commit.

## Slice 16 (2026-11-09) — merged as 35c6740, live

Customers in aggregate (`services/segments.py`, `CUSTOMER_SEGMENTS.md`): `GET /admin/reports/segments` and a Customers tab on Reports — by market (the geography decision; confirmed placements apart from inferred and unknown), by language, by channel; counts only, three bulk reads, nothing stored. No model call, no migration. Tests: 5 new. Rollback: revert the squash commit.

## Slice 15 (2026-11-09) — merged as c936832, live

The customer timeline (`services/timeline.py`, `CUSTOMER_TIMELINE.md`): a level (customer / technical) on every event of the activity ledger, repeated technical steps folded into one row with a count, `?level=` and `fold=` on the endpoint, and new customer-level rows written through the existing trail when a stage moves, a promised check is escalated or answered, or the customer asks for time / claims payment / complains / asks to stop (once per change). The panel's Activity tab gains a Timeline section (customer level, Neema's steps behind a toggle); the conversation view's Activity log keeps every step with a toggle to hide them. No model call, no migration. Tests: 10 new (1 on Postgres in the CI database job), one source pin updated. Rollback: revert the squash commit; the new rows render as plain lines under the previous code.

## Slice 14 (2026-11-09) — merged as 345a20b, live

Insights from evidence (`services/insights.py`, `CUSTOMER_INSIGHTS.md`): paid and unpaid orders kept apart with the hub's paid states; one set of score inputs shared by the panel and the leads list (the list now reads person-wide in four bulk queries); "qualified" needs the customer's own details, never a dialling prefix; the commercial snapshot with ONE next best action by precedence (opt-out, overdue check, payment claim, complaint, hold, unpaid order, live cart, readiness, interest, cold cart, buying rhythm). No model call, no migration, nothing stored. Customer-visible: nothing (operator views only). Operator-visible: the "Right now" section on Insights, paid/unpaid rows, a changed score for customers whose only orders are unpaid. Tests: 16 new (1 on Postgres in the CI database job); the lead-stage test updated to the new rule. Rollback: revert the squash commit.

## Slice 13 (2026-11-09) — merged as d402c0a, live

Geography with provenance (`services/geography.py`, `CUSTOMER_GEOGRAPHY.md`): one record on the person for the telephone country, the probable country, a confirmed residence, the shipping destination and the city, each with source, confidence and time; one decision shared by the WhatsApp turn, the shared catalogue link, the Meta evidence chain and the profile. No migration (JSONB). Customer-visible: a WhatsApp customer who says they are in Kenya or Zambia is quoted in that market from that turn, whatever their number's country; the profile shows the decided country with its source on hover and the telephone country beside it when they differ. Operator-visible: a country typed by name now sets the ISO and flag; an edit is recorded as confirmed. Tests: 31 new (4 on Postgres in the CI database job); adjacent suites green; web typecheck clean. Rollback: revert the squash commit; the `geo` key is ignored by the previous code.

## Slice 12 (2026-11-07) — merged as c04dda8, live

Accountable commitments (a new service, a 5-minute sweep, three settings, a health block), the person door (a detector and a route before the model on both inbound paths), the hard language guard with the held line in the customer's language, three relabelled safety cases, a runner feature (`setup.team_check`, `expect.commitment`). No migration. Customer-visible: an overdue promised check is owned in one line and escalated with an owner; "put me through to a person" is routed at once with an honest line; a wrong-language draft is held in the customer's language. Rollback: revert the squash commit (`ACCOUNTABLE_COMMITMENTS.md` §7).

## Slice 11 (2026-11-07) — merged as 4e01eb4, live

A prompt rule, two floor phrasings, a stricter `hold_ack` verdict in the two
scorers, eleven cases, fourteen tests, no migration, no new sender. The
customer-visible change: on "I'll come back" Neema keeps the item and names
the one step instead of asking when to be reminded; on a firm decline, one
gracious line. Rollback: `git revert` of the squash commit. Measured after the
owner lifts the evaluation stop (`COMMERCIAL_EI.md` §7).

## What ships in this slice if approved

Code: PRs #316, #317, #318 (and #319, the eval runner fix). No migration. Android untouched. Web: the Performance view, the rule-proposals card, honest Settings panels.
Rollback: `git revert` of the squash commit; no data changes to unwind
(app_settings `eval_history` is written only by an eval run).
