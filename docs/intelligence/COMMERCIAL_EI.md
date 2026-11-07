# Commercial Emotional Intelligence — slice 11 (2026-11-07)

The owner's directive of 2026-11-07 ("Commercial Emotional Intelligence across
the entire sales journey") is continuation work. This is the report it asks
for in §14, in its eight parts, written against the code as it is on branch
`claude/where-are-we-bx9v9w` (main 78535d8 + PR #343's fix). Everything here
is either read from a file (with its location), measured by a command named
here, or marked NOT MEASURED. No evaluation run was dispatched: the owner's
standing word of this morning ("stop all the passes until requested by me")
holds, so the model-in-the-loop measurement of this slice is listed in §7 as
the first thing to run when the owner lifts it.

---

## 1. What already existed (verified inventory)

The directive's thirteen journey stages and twelve audit areas map onto
components that are already in production. Each row names the component that
actually controls the behaviour, and how that was established.

| Capability (directive §4/§5) | Where it lives | How verified |
|---|---|---|
| First contact and welcome (Stage 1) | `prompt.py` "FIRST CONTACT — THE WELCOME" (owner's own shape, first touch only; returning customers get "the calm familiar greeting of someone known") | prompt text; `tests/test_commercial_ei.py` builds the prompt |
| Reading the customer before writing (Stages 2, 5, 6) | `prompt.py` "BEFORE YOU WRITE — THE CONSULTANT'S READ" (what they asked, what we know, what the hub says, where they are) and "READ THE ROOM" (eager / hurried / hesitant / price-sensitive / upset / grief / suspicious, each with a move) | prompt text |
| Buying-stage reading in code (Stage 5) | `services/customer_state.py`: a deterministic floor (`floor()`) reads stop › paid claim › complaint › consulting › comparing › needs time › ready › closing from the customer's words, in English, Swahili, French, Portuguese, Hindi; a light-model note fills in only where the floor reads nothing (`after_turn`, `note_llm`) | model-free scorer `eval_floors` (§7) |
| What the reading does (Stage 9, §9) | the reading is written on the person and the deal (`customer_state.apply`); a hold state (`needs_time`, `comparing`, `consulting`) puts `deal.next_action["hold"]` with an `until`, which the outreach dispatcher honours (`actions.py` "held by rules"; `deals.py` opens a deal for a hold even before a cart); the next live turn gets `turn_note` — "they asked for time … do NOT ask again when they will decide, do NOT re-pitch" (`runtime.py` ~2021) | `tests/test_outreach_stage3.py` (26 hold tests), `test_commercial_ei.py::…turn_note…` |
| A named time is kept (Stage 9) | tool `schedule_check_in` (`tools.py:486`): ONE open check-in per customer per purpose, moved rather than duplicated; calendar maths in the system | tool schema + existing stage-1A tests |
| Hesitation and objections (Stage 6) | `prompt.py` "THE OBJECTION LADDER" (value → honest smaller door → instalments as a statement → a colleague), "GIFT REQUESTS AND HARDSHIP APPEALS", "IF THE TRAY TOTAL MAKES THEM FLINCH" | prompt text; gate rule W4-1 forbids manufactured urgency/scarcity/discount (`review.manufactured_pressure`) |
| Trust (Stage 7) | "READ THE ROOM › SUSPICIOUS": who we are, the Nairobi workshop, the secure link, that they may call — "confidence, not pleading"; no unprompted credibility talk | prompt text |
| Closing (Stage 8) | "CLOSE, DON'T CHAT", "ONE ASK PER REPLY", "SLOT CHECK", "CLOSE WITH QUIET MOMENTUM", the soft two-step payment close ("THE ORDER JOURNEY" / `payment_rule`) | prompt text; `tests/test_ask_only_the_open_details.py`, `test_brevity_contract.py` |
| Pricing accuracy (Stage 4) | "THE HUB NAMES IT, THE HUB PRICES IT", "VARIANT PRICING" (the collar's 8-inch $3.50 / 10-inch $4 is the owner's own example of variant pricing — the "$8 then $3.50–$12" the directive cites is this rule working), "NEVER PRICE A GUESS", "A PRICE CARRIES ITS SCOPE"; the judge's `figures: hub-only` assertion | prompt text; runner assertion `figure not from this turn's tools` |
| Payment (Stage 10) | hard gate rule W1-9: a payment acknowledgement needs the hub's word (`review.paid_ack_without_source`); the turn note on a paid claim ("never announce it as received"); PAYMENT block per country | gate tests; `tests/test_intelligence_floors.py` (paid-claim floor) |
| Production, status, fulfilment (Stage 11) | `check_order_status` tool ("where is my order?" → the tool, never memory); "WHEN SOMETHING HAS GONE WRONG" steps 2–3 (find out, tell them what you found, never invent a date) | prompt text |
| Delivery and after-sales (Stage 12) | "WHEN SOMETHING HAS GONE WRONG" (acknowledge once, find out, tell them, `raise_complaint`, stay with them; never sell into a complaint), "READ THE ROOM › FRUSTRATED" (stop selling entirely); the complaint reply-length kind (W3-1) | prompt text; `reply_length.py` complaint target |
| Repeat purchase and memory (Stage 13) | `agent/memory.py` (facts, recent orders), `agent/measurements.py` (a returning customer is never measured twice), "THE COMPANION SET" (their own history as the only upsell), "SCHEDULE THE NEXT NEED", `product_interest` ("this product" for a returning customer) | code; `tests/test_memory*.py`, `test_measurements*.py` |
| Brevity and natural language (§8) | `reply_length.py` (a target computed from the customer's message, handed to the writer; long replies recorded), "TEXT LIKE A PERSON", "NEVER REPEAT YOURSELF", "A SHARED FACT IS SAID ONCE" (`said_once.py`), "PACING" | code + prompt; `test_brevity_contract.py` |
| Messaging safeguards (§9) | one commitment / one answer / one dispatcher (stages 1–3, PR #310); dedupe keys on `agent_actions`; cooling (`cooling.py`); opt-out on every door; the hold in the dispatcher; `OUTREACH_MODE=shadow` in production | `tests/test_outreach_stage1.py`, `_stage3.py`, `test_cooling*.py`; `/api/health` → `outreach: shadow` |
| Human takeover (§4.11) | `handoff_to_human` rings the team (W9-2); "A COLLEAGUE'S ANSWER OVERRIDES YOURS"; takeover re-check fails closed (W1-5) | existing tests |
| Measurement (§4.12, §11) | the Excellence Score (`EXCELLENCE_SCORE.md`), the case set (584 cases incl. blind), two scorers (`eval_floors` model-free; `agent_eval --cases` model-in-the-loop with `check_turn`), the Performance view | `BENCHMARK_RESULTS.md` |

Two things the inventory did NOT find, and that this slice does not add:
a separate "emotion classifier" or "sales-stage model" — the stage reading
is the floor plus the light note; and a per-turn "decision framework" call —
the twelve questions of directive §6 are what "THE CONSULTANT'S READ" and
"READ THE ROOM" already instruct, in one model call. Adding either would be
the second decision-maker §10 forbids.

## 2. What was missing (root cause, with evidence)

### 2.1 The Johana turn was the prompt working as written

The customer wrote "Waiting I will come back you Asap." after the sizes and
prices of a straight collar; Neema answered "Thank you, Johana, take all the
time you need. Is there a day you'd like me to check back with you?"

- **Intent reading — correct.** `floor("Waiting I will come back you Asap.")`
  → `needs_time` (verified in `test_commercial_ei.py`). The hold was written
  on the deal; the dispatcher would not have chased; the next live turn would
  have been told not to re-ask.
- **The instruction — wrong by the owner's standard.** The prompt rule "WHEN
  THEY SAY THEY WILL COME BACK" (`prompt.py:1060` at main) said, as step 2:
  *"ASK if there's a particular time we should remind them, or have the
  delivery ready for ('Is there a day we should check back with you?'). This
  is your ONE question."* The model obeyed it. A second source said the same
  in the team-takeover section (`prompt.py:1510`): *"'I'LL COME BACK' gets a
  short warm close and one offer: 'We look forward to serving you. Shall I
  remind you at the end of the month?'"* The rule came in with #251
  (2026-10-05) and was reworded, not changed, in #294 and #310. Its own
  test file records it as **the owner's rule of 2026-08-12** ("thank them,
  say we'll be waiting, and ask whether there's a time to remind them");
  the directive of 2026-11-07 supersedes that half on the owner's word, and
  this slice says so in the test's docstring rather than quietly rewriting
  it. The booking half (a time they name is kept) is unchanged.
- **A real contradiction inside the prompt.** "CLOSE, DON'T CHAT" (every
  question must move the order), "SLOT CHECK" (ask only the first empty
  slot) and "READ THE ROOM › HESITANT" (the smallest next step, never a
  chase) all point at *"just send me your size when you're back"*; the
  come-back rule overrode them with a question that moves nothing and takes
  back the next move the customer had just claimed. The owner's reading in
  the directive is the one the rest of the prompt already held.
- **The scorer never saw it.** `eval_run.check_turn` failed a `hold_ack`
  turn only for a pitch, or for a date ask *after the customer had already
  given one* (`after_hold`). The first, unprompted ask scored as a pass, so
  every measured run carried the habit invisibly. The recorded transcript of
  the first real-model run shows it twice in a row on one thread (after "Let
  me compare prices." and again after "I need to consult my bishop."), both
  marked `[experience] ok`.
- **It was already on the register, unfixed.** `UNFINISHED_REGISTER.md` row
  "The check-back question after a decline" (5 sales turns) recorded the
  same habit on declines as "a prompt change, measured with the model first".

**Measured baseline (replayed, no model call).** Re-reading every recorded
run in `results/*.json` with the new check (a sentence ending in "?" that
asks when to remind, check back or follow up, on a `hold_ack` turn that is
the first hold in the case):

| Recorded run | hold_ack turns | unprompted check-in asks |
|---|---:|---:|
| blind pass^3, main 6f1060a (run 42320051884) | 195 | 59 (30%) |
| blind first pass, main aaf7978 (run 42289125585, partial) | 101 | 33 (33%) |
| blind pass^3 VOID, main f4a5b37 (run 42339309914; its pass 1 valid) | 195 | 40 (21%) |
| sales tuning, main 6f1060a (run 42320054512) | 33 | 19 (58%) |
| safety runs ×4 (2 hold_ack turns each) | 8 | 2 |
| **all recorded** | **532** | **153 (29%)** |

Blind-set figures are aggregates only. (Disclosure: while building this
replay two example reply lines from blind-set files, and a dozen `hold_ack`
user lines from a grep across all case files including the blind one, were
printed to the session; nothing in this slice was tuned to them — the floor
additions are the directive's own Stage-9 phrasings, and the new cases are
authored from the directive.)

### 2.2 Floor phrasings the directive names that the floor did not read

`floor()` returned nothing for "I'll confirm later" (the regex knew "will
confirm" but not "'ll confirm") and for a bare "Let me consult." (the
consulting regex required a named person). Without a reading there is no
hold on the deal, so a planner could legitimately have messaged next day.
"Give me a moment" and "Please wait" also read as nothing — **by design, kept**:
in the case set those words precede a photo or a detail far more often than a
decision ("hold on, sending the photo"), and a hold there would block outreach
for days and tell the next turn the customer asked for time. The prompt's
"READ THE ROOM" handles them as a short acknowledgement.

### 2.3 Not a weakness of memory, hierarchy or a second system

The product was in context (the hold note, `product_interest`, the cart);
the instruction, not the memory, dropped it. No competing prompt, classifier
or workflow was involved: one rule, obeyed.

## 3. What was enhanced (and how it builds on prior work)

Smallest coherent set, all inside existing components:

1. **The come-back rule, rewritten** (`apps/api/app/agent/prompt.py`,
   "WHEN THEY SAY THEY WILL COME BACK"): (1) accept in one warm clause and
   KEEP THE ITEM — name the piece they were on; (2) NAME THE ONE STEP that
   completes it as a STATEMENT, the first empty slot from SLOT CHECK (the
   owner's own shape is quoted); (3) the instalment line only when money is
   the stated reason (unchanged, owner 2026-10-30). Then the new centre:
   NEVER ask when to remind them; a check-in is booked ONLY when they name a
   time, with `schedule_check_in` in the same turn, one per matter
   (unchanged mechanics). Then STOP: no pitch, no re-listing, no question of
   any kind. Builds on: SLOT CHECK, CLOSE DON'T CHAT, READ THE ROOM, the
   Stage-3 hold note, the Stage-1A check-in tool.
2. **A firm decline gets one gracious line and no question** (new bullet
   under the same rule) — the register's open row, same root cause, same
   habit; "a decline that carries a thank-you gets that same single line"
   keeps slice 6's decision that a decline-plus-thanks is not a bare closer.
3. **The team-takeover example corrected** (`prompt.py` "HOW OUR TEAM
   ANSWERS"): the team's "Shall I remind you at the end of the month?" is now
   named as one of the places Neema does better than the team, with the
   owner's shape beside it — the second source of the habit removed rather
   than out-ranked.
4. **The cross-reference in the bare-closer bullet** updated from "the
   three-part message" to "the come-back message (keep the item, name the
   one step, no question)".
5. **The floor** (`services/customer_state.py`): `'ll confirm/update you
   + later/tomorrow/by/on/next/after/once/when/in` → `needs_time`; a bare
   "let me / I need to / I must / I'll consult(.)" → `consulting`. "I'll
   confirm the size now" stays unread (tested).
6. **The scorer** (`jobs/eval_run.py`, `jobs/agent_eval.py`): a new
   `asks_for_a_check_in(reply)` — any sentence ending in "?" that asks when
   to remind, check back or follow up. On a `hold_ack` turn it is now a
   failure: "asked for a check-in date the customer did not offer" (first
   hold) or the existing "re-asked for a date the customer already gave"
   (after a named one). The experience flag for auditors gains "ASKED FOR A
   CHECK-IN DATE THEY DID NOT OFFER". A statement on *their* day ("I'll check
   back with you on Friday as you asked") and a product question ("the
   10-inch or the 8-inch?") are not caught (tested).
7. **Cases** (`jobs/eval_cases/commercial_ei.jsonl`, 10 developer cases;
   `audit.jsonl` gains `audit-011`, the owner's collar case): the pause,
   the bare consultation, "I'll confirm later", "give me a moment" (not a
   hold), the firm decline, comparing without a discount, a named Friday
   that must book the check-in and must not ask, the return after the pause
   ("Back. Size 15 please" moves the order with no re-welcome), money as
   the reason (instalment line required), and the same pause in Swahili.
   Every `hold_ack` turn forbids a question and the reminder phrasings and
   requires the item's name; `audit-011` additionally forbids
   `schedule_check_in` (no time was named) and "take all the time".

Not changed, deliberately: the hold mechanics, the dispatcher, the check-in
tool, the gate rules, the length targets (the owner's 27-word reply sits
inside the 45-word target that message earns; measured), the memory and
product-interest context, every other prompt rule.

## 4. What was preserved (verification)

| Safeguard | Evidence after the change |
|---|---|
| A hold still blocks outreach and informs the next turn | `tests/test_outreach_stage3.py` 26 tests pass unchanged; `test_commercial_ei.py` asserts the turn note still says "do NOT ask again when they will decide" |
| A named time is still booked, once | the rule keeps `schedule_check_in` "IN THE SAME TURN" (asserted on the built prompt); `cei-007` requires the tool on "by Friday" |
| No new outbound path, no new follow-up | the only automation touched is none: the change removes an ask, it adds no sender; `OUTREACH_MODE=shadow` untouched |
| Brevity | the owner's reply: 27 words against a 45-word target, `is_long` → None (tested) |
| No manufactured pressure | `manufactured_pressure(owner_reply)` → None (tested); the comparing case forbids discount/limited/today only |
| The bare-closer silence | unchanged rule; `cei-001`'s final "ok" expects silence; floors `silence` 1256/1268 (0.991) |
| The floor on everything else | model-free floors over all 464 non-blind cases: `said` 0.859 → 0.863 (the 14 newly labelled turns all read), `lang` 0.963 → 0.969, `opt_out` 0.952 unchanged, `silence` 0.991; no previously passing label lost (`results/floors-after-slice11-all.json` vs `floors-rescored-all.json`) |
| The two scorers still agree with production's gate | the new check reuses the runner's own turn verdict; the gate itself is unchanged |
| Full API suite | see §7 |

## 5. How Neema now decides on a pause (the framework, in the existing turn)

One model call, as before; what changed is the instruction it obeys at step
(4) of THE CONSULTANT'S READ when the register is "hesitant / asking for
time". In the twelve questions of directive §6:

| Question | Answered by |
|---|---|
| What did they communicate? | the floor's reading (`needs_time` / `comparing` / `consulting`) + the model's read of the words |
| Relevant history? | the thread, the hold note, `product_interest`, the cart, memory |
| What do they need now? | to be heard, and to find the thread warm when they return |
| Buying stage? | paused, not lost — a hold, not a decline |
| Emotional concern? | none stated → no reassurance, no apology, no instalment line (unless money was named) |
| Verified information? | the item and its open slot (size / colour / quantity) from the hub rows already quoted |
| Next useful action? | keep the item, name the one step as a statement |
| Closing opportunity? | no — "never the full close, and never a chase" |
| Is another question necessary? | no — every slot is theirs to fill when they return; a question now takes the move back |
| Would a brief acknowledgement suffice? | yes: one short message, then stop |
| Should automation stay silent? | yes: the hold blocks planners until `until`; nothing is booked unless they named a time |
| Human intervention? | no |

A firm decline follows the same shape minus the step: one gracious line, the
door open, no question, nothing booked.

## 6. Before and after

Only the first row is a measured "before" (the owner's screenshot and the
recorded runs); the "after" column is what the rewritten rule instructs and
what the new cases assert — **NOT MEASURED with the model yet** (§7).

| Moment | Before (recorded) | After (the rule; asserted by the cases) |
|---|---|---|
| The pause with an item in play — "Waiting I will come back you Asap." after a collar quote | "Thank you, Johana, take all the time you need. Is there a day you'd like me to check back with you?" | "Sure, Johana — happy to help you get the right collar. Just send me your preferred size when you're back, and we'll get your order sorted." (`audit-011`: requires collar + size, forbids any question, forbids booking) |
| Comparing — "Let me compare prices." | "Take your time. … Is there a day you would like me to check back with you?" (recorded transcript) | accept, keep the chasuble, no discount, no question (`cei-006`) |
| Consulting — "I need to consult my bishop." | "Please take all the time you need with your bishop. Is there a day you would like me to check back with you?" (recorded, the same thread, second time) | accept, keep the gowns, no question; when the committee says yes, the order moves (`cei-002`) |
| A named time — "I will confirm by Friday" | (not a failure before either) booked, sometimes also asked | booked in the same turn, confirmed in one clause, never asked (`cei-007`) |
| Money as the reason — "It's a lot right now, I'll come back when I get paid" | the instalment line (unchanged rule) | the instalment line as a statement, no question, no discount (`cei-009`) |
| A firm decline — "Thanks for the info. Not for me right now." | 5 recorded sales turns asked "Is there a day you'd like us to check back?" | one gracious line, no question, no alternative (`cei-005`) |
| "Give me a moment" | (varied) | a short line, no hold written, no reminder talk (`cei-004`) |
| The return — "Back. Size 15 please" | (not measured) | the order moves; no re-welcome; no reminder talk (`cei-008`) |

Opening, recommendation, objection, payment, fulfilment and after-sales
examples are NOT re-shown here because this slice did not change them; their
rules and evidence are in §1 and in `EVIDENCE_DOSSIER_FOR_INDEPENDENT_REVIEW.md`.

## 7. Tests and measurements

Run with CI's settings (`DATABASE_URL`, `DATABASE_URL_SYNC`, `SECRET_KEY`):

| What | Command | Result |
|---|---|---|
| The slice's own tests (14) | `pytest tests/test_commercial_ei.py` | pass — floor readings (Johana, the Stage-9 phrasings, the near-misses, "a moment is not a hold"), the built prompt (no "Is there a day…", the new instructions present, the booking kept), the owner's reply through the length and pressure gates, the scorer on both replies, every shape of the reminder caught and the two non-asks not caught, the experience flag, the hold note |
| Neighbouring suites | `pytest tests/test_commercial_ei.py tests/test_intelligence_floors.py tests/test_eval_harness.py tests/test_outreach_stage3.py tests/test_brevity_contract.py tests/test_ask_only_the_open_details.py` | 312 passed |
| Lint | `ruff check` on the five changed files | clean |
| Model-free floors, all non-blind cases (464 cases, 1,268 turns) | `python -m app.jobs.eval_floors --all --json results/floors-after-slice11-all.json` | `said` 436/505 = 0.863 (was 422/491 = 0.859); `lang` 0.969 (0.963); `opt_out` 0.952 (=); `silence` 0.991; `length_kind` 0.570 (0.566) |
| The new file alone | `python -m app.jobs.eval_floors --file commercial_ei.jsonl --misses` | `said` 13/13, `silence` 23/23, `lang` 2/2; `length_kind` 18/23 — the five misses are honest label-vs-target disagreements (the target gives a 45-word room to "Let me compare with other suppliers first"; the label says a come-back message is short) and are recorded, not relabelled |
| Baseline of the habit, replayed from recorded runs | the replay in §2.1 | 153 of 532 recorded `hold_ack` turns (29%) |
| Full API suite | `pytest tests` | see the row in `REGRESSION_SAFETY_REPORT.md` for this slice |
| **Model-in-the-loop, after** | `python -m app.jobs.agent_eval --cases --file commercial_ei.jsonl --repeat 1` and `--file independent_sales.jsonl` (its 33 hold_ack turns; 19 asked before) | **NOT RUN — evaluation is stopped on the owner's word.** This is the measurement that turns §6's "after" column from asserted into measured. Cost estimate from the ledger: the 10 new cases ≈ 23 model turns ≈ $1; the sales file ≈ 230 turns ≈ $8 (at ~3–4 ¢ per turn) |

Scorer note for comparability: because the `hold_ack` verdict is stricter
from this slice on, the next run's `hold_ack` failures are not comparable
with earlier runs' on that assertion alone; the replay above gives the
earlier runs' figure under the new rule (29%), so the before/after is
like-for-like.

## 8. Remaining opportunities (prioritised)

1. **Measure it** — the two runs in §7, when the owner lifts the stop. Until
   then everything in §6's "after" column is an instruction, not a result.
2. **Stages 10–13 beyond the pause.** This slice fixed the one confirmed
   weakness the directive diagnosed and its twin (the decline). The directive's
   other 23 scenarios are covered by existing rules and by readable cases
   (keyword map below), but the recorded runs have not been re-read for each
   of them with the directive's ten per-scenario criteria; that read is a
   model run plus a rater pass (`OWNER_ACTIONS.md` §3, people not yet named).
3. **"Give me a moment" / "please wait" in context.** Kept out of the floor
   on purpose; whether the model answers them with one short line or with a
   pitch is a model-run question.
4. **The decline-plus-thanks label conflict** (`UNFINISHED_REGISTER.md`): the
   labels expect silence, the code answers with one line by slice 6's
   decision. Unchanged here; the new rule says "one line, never more".
5. **The length floor at 0.57** is the weakest floor and the one most at odds
   with the labels; a come-back message now has a 45-word room where 25 would
   do. A tighter target for hold states is a later, measured change.
6. **Real-derived cases** (anonymised production threads) still need the
   admin credential (BLOCKED, `OWNER_ACTIONS.md` §2); the owner's screenshot
   cases are the only production-derived content so far.

### Coverage of the directive's 25 scenarios (§12), readable cases only

Keyword match over user turns and notes in the non-blind files — an
approximation (a keyword is not a scenario), listed so nothing is claimed
by silence. Counts are cases; up to four ids each.

| # | Scenario | Cases | Examples |
|---:|---|---:|---|
| 1 | new customer asks a price | 208 | audit-001, audit-002, audit-003, audit-004 |
| 2 | returning customer, earlier quotation | 73 | audit-001, ctx-028, ctx-032 |
| 3 | comparing several products | 15 | audit-002, audit-004, cei-006, ctx-041 |
| 4 | cannot choose the size | 86 | audit-006, audit-011, cei-008 |
| 5 | international shipping | 50 | audit-001, ctx-014, ctx-022, ctx-026 |
| 6 | product quality concern | 13 | ctx-012, ctx-039, ctx-049, lang-007 |
| 7 | possible fraud | 18 | ctx-014, ctx-018, ctx-019, ctx-028 |
| 8 | requests a discount | 40 | cei-006, ctx-007, ctx-014 |
| 9 | "expensive" | 10 | cei-009, ctx-014, lang-055, lang-057 |
| 10 | time to think | 8 | cei-001, ctx-014, ctx-031, ctx-047 |
| 11 | consulting a decision-maker | 57 | audit-004, audit-005, cei-002 |
| 12 | promising to return ASAP | 24 | audit-002, audit-005, audit-011, cei-008 |
| 13 | ready to purchase now | 26 | audit-006, cei-002, neg-008, neg-021 |
| 14 | struggling with payment | 7 | ctx-003, ctx-029, lang-095 |
| 15 | order update | 10 | ctx-019, ctx-033, ctx-034, ctx-039 |
| 16 | production delay | 3 | ctx-037, ctx-038, lang-060 |
| 17 | frustrated about delivery | 6 | neg-015, neg-031, ctx-032, ctx-037 |
| 18 | after-sales support | 8 | ctx-012, ctx-021, ctx-026, ctx-043 |
| 19 | repeat purchase | 20 | audit-005, audit-006, ctx-005, ctx-009 |
| 20 | declining further communication | 18 | audit-004, neg-007, neg-008, neg-009 |
| 21 | a human representative | 22 | audit-010, ctx-018, ctx-022, ctx-025 |
| 22 | conflicting prices | 2 | ctx-041, safe-003 |
| 23 | uncertainty in imperfect English | 0 by keyword | the Kenyan-English (`ke-en`, 116 cases) and Sheng files carry it; no case is labelled for it as such |
| 24 | French or another supported language | 20 | lang-017, lang-018, lang-019, lang-021 (+ pt, hi) |
| 25 | overlapping automated follow-ups | 0 true matches | this is an outreach-dispatcher property (one commitment, one dispatcher, dedupe keys: `tests/test_outreach_stage1.py`), not a scripted-customer case |

Thin rows (16, 22, 23, 25) are where the next case-authoring pass should go.

### Measurement dimensions (§11) — what exists, what is new

| Dimension | Existing indicator | Added here |
|---|---|---|
| A. Emotional intelligence | `judge: emotion` (raters, not yet named); the complaint length kind; care-first assertion | the hold-ack verdict (no unprompted reminder, item kept) |
| B. Commercial intelligence | `hold_ack` pitch check; `quote` figures; `ask_one`; `judge: sales` | `asks_for_a_check_in`; `cei-002/007/008` (the order moves after the pause; a named time is booked) |
| C. Conversation quality | words vs target, questions per reply, forbidden/required text, language | the "no question of any kind" forbids on every hold turn |
| D. Customer experience | opt-out floor; duplicate-send dedupe; review tallies (passed/rewritten/soft/held) | — |
| E. Sales effectiveness | `successful-sale` / `unsuccessful-sale` categories; the Performance view (orders, quotes) | — (needs production data over time; NOT MEASURED) |
