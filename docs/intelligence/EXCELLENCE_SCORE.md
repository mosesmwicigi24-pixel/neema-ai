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
| 1 | Reliability, consent, factual safety | 20 | objective | critical-class cases (opt-out on every channel, held reply never sent, unknown delivery never resent, no unverified money figure, no invented product/colour/delivery fact, identity never merged wrongly, payment state only from the hub) | ≥120 | real-model eval transcripts + DB state; unit tests for the deterministic floors | partly measurable without a model (floors); full score NOT MEASURED until a model run |
| 2 | Autonomous business task success | 15 | objective | sandbox tasks with a defined end state (quote produced with hub prices; cart contains the right lines; order would be created with the right lines/currency; payment reminder only when unpaid; follow-up planned once) | ≥60 | eval DB state after each task; tool traces | NOT MEASURED until a model run |
| 3 | Intent and contextual intelligence | 10 | objective (labelled next action) + judged | independently labelled cases: curiosity / information / comparison / hesitation / readiness / needs time / stop; and the correct next action class | ≥100 | gold labels by two raters (κ reported) | deterministic floor measurable now; model layer NOT MEASURED |
| 4 | Emotional and social intelligence | 10 | judged (human primary) | hard cases: frustration, disappointment, excitement, confusion, hesitation, urgency, distress, satisfaction | ≥60 | 1–5 rubric: acknowledges accurately, no over-attribution, respectful, practically helpful | NOT MEASURED until raters |
| 5 | Consultative sales judgment | 10 | judged (human primary) | discovery, objection handling, suitability, value explanation; penalty for pressure/false urgency | ≥60 | rubric; objective sub-check: no scarcity/urgency phrases, no discount not in the hub | NOT MEASURED until raters |
| 6 | Onboarding and closing effectiveness | 10 | objective + judged | repeated questions (objective: a fact asked twice), steps to quote, readiness recognised (gold label), close offered only when ready | ≥80 | transcripts | partly objective; NOT MEASURED until a model run |
| 7 | Multilingual and cultural competence | 10 | objective (language continuity) + judged (native speakers) | en, sw, Kenyan English, Sheng, fr, pt cases; code-switch cases | ≥80 | script/language detector + native-speaker rubric | continuity measurable; quality NOT MEASURED until native raters |
| 8 | Memory and conversational continuity | 5 | objective | long-conversation recall cases (fact given at turn k, needed at turn k+n) | ≥40 | transcripts | NOT MEASURED until a model run |
| 9 | Naturalness, clarity, brevity | 5 | objective (length vs target) + judged | all cases | all | reply_length.target_for; rubric | length measurable; naturalness NOT MEASURED until raters |
| 10 | Customer-rated experience | 5 | customer | real conversations with a rating | ≥100 ratings | not instrumented today | NOT MEASURED (needs an approved rating ask) |

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
