# Stages 5 and 6 — rollout control and the long tail

Both merged to main on 2026-11-06 at the owner's word (PR #312 → 4bec7a6 live
at ~07:25 UTC; PR #313 → 5582965, deploy result below). The Stage 1–3 build
(f7a502b) and the Stage 4 read-out (213af6e) went live earlier the same
morning. `OUTREACH_MODE` stays shadow; no rule is enforced.

## 1. Files and functions changed

Stage 5 — the rollout control
- `app/services/app_settings.py` — `get_outreach_control` / `set_outreach_control` / `outreach_control_cached`, `parse_outreach_rules`, `OUTREACH_RULES` (customer_replied, colleague_replied, daily_cap) on the existing `app_settings` table; redis-cached 5 min, cleared on write; `OUTREACH_MODE` / `OUTREACH_ENFORCE_RULES` are only the defaults.
- `app/services/actions.py` — `rule_of(why)`, `_control()`; `process_due` reads the control once per sweep, enforces when the mode is enforce **or** the rule is switched on, tallies `rule_<id>` for every firing.
- `app/routers/crm.py` — `GET/PUT /api/admin/settings/outreach` (PUT admin-only). `app/services/outreach_log.py` and `app/jobs/self_qa.py` report the control, not the environment.
- Web: Settings → **Unprompted messages** card (`SettingsView.tsx`, `lib/api.ts`).
- `docs/OUTREACH_ROLLOUT.md` §3 rewritten around the card.

Stage 6 — the long tail
- `app/routers/meta_webhook.py`, `app/agent/runtime.py` (`schedule_meta_reply`, `_meta_enqueue`, `_meta_drain`, `_run_meta_after_burst`, `_run_and_send_meta`), `app/services/meta_send.py` (`_graph_post`) — Meta parity: inbound ids through the burst buffer; `SendOutcomeUnknown` on a post-write transport failure; recorded, never resent.
- `app/services/outreach_log.py` — `backlog_bucket`, `backlog_age`, `backlog_view`; `/api/health` → `outreach.backlog`. `app/jobs/outreach_backlog.py` — the report and `--retire-older-than N`.
- `app/services/actions.py` (`upsert_follow_up`), `app/services/hub_events.py` (`_plan_fit_check`) — through `plan()`.
- Web: `lib/messageKinds.ts` (`outreachBadge`, `CUSTOMER_STATE_WORD`), `ConversationsView.tsx` (badge under unprompted outbound bubbles; customer-state chip on inbox rows), `lib/api.ts`, `types/index.ts`.
- Tests: `test_outreach_stage5.py` (8), `test_outreach_stage5_db.py` (2), `test_outreach_stage6.py` (8), `test_outreach_stage6_db.py` (2); fakes adapted in `test_outreach_stage2.py`, `test_outreach_stage2_db.py`, `test_relationship_loops.py`, `test_cost_cycle.py`, `test_voice_notes_db.py`, `test_cooling.py`.

## 2. What each corrects

| Gap | Correction |
|---|---|
| enforcement was an `.env` edit and a restart (Stage 5 brief: flags, monitoring, rollback) | a dashboard card, per rule, with the tally beside each switch; rollback is the same switch |
| Meta live turn lacked the Stage 1 overlap and unknown-outcome protection | parity with WhatsApp |
| 595 rows in needs-approval with no way to read them without SSH | counts by reason, age and kind on the health endpoint; a person-run retire command for stale routine rows |
| three planners with their own insert logic | the scribe's row and the fit check on `plan()`; the check-in tool keeps its path (legacy purpose mapping) |
| the inbox could not tell a template or an unprompted message from a reply | the bubble says what it is and how Meta reported it; the row says what the customer last said |

## 3. Design decisions

- **Per rule, not one switch.** The two "someone already answered" rules are near-certain; the daily cap trades recoveries for restraint. Switching them on separately lets the shadow tally argue each case.
- **Environment as default only.** Once anyone touches the card its rows win for good — the same contract as the team-translation switch. "-" stores "no rules, on purpose".
- **Retire is manual, floored at 7 days, routine only.** Nothing automated ever vetoes a promise or care; nothing is ever sent by the command.
- **The check-in tool not moved to `plan()`.** Its unit fakes and its legacy-row mapping made the change cost more than it returned; the unique index protects it regardless.
- **No Android change.** The inbox additions are web-only by instruction; the API fields are there for the app when wanted.

## 4. Tests executed

- Stage 5: 8 unit + 2 Postgres through the real router (admin flips a rule and the next sweep reads it; a non-admin reads but cannot flip). Full suite 3038 passed; CI green on 4a1f77a.
- Stage 6: 8 unit + 2 Postgres (backlog over real rows, retire sparing promises and care; fit check one row per order under the index). Full suite 3048 passed with the one cooling-fake failure fixed in 4d26206; CI on 4d26206: API tests, web, import smoke, lint and build green, Migrations still running at the owner's "merge and build" — re-run by the main gate before the image was built.
- ruff 96 (baseline 115); web `tsc` clean on both.

## 5. Known limitations and risks

- The backlog breakdown reads the parked rows' reason text; rows parked before Stage 1 may have no marker and count as "other".
- The retire command needs a person on the box; it is not on the dashboard by design.
- The customer-state chip shows only states that change what the team should do next; "exploring" and "quoting" stay quiet.
- Day-0 tallies are empty: the dispatcher had not yet met a routine row with a contextual verdict. The first real numbers come from the 08:00 standup and the daily read-out.

## 6. Customer-experience impact

- Messenger and Instagram customers get the same protection as WhatsApp against a second answer and against a duplicate after a dropped connection.
- Nothing changes in what customers receive until a rule is switched on; when one is, the matching messages stop, and the team sees each held row with its reason.

## 7. Migration and rollback

- No migration in either stage. Rollback of a rule: the switch. Rollback of the code: revert the squash commit; the rows and JSON written meanwhile are inert to earlier code.

## 8. Decisions requested

1. After the shadow week (from 2026-11-13): switch on **customer wrote after planning** and **colleague replied after planning** from the Settings card.
2. Once the backlog breakdown has been read: run `python -m app.jobs.outreach_backlog --retire-older-than 30` on the box, or not.
3. Whether the Android app should show the new inbox fields (an app change, outside this programme).

Deploy result for Stage 6: main gate green on 5582965 (API tests, Migrations with the Stage 1–6 Postgres suites, web, import smoke, lint, build); the box reported 5582965 at 08:06 UTC, health ok, replies ok.

## 9. First read of the parked pile (live, 08:06 UTC)

597 rows in needs-approval:

| by reason | | by age | | by kind | |
|---|---|---|---|---|---|
| other (no marker — parked before Stage 1) | 372 | over 30 days | 357 | follow_up (Neema's own promises) | 405 |
| human-held conversation | 112 | 7–30 days | 225 | replenishment (supplies check-ins) | 172 |
| outside the 24h window | 44 | under 7 days | 15 | customer_promise | 12 |
| flagged for the team | 39 | | | quote_follow_up | 6 |
| auto-send failed 3× | 27 | | | buying_follow_up / fit_check | 2 |
| sensitive total / already nudged | 3 | | | | |

Reading: 357 rows are over a month old and 405 of the 597 are Neema's own promise follow-ups, i.e. "I'll confirm and get back to you" rows whose moment has passed. The retire command (`--retire-older-than 30`) would veto only the ROUTINE part of the old rows (follow_up, quote_follow_up, buying_follow_up) and leave the 172 replenishment check-ins and 12 customer promises for a person. Recommended, under the owner's word: run it once at 30 days, then read the pile again.
