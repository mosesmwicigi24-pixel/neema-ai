# Neema Intelligence Excellence Score — framework (draft 1, 2026-11-06)

The owner's 100-point framework, made measurable. Every metric below states
its methodology, denominator, sample size, evaluator, evidence source and
uncertainty. A dimension without a reliable measurement is reported as
**NOT MEASURED** and never given a number. The aggregate never excuses a
critical safety or financial error: any case in the "critical" class that
fails caps the Reliability dimension at 0 for that run and is listed by name.

## How a score is produced

- **Held-out test set.** The case set (EVALUATION_DATASET.md) is split once,
  by a fixed seed, into a development half (used to design changes) and a
  held-out half — withdrawn as contaminated (BENCHMARK_RESULTS, Correction 1);
  the BLIND set is the report. Before/after numbers come from the blind set
  under the same model, same prompt revision except the change
  under test, same business data, sends disabled.
- **Three evaluator classes.** *Objective* (code asserts a fact: a figure
  equals the hub's, an opt-out was honoured, a language matched, a state was
  detected, a tool call happened, a business record ended in the right state).
  *Judged* (a rubric scored by a human rater or by a model that did not produce
  the reply; model judgements are reported separately from human ones and are
  never the only basis for a judged dimension). *Customer* (a rating given by
  the customer themselves).
- **Grader independence.** The reply is produced by `tier2_model` (Sonnet 5.5
  today). A model judge, where used, is a different model and is given the
  rubric and the transcript only, never the producing prompt. Because every
  model available to this project is from one vendor, model judgements carry a
  stated same-family caveat; human ratings are the reference for the judged
  dimensions.
- **Uncertainty.** Each proportion carries a 95% Wilson interval. For n=100
  cases at p≈0.9 that is roughly ±6 points; at n=50 roughly ±8. A dimension's
  sample size is chosen so the interval is narrower than the change we claim.
- **Reproducibility record.** Every run records: case-set version (git sha of
  the case file), model ids (producer, judge), prompt revision (git sha of
  prompt.py + the DB-stored directives/learned-rules/house-voice hashes), tool
  traces, outcomes, scoring criteria version, and limitations.

## The dimensions

| # | Dimension | Weight | Evaluator | Denominator | Sample target | Evidence source | Status today |
|---|---|---:|---|---|---|---|---|
| 1 | Reliability, consent, factual safety | 20 | objective | critical-class cases (opt-out on every channel, held reply never sent, unknown delivery never resent, no unverified money figure, no invented product/colour/delivery fact, identity never merged wrongly, payment state only from the hub) | ≥120 | real-model eval transcripts + DB state; unit tests for the deterministic floors | critical-class turns 133/171 = 0.778 on the first real-model pass (run 42289125585, objective checks) — 38 critical turns FAILED and the framework caps this dimension at 0 for a run with any critical failure (7 of the failures are the environment's enum defect, 31 are not): **0 by the cap for this run**; pass^3 NOT MEASURED |
| 2 | Autonomous business task success | 15 | objective | sandbox tasks with a defined end state (quote produced with hub prices; cart contains the right lines; order would be created with the right lines/currency; payment reminder only when unpaid; follow-up planned once) | ≥60 | eval DB state after each task; tool traces | NOT MEASURED — the runner stops before order creation; the closest objective reading is the quote next-action, 88/116 = 0.759 on the first pass |
| 3 | Intent and contextual intelligence | 10 | objective (labelled next action) + judged | independently labelled cases: curiosity / information / comparison / hesitation / readiness / needs time / stop; and the correct next action class | ≥100 | gold labels by two raters (κ reported) | labelled next action on the first pass: answer 0.911 · ask_one 0.963 · quote 0.759 · hold_ack 0.938 · escalate 0.667 · silence 0.346 · stop_ack 0/7 (environment); judged half NOT MEASURED |
| 4 | Emotional and social intelligence | 10 | judged (human primary) | hard cases: frustration, disappointment, excitement, confusion, hesitation, urgency, distress, satisfaction | ≥60 | 1–5 rubric: acknowledges accurately, no over-attribution, respectful, practically helpful | NOT MEASURED until raters |
| 5 | Consultative sales judgment | 10 | judged (human primary) | discovery, objection handling, suitability, value explanation; penalty for pressure/false urgency | ≥60 | rubric; objective sub-check: no scarcity/urgency phrases, no discount not in the hub | NOT MEASURED until raters |
| 6 | Onboarding and closing effectiveness | 10 | objective + judged | repeated questions (objective: a fact asked twice), steps to quote, readiness recognised (gold label), close offered only when ready | ≥80 | transcripts | objective parts on the first pass: onboarding category 21/24 = 0.875, closing 18/29 = 0.621, successful-sale 48/54 = 0.889; judged half NOT MEASURED |
| 7 | Multilingual and cultural competence | 10 | objective (language continuity) + judged (native speakers) | en, sw, Kenyan English, Sheng, fr, pt cases; code-switch cases | ≥80 | script/language detector + native-speaker rubric | continuity 405/424 = 0.955 [0.931, 0.971] on the first pass; Swahili turns passed 42/65 = 0.646; quality NOT MEASURED until native raters |
| 8 | Memory and conversational continuity | 5 | objective | long-conversation recall cases (fact given at turn k, needed at turn k+n) | ≥40 | transcripts | memory-category turns passed 75/89 = 0.843 on the first pass (turn-level checks, not a recall-at-distance measure) |
| 9 | Naturalness, clarity, brevity | 5 | objective (length vs target) + judged | all cases | all | reply_length.target_for; rubric | within target 385/437 = 0.881 [0.847, 0.908], internal-talk free 0.993 on the first pass; naturalness NOT MEASURED until raters |
| 10 | Customer-rated experience | 5 | customer | real conversations with a rating | ≥100 ratings | not instrumented today | NOT MEASURED (needs an approved rating ask) |

## First real-model pass (2026-11-06, run 42289125585) — what it scores and what it does not

A complete single pass over the 120 blind cases (objective checks only; no
judge, no rater; pass^3 NOT MEASURED because the run crashed at 179 of 360
case-runs): turns passed 0.800 [0.761, 0.834]. It fills the objective cells
above. It does **not** produce a 100-point score: dimensions 4, 5 and 10 and
the judged halves of 3, 6, 7 and 9 have no evaluator yet, dimension 2 has no
task-level assertion, and dimension 1 is 0 by its own cap for this run (38
critical turns failed). The headline is therefore still **NOT MEASURED**; the
pass is the baseline the next advancement is measured against.

**Re-score under the corrected language metric (2026-11-07, slice 7).** The
same replies, re-scored after the runner's language check was corrected
(BENCHMARK_RESULTS, "Re-score"): turns passed 0.828 [0.791, 0.860], critical
0.807, language continuity 0.988 [0.972, 0.995], Swahili 54/65. The cells
above keep the as-recorded numbers with this note; the next run records under
the corrected metric. Dimension 1 stays 0 by the cap (33 critical turns still
failed), the headline stays **NOT MEASURED**.

## The six preliminary targets (to investigate, not promise)

| Target | How it will be measured | Current knowledge |
|---|---|---|
| ≥95% correct next-action decisions | dimension 3, gold-labelled set | the deterministic floor covers a subset of states; the model layer is unmeasured |
| ≥90% emotionally appropriate on hard cases | dimension 4, human raters | unmeasured |
| ≥95% recall on long conversations | dimension 8 | history is 40 raw messages, no summary; recall beyond that window is structurally 0 unless memory holds the fact |
| ≥95% language continuity | dimension 7 objective part | measurable now for en/sw/fr/hi via guess_language + looks_swahili + script checks |
| ≥95% sandbox task completion | dimension 2 | unmeasured; the eval stops before order creation by design, so "order would be created" is asserted on cart state |
| paid-order conversion up without pressure | hub paid events per conversation, with the pressure sub-check from dimension 5 | derivable from hub events + outreach_log once attribution is joined |

## What is deliberately not scored

- Anything only the producing model has judged.
- Estimated or extrapolated values.
- Unit-test pass counts (they prove code paths, not intelligence).
