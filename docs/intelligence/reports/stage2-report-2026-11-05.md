# Stage 2 — communication consolidation (development branch only)

Commit on `claude/where-are-we-bx9v9w` on top of Stage 1 (58cd89f, CI green).
**Not deployed; the migration is not applied anywhere but a scratch database.**

## 1. Files and functions changed

- `app/models/agent_action.py` — `dedupe_key` (String 80, indexed), `source` (String 30).
- `alembic/versions/e8a1c3d5f7b9_agent_actions_commitment_identity.py` — columns, backfill (`_key`, mirrored from the code), merge of open duplicates, `UNIQUE_INDEX_SQL`; reversible downgrade. `app/main.py` boot statements add the two columns.
- `app/services/actions.py` — `dedupe_key_for`, `open_row`, `plan` (upsert under the index, IntegrityError → refresh existing), `upsert_follow_up` (one scribe row per deal, supersession recorded), `decide` + `_latest_turns` + `_routine_sent_today` + `_shadow_count`, `CODE_COMPOSED_KINDS`, `ROUTINE_KINDS` (+ `buying_follow_up`), `CARE_KINDS` (+ `payment_reminder`); `process_due`: promise-before-nudge ordering, payment live verdict, the decision (shadow/enforce), code-composed drafts, recovery results recorded for planner rows; `_send` carries shadow flags and the planner into the stamp.
- `app/services/quote_followup.py`, `app/services/hub_events.py`, `app/agent/tools.py` — rows filed with identity and source.
- `app/jobs/cart_recovery.py`, `app/jobs/payment_followup.py` — planners (`_handle` plans, `run` unchanged in shape); `payment_followup.live_verdict`.
- `app/services/recovery_jobs.py` — two jobs; re-engage removed. `app/jobs/reengage.py` + its three test files deleted. `app/core/config.py` — `outreach_mode` added; `recovery_reengage_*` removed.
- `app/jobs/self_qa.py` — standup line with the shadow tally. `app/routers/crm.py` — actions list exposes `dedupe_key`/`source`. `docs/NEEMA_HANDOFF.md` — pointers updated.
- Tests: `tests/test_outreach_stage2.py` (13), `tests/test_outreach_stage2_db.py` (5); `test_recovery_jobs_db.py`, `test_recovery_results_db.py`, `test_cooling.py`, `test_outreach_stage1.py` adapted.

## 2. Root causes addressed

| Audit | Correction |
|---|---|
| five senders, none consulting the others (§1.3) | planners file rows; one dispatcher decides and sends; re-engage retired |
| two different "one per deal" rules; deal-less rows counted nowhere (§3.2) | one identity per commitment on the row, DB-enforced |
| no per-customer memory of what was sent today (§1.2) | `_routine_sent_today` reads the Stage 1 stamps |
| "customer replied" honoured only for quote rows (§1.4 stale responses) | `decide()` for every sales row; promises re-compose with context |
| re-engage's timing-only trigger (§1.1 S2) | retired |
| payment reminder could chase a payment that landed between plan and send | hub re-read at send time |

## 3. Design decisions and alternatives considered

- **Semantic identity instead of `(conversation, kind)`** — the owner's concern. `buying:<deal>` merges a quote nudge and a cart nudge (one decision); `payment:<order ids>` keeps two independent orders in one reminder that names both (the existing one-message-per-customer rule) and distinct from a third order; `care:<order>` per order; check-ins per purpose. Alternative rejected: identity on `kind` alone (would merge two orders' fit checks).
- **Partial unique index + application upsert** rather than Postgres `ON CONFLICT` with a partial-index inference: the ORM path stays testable with fakes and readable; the index is the guarantee, the upsert the fast path; the IntegrityError branch is tested on a real race.
- **Shadow by default** for the three contextual rules; the Stage 1 safety rules (opt-out, team check, one message per tick, template purposes, payment paid) are never shadowed. Rationale: those are correctness; the contextual rules trade recoveries for restraint and deserve the comparison week the owner asked for (Stage 4).
- **A nudge merged behind a promise is dropped**, not deferred: the customer heard from us about the matter; a second unprompted contact tomorrow is the behaviour the audit set out to remove. (Care rows still defer rather than drop.)
- **Quote follow-up timing unchanged** (4 h, inside the window). It is an unprompted sales message and is now subject to `decide()`; the owner's decision 1 is honoured in that nothing is planned *to beat* the window any more — a row that comes due after the window closes holds for a person or an approved follow-up template, exactly like a check-in. The delay itself is a tunable for the shadow-week review.
- **Migration imports nothing from the app**: the key rules are inlined and a unit test pins them equal to `dedupe_key_for`.

## 4. Tests executed

- `tests/test_outreach_stage2.py` 13 passed; `tests/test_outreach_stage2_db.py` 5 passed (real Postgres with the index applied).
- Stage 1 suites still green (35 + 6); recovery jobs/results, actions, quote follow-up, companion upsell, relationship loops, hub events, deals, cart, payment, selfcheck: 184 passed in the combined run.
- Migration dry run on a scratch database: 5 seeded open rows with 3 duplicates → backfilled keys, 2 vetoed "[merged: duplicate of the same commitment — migration e8a1c3d5f7b9]", index created, a duplicate insert rejected with IntegrityError, downgrade and re-upgrade clean.
- ruff 96 (baseline 115); `import app.main` ok. Full suite (local, real Postgres, 2969 tests): 2962 passed, 6 failed — two inspection tests in `test_audit_fixes.py` still imported the deleted re-engage module (fixed in 55c2658, the Stage 2 close-out commit), and the four `test_payment_reminder_per_customer_db.py` tests, which pass alone, pass behind every neighbouring group of files when bisected, and pass in CI's Migrations job; an order-dependent leak in that local run that I could not reproduce; the next clean full run on the Stage 3 tree (3024 passed, 0 failed) did not show it. Noted as a flake to watch, not a product defect. CI on 6966080: Migrations (fresh-DB replay with the Postgres suites), import smoke, lint, web all green; API tests red on exactly the two stale tests above. CI on the close-out commit is reported with Stage 3.

## 5. Known limitations and remaining risks

- Stage 3 items are not here: the per-turn state note (needs time / comparing / consulting / paid / language), language preference storage, the prompt precedence line, Meta live-turn parity for inbound ids and unknown outcomes.
- `recovery_results` keeps `reengage` in its job list for historical rows; the Reports page label stays.
- `plan()` is used by the new planners; the scribe, the check-in tool and the fit-check planner still use their own upsert logic (now keyed) — the index protects all of them; consolidating them onto `plan()` is a later clean-up.
- `_routine_sent_today` counts Stage 1 stamps only; messages sent before Stage 1 deployed are invisible to the daily cap (correct from the first deployed day).

## 6. Customer-experience impact (when deployed)

- One matter, one row, whatever path or worker raised it; a customer who was quoted and also built a cart hears once.
- Nobody is nudged after they wrote or after a colleague answered (shadow: observed; enforce: held).
- Two orders, one reminder naming both; no reminder once paid.
- No afternoon "check-in" sweep.

## 7. Migration and rollback

- `alembic upgrade head` runs at container start (Dockerfile CMD) — the migration applies on the deploy. Backfill and merge touch only OPEN rows. Downgrade drops the index and the two columns; vetoed duplicates stay vetoed.
- `OUTREACH_MODE` flips without a deploy; `RECOVERY_CART_ENABLED` / `RECOVERY_PAYMENT_ENABLED` still gate the planners.

## 8. Decisions requested

1. Approve the Stage 2 commit for the staged PR (merge = deploy, held for your word).
2. Keep `OUTREACH_MODE=shadow` for the first week after deploy, then read the standup tally and Reports before `enforce`.
3. Quote follow-up delay: keep 4 h (inside the window), or move to the next working morning — your call for the shadow week.
