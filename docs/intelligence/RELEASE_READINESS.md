# Final Release Readiness Report — slice 1 (2026-11-06)

**Status: the owner has given the word to merge and deploy when green**
(2026-11-06, ~17:00 UTC). Gates before the merge: the full suite green on the
repaired state, CI green on the head. The verification pass's S1/S2 findings
are fixed or recorded (VERIFICATION_PASS_1 response table).

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

- Merge and deploy PR #316 (production deployment).
- A model key on the box or as the repository secret (to run the evaluation).
- Saving the dashboard credential from a browser (for production-derived cases).
- Naming human raters and native speakers.
- A post-conversation rating ask (an unprompted message).
- Retiring the legacy bridge order path and the expiring shortener (W9-4).
- A DB idempotency key for orders (migration).

## What ships in this slice if approved

Code: see PR #316. No migration. Android untouched. Web: one new view.
Rollback: `git revert` of the squash commit; no data changes to unwind
(app_settings `eval_history` is written only by an eval run).
