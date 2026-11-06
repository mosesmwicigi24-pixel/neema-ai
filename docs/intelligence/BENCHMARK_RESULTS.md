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
development half only; the held-out half is the report.

| Metric (floors) | Held-out before | Held-out after | Dev after (tuned) |
|---|---|---|---|
| customer state | 137/254 = 0.539 [0.478, 0.600] | 200/254 = 0.787 — **withdrawn: in-sample** (see correction above) | 204/214 = 0.953 (before narrowing) |
| language guess | 111/149 = 0.745 [0.669, 0.808] | **136/149 = 0.913 [0.856, 0.948]** | 182/183 = 0.995 |
| opt-out recognition | 22/29 = 0.759 [0.579, 0.878] | **28/29 = 0.966 [0.828, 0.994]** | 10/11 = 0.909 |
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

## Real-model baseline — NOT MEASURED

Command, once a key exists on the box or as the `ANTHROPIC_API_KEY`
repository secret:

```
docker compose -f docker-compose.yml -f docker-compose.vps.yml exec -T api \
  python -m app.jobs.agent_eval --cases --held-out --repeat 3 \
  --out agent-eval-heldout.json --packet rater-packet.md --history
```
