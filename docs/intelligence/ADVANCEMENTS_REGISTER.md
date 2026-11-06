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
- **Status:** VERIFIED COMPLETE (model-free layer). The effect on live replies
  (holds, paid-claim notes, closer silence) is IMPLEMENTED BUT NOT VERIFIED
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
- **Status:** VERIFIED COMPLETE at the rule level; live effect IMPLEMENTED BUT NOT VERIFIED (real-model run).

## W4-1 · No manufactured urgency, scarcity or discount from nowhere (hard gate rule)

- **Baseline:** prompt-only; no rule kind for it (INVESTIGATION 4.1; research memo §6).
- **Change:** `review.manufactured_pressure` — hard `pressure` finding for "today only / last piece / only N left / hurry / I can give you a discount / 10% off" unless a promotion tool in this turn supplied the offer. An honest "we don't offer discounts" passes.
- **Status:** VERIFIED COMPLETE at the rule level; live effect IMPLEMENTED BUT NOT VERIFIED.

## W1-7 · A promised offer that cannot be read is surfaced, not dropped

- **Baseline:** `granted_promise` → None on a redis error; the order went out without the discount, silently (INVESTIGATION 1.7).
- **Change:** the business rule "no offer recorded beats no order created" stands; the gap is now written on the order note, returned to the model as `offer_unverified` with a next step ("a colleague confirms the final amount"), and logged. **Rejected:** refusing the order (the owner's recorded trade-off prefers the order).
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
- **Status:** VERIFIED COMPLETE at unit level.

## W2-4 · The scribe never erases a team check or a hold

- **Change:** `deals._merge_next_action` — an open team check keeps its kind and tucks the new intent under `then`; a hold survives.
- **Status:** VERIFIED COMPLETE at unit level.

## W9-2 · `handoff_to_human` rings the team

- **Change:** the tool now files the same team note the other hand-over paths file (`_team_note`), never on a draft; result carries `team_told`.
- **Status:** IMPLEMENTED BUT NOT VERIFIED.

## W5-2 · A caption-less photo stays a turn in history

- **Change:** history renders an inbound image/video row with no text as "[the customer sent a photo]" instead of dropping it.
- **Status:** IMPLEMENTED BUT NOT VERIFIED.

## W3-1 · A complaint earns the care-first length

- **Change:** the length target's `negative` flag also reads the customer-state floor's `complaint`.
- **Status:** VERIFIED COMPLETE at unit level (target computed); effect on replies needs the model run.

## W8-1 · Language continuity checked without the model reviewer

- **Change:** `review.language_mismatch` — a soft, deterministic `language` finding for Hindi script, Swahili, French and Portuguese customers whose draft is plainly in another language; English and mixed left alone.
- **Status:** VERIFIED COMPLETE at rule level.

## W7-6 · State writes take the row lock

- **Change:** `intent.record_opt_out` and `customer_state.apply` lock the person row before rewriting `state` (the `state_lock` contract).
- **Status:** VERIFIED COMPLETE at unit level.
