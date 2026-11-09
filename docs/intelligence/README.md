# Neema intelligence programme — development records

Durable checkpoints for the "World-class intelligence transformation" directive
(owner, 2026-11-06). Every file here is written so a later session can resume
without the chat: what was examined, what was found, what was changed, what was
measured, what is still open. Statuses use only:
VERIFIED COMPLETE · IMPLEMENTED BUT NOT VERIFIED · PARTIALLY COMPLETE · BLOCKED ·
NOT STARTED · NOT APPLICABLE.

| File | What it is |
|---|---|
| `REQUIREMENTS_REGISTER.md` | every instruction in the directive, with evidence and status |
| `CAPABILITY_BASELINE.md` | what Neema genuinely does today, by capability, with file:line evidence |
| `INVESTIGATION_REPORT.md` | material weaknesses, root causes, affected execution paths |
| `STANDARDS_RESEARCH.md` | the international-practice research memo, science separated from marketing |
| `EXCELLENCE_SCORE.md` | the 100-point framework: methodology, denominator, evaluator, uncertainty per metric |
| `EVALUATION_DATASET.md` | the case set: sources, coverage, anonymisation, how it runs |
| `BENCHMARK_RESULTS.md` | reproducible before/after measurements, with model and prompt revision |
| `ADVANCEMENTS_REGISTER.md` | the ten workstreams: baseline → gap → change → tests → outcome |
| `REGRESSION_SAFETY_REPORT.md` | evidence that existing systems and customer protections remain intact |
| `UNFINISHED_REGISTER.md` | nothing silently omitted |
| `INTERNATIONAL_ASSESSMENT.md` | evidence-backed comparison against a defensible peer group |
| `RELEASE_READINESS.md` | measured improvement, remaining risks, items requiring owner approval |
| `VERIFICATION_PASS_1.md`, `_2.md`, `_2B.md`, `_3.md`, `_3B.md`, `_4.md`, `_5.md`, `_6.md`, `_6B.md` | the independent adversarial passes (one per slice) with the implementer's response tables |
| `EVIDENCE_DOSSIER_FOR_INDEPENDENT_REVIEW.md` | the self-contained evidence dossier for an outside reviewer: capabilities, before/after, examples, what is NOT MEASURED, the 100-point score status, appendix (6 Nov, main 7670de1) |
| `OWNER_ACTIONS.md` | the exact steps for what only the owner can do, and the decisions waiting |
| `CUSTOMER_TIMELINE.md` | slice 15 (2026-11-09): the customer timeline — a level on every ledger event (customer / technical), repeated technical steps folded, new customer-level events for discoveries, stage moves, promised checks and holds; the panel's Activity tab shows the customer level with Neema's steps behind a toggle |
| `CUSTOMER_INSIGHTS.md` | slice 14 (2026-11-09): insights from evidence — paid and unpaid kept apart, one set of score inputs for the panel and the leads list, no stage from a dialling prefix, the commercial snapshot with one next best action by precedence; tests, behaviour changes |
| `CUSTOMER_GEOGRAPHY.md` | slice 13 (2026-11-09): geography with provenance — telephone country, probable country, confirmed residence, shipping, city, each with source and confidence; the one decision the market and the profile share; the Bahrain/Kenya case before and after; writers, readers, tests, risks |
| `CUSTOMER_INTELLIGENCE_AUDIT.md` | 2026-11-09: Phase 1 forensic audit for the Customer Intelligence directive — the Bahrain/Kenya case verified, geography resolvers, Profile/Insights/Activity tabs, lead scoring, events, duplicates, and the implementation order |
| `CUSTOMER_KNOWLEDGE.md` | 2026-11-08: how a customer is placed (dialling code, connection, their words, the evidence chain), how names are stored, how information is gathered, ten gaps and seven proposals (owner's report; the editable copy is in Claude Docs) |
| `ACCOUNTABLE_COMMITMENTS.md` | slice 12 (2026-11-07): the owner's hybrid decision on safe-032 — accountable commitments, the person door, the hard language guard, the Chinese/Arabic labels; before/after, tests, risks, rollback |
| `COMMERCIAL_EI.md` | slice 11 (2026-11-07): the Commercial Emotional Intelligence directive's eight-part report — inventory, root cause of the collar case, the rewritten come-back rule, what was preserved, before/after, measurements, the 25-scenario map |
| `reports/` | the Stage 1–8 reports and the 5–6 November audits this programme built on |

Inputs that were **not available** to the session that started this record:
`NEEMA_CAPABILITY_INTELLIGENCE_PROFILE_2026.md` (not in the repository, the
uploads or the machine; the owner is asked to add it under `docs/`), earlier
Claude project conversations (reconstructed from git history, merged PRs and
the 5–6 November audits), the production box (no SSH; the live state is read
from `/api/health` and the admin endpoints once a credential is saved), and a
model API key in the session (real-model evaluations run on the box or in the
`agent-eval` workflow once the repository secret exists).
