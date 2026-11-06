# Final Release Readiness Report — slice 1 (2026-11-06)

**Recommendation: do not deploy this slice yet.** It is a draft PR (#316)
awaiting (a) the full-suite result recorded in REGRESSION_SAFETY_REPORT, (b)
the independent verification pass (VERIFICATION_PASS_1.md) and the fixes it
calls for, and (c) the owner's explicit word. The directive's own rule: no
production deployment without approval.

## Measured improvement

| What | Before | After | Where |
|---|---|---|---|
| Customer-state floor (held-out) | 0.539 | 0.787 | BENCHMARK_RESULTS |
| Language guess (held-out) | 0.745 | 0.913 | same |
| Opt-out recognition (held-out) | 0.759 | 0.966 | same |
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
