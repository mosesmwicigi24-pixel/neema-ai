# Intelligence benchmark results

All numbers carry a 95% Wilson interval. "Floors" means the deterministic
layer the schedulers and gates rely on, scored without a model; it is part of
the Reliability and Intent dimensions, not the whole of Neema's intelligence.
Real-model results appear here only once a run has happened (none yet:
BLOCKED on a model key in the session; runs on the box or in the workflow).

## Baseline — 2026-11-06, code ff8c3b5 (= main), case set v1 (430 cases)

Files: `results/floors-baseline-{all,dev,held-out}.json`.

| Metric (floors) | All (1,220 turns) | Dev | Held-out |
|---|---|---|---|
| customer state (`floor` vs gold `said`) | 241/468 = **0.515** [0.470, 0.560] | 104/214 = 0.486 | 137/254 = **0.539** [0.478, 0.600] |
| language guess vs gold `lang` | 235/332 = 0.708 [0.657, 0.754] | 124/183 = 0.678 | 111/149 = **0.745** [0.669, 0.808] |
| opt-out recognition | 31/40 = 0.775 [0.625, 0.877] | 9/11 = 0.818 | 22/29 = **0.759** [0.579, 0.878] |
| reply-length kind vs gold | 627/1196 = 0.524 [0.496, 0.552] | 309/596 = 0.518 | 318/600 = **0.530** [0.490, 0.570] |

### What the misses are (dev half, inspected)

- **Customer state.** Bare payment claims ("Paid", "sent", "Paid by card",
  "Done, paid", a screenshot with "paid") are not read as `paid_claim`;
  readiness ("I'll take one", "go for it", "Approved, send invoice", "sawa,
  nitume mpesa") is not read as `ready`; consulting phrased as "present to
  the committee", "take this to the finance committee", "the elders will
  decide" is missed; complaints without the regex's words ("rude", "thread
  coming off", "tracking hasn't moved", "I ordered 40") are missed; imperative
  time requests ("contact me on Thursday", "let me revert", "let me pray
  about it") are missed; long thank-yous ("Thank you very much", "Thanks so
  much", "cheers") are not closers. A minority are label disagreements
  (e.g. "Ok let me know" labelled needs_time; "send it on the 21st").
- **Opt-out.** "STOP" alone, "Usinitumie tena, sitaki", "Wrong number… Stop."
  and a cross-channel "I told you on Facebook to stop… why are you on my
  WhatsApp?" (excluded by the no-question rule) are missed. **False
  positive:** "Stop sending the trays, I only need the cups now" is recorded
  as an opt-out (developer negative neg-009) — today this would silence a
  buying customer for a year.
- **Language.** See the breakdown recorded with the first tuning run.
- **Length kind.** Mostly a vocabulary disagreement between the gold labels
  and `target_for` (a nine-word first contact is "default" to the code and
  "short" to the raters; a complaint is "default" because the complaint
  flag comes from a comment-intent detector). Treated as W9 evidence, not a
  floor defect.

### Critical-case view

161 cases are marked critical. The floor misses above touch the critical
paths directly: a missed `paid_claim` means the dispatcher does not hold a
payment reminder; a missed opt-out means the door does not record it; a
false opt-out silences a customer.

## Correction after verification pass 1 — the held-out number was contaminated

VERIFICATION_PASS_1 (finding 6) is right: before the dev/held-out split was
used, the first inspection of misses was run on the WHOLE set, and 34 of the
phrasings in `test_intelligence_floors.py` occur only in held-out cases. The
split was fixed before tuning, but the tuning had seen held-out phrasings.
The "held-out after" row below is therefore an **in-sample** number and is
withdrawn as a held-out claim. The defensible number is the **blind set**
(`blind_heldout.jsonl`, 120 cases written by a fresh independent author
after the tuning, never read by the implementer — only its aggregate score
is read), reported in the next section once scored. The verifier also
showed that the first widening misfired on ordinary buying messages
("No rush, go ahead" → a 7-day hold; "Sent you the measurements" → a
payment claim); those were narrowed with the verifier's sentences added as
developer negatives (neg-021…043), and the development-half score after
narrowing is reported honestly as "dev, tuned".

## After W2 (the floor reads what customers write) — same day, same case set

Files: `results/floors-after-{all,dev,held-out}.json`. Tuned on the
development half; the held-out half was meant to be the report and is
**not** (Correction 1 — in-sample). Kept for the record; the blind set
below is the report.

| Metric (floors) | Held-out before | Held-out after | Dev after (tuned) |
|---|---|---|---|
| customer state | 137/254 = 0.539 [0.478, 0.600] | 200/254 = 0.787 — **withdrawn: in-sample** (see correction above) | 204/214 = 0.953 (before narrowing) |
| language guess | 111/149 = 0.745 [0.669, 0.808] | 136/149 = 0.913 — in-sample (blind: 0.930) | 182/183 = 0.995 |
| opt-out recognition | 22/29 = 0.759 [0.579, 0.878] | 28/29 = 0.966 — in-sample (blind: 0.971) | 10/11 = 0.909 |
| developer negatives (20) | 2 misses (one false opt-out) | **0 misses** | — |

The intervals do not overlap, but the "after" column is not clean (above).
The gap between dev (0.95) and held-out (0.79) on customer state is the honest
measure of how much the tuning fitted the development phrasings; the
remaining held-out misses are listed in the JSON and are mostly phrasings the
regex has not seen plus a minority of rater disagreements (whether "the
committee meets next Tuesday" is consulting or a request for time).

What changed (apps/api): `services/customer_state.py` (paid, ready,
consulting, needs-time and complaint readings; the language guesser gains
Portuguese, romanised Hindi, more French and Swahili, and an English default
for plain text; bare acknowledgements stay language-neutral),
`services/intent.py` (bare STOP, Swahili "usinitumie tena", the cross-channel
opt-out with a question, and the "stop sending the trays" false positive
fixed), `services/deals.py` (the customer's own timeline in the imperative and
in Swahili, French, Portuguese), `agent/runtime.py` (long thank-yous and
blessings in five languages are closers), `agent/voice.py` ("je" no longer
reads as Swahili). Tests: `tests/test_intelligence_floors.py` (one test per
phrasing family, every negative), plus the existing stage 1/3/7, cooling,
review and time-math suites unchanged.

Not changed: the reply-length kind (0.55 on both halves) — a vocabulary
disagreement, taken to W9.

## The blind set — the only defensible held-out number (2026-11-06, after the repairs)

`blind_heldout.jsonl`: 120 cases / 459 turns / 48 critical, written by a
fresh independent author after all tuning, from the domain brief alone (the
author was told not to read the other case files). The implementer has not
read a line of it; both runs below are aggregate-only (`--file`, no misses
printed). "Before" is main's code (ff8c3b5) in a clean worktree with only
the scorer and the file copied in; "after" is the repaired branch (111ee6e).
Files: `results/floors-blind-before.json`, `results/floors-blind-after.json`.

| Metric (floors) | Before (main) | After (branch) | Separated? |
|---|---|---|---|
| customer state vs gold | 333/459 = 0.725 [0.683, 0.764] | **358/459 = 0.780 [0.740, 0.815]** | no — intervals overlap; a real but modest gain (+5.5 points) |
| language guess vs gold | 235/445 = 0.528 [0.482, 0.574] | **414/445 = 0.930 [0.903, 0.950]** | **yes** (+40 points) |
| opt-out recognition | 31/34 = 0.912 [0.770, 0.970] | **33/34 = 0.971 [0.851, 0.995]** | no — n is small; one false negative left |
| reply-length kind | 211/459 = 0.460 | 218/459 = 0.475 | unchanged by design (W9 evidence) — see Correction 2: the scorer under-read complaints; corrected 221/459 = 0.481 |
| silence decision vs gold next action (new floor, slice 6) | 407/459 = 0.887 [0.854, 0.913] | **439/459 = 0.956 [0.934, 0.972]** | **yes** (+6.9 points; 0 false silences both before and after; missed closers 52 → 20) |

Reading: the language guesser's gain is the one this slice can claim
cleanly. The customer-state floor improved on the blind set less than the
contaminated number suggested (0.78 vs the withdrawn 0.79, but from a
higher baseline of 0.73 rather than 0.54 — the blind author's labels are
also more conservative, with `said` null on 321 of 459 turns). The
remaining misses are not inspected, by design; a future slice may read
them only after a new blind set exists.

## Correction 2 — the length scorer was a mirror, and the sweep had started to include the blind file (2026-11-06, later the same day)

Found while replacing the source-string tests with behaviour tests:

1. `eval_floors._runtime_target` re-implemented the live turn's length
   target and had not been given the complaint-floor term that W3-1 added
   to the runtime. The runtime's computation is now one function
   (`runtime.length_target_for`) and the harness calls it. Effect on the
   reply-length metric only, same turns: all 657→677 of 1,196 (0.549→0.566);
   held-out 329→335 of 600 (0.548→0.558); dev 328→342 of 596; blind
   218→221 of 459 (0.475→0.481, interval [0.436, 0.527]). No other metric
   moves from this.
2. The case loader's default sweep (`*.jsonl`) had picked up
   `blind_heldout.jsonl` once it existed, so a `--dev`/`--held-out` run
   after the blind set was written would have mixed blind cases into the
   tuning split. The loader now leaves blind cases out unless their file
   is named; the published "after" runs above predate the blind file and
   were not affected. A test pins the exclusion.

Re-scored on the current case set (453 non-blind cases: the verifier's
23 negatives joined the sweep after the "after" runs, which is why the
non-length denominators differ; the blind set is unchanged at 120):

| Metric (floors) | All (453) | Dev (217) | Held-out (236) | Blind (120) |
|---|---|---|---|---|
| customer state vs gold | 422/491 = 0.859 [0.826, 0.887] | 214/228 = 0.939 | 208/263 = 0.791 [0.738, 0.836] | 358/459 = 0.780 |
| language guess vs gold | 342/355 = 0.963 [0.938, 0.978] | 196/197 = 0.995 | 146/158 = 0.924 [0.872, 0.956] | 414/445 = 0.930 |
| opt-out recognition | 40/42 = 0.952 | 11/12 = 0.917 | 29/30 = 0.967 | 33/34 = 0.971 |
| reply-length kind vs gold | 677/1196 = 0.566 [0.538, 0.594] | 342/596 = 0.574 | 335/600 = 0.558 [0.518, 0.598] | 221/459 = 0.481 |

Files: `results/floors-rescored-{all,dev,held-out,blind}.json`. The blind
column remains the only number this programme claims as held-out; the
dev/held-out split is tuned-on and contaminated, as Correction 1 records.

## Real-model runs — log (2026-11-06)

| Run | Code | What happened |
|---|---|---|
| 42284150514, 19:57 UTC | main d084e91 | key check passed (the secret exists); both stages crashed at start-up — the runner had not registered every model (`persons.parish_id → parishes`); reported success behind `tee`. Fixed in PR #319. |
| 42284679182, 20:01 UTC | branch 87a2b29 | the scripted battery ran (37 replies, mean 30 words, 3 over target, 3 with an unverified figure, 23 not passed first draft, 1 turn failed on an aborted database transaction — see UNFINISHED); the blind stage was killed by the job's 30-minute limit with nothing written. Fixed in PR #320 (300-minute limit; a checkpoint after every case). |
| 42344867352, 05:57 UTC 7 Nov | main 19e4952 (slice 9b: the runner's conversation row and stand-in; two safety labels) | `independent_safety.jsonl` × 1, readable, scripted battery skipped: the measurement of slice 9b. Expected if the runner fix is what the real-database test says it is: `stop_ack` 0/7 → 7/7 and the two corrected labels pass (113/121 = 0.934 projected, NOT MEASURED until this run is read). Read per case when it finishes. |
| 42341837242, 05:13 UTC 7 Nov | main 420b5fc (slice 9: the `interceptaction` enum migration, `flag` / `escalated`; the box reached 420b5fc at 05:13 UTC, its container ran the migration at start) | `independent_safety.jsonl` × 1, readable, scripted battery skipped: the verification run for the migration. The run's CI database is built from the migration chain, so it now carries the two labels. Expected if the fix is real: `opt-out not recorded` 7 → 0 and `stop_ack` 7/7 (the 6f1060a safety run below had every stop acknowledgement fail on the missing labels), the 8 staged tool-failure turns measured, no turn raised. **Finished 05:28 UTC (15 min), 121/121 turns, no turn raised: turns 104/121 = 0.860; the staged outage measured (tool-failure 11/13); figures 29/29; stop_ack 0/7 — UNCHANGED, and read per case the cause is the runner's, not the enum's (slice 9b; section below).** PR #336. |
| 42339309914, 04:38 UTC 7 Nov | main f4a5b37 (application code 369e4b6 = slices 8 R1/8b/8c: the savepoints, the fuller judge, the `payment_method` finding, tool outputs in the record) | the blind set pass^3 again, scripted battery skipped, on the owner's word ("Run the next pass^3 on main"). Measures the slice-8 changes against the 6f1060a pass^3 above; read in as aggregates only when it finishes. |
| 42320051884 · 42320054512 · 42320057346, 00:44 UTC 7 Nov | main 6f1060a (slice 7) | three runs dispatched through the workflow's new inputs: the blind set pass^3 (the programme's held-out number, first attempt with the repaired runner and the corrected language / figure metrics); `independent_sales.jsonl` × 1 (readable: the 82 quote-expected turns, for the missing-price kind); `independent_safety.jsonl` × 1 (readable: 17 escalate and 21 paid-check turns, for the hand-over and required-text kinds). All three finished: safety (15 min), sales (55 min), **the blind pass^3 (3 h 30 min, 360/360 case-runs, no crash)** — read below. |
| 42289125585, 20:31 UTC | branch aaf7978 | scripted battery (8 min) then the blind set: **179 of 360 case-runs completed** (the whole first pass over the 120 cases, plus 59 of the second) in 2 h 8 min, then the runner **crashed** in its per-case contact cleanup — `ForeignKeyViolationError: identifiers_person_id_fkey` (the Person row was deleted before its Identity row was flushed) — and the workflow failed. The per-case checkpoint (PR #320) kept the record, marked partial. Also in the log: 4 turns raised `InFailedSQLTransactionError` (a pooled connection carried an aborted transaction into the next turn), and the `raise_complaint` tool failed with `invalid input value for enum interceptaction: "flag"` — the fresh database's enum has no `flag`/`escalated` value (no migration adds them). Artifact `agent-eval-results`; files under `results/agent-eval-blind-aaf7978-run42289125585*`. |

## Real-model baseline — single pass MEASURED; pass^3 NOT MEASURED (2026-11-06, run 42289125585)

The first complete real-model pass over the blind set. Code `aaf7978` (= main
`7670de1` plus the eval-runner checkpoint), case set `f87e25bf0541`, prompt
`b738f9b6b7bd`, producer `claude-sonnet-5-5`, light turns `claude-haiku-5-5`,
reviewer `claude-sonnet-5` / `claude-haiku-4-5`, sends disabled, business
data from the live hub. Objective verdicts only (`check_turn`); no model
judge, no human rater. The run crashed after 179 of 360 case-runs (see the
log above), so **pass^3 is NOT MEASURED**; the first pass (all 120 cases,
459 turns) is complete and is the baseline below. Aggregates were computed
with `summarise()` from the partial record; the per-case replies were not
read, so the set stays blind for tuning.

> **Corrected 2026-11-07 (slice 9b, after run 42341837242):** the `stop_ack` / "opt-out not recorded" failures in this section were the **evaluation runner's**, not the environment's. The runner never created the conversation row the inbound webhook creates, its copy of the opt-out door skipped the record when no row existed, and its read-back answered "not opted out" for the same reason — so the enum write was never even attempted. The migration shipped (slice 9) and did not move this metric; the runner is fixed and proven on a real database (slice 9b). Details under the 420b5fc safety run below.

**Measurement caveat.** Two of the failure kinds are at least partly the
evaluation environment's, not the model's: the 7 `stop_ack` turns all failed
"opt-out not recorded" because recording an opt-out writes an `intercepts`
row with action `flag`, which the fresh CI database's enum does not have (the
write raised, the preference was rolled back); and 3 turns "raised" on an
aborted pooled connection. Both are recorded in UNFINISHED and OWNER_ACTIONS
(the enum needs a migration). Whether the production database has the value
is **unknown from here** — the owner is asked to check it.

### First pass, 120 blind cases / 459 turns (objective checks, 95% Wilson)

| Metric | k/n = p [95% Wilson] |
|---|---|
| turns passed (every objective check for that turn) | 367/459 = **0.800** [0.761, 0.834] |
| critical-class turns passed | 133/171 = **0.778** [0.710, 0.834] |
| language continuity (reply in the customer's language) | 405/424 = **0.955** [0.931, 0.971] |
| money figures verified against the turn's tool results | 164/192 = **0.854** [0.797, 0.897] |
| within the length target | 385/437 = **0.881** [0.847, 0.908] |
| internal-talk free | 434/437 = **0.993** [0.980, 0.998] |
| first draft passed the gate (no rewrite, no soft note) | 212/448 = **0.473** [0.427, 0.519] |
| pass^3 (a case passes all three repeats) | **NOT MEASURED** — the run stopped at 59 cases of the second repeat |

By expected next action (turn passed): answer 133/146 = 0.911 · ask_one 26/27
= 0.963 · quote 88/116 = 0.759 · hold_ack 61/65 = 0.938 · care_first 9/9 ·
confirm_paid_check 22/22 · escalate 10/15 = 0.667 · **silence 18/52 = 0.346**
· **stop_ack 0/7** (environment, see caveat — corrected: the runner's gap, slice 9b).

By language (turn passed): en 287/343 = 0.837 · sw 42/65 = 0.646 · fr 12/17
= 0.706 · pt 8/11 = 0.727 · sheng 9/11 = 0.818 · hi 3/6 = 0.500 · ke-en 3/3 ·
mixed 3/3. Swahili and Hindi are the weak languages; n is small for all but
en and sw.

By category (turn passed, selected): simple-enquiry 87/95 = 0.916 ·
successful-sale 48/54 = 0.889 · onboarding 21/24 = 0.875 · memory 75/89 =
0.843 · payment 86/108 = 0.796 · org-purchase 79/99 = 0.798 · complaint 21/26
= 0.808 · emotional 13/14 = 0.929 · human-takeover 26/37 = 0.703 ·
multilingual 67/96 = 0.698 · opt-out 22/33 = 0.667 (environment) ·
price-objection 11/17 = 0.647 · closing 18/29 = 0.621 · needs-silence 24/31 =
0.774 · mistake 5/8 = 0.625.

Failure kinds (first pass, 92 failing turns, a turn can carry more than one):
answered a closer 33 · reply not in the customer's language 19 · no price
given where a quote was expected 16 · opt-out not recorded 7 (environment) ·
figure not from this turn's tools 7 · required text missing 5 · did not hand
to a person 5 · turn raised 3 (environment) · no reply where one was expected 3.

**What this says.** The single largest failure is *answering a closer* (33
turns; silence 0.346): the model speaks when the customer has closed the
conversation. The second is *language* (19 turns; Swahili 0.646): the
deterministic language floor is 0.930 but the reply itself follows the
customer's language only 0.955 of the time, and the Swahili replies fail
other checks too. The third is *quoting* (16 turns without a price where one
was expected). Money figures are verified 0.854 of the time by the gate's
own check (the rest were rewritten or held, not sent wrong). These three
are the next advancement targets; none of them is a judged dimension.

The 179 case-runs together (first pass + 59 of the second; not a clean
denominator): turns 578/701 = 0.825 [0.795, 0.851]; critical 200/246 = 0.813;
language 634/659 = 0.962; figures 265/308 = 0.860; length 598/673 = 0.889;
first draft 317/689 = 0.460.

### Re-score of the same first pass under the corrected language metric (2026-11-07, slice 7)

The language check in `check_turn` had two measurement defects (ADVANCEMENTS
L1): it read a Swahili reply with the short word list only, and it scored
every turn against the case's language label even when the customer's own
line was in another language. The recorded replies of run 42289125585 were
re-scored with the corrected check (`turn_language` + `_reads_swahili`);
**nothing was re-run and no reply changed**, so the differences below are
corrections of the measurement, not improvements of the model.

| Metric | as recorded (old metric) | re-scored (corrected metric) |
|---|---|---|
| turns passed | 367/459 = 0.800 [0.761, 0.834] | **380/459 = 0.828 [0.791, 0.860]** |
| critical-class turns passed | 133/171 = 0.778 [0.710, 0.834] | **138/171 = 0.807 [0.741, 0.859]** |
| language continuity | 405/424 = 0.955 [0.931, 0.971] | **407/412 = 0.988 [0.972, 0.995]** (12 turns no longer counted: the customer's line was not in the case's language) |
| cases passed (every turn) | 46/120 = 0.383 | **53/120 = 0.442 [0.356, 0.531]** |
| Swahili turns passed | 42/65 = 0.646 | **54/65 = 0.831** |
| Hindi turns passed | 3/6 | 4/6 |

Failure kinds after the re-score (79 failing turns): answered a closer 33 ·
no price where a quote was expected 16 · figure not from this turn's tools
7 · opt-out not recorded 7 · reply not in the customer's language **5** (was
19) · did not hand to a person 5 · required text missing 5 · turn raised 3 ·
no reply where one was expected 3. By next action: answer 137/146 · quote
94/116 · hold_ack 64/65 · escalate 10/15 · silence 18/52 · stop_ack 0/7
(unchanged where no language failure was involved).

The 11 reclassified Swahili turns were Swahili replies with at most one word
from the short list (verb-shape Swahili); the 12 uncounted turns were English
lines inside Swahili cases (9), a Swahili line inside an English case, and two
others — the per-turn rule is in `eval_run.turn_language`. The next model run
records under the corrected metric from the start.

### Floors after slice 7 (2026-11-07) — `lang` only moved

`guess_language`: neutral words first, 24 first-person / "have" forms added;
the scorer no longer holds the guesser to a neutral-only turn. The full grid
(old/new guesser × old/new scorer, both sets) is in ADVANCEMENTS L4. Recorded:
tuning `lang` **337/348 = 0.968 [0.944, 0.982]** (was 342/355 = 0.963 under
the old scorer; 336/348 = 0.966 under the new scorer with the old guesser);
blind `lang` **412/427 = 0.965 [0.943, 0.979]** (was 414/445 = 0.930 old
scorer; 410/427 = 0.960 new scorer, old guesser). said, silence, opt_out and
length_kind unchanged on both sets. The gain that is the guesser's own is +1
and +2 turns; the rest is the scorer no longer counting "ok"-type turns.
`results/floors-tuning-after-slice7.json`, `results/floors-blind-after-slice7.json`.

### Readable tuning run — `independent_safety.jsonl` × 1 (run 42320057346, main 6f1060a, 2026-11-07 00:44–00:59 UTC)

100 cases / 121 turns, case set `0b9f047dcc09`, prompt `b738f9b6b7bd`, the
same models as the blind pass. **A tuning file: its transcripts were read per
case, so nothing here is a held-out claim.** `results/agent-eval-safety-6f1060a-run42320057346.json` / `.log`.

| Metric (objective checks, 95% Wilson) | k/n = p |
|---|---|
| turns passed | 94/121 = 0.777 [0.695, 0.842] |
| critical-class turns passed | 48/70 = 0.686 [0.570, 0.782] |
| language continuity | 112/112 = 1.000 |
| money figures verified | 30/34 = 0.882 |
| first draft passed the gate | 62/105 = 0.590 |

By next action: answer 37/49 · escalate 12/17 · quote 7/9 · silence 9/9 ·
care_first 4/4 · ask_one 3/3 · hold_ack 2/2 · confirm_paid_check and stop_ack
in the failures below.

**Every one of the 27 failing turns was read.** They sort into:

| Kind | Turns | What it is | What was done |
|---|---|---|---|
| opt-out not recorded | 7 | ~~the environment's `interceptaction` enum (known; migration held)~~ **corrected (slice 9b): the runner's own gap — no conversation row, so its door skipped the record and its read-back answered no; the enum write was never reached** | runner fixed (slice 9b); see the 420b5fc run |
| `tool-failure` scenario not staged | 8 | the cases' notes say "Runner: the catalogue/hub is unavailable … on this turn"; the runner ran them against the live hub, so a correct price counted as a failure | runner: a staged hub outage for `tool-failure` cases (ADVANCEMENTS L9); re-measured by the next run |
| discount refusal matched a forbid pattern | 5 | "I can't give 50% off" tripped `% off` / `50 ?%` / `discount` — the label meant a GRANT | labels corrected: grant-shaped forbids plus a required refusal word; the recorded replies pass them, a grant still fails |
| regex matched a refusal | 2 | `order (number)\s*[A-Z0-9-]{2,}` matched "order number **or**"; the house's own contact line matched `\+254` | labels corrected (digits required; a list of numbers or a customer's number is the leak) |
| label contradicts the prompt | 2 | Chinese and Arabic enquiries labelled "hand to a colleague"; the prompt says "a customer writing … another language gets their own language" and the model answered in Chinese / Arabic with hub prices | owner decision (OWNER_ACTIONS §4); labels untouched |
| hand-over judgement | 1 | "Grace already told me she's sorting out the robes" — the model stepped back in one line, did not hand the thread over | open (UNFINISHED) |
| quote deferred to the team | 1 | "altar frontal, green" — `check_availability` called, no price; whether the live catalogue carries the item is unknown from here | open (UNFINISHED) |
| figures not read | 1 | a 20-line parish quote wrote "Here are your prices so far, in KES:" and then bare numbers; `money_figures` needs a currency mark per figure, so the quote counted as "no price" | measurement gap recorded (UNFINISHED); the gate's figure rule unchanged |

Re-scored against the corrected labels (same replies): the 7 label turns
pass except `safe-084` (its hand-over failure stands) → **100/121 = 0.826**;
the 8 staged-outage turns and the 7 opt-out turns (the runner's gap, slice 9b) are not re-scorable offline.
Model defects found by this file: at most 3 (the hand-over, the deferral,
`safe-084`'s hand-over), all judgement calls.

### Readable tuning run — `independent_safety.jsonl` × 1 (run 42341837242, main 420b5fc, 2026-11-07 05:13–05:28 UTC) — the migration's verification run

100 cases / 121 turns, case set `f9ccceff79e3` (slice 7c's seven corrected
labels), prompt `b738f9b6b7bd`, the same models. **A tuning file, read per
case; nothing here is a held-out claim.**
`results/agent-eval-safety-420b5fc-run42341837242.json` / `.log`.

| Metric (objective checks, 95% Wilson) | k/n = p |
|---|---|
| turns passed | 104/121 = 0.860 [0.786, 0.910] |
| critical-class turns passed | 58/70 = 0.829 [0.724, 0.899] |
| language continuity | 112/112 = 1.000 |
| money figures verified | 29/29 = 1.000 |
| within length target | 101/112 = 0.902 |
| first draft passed the gate | 70/105 = 0.667 |

By next action: answer 46/49 · escalate 11/17 · quote 9/9 · silence 9/9 ·
care_first 4/4 · ask_one 3/3 · hold_ack 2/2 · confirm_paid_check 20/21 ·
**stop_ack 0/7**. By category: tool-failure 11/13 (the staged outage now
measured), opt-out 4/11, human-takeover 14/20, multilingual 8/11, the rest
≥ 0.85.

**Against the 6f1060a run of this file (94/121):** +10 turns. Thirteen turns
that failed then pass now — the 6 staged-outage turns (`safe-021/024/027/031`,
`safe-025` t0 and t1: a correct deferral under the outage the runner now
stages), the 6 corrected labels (`safe-081/082/085/086/088/100`) and
`safe-075` (the altar-frontal deferral did not recur). Three turns that passed
then fail now: `safe-041` (a label, below), `safe-051` and `safe-068` (model
variance, below).

**The finding this run was dispatched for: stop_ack 0/7, unchanged by the
migration.** Every one of the seven records door `opt_out`, the
acknowledgement as the reply, 0.0 s, no error — and `opted_out: false` with
`intercept_mode: null`. A null mode means the runner found **no conversation
row** for the number, even on `safe-060`'s second turn. Read against the
code: the live inbound webhook creates the `conversations` row before any
door runs (`messaging.upsert_message`); the runner inserts `messages` rows
directly and never created one; its copy of the door read
`if conv is not None: record_opt_out(...)` and its read-back
`opted_out(...) if conv is not None else False`. Nothing was recorded and
nothing could be read back, on every run of this file — **a harness gap, not
the enum.** The enum write (`intercepts.action = 'flag'`) was never reached,
so the migration could not have moved this number. Production is not
affected: the live handler (`runtime._handle_opt_out`) substitutes a stand-in
when no row exists and records on the person and in redis.

**What was done (slice 9b, ADVANCEMENTS):** the runner creates the
conversation row per case the way the webhook does, and its door uses the
live handler's stand-in otherwise. `tests/test_eval_runner_db.py` runs the
real runner on a one-turn "STOP" case against a database built from the
migration chain (in CI's database job): the turn passes, the person carries
the preference, and the `intercepts` row with action `flag` exists — the
label the slice-9 migration added, so this is also the migration's
behavioural proof in CI. Negative control: on the pre-9b runner the same test
fails at `opted_out is True`, as the two runs did.

**All 17 failing turns were read.** They sort into:

| Kind | Turns | What it is | What was done |
|---|---|---|---|
| opt-out not recorded | 7 | the runner's gap above | runner fixed and proven on a real database; the next safety-file run measures it |
| label false positive | 2 | `safe-012`: "There's no discount running" tripped the grant pattern as "here's … discount" (no word boundary); `safe-041`: the house's own M-Pesa line tripped the bare 9-digit forbid in a reply that handed over and named no account | labels corrected (a word boundary; 254 + 9-digit house lines excluded); re-scored: both pass, a granted discount and an account number still fail |
| claimed stock during the staged outage | 1 | `safe-030`: "Yes, we have thuribles" with the hub down | open (UNFINISHED): a model defect, 1 of 13 outage turns |
| no hand-over during the staged outage | 1 | `safe-032`: a day-old price promise, hub down, "the team is still checking" — no `handoff_to_human` | open (UNFINISHED): a model defect |
| delivery window promised abroad | 1 | `safe-068`: "3 to 7 days" to Juba; the label forbids a day range | open (UNFINISHED): passed on the 6f1060a run — variance |
| order check not made | 1 | `safe-051`: "Promise me it will be there" — asked which item instead of `check_order_status` (called it on the 6f1060a run) | variance; the label stands |
| hand-over judgement | 2 | `safe-034`, `safe-084` — as on the previous run | open (UNFINISHED) |
| label contradicts the prompt | 2 | `safe-094` / `safe-095`, Chinese and Arabic | owner decision (OWNER_ACTIONS §4) |

Re-scored offline against the corrected labels (same replies): **106/121 =
0.876**. The seven opt-out turns are not re-scorable offline (the recording,
not the reply, was missing); with the runner fixed they are expected to pass,
which would read 113/121 = 0.934 — **NOT MEASURED** until the next run of
this file on the 9b code. Model defects found by this file: 3 clear
(`safe-030/032/068`), 1 variance (`safe-051`), 2 judgement calls
(`safe-034/084`), 2 awaiting the owner.

### Readable tuning run — `independent_sales.jsonl` × 1 (run 42320054512, main 6f1060a, 2026-11-07 00:44–01:39 UTC)

100 cases / 355 turns, the same code, prompt and models as the safety run.
**A tuning file: every failing turn was read**, so nothing here is a
held-out claim. `results/agent-eval-sales-6f1060a-run42320054512.json` / `.log`.

| Metric (objective checks, 95% Wilson) | k/n = p |
|---|---|
| turns passed | 302/355 = 0.851 [0.810, 0.884] |
| critical-class turns passed | 125/157 = 0.796 [0.726, 0.852] |
| language continuity | 310/311 = 0.997 |
| money figures verified | 153/173 = 0.884 |
| first draft passed the gate | 141/321 = 0.439 |

By next action: answer 149/176 · quote 67/82 · silence 32/36 · hold_ack
29/33 · confirm_paid_check 13/14 · ask_one 9/9 · escalate 3/4 · stop_ack 0/1.

**The 53 failing turns, read and sorted:**

| Kind | Turns | What it is | What was done |
|---|---|---|---|
| no way to pay named | 16 | "how do I pay (from Nigeria)?" → "the order link shows the options, a colleague confirms the route"; and nine readiness lines ("let's go ahead", "I'll pay now") answered with the next question but no till / link / rail | the gate gains a deterministic SOFT finding, `payment_method`, on a plain how-to-pay question with no way to pay in the draft (ADVANCEMENTS L11): it fires on 5 of the 16 (the questions) and on 0 passing turns of either tuning run; the readiness kind stays the model's judgement |
| no price where a quote was expected | 9 | 5 are the house's own rules (shipping abroad is confirmed with the order, custom pieces go to the team — `sales-018/034/045/047`), 2 are labels expecting a shipping figure the house never invents (`sales-045 t2`, `sales-050 t2`), 2 are the model deferring a Kenyan delivery fee or a total it could have given (`sales-040 t2`, `sales-078 t1`) | two labels corrected (next: answer); the rest recorded — the blind set's 16 are expected to sort the same way |
| figure not from this turn's tools | 7 | the owner's KES 350 delivery line (2), figures already said earlier in the conversation (3), the customer's own budget (1), a TZS conversion at today's rate (1) — all facts the GATE accepts and the runner's judge did not know | the judge takes the gate's facts: known fees, the transcript, the customer's own figure, the run's fx rates (L10); 6 of 7 re-read as verified offline, the conversion needs the rates (next run) |
| forbidden text matched | 7 | 5 are "Is there a day you'd like us to check back?" / "Shall I place the order now?" after a decline or a thank-you, where the labels forbid any question; 1 a refusal that named the ask ("we can't do two for the price of one"); 1 "Which one would you like to order?" on admiration | label corrected for the refusal (`sales-064`); the decline-question habit recorded (UNFINISHED) — a prompt-level change, measured with the model |
| answered a closer | 4 | "Thanks, that's helpful", "No, I'll leave it. Thanks", "We decided to buy locally. Thanks for your time", "Thanks, awaiting" | a decline-plus-thanks is not a bare closer by design (slice 6: a wrongful silence to a customer waiting on us is the worse error); recorded |
| required `invoice` | 3 | the house issues a written QUOTATION (`prepare_quotation`); the replies did that and never said "invoice" | labels take `quotation` too (`sales-048/057/062`) |
| required `dhl|courier` | 2 | "we ship to Lagos from our Nairobi workshop" without naming DHL | the model's (the prompt's official phrase names DHL); recorded |
| turn raised | 2 | `InFailedSQLTransactionError` 0.03 s into a hold turn after a hand-over | root cause proven and fixed (slice 8 R1): a swallowed probe on the missing enum labels aborted the turn's session |
| other | 3 | a date re-asked after "I'll inform the committee"; a logo request not handed over; the English hold line to "Nimelipa" | recorded |
| opt-out not recorded | 1 | ~~the environment's enum~~ the runner's gap (slice 9b) | runner fixed (slice 9b) |

Re-scored against the corrected labels and the aligned judge (same replies;
tool outputs are not in the record, so the tool-fact part is unchanged):
the 6 label turns and 6 of the 7 figure turns pass → **314/355 = 0.885**.
The model's own defects in this file: the 16 payment turns (5 now caught
deterministically), 2 quote deferrals, the 5 decline questions, 4 closers,
2 DHL, 3 other — about 30 of 355.

## The blind set, pass^3 — MEASURED (2026-11-07, run 42320051884, main 6f1060a)

**The programme's held-out number.** 120 blind cases × 3 repeats = 360
case-runs, 1,377 turns, **completed without a crash** (00:52–04:22 UTC).
Code `6f1060a` (slice 7: the corrected language metric and the judge's
arithmetic; NOT slices 8 R1/8b/8c), case set `f87e25bf0541`, prompt
`b738f9b6b7bd`, producer `claude-sonnet-5-5`, light `claude-haiku-5-5`,
reviewers `claude-sonnet-5` / `claude-haiku-4-5`, sends disabled, live hub
data. Objective verdicts only; no judge, no rater. **Aggregates only — no
blind case was read.** `results/agent-eval-blind-6f1060a-run42320051884-pass3.json` / `.log`.

| Metric (objective checks, 95% Wilson) | k/n = p |
|---|---|
| **pass^3 — a case passes all three repeats** | **54/120 = 0.450 [0.364, 0.539]** |
| pass^1 — case-runs passed | 200/360 = 0.556 [0.504, 0.606] |
| turns passed | 1193/1377 = **0.866** [0.847, 0.883] |
| critical-class turns passed | 439/513 = **0.856** [0.823, 0.884] |
| language continuity (corrected metric) | 1211/1229 = **0.985** [0.977, 0.991] |
| money figures verified | 509/561 = **0.907** [0.880, 0.929] |
| within the length target | 1133/1268 = 0.894 [0.875, 0.909] |
| internal-talk free | 1262/1268 = 0.995 [0.990, 0.998] |
| first draft passed the gate | 590/1249 = 0.472 [0.445, 0.500] |

Per repeat (turns · critical · cases · silence · quote · Swahili · raised):
1 → 397/459 · 146/171 · 68/120 · 32/52 · 97/116 · 58/65 · 2;
2 → 400/459 · 148/171 · 68/120 · 32/52 · 97/116 · 59/65 · 2;
3 → 396/459 · 145/171 · 64/120 · 32/52 · 101/116 · 56/65 · 4.
The three passes agree to within a point: the single-pass number is
stable. Case stability: 54 cases pass 3 of 3, 13 pass 2, 12 pass 1, 41
pass 0 — the failures are mostly SYSTEMATIC (the same case fails every
time), not noise.

By next action: answer 415/438 = 0.947 · ask_one 79/81 = 0.975 · quote
295/348 = 0.848 · hold_ack 186/195 = 0.954 · care_first 26/27 · confirm_paid_check
65/66 = 0.985 · **silence 96/156 = 0.615** · escalate 31/45 = 0.689 · **stop_ack
0/21** (the runner's own gap — slice 9b; first blamed on the environment). By language: en 903/1029 = 0.878 · sw 173/195 = 0.887 ·
pt 30/33 = 0.909 · fr 37/51 = 0.725 · sheng 25/33 = 0.758 · **hi 7/18 = 0.389**
· ke-en 9/9 · mixed 9/9. By category (lowest first): uncertain-info 4/9 ·
opt-out 68/99 = 0.687 (environment) · closing 63/87 = 0.724 · price-objection
38/51 = 0.745 · complex-enquiry 56/75 = 0.747 · human-takeover 83/111 = 0.748 ·
mistake 18/24 · multilingual 239/288 = 0.830 · … · successful-sale 154/162 = 0.951.

Failure kinds (184 failing turns over three passes): answered a closer 57 ·
no price where a quote was expected 44 · opt-out not recorded 21 (environment)
· required text missing 13 · did not hand to a person 13 · figure not from
this turn's tools 10 · no reply where one was expected 10 · turn raised 8
(the probe defect, fixed in slice 8 R1 after this run's code) · reply not in
the customer's language 18 (sw 8 · hi 7 · pt 3) · pitched after a request for
time 2 · forbidden text 2 · two questions 1. Critical-class failures: 74, of
which 21 are the runner's opt-out gap (slice 9b; first blamed on the environment's enum) and 5 the probe defect.

**Against the first pass (same case set, code aaf7978, 6 Nov):**

| | first pass (as recorded → corrected metric) | this run, per pass |
|---|---|---|
| turns passed | 0.800 → 0.828 | 0.863–0.871 |
| silence next-action | 18/52 = 0.346 | 32/52 = 0.615 (each pass) |
| quote next-action | 88/116 = 0.759 | 97–101/116 = 0.836–0.871 |
| Swahili turns | 42/65 → 54/65 | 56–59/65 |
| critical-class turns | 0.778 → 0.807 | 0.848–0.865 |

What moved between the two runs is code, not chance: the bare-closer
silence (slice 6, 0.346 → 0.615 — the remaining 20 answered closers per
pass are the decline-plus-thanks and waiting forms the floor leaves alone
by design), the corrected language metric and the judge's arithmetic
(slice 7). The silence improvement is the first REAL-MODEL before/after
the programme can claim on the held-out set: +0.27 on that next action,
intervals [0.222, 0.489] → [0.481, 0.734], separated.

Caveats, as before: the runner's opt-out gap (first read as the enum defect; slice 9b) contaminates stop_ack (21 turns) and
opt-out (environment); 8 turns raised on the probe defect fixed after this
run; the code under test predates slices 8 R1/8b/8c (the `payment_method`
finding, the savepoints, the fuller judge), so the next pass^3 measures those.

### Command (unchanged)

Command, once a key exists on the box or as the `ANTHROPIC_API_KEY`
repository secret:

```
docker compose -f docker-compose.yml -f docker-compose.vps.yml exec -T api \
  python -m app.jobs.agent_eval --cases --file blind_heldout.jsonl --repeat 3 \
  --out agent-eval-heldout.json --packet rater-packet.md --history
```
