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

## What ships in this slice if approved

Code: PRs #316, #317, #318 (and #319, the eval runner fix). No migration. Android untouched. Web: the Performance view, the rule-proposals card, honest Settings panels.
Rollback: `git revert` of the squash commit; no data changes to unwind
(app_settings `eval_history` is written only by an eval run).
