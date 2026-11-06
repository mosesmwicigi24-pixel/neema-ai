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

## Real-model baseline — NOT MEASURED

Command, once a key exists on the box or as the `ANTHROPIC_API_KEY`
repository secret:

```
docker compose -f docker-compose.yml -f docker-compose.vps.yml exec -T api \
  python -m app.jobs.agent_eval --cases --held-out --repeat 3 \
  --out agent-eval-heldout.json --packet rater-packet.md --history
```
