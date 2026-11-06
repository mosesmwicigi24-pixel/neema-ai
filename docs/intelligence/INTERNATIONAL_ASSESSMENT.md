# International Competitiveness Assessment

Evidence-backed, with the peer group and method stated. Where evidence is
missing the row says so; no ranking is claimed.

## Peer group and method

Peer systems with public material (STANDARDS_RESEARCH §4): Intercom Fin,
Sierra, Salesforce Agentforce, Decagon. None publishes an intelligence or
quality score; all publish resolution or deflection rates on vendor-defined
denominators, none independently audited. A like-for-like comparison would
need: the same tasks (our case set), the same business information (the hub
and the prompt inputs), the same scoring (the objective verdicts and human
rubric), run on each system — which means building a reference agent with
Neema's tools on a general-purpose agent framework and running it on the
blind set. That reference-agent run has not happened.

## The four levels, assessed

| Level | Question | Assessment today | Evidence |
|---|---|---|---|
| 1. High-quality production engineering | Are the engineering practices at the level of a serious production agent? | **Partly.** Strong: a deterministic reply gate with hard rules and hub-grounded figures; durable opt-out; per-turn cost ledger; shadow rollout control; a sizeable test suite (3,100+). Weak until this slice: a fail-open gate, a single-channel opt-out door, no held-out evaluation, no run history, no fail-closed defaults, metrics that mixed paid and unpaid revenue. This slice addresses each; verification in production is pending. | INVESTIGATION_REPORT; ADVANCEMENTS_REGISTER |
| 2. Skilled-human conversational and commercial parity | Does Neema sell and converse as well as an experienced consultant? | **NOT MEASURED.** Requires the real-model run plus human ratings and the blind comparison. The 5 Nov audit's one thread (Mama Beth) showed repetition, an invented liturgical claim and internal talk — corrected since, but unmeasured. | BENCHMARK_RESULTS (real-model section empty) |
| 3. Superior to skilled humans on specific tasks | Is there any task where Neema beats a person? | **NOT MEASURED.** Candidate tasks where a measurement is cheap once the model runs: first-response time (median seconds vs minutes — measured on the dashboard, but speed is not quality), price accuracy against the hub (objective), language continuity (objective). A claim of superiority needs the human arm. | performance.py; EXCELLENCE_SCORE |
| 4. Competitive with leading agents | Would Neema score comparably to Fin/Sierra/Decagon/Agentforce on equivalent tasks? | **NOT MEASURED, and not claimable from vendor numbers** (different denominators, no audits). What can be said: Neema's evaluation design (τ-bench-style end states, pass^k, blind-set split, Wilson intervals, same-vendor judge caveat) matches the published research practice better than the vendors' published claims do. | STANDARDS_RESEARCH §1, §4 |

## Where Neema is ahead of common practice (evidence-backed)

- Hard grounding of money figures and links to tool results in a deterministic gate (review.py) — most published agents rely on the model alone.
- A durable, multi-language opt-out with a deterministic recogniser measured at 0.971 on the blind set (n=34, wide interval; the held-out figure was withdrawn as contaminated).
- Consent and outreach controls per rule with a shadow tally (Stages 2–5).

## Where Neema is behind (evidence-backed)

- No measured conversational quality (humans or model) yet.
- Prompt size (~24 K tokens of rules every turn) against research showing focused context outperforms full history.
- No production-derived evaluation cases; no inter-rater agreement.

## What would make a defensible claim

1. The real-model run on the blind set (pass^3, intervals).
2. Human ratings on the rater packet from two raters with κ.
3. A reference agent with the same tools on the same cases.
4. Two human sellers on a 40-case sample, blind.
Only then can levels 2–4 be scored; until then the honest statement is
"engineering practice improving, intelligence unmeasured".
