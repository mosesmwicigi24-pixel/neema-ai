# Audit execution verification — second pass (2026-11-06)

This pass repeats the verification with deeper evidence on the two sections the first pass left thinnest: the per-test record (§6 of the instruction) and the pathway-by-pathway trace (§5). It also corrects one claim in my own Stage 1 report that this pass found overstated (§C.4). Everything is read-only; sources are the session transcript on disk, the repository at main `5582965`, the public health endpoint, and test runs against the local scratch Postgres. The first-pass report (`audit-execution-verification-2026-11-06.md`) remains valid where this one does not supersede it.

Supporting files beside this report: `verify/audit-prompt-1.txt`, `verify/audit-prompt-2-expansion.txt`, `verify/implementation-brief.txt` (the instructions, verbatim), `verify/audit-window-inventory.json` (all 61 tool calls of the audit window), `verify/pytest-v-2026-11-06.txt` (per-test results, today), `verify/test-inventory.md` (fixture and assertions per test, generated from the test sources).

---

## A. Original instruction compliance matrix

Unchanged from the first pass except where noted. Summary by requirement row (31 applicable): 17 COMPLETE, 12 PARTIAL, 2 N/A; the detailed rows are in the first-pass report §A.1–A.3. Changes from this pass:

| Row | Change |
|---|---|
| Expansion §1 (complete messaging architecture) | downgraded PARTIAL → **PARTIAL with a count**: 8 pathways absent from the 17-row table (see §B.2 below; the first pass found 7 and missed the SMS bridge, which turns out to be receive-only). |
| Brief §3C / expansion §7 "explicit opt-outs" | **the opt-out coverage claim is narrower than reported**: see §C.4. |
| Brief §7 tests | per-test evidence now recorded (§E, and `verify/test-inventory.md`). |

## B. Actual inspection inventory

### B.1 The audit window, from the transcript
61 tool calls between 2026-11-05 15:25:44 and 22:18:31 UTC: 57 Bash commands (`cat`, `sed -n`, `grep`, `awk`, `ls`, `wc`, `curl` GET of `/api/health` ×2, `python -c` running pure detector functions and `httpx.AsyncClient().timeout`, `alembic heads`), 2 Writes to the scratchpad reports, 2 file sends. No Read/Grep tool, no subagent, no Edit, no git write, no pytest. Files and ranges are listed in the first-pass report §B.1.

### B.2 Pathway traces — every way a customer can receive a message, today

Trigger → chain → external call, with the safeguards the code references on that path (read today; line numbers are main `5582965`). "In the 17" = listed in the expanded audit's table.

| # | In 17 | Trigger | Chain (file:line) | External call | Safeguards on the path (verified by reading) |
|---|---|---|---|---|---|
| L1 | yes | WhatsApp inbound | `wa_native.handle_webhook`:670 → `_ingest_guarded`:523 → `_enqueue`:300 → `_reply_after_debounce`:407 → `runtime.schedule_reply`:2719 → `_run_and_send`:2594 → `messaging._send_waba`:223 → `_post_graph`:212 | Graph `/{phone}/messages` | wamid guard, `agent:seen` 600 s, pause, closer gate, opt-out door (`_handle_opt_out`:2675), slow lane, 30 s debounce with row ids, in-flight lock :2546, `_still_ai`, echo guard, `SendOutcomeUnknown` recorded, scribe → customer state |
| L2 | yes | Messenger/Instagram/Facebook DM | `meta_webhook` :468 → `schedule_meta_reply`:3009 → `_meta_enqueue`:3072 / `_run_meta_after_burst`:3123 → `_run_and_send_meta`:2907 → `meta_send.send_to_channel`:613 → `send_meta_message`:63 → `_graph_post`:35 | Graph `me/messages` | `agent:seen:meta`, pause, closer, slow lane, 12 s burst with row ids (Stage 6), in-flight, `_still_ai`, echo, unknown outcome (Stage 6) |
| L3 | yes | a cassock priced in a turn | inside `_run_and_send` :2644 / `_run_and_send_meta` :2969 (`facts["follow_up"]`) | as L1/L2 | once per customer per 30 d (`cassock_ladder.py:124`); skipped after an unknown outcome |
| L4 | yes | a live turn crashed | `_send_hold_line`:2424 | as L1/L2 | once per thread per 2 h (:2447) |
| R1 | yes | newest row is an inbound ≥ 90 s old | `main._missed_reply_loop`:391 → `reply_sweeper.sweep_missed_replies`:321 → `_run_and_send(hold_line=False)`:472 / `_run_and_send_meta`:474 | as L1/L2 | tick lock, per-thread lock, silenced-since, 3 strikes. **Bypasses `schedule_reply`'s opt-out door** (it re-runs a reply to the customer's own message; the live turn inside still reads the person's state) |
| R2 | yes | human-held thread unanswered 30 min | `main._unclaimed_loop`:436 → `unclaimed.py` → `_send`:107 | as L1/L2 | tick lock, once per customer message. **No opt-out check** |
| S1 | yes | due `agent_actions` row | `actions_loop`:1006 (leader lock :1014) → `process_due`:651 → `claim()`:578 → `_send`:509 or `_send_followup_template`:390 → `templates.send`:137 → `send_wa_template` | Graph `/messages` | opt-out, team check, one per tick, hold, language park, `decide()` (shadow/enforce per rule), approval gate (window, human-held, flagged, >KES 50k, ≥2 sent per deal), repeat check, unknown outcome parks, stamp |
| S2 | yes | 15:00 sweep | **deleted** (Stage 2; `git log` shows `app/jobs/reengage.py` removed in 731fa82) | — | — |
| S3 | yes | 11:00 cart sweep | `recovery_jobs.loop`:145 → `cart_recovery.run`:261 → `_handle`:203 → `actions.plan()` | none (plans a row for S1) | opt-out, quiet hours, basket guard 7 d; sends nothing itself |
| S4 | yes | 10:00 payment sweep | `recovery_jobs.loop` → `payment_followup.run`:347 → `_handle`:251 → `actions.plan()` | none (row for S1; hub re-read at send) | opt-out, quiet hours, once per order |
| S5 | yes | manual campaign | `seasonal_outreach.run`:295 → `_handle`:230 → `send_wa_template` / `_send_waba` / `send_to_channel` | Graph | once per year per customer (:245), quiet hours, human-held. **No opt-out check.** Not in `recovery_jobs.JOBS`; runs only when a person invokes it (no scheduler reference found) |
| E1 | yes | hub webhook (paid/production/shipped/delivered) | `routers/hub_events` → `hub_events.handle_event`:483 → `_celebrate`:203 (or `deferred_loop`:594) → `_send_waba`:279 / `send_to_channel`:289 / `templates.send` | Graph | event id 7 d, per-order 24 h, quiet-hours deferral, opt-out → human, unknown outcome recorded, stamp |
| E2 | yes | call events | `missed_call.py`:86, `recording_notice.py`:156/159 | `send_to_channel` / `_send_waba` / `send_meta_message` | 6 h cooldown (missed call). **No opt-out check** |
| H1 | yes | a person taps Send / Approve / sends media | `conversation.send_agent_reply`:612, `approve_draft`:780, media :918, direct Graph post :977 | Graph | holder rules, human-agent tag outside the window, `clear_team_check` + `withdraw_routine` (Stage 1) |
| H2 | yes | "team answer" compose | `admin.answer_through_neema`:1748 → `_send_waba`:1797 / `send_to_channel`:1802 | Graph | inside window only (409), stamp ANSWER, closes the team check, withdraws nudges |
| H3 | yes | Invite / follow-up template button | `admin.py`:2934 `bridge.send_wa_template` | Graph | person-initiated |
| A1 | yes | Approve a planned action | `POST /admin/actions/{id}/approve` → S1 rules | as S1 | `claim()` |
| X1 | **no** | a Facebook/Instagram comment | `meta_webhook` → `runtime._run_comment_engage`:5622 → `meta_send.reply_to_comment`:220 (public) and `send_private_reply`:267 (DM) | Graph `{comment}/comments`, `{comment}/private_replies` | comment-id dedup upstream, intent classification, negative → human. **No opt-out / pause consult** |
| X2 | **no** | website chat | `routers/web_chat.py`:218 `run_turn` | the HTTP response (no push) | session dedup; reply = answer to the visitor's message |
| X3 | **no** | TikTok (native) / ManyChat | `tiktok_webhook.py`:163 → `schedule_meta_reply` → `tiktok_native.send_to_user`:198; `manychat.py` reply in response | TikTok Business API / ManyChat | `agent:seen:meta`; **no inbound row id** on TikTok (Stage 6 parity is Messenger/Instagram only) |
| X4 | **no** | a hub order created from a chat | `messaging.py`:924 → `_relay_order_confirmation`:1003 → `_send_waba`:1016 | Graph | one per order creation; transactional; **not stamped** by `outreach_log` |
| X5 | **no** | a person requests call permission | `admin.py`:3740–3812 → `wa_calling.request_call_permission*`:221/251, `messenger_calling.request_call_permission` | Graph interactive `call_permission_request` | person-initiated |
| X6 | **no** | product cards / photos inside a live turn | `tools.py`:2824 `send_meta_carousel`, :2843/:2872 `send_meta_media`; WhatsApp interactive card `messaging.py`:250–330 | Graph | within L1/L2's guards |
| X7 | **no** | opt-out acknowledgement (added in Stage 1) | `runtime._handle_opt_out`:2675 → `_send_waba`:2707 / `send_to_channel`:2713 | Graph | once (`already` check), stamped ANSWER |
| X8 | **no** | SMS bridge | `routers/sms.py` | **none** — receive-only by design (docstring :9; no send call in the file) | not a send pathway |

Not pathways (checked): `wa_native._mark_read_and_typing` (read receipt + typing indicator), `post_catalog.sweep_page_posts` (`client.get`, reads posts), `push.py` (staff devices), `hub_client.py` (no customer send).

### B.3 Scope items from §2 of the instruction

| Area | Inspected in the audit | Inspected today | Not inspected |
|---|---|---|---|
| Active AI prompts | `prompt.py` (structure, 9 blocks, rule counts) | all 14 prompt sites inventoried: `prompt.build_system_prompt`, reviewer (`review.py:1364`), comment reader (`runtime.py:3934`), photo describer (:4753), standing-rules improver (`self_qa.py:324`), call analysis, customer-state note, photo check ×2, post catalogue ×2, translate ×2, stylebook | the texts of the 13 auxiliary prompts (only the live prompt was read) |
| Legacy prompts | re-engage's `build_prompt` (read, since deleted) | `git log --diff-filter=D` finds no other deleted prompt file | — |
| Laravel | — | N/A: no Laravel code in this repository; the hub is external | the hub |
| n8n | — | removed in PR #309 the same morning; 8 residual mentions are the hub-bridge alias | — |
| Background jobs / loops / workers | `main.py` loops, `recovery_jobs`, `actions_loop` | 7 loops + their tick locks listed; hourly jobs inside `actions_loop` (self-QA 03:00, stylebook, post sweep 06:00, standup 08:00) read | `agent_eval`, `backfill_*`, `enrich_names`, `fix_phantoms` (manual scripts) |
| Outbound pathways | 17 | 25 (table above) | safeguard review of X1, X3, X4, E2, S5, R2 |
| Conversation state/history | `_history`, scribe, deal model | — | memory module (`agent/memory.py`), `said_once.py` |
| DB models/migrations/constraints/triggers | `agent_action`, `deal`, `message` columns; alembic heads | all unique constraints listed; no triggers in any migration; `messages.waba_msg_id` not unique | the other 40 revisions' content |
| Redis locks/concurrency/retries | leader locks, in-flight, `claim()`, sweeper strikes, `_recover_interrupted` | 40 `nx=True` sites inventoried; `claim()` read | per-site TTL correctness |
| Endpoints/webhooks | WhatsApp statuses, meta webhook (grep), admin team-answer/invite/approve | router inventory (admin 79, crm 33, meta 5, …) | the bodies of most endpoints |
| Payment/quotation/inventory/shipping/order integrations | `payment_followup` hub re-read, `check_order_status` grep, hub events | `hub_client.py` sends nothing; the quotation tool composes text only; order confirmation relay found (X4) | shipping/inventory have no messaging code of their own |
| Fallback/recovery/error handlers | hold line, sweeper, `_recover_interrupted`, 3-strike parking | unknown-outcome branches (both channels) | `agent_health`, `cost_circuit_breaker` |
| Human takeover / approval | `conversation.py` (grep), admin approve, `_still_ai` | H1/H2/A1 chains | holder-rule bodies (#305–#307) |
| Production config/deploys | `/api/health` recovery switches | health: version, mode, rules, jobs, backlog; Dockerfile boot `alembic upgrade head` | the box `.env`, template approvals, model settings, logs, database |

## C. Evidence validation

### C.1 Findings supported by inspected code — unchanged from the first pass (ten root causes, each with file:line).
### C.2 Findings supported by runtime records — recovery switches and run history (health), the live version, the parked-pile breakdown, the 5 s default timeout (executed).
### C.3 Findings supported by reproducible tests — the 139 tests below, re-run today.
### C.4 A claim in my own Stage 1 report that this pass found overstated

The Stage 1 report says "every unprompted sender checks it [the opt-out]". The test backing it, `test_every_unprompted_sender_checks_the_opt_out_and_stamps_its_rows` (`tests/test_outreach_stage1.py:638`), asserts the check in exactly four places: `cart_recovery._handle`, `payment_followup._handle`, `hub_events._celebrate`, `actions.process_due`. Read today, these senders do **not** consult the opt-out: the unclaimed-chat reply (R2), the seasonal campaign (S5), the missed-call and recording notices (E2), the comment-engagement DM (X1), and the sweeper's retry (R1, which bypasses the opt-out door in `schedule_reply`). The live turn itself reads the person's state (Stage 3), so a reply to a message the customer sent is still shaped by it; the gap is on the unprompted event-driven paths S5, E2 and X1. **Reclassified: the opt-out is enforced on the dispatcher, the planners and hub celebrations; NOT VERIFIED (in fact absent) on S5, E2, X1, R2.** Not fixed in this pass (read-only).

## D. Unverified assumptions — unchanged from the first pass (ten items), plus:
11. "Seasonal outreach runs only when a person invokes it" — inferred from the absence of a scheduler reference; the box could run it by hand or cron outside this repository. NOT VERIFIED.

## E. Test evidence

**Executed today** (`verify/pytest-v-2026-11-06.txt`): command `cd apps/api && python -m pytest tests/test_outreach_stage{1..6}.py tests/test_outreach_stage{1,2,3,5,6}_db.py -v -p no:cacheprovider -rs` → **139 passed, 0 failed, 0 skipped** (107 test functions; parametrised cases expand to 139). Per test: name, fixture/input and the first assertions are in `verify/test-inventory.md` (generated from the sources, not written by hand). The Postgres tests run on a scratch database created by the `fresh_db` fixture with the migration's unique index applied; nothing touches production.

**Pre-existing tests only reviewed** (names read, bodies not re-verified by me): `test_one_turn_at_a_time.py` (`_still_ai` before send), `test_holds_reach_a_person_db.py`, `test_hold_line_sweep_db.py` (sweeper strikes, hold lines), `test_actions.py`, `test_quote_followup_db.py` (quote replaced by a newer one), `test_relationship_loops.py` (fit check), `test_recovery_jobs_db.py`, `test_payment_reminder_per_customer_db.py`. They pass in the full suite (3,048 on the final tree) but I did not inspect their assertions line by line.

**Recommended, not executed**: a model-in-the-loop replay (`agent_eval`) of the seven statements and the three threads; a generic "scheduled job retried after a timeout" test; an explicit "quotation updated after a follow-up was scheduled" test of my own.

Scenario coverage (brief §7 and expansion §7), each mapped to an executed test name:

| Scenario | Executed test(s) | Coverage |
|---|---|---|
| three follow-up jobs eligible at once | `test_three_due_rows_for_one_customer_become_one_message`, `test_judas_wednesday_three_due_rows_become_one_message_without_a_greeting` | full |
| follow-up received, no response | `test_one_unprompted_sales_message_a_day_while_a_promise_still_goes` | daily cap only; "pause after two" not tested by me |
| customer asks for a week | `test_a_bare_request_for_time_holds_a_week_and_a_real_message_clears_it`, `test_a_named_day_is_one_promise_and_one_hold` | full |
| comparing prices | `test_willy_comparing_in_arusha_holds_the_nudge_and_tells_the_next_turn` | full |
| reply immediately before a scheduled follow-up | `test_a_customer_who_wrote_after_planning_is_not_nudged_in_enforce_and_is_flagged_in_shadow` | full (shadow and enforce) |
| awaiting availability confirmation | `test_check_availability_records_the_check_and_forbids_closing_on_it`, `test_pastor_emmanuel_team_check_holds_every_sales_follow_up…` (stage1_db) | full |
| Swahili/Hindi/French/English | `test_the_floor_reads_what_the_schedulers_must_never_miss` (parametrised), `test_language_is_read_from_their_own_words`, `test_a_hindi_speaking_pastor…` | detectors and parking; no model reply tested |
| job retried after a timeout | `test_a_dropped_connection_after_the_write_is_an_unknown_outcome`, `test_live_turn_records_an_unknown_outcome_and_never_resends`, `test_planned_action_with_unknown_outcome_parks_for_a_person` | unknown-outcome case; generic retry not tested by me |
| two workers, same message | `test_plan_keeps_one_open_row_per_commitment_and_survives_a_race` (real IntegrityError) | identity race; `claim()` atomicity relies on pre-existing tests |
| quotation updated after planning | `test_scribe_rows_stay_one_per_deal_and_say_what_superseded_what`, `test_a_quote_and_a_cart_are_one_buying_follow_up` | supersession; the quote re-composition relies on pre-existing `test_quote_followup_db.py` |
| malformed template / unresolved placeholder | `test_registry_never_sends_nonsense_parameters`, `test_registry_maps_purposes_and_refuses_what_it_has_no_template_for`, `test_judas_thursday_promise_is_one_row_and_never_the_replenishment_template` | full |
| human takeover | `test_a_colleagues_reply_withdraws_routine_nudges_and_closes_the_check`; `_still_ai` from pre-existing tests | partial (takeover mid-composition not tested by me) |
| simultaneous messages | `test_second_message_during_a_turn_is_seen_once_and_flagged`, `test_history_excludes_the_rows_being_answered_and_notes_an_overlap`, `test_the_burst_buffer_carries_every_row_id` | plumbing; the model's silence decision not tested |
| duplicate scheduling | `test_second_call_for_the_same_purpose_moves_the_one_check_in`, `test_plan_keeps_one_open_row…` | full |
| failed dispatch (5xx) | pre-existing 3-strike tests (reviewed only) | reviewed |
| language switching | `test_the_stored_language_follows_a_switch` | stored preference only |
| explicit opt-out | `test_opt_out_is_acknowledged_once_recorded_for_good_and_ends_outreach`, `test_opt_out_acknowledgement_speaks_their_language`, `test_every_unprompted_sender_checks_the_opt_out…` | **partial** — see C.4 |
| completed purchase | `test_a_payment_reminder_never_chases_money_that_landed`, `test_two_independent_orders_get_one_reminder…` | reminders; "all open rows vetoed on paid" not tested by me |
| legitimate order update during the cap | hub events do not pass through the cap (code read); `test_a_care_row_merged_behind_a_promise_is_deferred_to_morning` (stage1) | by construction + one test |
| delayed webhooks / delivery statuses | `test_delivery_statuses_land_on_the_row_and_a_duplicate_webhook_is_ignored` | full for WhatsApp; Meta statuses not recorded |

## F. Read-only compliance — unchanged from the first pass: the audit window contains no write to the repository, no commit, no test run, no database session; production stayed on fa177bb until the approved deploy at 06:07 UTC on 6 Nov. No byte-level pre-audit baseline exists, so compliance rests on the command log and git, which I state as the limit of proof. This pass changed nothing.

## G. Outstanding verification requirements
1. Box-side reconstruction of the three incidents (trace CLI, logs); until then the attributions stay plausible, not proven.
2. The three DB-stored prompt inputs on the box and one assembled runtime prompt.
3. Opt-out enforcement on S5, E2, X1 (and a decision on R2): a code change, to be approved and done outside this read-only pass.
4. Safeguard review of X1 (comment DM), X3 (TikTok ids), X4 (order-confirmation stamping).
5. Model-in-the-loop experience test for the seven statements and the three threads.
6. Explicit tests: generic job-timeout retry; quotation updated after planning; all open rows vetoed on paid; takeover mid-composition.
7. Owner decision on the scope of "pause after two unanswered".

## H. Final verdict

**PARTIALLY VERIFIED** — unchanged. Denominator 31 applicable requirement rows (17 COMPLETE, 12 PARTIAL, 2 N/A), criterion: a transcript tool call that accessed the implementation plus a traceable report statement. This pass adds eight pathways outside the audited seventeen (one of them receive-only), a per-test record of 139 executed tests, and one correction to my own Stage 1 claim about opt-out coverage. Nothing contradicts a reported root cause; the runtime proof of the incidents still requires the box.
