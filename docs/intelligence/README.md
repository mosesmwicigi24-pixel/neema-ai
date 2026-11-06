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
| `VERIFICATION_PASS_1.md`, `_2.md`, `_2B.md`, `_3.md`, `_3B.md`, `_4.md` | the independent adversarial passes (one per slice) with the implementer's response tables |
| `EVIDENCE_DOSSIER_FOR_INDEPENDENT_REVIEW.md` | the self-contained evidence dossier for an outside reviewer: capabilities, before/after, examples, what is NOT MEASURED, the 100-point score status, appendix (6 Nov, main 7670de1) |
| `OWNER_ACTIONS.md` | the exact steps for what only the owner can do, and the decisions waiting |
| `reports/` | the Stage 1–8 reports and the 5–6 November audits this programme built on |

Inputs that were **not available** to the session that started this record:
`NEEMA_CAPABILITY_INTELLIGENCE_PROFILE_2026.md` (not in the repository, the
uploads or the machine; the owner is asked to add it under `docs/`), earlier
Claude project conversations (reconstructed from git history, merged PRs and
the 5–6 November audits), the production box (no SSH; the live state is read
from `/api/health` and the admin endpoints once a credential is saved), and a
model API key in the session (real-model evaluations run on the box or in the
`agent-eval` workflow once the repository secret exists).
