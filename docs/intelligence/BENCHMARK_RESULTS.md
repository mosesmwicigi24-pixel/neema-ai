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

## Real-model baseline — NOT MEASURED

Command, once a key exists on the box or as the `ANTHROPIC_API_KEY`
repository secret:

```
docker compose -f docker-compose.yml -f docker-compose.vps.yml exec -T api \
  python -m app.jobs.agent_eval --cases --file blind_heldout.jsonl --repeat 3 \
  --out agent-eval-heldout.json --packet rater-packet.md --history
```
