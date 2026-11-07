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
| 42320051884 · 42320054512 · 42320057346, 00:44 UTC 7 Nov | main 6f1060a (slice 7) | three runs dispatched through the workflow's new inputs: the blind set pass^3 (the programme's held-out number, first attempt with the repaired runner and the corrected language / figure metrics); `independent_sales.jsonl` × 1 (readable: the 82 quote-expected turns, for the missing-price kind); `independent_safety.jsonl` × 1 (readable: 17 escalate and 21 paid-check turns, for the hand-over and required-text kinds). Results are read in when they finish. |
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
· **stop_ack 0/7** (environment, see caveat).

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

### Command (unchanged)

Command, once a key exists on the box or as the `ANTHROPIC_API_KEY`
repository secret:

```
docker compose -f docker-compose.yml -f docker-compose.vps.yml exec -T api \
  python -m app.jobs.agent_eval --cases --file blind_heldout.jsonl --repeat 3 \
  --out agent-eval-heldout.json --packet rater-packet.md --history
```
