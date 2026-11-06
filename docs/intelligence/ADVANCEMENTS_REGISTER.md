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
