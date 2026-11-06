# Ten-Advancement Implementation Register

One entry per change. Columns: workstream · baseline evidence · verified gap ·
the change (smallest effective) · existing system it extends · simpler
alternative rejected and why · tests · measured outcome · regressions checked ·
status (VERIFIED COMPLETE · IMPLEMENTED BUT NOT VERIFIED · PARTIALLY COMPLETE ·
BLOCKED · NOT STARTED). Nothing here is deployed; deployment needs the owner's
explicit word.

## W2-1 · The deterministic floor reads what customers actually write

- **Baseline:** floors-baseline-held-out.json — customer state 0.539, language
  0.745, opt-out 0.759; developer negatives: one false opt-out ("stop sending
  the trays").
- **Verified gap:** INVESTIGATION_REPORT 2.1, 2.2, 2.5 and the opt-out false
  positive; the misses were inspected by state (BENCHMARK_RESULTS).
- **Change:** widened regexes in `customer_state.py`, `intent.py`, `deals.py`,
  `runtime._ACK_RE`, `voice.looks_swahili`; precedence: a strong complaint
  outranks a payment mention; readiness with a named time is readiness; a
  question softens "comparing"/"needs time" unless a date was named; an
  explicit opt-out survives a trailing question; bare acknowledgements stay
  language-neutral.
- **Extends:** the Stage 3 floor and the Stage 1 opt-out recogniser — no new
  module, no model call added.
- **Rejected:** a model classifier for intent (would add a call per message
  and move the floor's guarantees onto the model; the research memo's
  multi-turn degradation results argue for keeping the floor deterministic).
- **Tests:** `tests/test_intelligence_floors.py` (118 parametrised cases) +
  unchanged existing suites; full suite run recorded in
  REGRESSION_SAFETY_REPORT.
- **Outcome (held-out):** state 0.787 [0.733, 0.833], language 0.913,
  opt-out 0.966, negatives 0 misses.
- **Status:** PARTIALLY COMPLETE — the held-out claim was withdrawn after verification pass 1 (the tuning had seen held-out phrasings); the blind-set score is the measure. The first widening misfired on ordinary buying messages and was narrowed with the verifier's sentences as negatives (neg-021…043). Live effect IMPLEMENTED BUT NOT VERIFIED.

  until the real-model run.

## W1-1 · The reply gate fails closed

- **Baseline:** runtime.py:2214–2231 sent the unverified draft on any gate exception; no test covered the branch (INVESTIGATION 1.1).
- **Change:** `_gate_failed_closed()` — a gate error is the held outcome: silence on a closer or a public comment, otherwise the holding line, the colleague flagged with the error, the verdict tallied as `held/gate_error`.
- **Extends:** the existing held path (`_flag_held_reply`, `held_recently`, the hold lines). **Rejected:** retrying the gate (a second failure in the same turn is likely; the customer would wait twice).
- **Tests:** `test_intelligence_w1_fail_closed.py` (held outcome, silence cases, call-site assertion).
- **Status:** IMPLEMENTED BUT NOT VERIFIED in production (needs a gate error to occur; the eval records `review=held` when it does).

## W1-2 · The opt-out door on every inbound channel

- **Baseline:** only `schedule_reply` (WhatsApp) called `_handle_opt_out`; Messenger, Instagram, TikTok (native and relay) and web chat had no recogniser (INVESTIGATION 1.2, D §9 #1).
- **Change:** `schedule_meta_reply` has the same door; web chat and the ManyChat relay record the preference and acknowledge once; the sweeper's cross-channel bridge checks `opted_out` before composing.
- **Extends:** `intent.record_opt_out` / `acknowledgement` / `opted_out` — no new store.
- **Tests:** same file (door placement before the closer gate and the model turn; the Meta door exercised with a fake).
- **Status:** IMPLEMENTED BUT NOT VERIFIED on Meta in production (`meta_agent_reply` flag value unknown).

## W1-5 · The takeover re-check fails closed without losing the reply

- **Baseline:** `_still_ai` returned True on a DB error (talk over a colleague).
- **Change:** returns None on error; both senders then do not send and return "not handled", so the missed-reply sweeper retries later.
- **Status:** IMPLEMENTED BUT NOT VERIFIED (DB-error path).

## W1-9 · A payment acknowledgement needs the hub's word (hard gate rule)

- **Baseline:** "PAID IS A CLAIM" lived as a prompt rule and a soft, dm-only reviewer rule; no code stopped "thank you for your payment" after "I've paid" (INVESTIGATION 1.9; C summary).
- **Change:** `review.paid_ack_without_source` — a hard `paid_ack` finding unless a `check_order_status`/`create_order` result in this turn carries a paid-like state (the same vocabulary as `payment_followup.PAID_STATES`). "The team will match it to your order" passes.
- **Extends:** `rule_findings` beside the `status` rule, same shape. **Rejected:** a model-only rule (that is what existed).
- **Tests:** `test_intelligence_w1_grounding.py`; `test_reply_review`, `test_checker_rules`, `test_official_payment_lines` unchanged.
- **Amended (verification 1):** the first cut flagged "we have not received your payment yet" and "once your payment is confirmed we start production"; now guarded against negation and condition, and it runs in every mode.
- **Status:** VERIFIED COMPLETE at the rule level (behaviour tests incl. the verifier's four); live effect IMPLEMENTED BUT NOT VERIFIED.

## W4-1 · No manufactured urgency, scarcity or discount from nowhere (hard gate rule)

- **Baseline:** prompt-only; no rule kind for it (INVESTIGATION 4.1; research memo §6).
- **Change:** `review.manufactured_pressure` — hard `pressure` finding for the urgency and scarcity words ("today only / last piece / only N left / hurry / offer ends tonight / don't miss out / leo tu") unless a promotion tool in this turn supplied the offer. Discount FIGURES stay the `figure` rule's business (every money figure from a hub row or a recorded promotion) — the first cut also flagged "10% off" and the existing verification stress tests showed that broke legitimate campaign replies, so it was narrowed. An honest "we don't offer discounts" passes.
- **Amended (verification 1):** flagged "no hurry, take your time" and "the last one we sent you"; now needs an imperative hurry or "last X left", is exempt for a stock figure a tool returned, and is **SOFT** (one rewrite) until the live tally shows no false findings.
- **Status:** PARTIALLY COMPLETE (soft; rule-level tests).

## W1-7 · A promised offer that cannot be read is surfaced, not dropped

- **Baseline:** `granted_promise` → None on a redis error; the order went out without the discount, silently (INVESTIGATION 1.7).
- **Change:** the business rule "no offer recorded beats no order created" stands; the gap is now written on the order note, returned to the model as `offer_unverified` with a next step ("a colleague confirms the final amount"), and logged. **Rejected:** refusing the order (the owner's recorded trade-off prefers the order).
- **Amended (verification 1):** the team is told (`_team_note`) in the same branch, not only the model.
- **Status:** IMPLEMENTED BUT NOT VERIFIED (redis-error path).

## W1-13 · The Meta door no longer acks a message it lost

- **Change:** a capture exception on `/api/meta/webhook` answers 502 like the WhatsApp door, so Meta redelivers; the mid dedupe absorbs the repeat.
- **Status:** IMPLEMENTED BUT NOT VERIFIED in production.

## W1-6 · Tools that act before the gate — decision: no deferral

- **Finding:** `send_product_cards`, `send_measurement_guide` and `create_order` act during the tool loop, before the words are reviewed (B §5).
- **Decision:** cards and the guide carry hub data only (grounded by construction); deferring their sends until after the gate would create a worse failure (words promising cards that then fail to send, which the `photos` rule cannot see). Order creation keeps its own guards and the held path flags the colleague with the draft and the order. Recorded as an accepted, reasoned limitation; revisit if the real-model run shows held replies following sent cards.
- **Status:** NOT APPLICABLE (by decision), evidence recorded.

## W7-4 · An empty reply is silence when the turn was told silence is right

- **Baseline:** the loop turned any empty text into a nudge call and then "One moment — let me check on that for you.", the line the prompt bans (INVESTIGATION 7.4; A §0.1).
- **Change:** when the overlap note was attached or the inbound is a closer, an empty reply ends the turn as silence; the words-only nudge and the stall line remain the last resort for a real question.
- **Status:** IMPLEMENTED BUT NOT VERIFIED (real-model run shows it as `silent` turns).

## W2-3 · A hold lifts when the customer comes back

- **Baseline:** only model-note states cleared a hold; the floor never returns them (INVESTIGATION 2.3).
- **Change:** `customer_state._buying_message` — a question or a buying signal from a customer on hold lifts the hold.
- **Status:** VERIFIED COMPLETE — a behaviour test calls `apply()` with a held deal and a question (verification 1 downgraded the source-string version).

## W2-4 · The scribe never erases a team check or a hold

- **Change:** `deals._merge_next_action` — an open team check keeps its kind and tucks the new intent under `then`; a hold survives.
- **Status:** VERIFIED COMPLETE — `_merge_next_action` tested, and `scribe_update` itself tested with a deal holding an open team check while the customer names a day (`test_the_scribe_keeps_the_team_check_when_the_customer_names_a_day`): the team check stays, the promise is tucked under it, the check-in is queued.

## W9-2 · `handoff_to_human` rings the team

- **Change:** the tool now files the same team note the other hand-over paths file (`_team_note`), never on a draft; result carries `team_told`.
- **Status:** IMPLEMENTED BUT NOT VERIFIED.

## W5-2 · A caption-less photo stays a turn in history

- **Change:** history renders an inbound image/video row with no text as "[the customer sent a photo]" instead of dropping it.
- **Status:** IMPLEMENTED BUT NOT VERIFIED.

## W3-1 · A complaint earns the care-first length

- **Change:** the length target's `negative` flag also reads the customer-state floor's `complaint`. The computation now lives in `runtime.length_target_for` (the live turn and the evaluation harness call the same function — the harness's mirror had lacked the complaint term).
- **Status:** VERIFIED COMPLETE — behaviour test on `length_target_for`: a complaint the comment detector misses lands on the 60-word care-first target; a price ask does not; the harness scores the same function.

## W8-1 · Language continuity checked without the model reviewer

- **Change:** `review.language_mismatch` — a soft, deterministic `language` finding for Hindi script, Swahili, French and Portuguese customers whose draft plainly reads as English (three or more English function words and none of the customer's language); English and mixed left alone. The first cut flagged a short Swahili price line ("Trei tatu za … ni KES 66,000") — caught by the existing stress tests and narrowed.
- **Amended (verification 1):** flagged a short Swahili price line; now needs a draft that plainly reads as English. SOFT by design: one rewrite, never a hold.
- **Status:** VERIFIED COMPLETE at rule level (soft).

## W7-6 · State writes take the row lock

- **Change:** `intent.record_opt_out` and `customer_state.apply` lock the person row before rewriting `state` (the `state_lock` contract).
- **Status:** VERIFIED COMPLETE — behaviour tests: both writers hand the person to `lock_for_write` and write to the row it hands back (the re-read row, not the stale copy). The best-effort fallback is a recorded trade-off with its own test: when the lock cannot be taken, the opt-out is still written unlocked, because a lost opt-out is the worse failure.

## W7-2 · The newest learned rules survive the combined cap

- **Baseline:** prompt.py:216 sliced standing orders + learned rules at 1,800 characters from the front (INVESTIGATION 7.2).
- **Change:** `prompt._cap_standing_orders` keeps the whole standing orders and the newest learned-rule lines within the cap.
- **Tests:** `test_intelligence_w2_w7.py`; `test_standing_orders`, `test_learning_loops` unchanged.
- **Status:** VERIFIED COMPLETE at unit level.

## W7-3 · Four prompt contradictions resolved toward the code's own behaviour

- **Baseline:** "ask EXACTLY ONE question" vs "not every message ends in a question"; a closer "gets ONE short warm sentence" vs the closer gate's silence; three competing length numbers; "ONE '?' per message" (INVESTIGATION 7.3, A §4.3).
- **Change:** "at most one question, and only when it moves the order"; a bare closer "gets NOTHING back — reply with an empty message" (now honoured by W7-4); the LENGTH line on the message is the cap and overrides the prose numbers; "at most one '?', none when nothing moves the order". Block 0 changes once (one fleet-wide cache rewrite).
- **Tests:** `test_brevity_contract`, `test_house_voice`, `test_meta_audit` updated to the new wording where they pinned the old.
- **Status:** IMPLEMENTED BUT NOT VERIFIED (the real-model run measures questions per reply and length).

## W9-1 · After-sale outcomes say whether the customer was told

- **Change:** every `_celebrate` return carries `customer_told` (True / False / None for unknown delivery); "handled" no longer implies a customer heard anything (INVESTIGATION 9.1).
- **Status:** VERIFIED COMPLETE — corrected after verification pass 4, which found only two of the seven branches asserted: `test_every_celebrate_branch_says_whether_the_customer_was_told` now pins the opted-out (False), rules-held (False), unknown-delivery (None) and template (True) branches as well as the two freeform/notified cases already tested.

## W10-3 · The usage row logs the model that actually answered

- **Change:** `_served` prefers `llm.last_model` (set after a fallback) over the configured `_model`; now `runtime.served_model(llm)`, used by the verdict record and the usage row alike.
- **Status:** VERIFIED COMPLETE — behaviour test on `served_model` (last_model wins; falls back to the configured model; empty when the client says nothing) plus the usage-row pin.

## W1-5 (amended) · Fail closed on infrastructure errors only

- The first cut returned None on any exception, which also muted every unit test whose fake session raises an AttributeError. The takeover re-check now fails closed on `SQLAlchemyError`, `OSError` and timeouts (what a database outage raises) and assumes AI on a programming error inside the check, with a warning. Both branches tested.


## Slice 5 (2026-11-06) · model-independent reliability defects from the registers

Six open rows that needed neither the model run nor an owner decision, each
taken through investigate → smallest change → behaviour test → mutation
check (harness `v5-mutate.py`, 12 mutants, 12 killed).

### S1 · Turn failures are classified by exception type before text

- **Change:** `agent_health.classify` checks the exception's type first: SQLAlchemy, asyncpg and psycopg errors → `database`; the gate's `RuntimeError("reply gate error: …")` → `gate`. Neither is ACTIONABLE or AI_DOWN, so a database outage no longer reads as "check ANTHROPIC_API_KEY" on health or pauses the missed-reply sweep for an hour; each has its own operator line.
- **Status:** VERIFIED COMPLETE — `test_a_database_error_is_never_read_as_the_ai_account` (an OperationalError whose text says "permission denied" and a ProgrammingError saying "does not exist"), `test_a_driver_error_counts_as_database_by_module`, `test_the_gate_s_own_error_is_named_gate_not_other`; mutants S1, S1b killed.

### S2 · The opt-out read has three answers; unprompted senders never send on a guess

- **Change:** `intent.opt_out_state` returns yes / no / unknown ("unknown" = the durable read could not be made: no session or a database error). `opted_out(…, fail_closed=True)` maps unknown to True and is passed by every Neema-initiated sender (cart recovery, seasonal, payment follow-up, the sweeper's cross-channel bridge, hub-event celebrations, missed-call text, recording notice). The dispatcher (`actions.process_due`) reads the three-state form and **defers** an unreadable row to the next tick — it is neither sent nor vetoed nor parked on a guess. Doors that only decide whether to re-acknowledge keep the fail-open default.
- **Status:** VERIFIED COMPLETE — `test_an_unreadable_preference_is_unknown_not_no`, `test_a_readable_no_is_still_no_for_a_sender`, `test_cart_recovery_skips_the_nudge_when_the_preference_cannot_be_read` (query error and no-session), `test_the_dispatcher_defers_a_row_it_cannot_read_the_preference_for` (through `process_due`: status stays `planned`, nothing composed or sent), `test_every_unprompted_sender_reads_the_opt_out_fail_closed`; mutants S2, S6, S6b, S7 killed. Three Stage 1 / Stage 7 tests and the circuit-breaker world were updated to supply a readable "no" (their fakes could not be read at all, which is now a deferral, not a send).

### S3 · The comment-DM gate fails closed on any read failure

- **Change:** `_comment_dm_allowed(redis, channel, ext)` — one helper the comment flow must pass before `send_private_reply`; a query error, a session error or an unreadable preference all mean no DM (before: a query error sent it, a session error skipped it).
- **Status:** VERIFIED COMPLETE — `test_the_comment_dm_gate_fails_closed_on_any_read_failure` (query error → no; session error → no; readable no → yes; the flow calls the helper above the send); mutants S3, S3b killed.

### S4 · The once-more draft re-checks its own token ceiling

- **Change:** `_reply_in_words` reads `stop_reason`; on `max_tokens` the retry is cut to its last whole sentence (nothing to keep → as written), the same settlement the first draft gets.
- **Status:** VERIFIED COMPLETE — `test_the_once_more_draft_is_cut_to_a_whole_sentence_when_it_hits_the_ceiling`; mutant S4 killed.

### S5 · The opt-out resolver shares the WhatsApp door's phone predicate

- **Change:** `record_opt_out` resolves a WhatsApp person only when `is_plausible_phone` accepts the `+`-stripped key (the door's own check in `provision_user`), resolving with the normalised key; a key that cannot resolve logs "redis only".
- **Status:** VERIFIED COMPLETE — `test_the_opt_out_resolver_uses_the_door_s_phone_predicate` ("+254…" resolves as "254…"; "web_…" and a 17-digit Meta id never do); mutants S5, S5b killed.

### S6 · W2-3's question half is now proven

- **Change:** none to production; the pass-4 "fix" used "Where is your shop?", which `cooling._BUY_RE` matches on `shop`, so M6 (the `"?"` branch) survived. The new test uses "Are you there?" (no buying word) through `customer_state.apply`.
- **Status:** VERIFIED COMPLETE — `test_a_bare_question_with_no_buying_word_lifts_a_hold`; mutant M6 killed.

### Verification pass 5 (same day) — ten findings, all acted on

- **Status of the slice: VERIFIED COMPLETE** (restated 22:29 UTC) — the full suite on b002177 passed apart from one source-string test fixed in 1365420, and CI on the final head is recorded in REGRESSION_SAFETY_REPORT (the 1365420 run was cancelled by the next push, not green); the first head `a5b4dc1` had been red on twelve test worlds (pass 5, finding 9). S7 (CI apt bound) stays IMPLEMENTED BUT NOT VERIFIED and the four source-level sender proofs stay in UNFINISHED.
- **S1 amended:** `database` and `gate` are in `AI_DOWN` and `ACTIONABLE` — the sweep stands down on a fleet-wide database or gate failure instead of burning every thread's strikes, health says a person is needed, and the next completed turn clears it (finding 2).
- **S2 amended:** the four senders whose surrounding `except` fell through to a send now skip on any read failure (finding 3); the dispatcher's deferral rolls the session back, counts the try, parks after three, and tallies `defer_optout_unreadable` / `park_optout_unreadable` for the shadow report (finding 4).
- **S3 amended:** the complaint DM goes through `_comment_dm_allowed` too (finding 5); the skip log names "opted out, or the preference could not be read" (finding 6).
- **S4 amended:** the retry is cut only when the dropped tail carries no figure, currency or question; otherwise it goes to the gate as written (finding 1).
- **S5 amended:** the resolver key is the digits only and the redis key is written on it (finding 7); the "redis only" line and the psycopg branches are tested (finding 8).
- **S7 amended:** `timeout 60` on each `dpkg --configure -a` (finding 10).
- Evidence: VERIFICATION_PASS_5.md with the response table; 24 of 24 mutants killed; `tests/test_intelligence_slice5.py` (21 tests).

### S7 · CI apt step bounded for its real worst case

- **Change:** `timeout-minutes: 16` (three attempts × ~305 s) and `sudo dpkg --configure -a || true` before each attempt, in both jobs that install ffmpeg. The 8-minute bound was hit again on PR #321 (docs-only; a stalled mirror; the re-run passed).
- **Status:** IMPLEMENTED BUT NOT VERIFIED — proven only by the next stalled-mirror run.

## Slice 6 (2026-11-06, 23:1x) · the eval runner after its first real run

### R1 · Contact cleanup in FK order, one transaction per contact

- **Change:** `_cleanup_contacts` deletes identity → flush → identifiers → flush → person, each contact in its own transaction; a failing contact is rolled back, logged and skipped (run 42289125585 crashed at case-run 180 of 360 on `identifiers_person_id_fkey`).
- **Status:** VERIFIED COMPLETE (behaviour test on a recording session: the order, and a raising commit that does not end the run).

### R2 · A failed turn drops its pooled connections

- **Change:** `_recover_from_failed_turn` rolls the session back and disposes the engine pool after any turn error; called from the runner's except branch.
- **Status:** IMPLEMENTED BUT NOT VERIFIED against the real symptom (the carried-over aborted transaction is not reproduced locally); the helper itself is tested.

### R3 · The `interceptaction` enum migration — HELD for the owner's approval

- **Change (prepared, not in the repository):** `ALTER TYPE interceptaction ADD VALUE IF NOT EXISTS 'flag' / 'escalated'`, idempotent, in alembic's autocommit block, revision a9c1e3f5b7d9 on head e8a1c3d5f7b9. Kept in the session scratchpad until the owner says "approve the enum migration" (DB migrations need explicit approval). OWNER_ACTIONS carries the one-line read-only check for the production database.
- **Status:** BLOCKED (owner decision).

## Verification pass 1 — further repairs (2026-11-06)

- **W1-5 (sync channels):** web chat and the ManyChat relay re-check the takeover after composing and return the human line if a colleague took the thread.
- **W1-2 (opt-out guards):** "stop messaging me about the cups" and "remove me from the group" are no longer opt-outs (the messaging object is required); real removal requests still are.
- **W7-4 (closer key):** silence on a closer now arms the closer key, so the next "ok"/"thanks" costs no model turn (the verifier's cost regression).
- **W1-1 (loud failure):** a gate error is also counted as a failing turn in `agent_health`, so a bug in rule code shows on `/api/health` and the standup instead of holding replies in silence.
- **W2-1 (closers):** "Thanks for nothing" / "Thanks for the delay" are not closers (object whitelist).
- **W8 (language):** Swahili with borrowed shop nouns ("Sawa size 42") stays Swahili; `apply()` no longer flips such customers to English.
- **Runner (§5):** an empty reply fails wherever a reply was expected; `require` fails on an empty reply; a raised turn fails; the paid and pressure readings are the gate's own.
- **Accepted, recorded (not changed):** Neema-initiated compositions bypass the gate by the existing `read_only` design (verification 1.3); the opt-out door checks text-only messages on every channel (1.4); on an unverifiable takeover the sweeper re-composes rather than re-sends (1.5); ~~comment dedupe is redis-only (1.6)~~ (fixed later the same day: W1-15 below); the performance view rides in the same PR (1.15 — the owner may ask for a split).

- **W1-14 (verification 1.3, fixed; the announcement half behaviour-tested after pass 4):** Neema-initiated messages now meet the deterministic rules before they are sent — `review.initiated_issues` (paid acknowledgement, order status, pressure, internal talk, no tool results needed). The dispatcher's `_send` raises `HeldByRules` before delivery and the action is parked for a person with a bell; an after-sale announcement held by the rules asks a person instead (the hub's own `.paid` event may say "payment received" and every hub event carries its own status); the sweeper's bridge escalates instead of sending. Tests: `test_intelligence_w1_grounding.py`.
- **W1-2 (verification 1.4, fixed):** the opt-out door on WhatsApp and Meta reads the words whether or not a photo is attached. Test: `test_intelligence_w1_fail_closed.py`.
- **Verification 1 finding 12 (fixed):** the four register rows that rested on source-string tests (W3-1, W7-6, W10-3, W2-4 wiring) now have behaviour tests; two small extractions made that possible (`runtime.length_target_for`, `runtime.served_model`), with no change in what the turn does.
- **Scorer correction (found while fixing finding 12):** the floors harness computed the reply-length target with a mirror of the runtime that lacked the complaint floor; it now calls the runtime's own function. Re-scored: `results/floors-rescored-*.json` (see BENCHMARK_RESULTS, "Correction 2").
- **Blind set isolation (finding 6, hardened):** the case loader's default sweep now leaves `"blind": true` cases out, so the development/held-out split can never contain a blind case; the blind file is scored only when named. Test: `test_the_default_sweep_leaves_the_blind_set_out`.
- **W1-15 (verification 1.6, fixed):** a Facebook or Instagram comment is deduped on its own row (`Message.waba_msg_id = comment id`, the DM path's pattern) before it is stored or engaged, in addition to the redis mark. A 502 redelivery with redis down no longer answers a comment twice. No migration. Test: `test_inbound_social.py::test_a_redelivered_comment_is_not_answered_twice_without_redis`.
- **W7-4 (second half, verification: `stop_reason` never inspected — fixed):** a draft the writer could not finish (stop_reason `max_tokens`) is cut back to its last whole sentence before the gate (`runtime.trim_truncated`), when one exists and enough remains to stand as the answer; the turn facts record `truncated`. A draft with no sentence boundary goes on as written. Tests: the trimmer on nine shapes (English, Swahili, a newline, a quoted figure, a decimal, a short tail) and `run_turn` with a fake writer stopping on `max_tokens` vs `end_turn`.
- **W9-5 (currency mutation mid-turn) — deferred with reasons:** `search_catalog` and `capture_contact` move `ctx.currency` within a turn by design (the "Kenya money plz" case: the model re-fetches in KES in the same turn, and a placed customer is already `market_locked`). Locking the currency once a figure is quoted would hold that correction to the next turn; whether that helps or hurts needs the real-model run on the `price-objection`/`org-purchase` cases. Recorded in UNFINISHED_REGISTER.
- **W7-5 (split memory homes — first half, fixed):** a Messenger/Instagram turn now also reads the facts on the linked WhatsApp `User` row (the WhatsApp side already read the person's), so a thread continues where the other channel left off. Best-effort lookup, de-duplicated. Test: `test_a_messenger_turn_reads_the_linked_whatsapp_users_facts`. Still open from 7.5: `said_once` and product interest keyed by channel+handle, and the phone call stored three times (each needs its own measured change).
- **Verification pass 2 (slice 2) — 0 × S1, 1 × S2, 7 × S3; the S2 and two S3 fixed the same day:** the real-model runner can reach the blind set again (`--file blind_heldout.jsonl`); the loader's blind exclusion holds for every pattern; the comment-redelivery test reads the statement it answers. Report and response table: `VERIFICATION_PASS_2.md`. Eleven of thirteen targeted production mutations were killed by the new behaviour tests; the two survivors were the predicate mutants the fake DB could not see, now covered.
- **Verification pass 2b (slice 3) — 0 × S1, 2 × S2, 10 × S3; both S2 and nine S3 fixed the same day:** the trimmer no longer reads an abbreviation, an initial or a list number as a sentence end; a cut that would drop a figure, a currency or a question asks once more for the reply in words instead (`_settle_truncated`, also on the ran-out-of-iterations branch); the memory lookup orders by `updated_at` and unions case-insensitively, with a fake that reads the statement and an error-path test; both scorers reach the blind set through `--file` with `include_blind` pinned, refuse an empty run (exit 2), record `file:` as the selection, and withhold a blind file's misses (the three committed blind result files had their misses removed unread). Report and response table: `VERIFICATION_PASS_2B.md`.
- **W5-3 (timestamps on facts — fixed):** `add_fact` records the day each fact was noted or last confirmed (`persons/users.state.agent_memory_at`, pruned with the cap); the memory block shows "(noted YYYY-MM-DD)" beside each dated fact and tells the model to confirm an old one rather than assume it. Rows written before the dates existed render as before. Test: `test_a_fact_carries_the_day_it_was_noted_and_a_restatement_refreshes_it`.
- **W7-5 (second half: `said_once` and product interest keyed by channel+handle) — deferred with reasons:** both live in redis keyed by (channel, handle), and `run_turn` holds no person id at those call sites; a person-keyed read costs one identity lookup per turn on every channel. Measure first how often one person is active on two channels inside the said-once TTL (the inbox has the merged identities); if it is rare the extra read is not worth its latency. UNFINISHED_REGISTER.
- **W3-3 (four pause mechanisms, one decision point) — deferred with reasons:** cooling, the model's `pause_conversation` tool, the conversation budget (record-only) and the closer gate each pause on their own thresholds; the budget module records that pacing fires rarely. Unifying them is a redesign whose effect can only be judged with the real-model run on the `needs-silence` and `closing` cases; no change without that measurement. UNFINISHED_REGISTER.
- **W10-3 (second half — fixed):** the weekly distillation's rule proposals now have an approval UI: a Settings card lists pending proposals with Approve / Reject (admin), shows the learned rules in force, and is the first caller of the D4 endpoints. Typecheck clean.
- **W10-2 (panels that saved nothing — fixed):** the Business, Neema and Integrations panels no longer show a "saved" toast with no write behind it; they say they are shown for reference and set in the box's configuration, and every button on them (including the Integrations rows) says "Managed on the box" / "Not editable here". (A server side for them is a separate decision; UNFINISHED_REGISTER.)
- **W1-1 (amended, verification 1.7 — fixed, corrected after pass 3):** when the gate breaks, the held-draft flag now REPORTS whether it landed (it used to swallow every error, so the first version of this fix was dead code); if it did not, the handover is tried (its own session, so a database outage fails it the same way); if that fails too the outcome is `unowned`: no hold line is promised, and the senders leave the thread UNMARKED (not "silence"), so the customer's message stays the latest inbound and the missed-reply sweep retries it and hands it to a person after three strikes. Tests: the real flag with a dead database; the handover failing or raising; and through `run_turn` to the facts the senders read.
- **W1-16 (investigation 1.3 — fixed, corrected after pass 3):** an opt-out from a contact with no person row used to live in redis alone. `record_opt_out` now makes the person through the resolver every inbound door uses — only for a real identity (a digit-only WhatsApp number, a Meta/TikTok handle; a web-chat visitor's `web_…` key stays redis-only, never a phantom person), named `source=opt_out` — writes the preference on it and links the thread; `opted_out` finds the preference through the identity when a thread has no person, and the comment-DM path now opens a session for that read. Tests: `test_an_opt_out_from_a_contact_with_no_person_makes_one_and_lands_on_it`, `test_a_web_chat_opt_out_never_mints_a_whatsapp_person`.
- **W1-10 (Meta delivery receipts — fixed):** Messenger/Instagram delivery and read receipts are no longer discarded: they are stamped on the outbound rows they cover by Meta's watermark (every message to that contact up to that moment), as WhatsApp's statuses are stamped by id, never lowering a higher status. "Delivered"/"read" is now known on Meta threads. Test: `test_a_meta_delivery_receipt_stamps_the_outbound_rows_it_covers`.
- **W1-15 (figure grounding — first half, fixed):** the gate's "numbers a tool returned" no longer count ids, quantities, counts, sizes, pages and the like as money facts (`_NOT_MONEY_KEYS`), so a pack size of 350 or an id can no longer vouch for a "KES 350" in the draft. Money keys and money-marked strings unchanged. Test: `test_a_tools_ids_counts_and_sizes_are_not_money_facts`; one pin updated. **Second half deferred:** the prompt's delivery figure ("KES 350 within Nairobi") is allowed in every currency by design, so a "$350" would pass; restricting it per currency would hold a true "KES 350" line said to a USD customer — judge the false-hold rate with the real-model run first. UNFINISHED_REGISTER.
- **Verification pass 3 (slice 4) — 2 × S1, 2 × S2, 8 × S3; all four S1/S2 and six S3 fixed the same day, before merge:** the 1.7 fix was dead code and its silence was being honoured by the sweep (both repaired, see W1-1 above); web-chat opt-outs minted phantom persons and the comment-DM read had no session (both repaired, see W1-16). Report and response table: `VERIFICATION_PASS_3.md`.
- **Verification pass 3b (the pass-3 repairs) — 0 × S1, 2 × S2 (test gaps), 6 × S3:** the code claims held under probing and mutation; the two tests that could not catch their mutants were replaced with tests through the real senders and a recording resolver fake; the flag's contract is pinned at both ends. Report and response table: `VERIFICATION_PASS_3B.md`.
- **Verification pass 4 (register audit on main d084e91) — 1 × S1, 3 × S2, 13 × S3; all repaired or recorded:** every benchmark number reproduced to the digit, the suite green, the live claims true, 23 of 29 mutants killed. Repaired: W9-1's evidence (four more branches now behaviour-tested), W1-14's announcement half (a behaviour test, not a source pin), R5.6 restated as PARTIALLY COMPLETE, every "BLOCKED on a model key" row re-pointed at the real blocker (the runner crash, fixed in PR #319, with the secret already in place), W2-3's question-only half tested, the dashboard counting only blind runs as measured and never trending them with tuned-on rows, the Stage 1–8 reports and audits brought into `reports/`, the contaminated-split wording in EXCELLENCE_SCORE / INTERNATIONAL / UNFINISHED corrected, pass-3b items 6 and 8 recorded. Report and response table: `VERIFICATION_PASS_4.md`.
