# Evaluation dataset — the intelligence case set

Location: `apps/api/app/jobs/eval_cases/*.jsonl` (schema in `__init__.py`).
Version: the git sha of those files; every run record carries a hash of the
cases it used.

## Composition (2026-11-06, first version)

| Source | Cases | How authored |
|---|---:|---|
| `audit` | 10 | the three incident threads and the seven statements from the 5–6 Nov audits, anonymised, plus the Mama Beth thread's shape |
| `independent` | 400 | four separate authoring instances briefed on the domain and the label vocabulary only, forbidden from reading the implementation (sales 100 · context/emotion 100 · language/culture 100 · safety/operations 100) |
| `developer` | 20 | negations and near-misses written by the implementer so a floor tuned on the independent cases cannot overreach; reported separately, never in a headline score |
| `real-derived` | 0 | **not yet**: anonymised production threads need the admin credential (BLOCKED) |

Totals: 430 cases, 1,220 turns, 161 critical. Languages (case level): en 210,
Kenyan English 116, Swahili 49, mixed 18, French 15, Portuguese 11, Sheng 7,
Hindi 4. Categories cover all eleven the directive lists (coverage table in
`results/floors-baseline-all.json`).

## Split

A fixed development / held-out split by a seeded hash of the case id
(`eval_cases.split`): dev 217 cases / 596 length turns, held-out 236 cases /
600 length turns (453 tuning cases after the verifier's negatives joined).
The split does not change when files are added (an id's half is a property
of the id). **The held-out half is contaminated** (BENCHMARK_RESULTS,
Correction 1): the implementer inspected its misses during tuning. Reported
numbers therefore come from the **blind set** — `blind_heldout.jsonl`, 120
cases / 459 turns written by a fresh author after all tuning, never read by
the implementer, scored aggregate-only with `--file`. The default loader
leaves blind cases out of the dev/held-out sweep (`"blind": true`), so no
future tuning run can touch them.

## What a case asserts

Per turn: the gold next action (required), the customer state the words
express (when clear), the language, whether it is an opt-out, the
reply-length kind, forbidden and required patterns, "hub-only" figures, a
tool that must or must not be called, and the judged dimensions a human
rater scores. Independent authors recorded the labels they were unsure of;
those notes are in their hand-back summaries and in `notes` fields, and are
candidates for a second rater (κ to be reported).

## Two layers read it

- `python -m app.jobs.eval_floors` — model-free, seconds, anywhere: the
  deterministic floors (customer state, language guess, opt-out, length
  target) against the gold labels.
- `python -m app.jobs.agent_eval --cases --file blind_heldout.jsonl [--repeat 3] --out … --packet … --history` (the blind set is the report; `--held-out` is the contaminated half, for diagnosis only) —
  the real prompt, model, catalogue, cart and gate with sends sandboxed;
  objective verdicts per turn; pass^k; run record with model ids and prompt
  hashes; rater packet for the judged dimensions; history row in
  `app_settings.eval_history`.

## Limitations stated

- No production-derived cases yet; the independent cases are realistic by
  construction, not by sampling.
- Labels have one rater each; inter-rater agreement is not yet measured.
- Native-speaker review of the Swahili, French, Portuguese and Sheng cases
  has not happened; the language author flagged specific items to check.
- The real-model layer has not run (no key in the session).

## Label note (slice 6, 2026-11-06)

"We're waiting" closers are labelled both ways by the independent authors:
`Ok waiting` / `Sawa nasubiri` (ctx-021, ctx-037, ctx-050, ctx-058, sales-056)
expect a one-line `hold_ack`, while `Sawa, tunasubiri.` / `Bien. J'attends.` /
`Está bem, fico à espera.` / `Thanks, awaiting` (lang-011, lang-020, lang-030,
sales-052) expect `silence`. The deterministic silence decision keeps these
forms OUT (a turn is run), so the four `silence`-labelled ones count as misses
in the `silence` floor. The labels are left as written (no relabelling after
measurement); a native-speaker review should settle the convention.
