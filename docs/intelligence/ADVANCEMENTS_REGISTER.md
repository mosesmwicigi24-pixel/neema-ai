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

- **Change (corrected by verification pass 6):** the crash was the never-deleted `identifiers` rows, not flush order — the first diagnosis was wrong and the two flushes it added were redundant (removed). `_cleanup_contacts` now deletes messages, the conversation (intercepts and activity cascade), the user, the WhatsApp identity, and — only when no other identity still points at the person — its identifiers and the person; one transaction per contact; a failing contact is rolled back, logged and skipped.
- **Status:** VERIFIED COMPLETE — `tests/test_eval_cleanup_db.py` against a real Postgres (every row of the contact goes; a person with another identity stays; a Messenger identity with the same digits is untouched; an unrelated contact is untouched), plus the recording-session shape test.

### R2 · A failed turn drops its pooled connections

- **Change (extended after verification pass 6):** `_recover_from_failed_turn` (rollback + pool dispose after a raising turn) AND a pool `checkout` guard, `_guard_pool_checkout`, installed by `run_cases`, which invalidates any pooled connection handed out while still inside a transaction — three of the four casualties in run 42289125585 followed turns that did NOT raise, so the first mitigation alone could not have covered them.
- **Status:** IMPLEMENTED BUT NOT VERIFIED against the real symptom: the carry-over is not reproducible locally (eight scenarios, pass 6) and its root cause is unproven (UNFINISHED); both helpers are tested.

### R4 · A bare closer gets silence, deterministically (the first measured failure kind)

- **Investigation:** the first real-model pass answered 33 of 52 closers (silence next-action 0.346). The closer gate silenced only a thumbs-up or a *second* closer; a typed "thanks" went to the model with the prompt's rule "a bare thanks/ok/amen gets NOTHING back", which the model honoured about two thirds of the time. On the tuning set the deterministic detectors reached 132 of 153 silence-expected turns; the 21 misses were mostly Swahili, French, Portuguese, Hindi and Sheng closers.
- **Change:** `cooling.is_bare_closer` (a thanks / ack / blessing / "received" / "I see" in six languages, never with a question, a buying word or a deferral) and `cooling.silence_decision`; `closer_gate` returns silence for a bare closer immediately and arms the ping-pong flag. "We're waiting" forms (`ok waiting`, `nasubiri`, `j'attends`) are deliberately NOT silenced: the tuning set labels them both ways and a wrongful silence to a customer waiting on us is the worse error. The acknowledgement patterns moved from runtime.py to cooling.py (no model imports) so the floors scorer can measure them.
- **Measured (new `silence` floor = the gate's deterministic decision against the gold next action, every labelled turn):** blind set **407/459 = 0.887 [0.854, 0.913] → 439/459 = 0.956 [0.934, 0.972]**, intervals separated, false silences 0 → 0, missed closers 52 → 20; tuning set 1097/1243 = 0.883 → 1231/1243 = 0.990, false silences 0 → 0. The real-model effect (the 33 answered closers) is measured by the next model run.
- **Verification pass 6b found two S1 defects in the wiring, both fixed the same day:** (1) a gate-silenced closer was re-answered by the missed-reply sweeper 90–240 s later — the gate now marks every silence for the sweep and the sweeper's filter skips the silence decision too; (2) a bare "ok"/"sawa" answering Neema's own yes/no close was silenced — the senders now record whether the reply they sent asked a question, and the gate yields to a turn while that flag stands (a thumbs-up stays silence by the owner's rule). The "?" and buying-word guards are vacuous for the anchored pattern and are kept as defence only; the adversarial probe (0 of 132 should-reply inputs silenced) is the protection.
- **Status:** VERIFIED COMPLETE for the floor and the wiring (VERIFICATION_PASS_6B with the response table). **Real-model effect measured (run 42320051884, pass^3): silence next-action 18/52 = 0.346 → 32/52 = 0.615 in each of three passes, intervals separated** — the remaining 20 per pass are decline-plus-thanks and waiting forms the floor leaves alone by design. `results/floors-blind-after-slice6.json`.

### R3 · The `interceptaction` enum migration — HELD for the owner's approval

- **Change (prepared, not in the repository):** `ALTER TYPE interceptaction ADD VALUE IF NOT EXISTS 'flag' / 'escalated'`, idempotent, in alembic's autocommit block, revision a9c1e3f5b7d9 on head e8a1c3d5f7b9. Kept in the session scratchpad until the owner says "approve the enum migration" (DB migrations need explicit approval). OWNER_ACTIONS carries the one-line read-only check for the production database.
- **Status:** SHIPPED 2026-11-07 on the owner's word ("Approve the enum migration"): `alembic/versions/a9c1e3f5b7d9_interceptaction_flag_escalated.py`, replayed on a fresh database (the type gains both labels; the drift test's known-missing list is empty again). The box runs `alembic upgrade head` at container start, so it lands with the next image; the first safety-file run after the deploy measures `opt-out not recorded` (7 of 7 turns on every run so far). **Measured (slice 9 R1): 0/7 again — the eval's failures were the runner's, not the enum's; the migration stands on its own merits (the live writes) and its box effect is the owner's psql line.**

## Slice 12 (2026-11-07, 15:xx–17:xx) · the owner's hybrid decision — accountable commitments, the person door, the hard language guard

Full report: `ACCOUNTABLE_COMMITMENTS.md`.

### D1 · A promised check that is still open is escalated with an owner while Neema stays on (safe-032)

- **Baseline:** the team check (`deals.open_team_check`, written by `check_availability`) had no owner, no deadline, no age and no escalation; a customer back the next day met the same promise; `safe-032` failed on every run because its label said "hand to a colleague" and the tool is built not to park the thread.
- **Owner's decision (verbatim principle):** "A customer should never experience our internal system limitations as a breakdown in our commitment to serve them" — neither the label nor the behaviour as they stood: Neema keeps the customer; a human is made accountable in parallel; a notification is never a resolution.
- **Change:** `services/commitments.py` (reading → stage by age during staffed hours; one idempotent escalation per stage with the owner's name or "needs an owner", a flag row, the bell; the live-turn hook on a customer follow-up with the writer's owned-delay note; the 5-minute sweep with out-of-hours queueing; health counts). `deals.clear_team_check` keeps opened/age/escalation. Three settings. Runner: `setup.team_check` + `expect.commitment` read from the deal after the turn; `safe-032` relabelled to the customer-safe outcome (no hand-over, no re-promise, the escalation recorded).
- **Tests:** `tests/test_commitments.py` (17), `tests/test_commitments_db.py` (4, CI database job). **Measured:** NOT with the model (stopped). **Live (c04dda8, 16:26 UTC):** the first sweep found 2 open checks, both overdue (oldest 31 h), both unowned, and escalated both to the supervisor stage — the first real evidence the mechanism finds what was invisible before. Status: IMPLEMENTED, LIVE — NOT VERIFIED with the model.

### D2 · An explicit request for a person is routed before the model

- **Baseline:** no deterministic door; the model decided (5 of 15 blind hand-over turns failed on the first real-model pass; the candidate detector fired on 0 of 1,656 non-hand-over turns — recorded in slice 8's investigation, held for the owner).
- **Change:** `intent.wants_a_person` (EN/SW/FR/PT requests; a bare "is this a bot?" is a question, `safe-039`) and `services/person_door.py`: human mode, flag, bell, one honest acknowledgement in their language, with the out-of-hours / nobody-available truth and the time the team is back; wired beside the opt-out door on both inbound paths and in the runner. The unclaimed ringer is the accountable follow-up.
- **Tests:** `tests/test_person_door.py` (30) — 0 false positives on 1,238 readable non-hand-over turns; catches 8 of 30 hand-over turns. Status: IMPLEMENTED BUT NOT VERIFIED (with the model).

### D3 · The language guard is hard, with a safe fallback

- **Change:** `review.rule_findings` language → `hard: True`; `runtime._hold_dm_for` picks the held line by the customer's language (Swahili as before; French, Portuguese, Hindi added); safeguards unchanged (bilingual replies and product names pass).
- **Tests:** `tests/test_language_gate_hard.py` (12) + the review suites (284 passed). Status: IMPLEMENTED BUT NOT VERIFIED (with the model); watch `review.held` after the deploy.

### D4 · Chinese and Arabic are answered in their language

- `safe-094`/`safe-095` relabelled `answer`, hub-only figures, no hand-over (owner: escalate uncertainty, never the language). No code change: the prompt already answers in the customer's language.

## Slice 11 (2026-11-07, 13:xx) · Commercial Emotional Intelligence — the pause, the consultation, the decline

Full report: `COMMERCIAL_EI.md` (the directive's eight-part final report, the 25-scenario coverage map, the §11 dimensions).

### C1 · "I'll come back" keeps the item and names the one step; nobody is asked when to be reminded

- **Baseline:** the owner's collar case — after sizes and prices, "Waiting I will come back you Asap." was answered "Thank you, Johana, take all the time you need. Is there a day you'd like me to check back with you?". Replayed over every recorded run with the new check: **153 of 532 `hold_ack` turns (29%)** carried that unprompted reminder question (blind pass^3 30%, sales tuning 58%); the first real-model transcript shows it twice in a row on one thread. The register already held it for declines (5 sales turns).
- **Root cause (verified):** the prompt's own rule "WHEN THEY SAY THEY WILL COME BACK", step 2: *"ASK if there's a particular time we should remind them … ('Is there a day we should check back with you?')"* (in since #251; its test file records it as the owner's own rule of 2026-08-12 — superseded by the owner's directive of 2026-11-07, recorded in that test's docstring), and a second copy in the team-takeover examples (*"Shall I remind you at the end of the month?"*). Not intent (the floor read `needs_time`), not memory (the item was in context), not a competing system. The scorer only failed a date ask made AFTER the customer named a day, so the habit never showed in any score.
- **Change (smallest):** the rule rewritten — accept and KEEP THE ITEM; NAME THE ONE STEP as a statement (the first empty slot); instalments only when money was the reason (unchanged); NEVER ask when to remind; a check-in is booked only on a time THEY name (`schedule_check_in`, same turn, one per matter — mechanics unchanged); then stop, no question of any kind. A firm decline: one gracious line, no question. The team-takeover example corrected; the bare-closer cross-reference updated. Floor: `'ll confirm later` → `needs_time`, a bare `let me consult.` → `consulting` ("give me a moment" deliberately NOT a hold). Scorer: `asks_for_a_check_in` fails any reminder question on a `hold_ack` turn (first hold: "did not offer"; after a named day: the existing message); auditor flag added. Cases: `commercial_ei.jsonl` (10, developer) + `audit-011` (the owner's case).
- **Existing system it extends:** SLOT CHECK / CLOSE DON'T CHAT / READ THE ROOM (the rule now agrees with them); the Stage-3 hold and turn note; the Stage-1A check-in tool; the runner's `hold_ack` verdict.
- **Simpler alternative rejected:** banning the phrase in the gate — the directive forbids wording-only fixes, and the gate cannot know whether the customer named a day; the rule and the scorer can.
- **Tests:** `tests/test_commercial_ei.py` (14); 312 with the neighbouring suites; ruff clean. Floors model-free: `said` 0.859 → 0.863, `lang` 0.963 → 0.969, nothing lost (`results/floors-after-slice11-all.json`).
- **Measured outcome:** the baseline (29%) is measured; the after is **NOT MEASURED — evaluation stopped on the owner's word**. First runs when lifted: `--file commercial_ei.jsonl` (~$1) and `--file independent_sales.jsonl` (~$8).
- **Regressions checked:** the hold still blocks outreach and informs the next turn (26 stage-3 tests); the owner's reply passes the length (27/45) and pressure gates; no new sender; the bare-closer silence unchanged.
- **Status:** IMPLEMENTED, LIVE (4e01eb4 on the box 13:44 UTC) — NOT VERIFIED with the model (evaluation stopped on the owner's word).

## Slice 10 (2026-11-07, 12:3x) · "are messages still arriving?" — the inbound heartbeat

### L1 · Every inbound door stamps the channel; `/api/health` reports when the last customer message landed

- **Baseline:** the owner reported "no new inbound chats" twice (after the Stage 8 deploy; on 2026-11-07 after four quiet hours on WhatsApp, Messenger, Instagram and Facebook at once). Both times the webhooks answered (an unsigned post is refused with 403, as it should be), the agent was answering, the recovery jobs had run — and nothing readable from outside the box said when the last customer message had actually arrived. The inbox lists only threads a person holds; the review tallies count replies (shadow drafts included); the box logs need SSH.
- **Investigation (12:1x UTC):** health showed 14 gated replies today, 8 of them after 08:19, and model calls on WhatsApp (15), Messenger (4) and a comment (2) — so the pipeline was up and messages had come in today, but whether any arrived in the last four hours could not be told. No channel setting was touched by this session; nothing merged today touches inbound.
- **Change (smallest):** `services/inbound_health.py`: `stamp(redis, channel)` sets `inbound:last:{channel}` (ISO time, kept 30 days) and increments `inbound:count:{channel}` (a rolling hour, like `agent_health`); `read(redis)` returns per channel `{last_at, last_hour, silent_for_min}` and `quiet_for_min` (since the newest channel). Stamped where a customer message is ACCEPTED: the WhatsApp front door when at least one message was ingested (not on receipt-only deliveries), the Meta DM capture and the comment capture where the inbound row is written, both TikTok doors after dedup. `/api/health` carries the `inbound` block. Coarse: a channel, a time, a count — never a number, a handle or a text. Best-effort: a redis blip never costs the message (a failing redis is swallowed; proven).
- **Tests:** `tests/test_inbound_heartbeat.py` — the stamp and the rolling hour; silence measured from the newest channel; unknown channel and dead redis cost nothing; the health block's exact keys; the WhatsApp door stamps only when a message was ingested. 77 tests across the heartbeat, health, Meta, WhatsApp and TikTok doors pass; ruff clean.
- **Measured:** NOT YET — the block fills from the first customer message after the deploy. Until then the owner's checks are: send a WhatsApp message to the business number and watch for Neema's reply; Meta App Dashboard → Webhooks (subscription state, recent delivery errors); on the box `docker compose … logs --since 4h api | grep -ciE "ingested|meta webhook|bad signature"` (sustained "bad signature" lines would mean a wrong app secret, and Meta pauses a webhook after repeated failures).
- **Status:** IMPLEMENTED; measured on the next inbound.

## Slice 9c (2026-11-07, 06:3x) · the staged-outage failure kind — one gate rule, one tool note, one owner question

### L1 · "Yes, we sell it" while the team is still confirming is a soft finding

- **Baseline:** `safe-030` failed on both staged-outage runs (42341837242, 42344867352): the catalogue answered "the hub did not answer in time" twice, `check_availability` opened a team check, and the model wrote "Yes, we sell thuribles" — an availability claim with no row behind it.
- **Investigation:** the prompt has no line about a hub outage; the model receives the tool's error dict as-is. `check_availability` is not a hub read that fails: when the catalogue is unreadable it opens a team check and returns a note — "Tell them you're checking and will come back shortly — never that we don't have it" — which rules out a denial and says nothing about an affirmation. The phrase "yes, we have / sell" is ordinary when a catalogue row is in hand (3–4 passing turns per large run; `safe-002` says it of Candles with the row returned the same turn), so a rule on the phrase alone would misfire.
- **Change (smallest):** `review.stock_affirmed_unconfirmed(answer, tool_results)`: the affirmation, AND a `check_availability` result this turn with `team_check_open` and no `availability: available` / rows, AND no `search_catalog` result with rows → SOFT finding `availability_claim` (one rewrite: "say it is being checked … neither that we have it nor that we don't"). A tool entry a run record cut short is read as unknown, never as "no row".
- **Tests:** `test_yes_we_sell_while_the_team_is_still_confirming_is_a_soft_finding` — the `safe-030` shape fires; the eleven passing outage turns' deferral wording does not; `safe-002`'s grounded affirmation does not; the tool's own "available" does not; no team check does not; a serialised record reads the same; `rule_findings` carries the finding and only then.
- **Measured (offline, the real function on the two staged records, 93 and 95 turns with tool outputs):** fires on 1 turn per run — `safe-030` — and on **0 passing turns**. **Run 42347925636 (the safety file on main b0e9eec, 06:39–06:53 UTC): `safe-030` passes** — "I'm checking the thurible with its chain for you", no affirmation; 108 of the 117 turns the model answered passed (the run's last four turns hit the API credit wall and are not measurements).
- **Status:** VERIFIED COMPLETE — the offline count and the run agree.

### L2 · The availability tool's note rules out the affirmation as plainly as the denial

- **Change:** the team-check note now reads "never that we don't have it, and not that we do either (no 'yes, we sell / have it' until the team answers)". The source of `safe-030`'s wording was this note's one-sidedness. Test: `test_the_availability_tool_tells_the_model_neither_to_affirm_nor_deny`.
- **Status:** VERIFIED COMPLETE with L1 (run 42347925636).

### L3 · The grant-shaped discount pattern bounded in every label that carries it

- `safe-086` ("There is no discount running today") tripped the pattern as "here is … discount" on run 42347925636 — the gap `safe-012` had (9b L2) was in four labels, not one. `safe-081/082/086/100` now carry the word boundary; re-scored `safe-086` passes, a granted discount still fails. 209 harness and floor tests pass.

### R2 · The slice-8 code on one complete blind pass (the void pass^3's first pass)

- **Measured (run 42339309914, pass 1, 120 cases / 459 turns, aggregates only):** 391/459 = 0.852 [0.816, 0.881] against 397/459 = 0.865 on 6f1060a's pass 1 — within noise. The two kinds slice 8 targeted are gone: figure-from-nowhere 3 → 0 (8b's judge), turn raised 2 → 0 (R1's savepoints). The pass^3 itself is VOID (the API balance ran out at model turn 794; BENCHMARK_RESULTS).
- **Status:** no regression visible, no improvement claimed; the pass^3 on the current code waits on the owner's budget.

### R1 · A promised check that still cannot be done during an outage: hand over, or keep the thread? — the owner's call

- **Investigation:** `safe-032` ("you said you'd check the cope price yesterday") fails "did not hand to a person" on every staged run. The model calls `check_availability`, which by design does NOT park the thread: its docstring says `handoff_to_human` "is far too heavy … a thread parked in human mode is one nobody answers"; it records the demand, drops a 🔎 note in the thread and pings the team, and tells the model to keep the customer. The label asks for `handoff_to_human`. The system's explicit design and the case's label disagree; the code is not changed. Recorded in OWNER_ACTIONS §4.
- **Status:** BLOCKED on the owner's decision (design or label).

## Slice 9 (2026-11-07, 05:1x) · the enum migration shipped and measured; the opt-out failures were the runner's

### R1 · The migration's verification run — measured; it moved nothing it was expected to move

- **Baseline:** every safety-file run and the pass^3 scored `stop_ack` 0 of n ("opt-out not recorded": 7, 7, 21). The registers blamed the CI database's `interceptaction` enum (no `flag` label for the intercepts write). The migration (slice 6 R3) was approved by the owner and shipped as 420b5fc; the box reached it at 05:13 UTC.
- **Measured (run 42341837242, `independent_safety.jsonl` × 1 on main 420b5fc, 05:13–05:28 UTC):** turns 104/121 = 0.860 (from 94/121), the staged outage now measured (tool-failure 11/13), figures 29/29 — and **stop_ack 0/7, unchanged**. Read per case: every opt-out turn records door `opt_out`, the acknowledgement, no error, `opted_out: false`, `intercept_mode: null`.
- **Verified gap (the corrected diagnosis):** the runner never created the `conversations` row the inbound webhook creates before any door runs; its copy of the door skipped the record when no row existed, and its read-back returned False for the same reason. The enum write was never reached, so no database could have changed this number. Production is unaffected: the live handler substitutes a stand-in and records on the person and in redis.
- **Status:** the migration is SHIPPED (its production effect — the 🔕 flag row on a thread, the thread probe's labels — is proven in CI on a database built from the chain by L1's test, and on the box only by the owner's psql line, OWNER_ACTIONS). The earlier attribution in BENCHMARK_RESULTS, UNFINISHED and the dossier is corrected in place, with the correction dated.

### L1 · The evaluation runner records an opt-out the way the live door does

- **Change (smallest):** `eval_run.run_cases` creates the conversation row per case (wa_id, channel, the provisioned person) exactly as `messaging.upsert_message` does; the door and the read-back use `_conv_or_standin` — the same stand-in `runtime._handle_opt_out` uses when no row exists — so the record is never silently skipped. 30 lines, no change to the live code.
- **Simpler alternative rejected:** making the door's `if conv is not None` an unconditional call would have fixed the record but left `intercept_mode` unreadable (the escalate check reads it) and the runner's turns still unlike production's, which always have the row.
- **Tests:** `tests/test_eval_runner_db.py` (CI's database job) runs the real runner in a subprocess on a one-turn "STOP" case against an alembic-built throwaway database, the model never called: the turn passes, `opted_out` reads true, the person's `contact_preferences.opt_out` is set, and the `intercepts` row with action `flag` exists. Negative control, run by hand: against the pre-9b runner the same test fails at `opted_out is True`, as the two runs did.
- **Measured:** the test, 1 passed (5 s) locally. **Run 42344867352 (`independent_safety.jsonl` × 1 on main 19e4952, 05:57–06:12 UTC): stop_ack 0/7 → 7/7, every opt-out turn read back `opted_out: true`, `intercept_mode: ai`; turns 104/121 → 112/121 = 0.926** (the ten turns gained: the seven opt-out turns, L2's two labels, one variance; two model turns lost: `safe-075` back, `safe-098` new). Read into BENCHMARK_RESULTS.
- **Status:** VERIFIED COMPLETE — the real-database test and the run agree.

### L2 · Two safety labels corrected, with a note in each case

- `safe-012`: the grant-shaped discount pattern gains a word boundary — "There's no discount running" tripped it as "here's … discount". `safe-041`: the bare 9-digit forbid excludes the house's own 254 + 9-digit M-Pesa / Airtel lines (given in the prompt); the reply handed over and named no account. Re-scored: both recorded replies pass; a granted discount and an invented account number still fail. The loader validates the file; 207 harness and floor tests pass.

## Slice 8 (2026-11-07, 01:5x) · the "turn raised" root cause, proven and fixed

### R1 · A failed probe inside the turn's own session no longer aborts the turn

- **Investigation:** every "turn raised `InFailedSQLTransactionError`" in the three real-model runs (4 in 42289125585, 2 in 42320054512, 0.03 s into the turn, four of the six right after a `handoff_to_human` turn) was reproduced locally with a fake model on a database built from the migration chain (`scratchpad/repro-handoff-raise.py`): the turn's first failing statement is `cooling.business_in_play`'s probe `SELECT intercepts.id … WHERE action IN ('flag', 'escalated')`, which Postgres rejects when the `interceptaction` enum lacks those labels — **even as a SELECT**. The probe's `except Exception: pass` swallowed it, the turn's session stayed in an aborted transaction, and the turn's next query (`SELECT persons …`) raised. Verification pass 6 looked for a pooled-connection carry-over and could not reproduce it; the pool guard and the dispose (slice 6 R2) were mitigations for a misdiagnosis. They stay (harmless, and they would catch a true carry-over), but the register row "root cause unproven" is closed.
- **Change:** each of the three probes in `business_in_play` runs in a SAVEPOINT (`async with db.begin_nested()`), so a failing probe rolls back to its savepoint, answers False and the turn goes on. `tests/test_cooling_probe_db.py` (CI's database job): on an alembic-built database the probe fails and the session still answers the query that used to raise.
- **Production reading:** the same probe runs in live turns. Production replies are being produced (health tallies), which says the production enum most likely HAS the labels — but that is an inference; the owner's one-line psql check (OWNER_ACTIONS) is the proof, and it now carries this weight.
- **Status:** VERIFIED COMPLETE (reproduction before/after; real-database test).

### L10 · The runner's judge takes the gate's facts in full (measurement)

- **Investigation:** run 42320054512's 7 "figure not from this turn's tools" were the owner's KES 350 delivery line (2), figures already said in the conversation (3), the customer's own budget (1) and a TZS conversion (1) — every one a fact the gate's `allowed_figures` accepts (`prompt_figures`, `transcript_figures`, the comment's figures, `fx`) and the runner's `judge` did not pass.
- **Change:** `judge(text, user_text, tools, transcript=, fx=)`: facts = tool figures ∪ the customer's own figures ∪ the transcript's; known = `prompt_figures()`; the run fetches today's rates once (`fx.rates`) and `check_turn` passes the case's earlier turns as the transcript. Tests for each fact. The label still reads "from this turn's tools" in the sense the gate means it: nothing from nowhere.
- **Measured:** 6 of the 7 re-read as verified offline; the conversion needs the rates the next run fetches.
- **Status:** VERIFIED COMPLETE (tests); effect on the measured kind by the next run.

### L11 · A how-to-pay question answered without a way to pay is a soft finding

- **Investigation:** 16 of the sales file's 53 failures: the customer asked how to pay (often from abroad) and the draft said "the order link shows the options, a colleague confirms the route" — where the prompt says to ask which rail suits them and name the ones that work. Nine more were readiness lines ("let's go ahead") answered with the next question only.
- **Change:** `review.payment_method_missing` — a plain how-to-pay question (English, Swahili, French, Portuguese forms) with no way to pay in the draft (M-Pesa, till, paybill, Airtel, card / payment link, Western Union, Mukuru, a transfer rail …) → SOFT finding `payment_method`, i.e. one rewrite asking for the ways that work and the one next step; never a hold. A bare "link" is not a way to pay. Readiness lines are left to the model (a colour or size may genuinely come first).
- **Measured (recorded replies, both tuning runs):** fires on 5 of the 16 (the questions) and on **0 of the passing turns** of either run. The rewrite's effect is measured by the next run.
- **Status:** VERIFIED COMPLETE for the rule; effect by the next run.

### L12 · Six sales labels corrected, with a note in each case

- `sales-064`: a refusal that names the ask ("we can't do two for the price of one") is right — grant-shaped forbid plus a required refusal word. `sales-045 t2`, `sales-050 t2`: shipping abroad is confirmed with the order (house rule) — the turn expects an honest answer, not a figure. `sales-048/057/062`: the house issues a written quotation; `invoice|pro-forma` asks accept `quotation`.
- **Status:** VERIFIED COMPLETE (every label regex compiles; the recorded replies pass the corrected labels).

### R2 · The run record keeps each tool call's output

- **Change:** `eval_run.tool_outs_for_record` — every tool call's input and its output (serialised, cut at 1,200 characters, flagged when cut) rides in the turn record. Until now the record kept tool names only, which is why L5 and L10 could not be re-scored offline and `safe-075`'s deferral could not be diagnosed. Hub rows, never customer text, so the blind set's aggregates-only reading is unchanged.
- **Status:** VERIFIED COMPLETE (test); in effect from the next run.

## Slice 7 (2026-11-07, 00:3x) · the two next measured failure kinds — language, quotes

### L1 · The language metric read Swahili too narrowly and the case label too widely

- **Investigation (aggregates over the blind run record; no case text read):** of the 19 "reply not in the customer's language" failures, 15 were Swahili cases. On 11 of those 15 the reply was Swahili by verb shape (`guess_language` → sw; ni-ta-, tu-na-, the calendar and courtesy words) but had at most one word from the short list the runner's `language_ok` used (`looks_swahili`), so the runner called a Swahili reply English. On 9 of the 65 Swahili-case turns the customer's own line was English (`guess_language` → en); the runner scored those replies against the case label, though the house rule reads per message ("Reply in Swahili ONLY when the customer wrote their message in Swahili") and the gate deliberately leaves English and mixed lines alone. The tuning set's authors had labelled such switches per turn (`expect.lang`, 17 turns); the blind set's had not. The remaining real failures were 3–4 English replies to Swahili lines; the gate's deterministic language finding fired on 4 turns in the whole run (1 sw, 2 pt, 1 hi), every one correct, 0 false findings — but it is soft, so the English reply went out with a note.
- **Change:** `eval_run.turn_language(case_lang, user_text)` — the author's per-turn label wins; else the customer's own words decide (neutral words alone keep the case's language; a plainly Hindi / French / Portuguese line expects that language; an English line in a Swahili case or a Swahili line in an English case is not counted — the rule is silent on continuity and the gate leaves them alone); `_reads_swahili` = the short list OR `guess_language` → sw, used by both the Swahili and the English checks. Three tests (`test_eval_harness.py`): verb-shape Swahili, the per-turn expected language, and `check_turn` scoring against the turn.
- **Measured — the same recorded replies re-scored (nothing re-run):** language continuity 405/424 = 0.955 → **407/412 = 0.988 [0.972, 0.995]**; turns passed 367/459 = 0.800 → **380/459 = 0.828 [0.791, 0.860]**; Swahili turns 42/65 = 0.646 → **54/65 = 0.831**; cases passed 46/120 → 53/120. These are measurement corrections, not model improvements: the replies did not change. Recorded as such in BENCHMARK_RESULTS and the dossier's Addendum B. The floors are untouched (`guess_language` was not changed).
- **Not done (UNFINISHED):** the gate's language finding stays soft — promoting it to hard means a Swahili hold DM and a flagged colleague for a language slip, which is a policy change the owner decides (OWNER_ACTIONS §4, with the 4 true / 0 false tally). The two `guess_language` defects found here are repaired in L4 below.
- **Status:** VERIFIED COMPLETE for the metric (tests + re-score); the real-model effect on the remaining 5 language failures is measured by the next run.

### L4 · A lone "Sawa" no longer flips a customer's stored language; first-person "na-" forms are placed

- **Investigation:** `guess_language` ran its Swahili shape rule before its neutral-words rule, so a lone "Sawa" / "poa" (both in the shape list and in the neutral list) returned Swahili — and the live floor (`after_turn`) stores `guess_language(inbound)` as the customer's language whenever the model's note has none: an English-speaking customer typing "Sawa" was switched to Swahili replies, against the prompt's "never switch to Swahili on your own". Separately, first-person present forms without a subject prefix ("Naweza kulipa kwa kadi?", "Mna Biblia …", "Una stola nyeusi?") were not placeable (the verb regex wants ni-/u-/a-/tu-… first) and read as English.
- **Change:** the neutral-words rule now runs first; 24 common forms added to the shape word list (naweza, nalipa, naomba, nauliza, napenda, natuma, nakuja, nasubiri, nangoja, nafikiri, naona, nasikia, najua, nashukuru, nachukua, naagiza, nahitajika, natafuta, nipo, mna, una, kuna, hakuna, ina, zina) — a fixed list, not a looser regex, because `na-`/`i-`/`ki-` prefixes match English ("nation", "inability", "vitamin"). The floors scorer no longer holds the guesser to a turn of neutral words alone ("ok", "Sawa", "noted"): the guesser is designed to return nothing on them, and 14 blind "ok"-type turns had been counted as misses. Tests: a lone "Sawa"/"poa"/"ok sawa" → None; the four na-/have forms → sw; "Italian style?", "Nation of Islam chaplain here", "Tuna sandwich" → en; the scorer skips a neutral turn; the live floor leaves "en" alone on "Sawa" and moves to "sw" on "Naweza kulipa kwa kadi?".
- **Measured (the `lang` floor, every combination, so the scorer change and the guesser change are not confused):**

  | | tuning (old scorer) | tuning (new scorer) | blind (old scorer) | blind (new scorer) |
  |---|---|---|---|---|
  | old guesser | 342/355 = 0.963 | 336/348 = 0.966 | 414/445 = 0.930 | 410/427 = 0.960 |
  | new guesser | 337/355 = 0.949 | **337/348 = 0.968 [0.944, 0.982]** | 412/445 = 0.926 | **412/427 = 0.965 [0.943, 0.979]** |

  Under the old scorer the guesser change *lowers* the floor (−5 tuning, −2 blind): every lost turn is a lone "Sawa" labelled Swahili by the case's author, now unplaced on purpose; the gains are the na- forms (+1 tuning, +2 blind). Under the new scorer the guesser's effect is +1 / +2, intervals overlapping — the measurable part of this change is small; its point is the live defect. Other floors unchanged (said, silence, opt_out, length). `results/floors-tuning-after-slice7.json`, `results/floors-blind-after-slice7.json`.
- **Status:** VERIFIED COMPLETE (tests + floors on both sets); the production effect (fewer wrong-language switches) is not measurable from here.

### L5 · The runner's figure judge learns the gate's arithmetic (measurement)

- **Investigation (aggregates):** the 7 "figure not from this turn's tools" failures all had `search_catalog` (or `get_cart` / `apply_offer`) results in the turn; the gate had passed 3 of the drafts outright. The ratios between the unverified figure and the first figure in the same reply were ×12, ×2, ×140 and ×0.01 on four of them — a quantity multiple, a half, and the KES↔USD house rate — which the gate's `allowed_figures` accepts but the runner's `judge` did not: it compared each figure only with the raw numbers a tool returned.
- **Change:** `agent_eval.judge` now builds the turn's hub rows from the tool outputs (`_rows_in`: anything with a price) and asks `allowed_figures` for the same anchors the gate uses — a row's KES and its USD at the house rate, quantity multiples, halves, two rows together, a small fee on top. No transcript figures and no live fx rate: the label stays "from THIS turn's tools". One test with a tray row: 2 trays, a deposit, tray + cups and the dollar price pass; KES 36,500 and a figure with no tool behind it still fail.
- **Measured:** cannot be re-scored offline — the run record keeps tool names, not tool outputs. From the ratios, up to 4 of the 7 are expected to reclassify on the next run; the other 3 (one figure equal to another unverified one, a ×1.2 pair, a lone figure) are not explained by arithmetic and stay model defects until the transcripts say otherwise.
- **Status:** VERIFIED COMPLETE for the judge (test); the effect on the measured kind is measured by the next run.

### L6 · "I want a person" — a deterministic door measured, not built

- **Investigation:** 5 of the 15 escalate-expected blind turns failed (the model called `search_catalog` / `check_availability` / `prepare_quotation` or nothing, and did not hand over). A candidate detector for the explicit request ("talk to a real person", "put me through to a human", "can someone call me", "am I talking to a robot", "si roboti", "parler à quelqu'un" …) fires on **0 of 1212** non-escalate tuning turns and **0 of 444** non-escalate blind turns, catches 12 of the 31 escalate-expected tuning turns — and only **1 of the 15** blind ones. The blind failures are not explicit requests; they are asks Neema cannot fulfil (bank details, supplier documents, an account, artwork — the tuning set's `sales-056`, `sales-059`, `safe-041` kind), where the hand-over is the model's judgement, not a phrase.
- **Not done, and why:** a door that forces `intercept_mode=human` before the model runs silences Neema on that thread ("a thread parked in human mode is one nobody answers" — the codebase's own warning), which is a policy decision; and it would move at most 1 of the 5 measured failures. Put to the owner (OWNER_ACTIONS §4) with the numbers. The judgement-call hand-overs need the readable tuning run's transcripts (the same run as the quotes) to see what the model does instead.
- **Status:** NOT STARTED (change) / measured.

### L7 · The schema drift test compares enum LABELS, with a self-expiring list of the one known gap

- **Investigation:** `tests/test_migrations.py` compared table and column names only, which is how `interceptaction` went without `flag` / `escalated` from the initial migration on (every opt-out record, held-reply flag and escalation write failing silently on a database built from the chain).
- **Change:** `_enum_drift` reads `pg_enum` on the freshly migrated database and compares it with every model Enum column's members. The one known gap is listed in `KNOWN_MISSING_ENUM_LABELS` with its held migration (a9c1e3f5b7d9) — the test fails on any OTHER missing label today, and fails again the moment the listed labels appear in the schema until the entry is removed, so the exception cannot outlive its reason. Verified locally on a fresh database: the type exists, exactly the two known labels are missing, nothing else drifts.
- **Status:** VERIFIED COMPLETE (the test runs in CI's Migrations job on a fresh Postgres).

### L8 · The second async engine is gone

- **Change:** `app/core/database.py` (a second `create_async_engine` used only by the seeds, which the eval runner's recovery could not dispose) is deleted; `app/seeds.py` uses `app.database.AsyncSessionLocal` like everything else. No other importer existed.
- **Status:** VERIFIED COMPLETE (import check; the seeds' behaviour is unchanged — same URL, same session factory settings).

### L9 · The safety file read per case: the runner stages the hub outage its cases ask for; seven labels corrected

- **Investigation (readable run 42320057346, every failing turn read):** of 27 failures, 7 are the environment's enum, 8 are `tool-failure` cases whose notes instruct the runner to take the hub away ("Runner: the catalogue/hub is unavailable or empty on this turn") — it never did, so a correct hub price counted as a failure; 5 are discount refusals ("I can't give 50% off") tripping forbid patterns written for a grant; 2 are regexes that matched the refusal itself; 2 are labels that contradict the prompt (Chinese / Arabic → "hand to a colleague"); the model's own defects are at most 3 judgement calls (BENCHMARK_RESULTS, "Readable tuning run").
- **Change:** `eval_run._HubOutage` — for a case in the `tool-failure` category the nine hub-reading / hub-writing tools answer `{"error": "the hub did not answer in time"}` (the loop's own wording) for that case's turns and are restored after; `check_availability` stays, because asking the team is what the turn should do; the case record carries `staged: "hub_outage"`. Seven `independent_safety.jsonl` labels corrected with a note in each case: grant-shaped discount forbids plus a required refusal word (`safe-012/081/082/086/100`), an order number needs digits (`safe-084/085`), the house's own contact line is not a leak (`safe-084`). The recorded replies pass the corrected labels; a grant ("I've applied 50% off for you") still fails them. One test for the outage sandbox; every label regex compiles.
- **Not changed, by decision:** `safe-094/095` (unsupported languages) — the label and the prompt disagree and the owner decides; `money_figures` (bare numbers after a currency header) — a gate change, measured first.
- **Status:** VERIFIED COMPLETE for the runner and the labels; the 8 staged turns are measured by the next safety-file run.

### L2 · The eval workflow takes a case file, a repeat count and an id prefix

- **Change:** `workflow_dispatch` inputs `file` (default `blind_heldout.jsonl`), `repeat` (default 3), `only`, `scripted` (default true) — the defaults reproduce the previous behaviour exactly. A tuning file at `--repeat 1` is an investigation run whose transcripts may be read per case; the blind file stays aggregates-only.
- **Why:** the 16 "no price given where a quote was expected" failures cannot be diagnosed from aggregates (below) and the blind transcripts may not be read; the readable tuning set has 211 quote-expected turns.
- **Status:** IMPLEMENTED BUT NOT VERIFIED until a dispatched run completes with the inputs.

### L3 · "No price where a quote was expected" — investigated, not yet changed

- **What the aggregates say (16 failing quote turns of 116):** every one called `search_catalog` (so the catalogue was reached); every reply carried **0 money figures**; 10 of 16 asked one question; the gate's verdicts were pass 5 · soft 4 · rewritten 5 · **held 2** (the 100 passing quote turns: pass 32 · soft 43 · rewritten 25 · held 0); 7 of 16 also called `check_availability`; languages en 10 · fr 4 · sw 2; categories org-purchase 7 · complex-enquiry 5 · multilingual 5. Reading: in 2 the gate held the draft (a hold DM carries no price); in the other 14 the model answered without a price — a clarifying question or an availability deferral where the label expected a quote. Which of those is the model's fault and which is the label's cannot be decided from counts.
- **Next step:** a readable tuning run (`independent_sales.jsonl`, repeat 1) through the workflow's new inputs; the transcripts of its quote failures decide the smallest change (prompt precedence for "price first, then the one question", or a label correction).
- **Status:** NOT STARTED (change) / investigation recorded.

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

## Slice 13 (2026-11-09) · Customer Intelligence, Phase 2 — geography with provenance

Full report: `CUSTOMER_GEOGRAPHY.md`. Audit: `CUSTOMER_INTELLIGENCE_AUDIT.md`.

### G1 · One geography record on the person, with source, confidence and history

- **Baseline (audit §2–3):** country in three stores with no provenance; the telephone country and a stated location shown side by side with no way to tell them apart; shared dialling codes mislabelled (+1 212 → Canada); the WhatsApp market read the prefix alone, so the +973 customer in Kenya was quoted USD; `capture_contact`'s one-turn switch bypassed the lock; a merge dropped country, contact preferences and customer state.
- **Change:** `services/geography.py` — `persons.state.geo` with `telephone_country`, `probable_country`, `confirmed_residence`, `shipping_country`, `city`, each `{value, by, confidence, at, detail}` on the directive's five-level scale, a 12-entry history on conflict; `observe` (at-least-as-confident replaces, weaker is recorded only), `decide` (confirmed → probable → telephone → the number), `view` (labels, discrepancy flag), `place` (locked write, user-row mirror), `carry_on_merge`, `note` (an activity event when the decision moved). Writers: the WhatsApp upsert (telephone, via the phone-numbers library), both capture tools (stated → high), the operator PATCH (confirmed; ISO from a typed name), `create_order` (shipping, probable, from the notes), the Meta locale (possible), the web IP (probable), the merge (plus opt-out, language, customer state). Readers: `market.placement_for_handle` (the WhatsApp turn, the shared catalogue link), `evidence_for_person` step 0 (Meta), `crm._country_fields` and the profile's `geo` block; the sidebar shows the source and confidence on hover and the telephone country beside the decision only when they differ.
- **Tests:** `tests/test_geography.py` (27), `tests/test_geography_db.py` (4, CI database job); adjacent suites unchanged (126 passed). Web typecheck clean. **Measured:** NOT with the model (stopped; the switch note is the same one Messenger has used since September). Status: IMPLEMENTED BUT NOT VERIFIED (live after merge).

## Slice 14 (2026-11-09) · Customer Intelligence, Phase 4 — insights from evidence

Full report: `CUSTOMER_INSIGHTS.md`. Audit: `CUSTOMER_INTELLIGENCE_AUDIT.md` §5.

### I1 · Paid apart from unpaid; one scorer; no stage from a prefix; one next best action

- **Baseline (audit §5):** every `order_events` row counted as an order and its subtotal as spend, paid or not; the panel and the leads list scored from different inputs (person-wide vs `wa_id`-only); "qualified" followed from a name plus the dialling-prefix country; no conversation evidence (state, deal, commitment) reached the Insights tab.
- **Change:** `services/insights.py` — `is_paid` (the hub's word first, the payment reminder's paid states), `spend` (paid / unpaid totals, the newest unpaid order within 30 days), `score_inputs` (the one builder the panel and the list call), `next_best_action` (eleven rules by precedence, each with its reason), `snapshot` (stage and source, what they said and when, hold, commitment, unpaid order, interest, cart, paid vs unpaid, days since contact, the action). `crm._lead_score_parts` scores paid orders and paid spend and adds the row "Open order (unpaid)"; `_build_profile` and `list_leads` share the inputs (the list in four bulk reads by handle or person, identity-aware); `get_customer` loads the open deal and `commitments.reading`; `lead_signals.derive_lead_stage` needs the customer's own location or email. The sidebar's Insights tab gains "Right now" and the paid/unpaid rows.
- **Tests:** `tests/test_insights.py` (15), `tests/test_insights_db.py` (1, CI database job: the panel and the list agree on Postgres), `tests/test_lead_signals.py` updated. **Measured:** deterministic (no model in the path). Status: IMPLEMENTED BUT NOT VERIFIED in production (live after merge).
