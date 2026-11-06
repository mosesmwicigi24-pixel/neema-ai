# Requirements and Evidence Register

Directive: "Neema AI — world-class intelligence transformation, master execution
directive" (owner, 2026-11-06). One row per instruction. Columns: requirement ·
capability · paths examined · baseline evidence · weakness found · improvement
implemented · tests and results · before/after · remaining limitations · status.
Statuses: VERIFIED COMPLETE · IMPLEMENTED BUT NOT VERIFIED · PARTIALLY COMPLETE ·
BLOCKED · NOT STARTED · NOT APPLICABLE. A row is VERIFIED COMPLETE only when the
evidence column points at a repeatable measurement or an inspection record, never
because code or tests exist.

Last update: 2026-11-06 (session 1, discovery phase).

## §1 Non-negotiable rules (standing; audited at every phase gate)

| ID | Rule | How it is enforced in this record | Status |
|---|---|---|---|
| R1.1 | Never assume implementation | every capability row carries file:line and a test or production evidence, or says UNVERIFIED | applied |
| R1.2 | Never assume compliance | prompt instructions are measured on transcripts (real-model eval), not read | applied; model runs BLOCKED on key (see UNFINISHED) |
| R1.3 | Never skip relevant code | inventories trace callers, dependencies, paths; inaccessible paths listed | applied |
| R1.4 | Never blindly trust previous audits | 5–6 Nov audit claims re-checked against current code in CAPABILITY_BASELINE | applied |
| R1.5 | Never mistake tests for intelligence | EXCELLENCE_SCORE separates objective assertions from judged dimensions; judged ones need human raters | applied |
| R1.6 | Never invent evidence | tags [C] confirmed / [H] hypothesis / [P] planned / [U] unavailable throughout | applied |
| R1.7 | Never duplicate architecture | ADVANCEMENTS_REGISTER names the existing system each change extends | applied |
| R1.8 | Never weaken working functionality | REGRESSION_SAFETY_REPORT: full suite + safeguard checklist per change | applied |
| R1.9 | Never declare success prematurely | BENCHMARK_RESULTS before/after on a held-out set; otherwise "not demonstrated" | applied |
| R1.10 | Never expand scope without justification | every new component in ADVANCEMENTS_REGISTER must cite the proven limitation and the simpler alternative rejected | applied |

## §2 Reconstruct the actual current state

| ID | Requirement | Evidence / where | Status |
|---|---|---|---|
| R2.0 | Start from `NEEMA_CAPABILITY_INTELLIGENCE_PROFILE_2026.md` | not in repo/uploads/machine; owner asked to add it | BLOCKED (input) |
| R2.0b | Nov 5–6 audits, development reports, git history, production evidence | scratchpad audits; git-history.txt (87 commits, PRs #251–#315); /api/health | PARTIALLY COMPLETE |
| R2.1 | FastAPI runtime and model orchestration | inventory A | NOT STARTED → in progress |
| R2.2 | Assembled prompts and instruction hierarchy | inventory A | in progress |
| R2.3 | Customer memory and conversation state | inventory F | in progress |
| R2.4 | 23-tool architecture and permissions | inventory B | in progress |
| R2.5 | Hub and commercial data integrations | inventory C | in progress |
| R2.6 | Quotation, cart, order, payment, after-sales | inventory C | in progress |
| R2.7 | WhatsApp, Messenger, Instagram, web chat, comments, TikTok | inventory D | in progress |
| R2.8 | Autonomous actions, follow-ups, dispatch, takeover, consent | inventory D + Stage 1–8 reports | in progress |
| R2.9 | Response verification and factual grounding | inventory E | in progress |
| R2.10 | Dashboard, monitoring, evaluation tools | inventory G | in progress |
| R2.11 | Android/iOS contracts (inspect only) | inventory G | in progress |
| R2.12 | Verify deployed commit, flags, models, credentials, channel status, execution behaviour | health: ff8c3b5; models from config (tier2 sonnet-5-5 / haiku-5-5; review sonnet-5 / haiku-4-5); live flags readable only via health + admin endpoints (credential pending) | PARTIALLY COMPLETE |
| R2.13 | Capability-to-implementation inventory with all listed fields | inventories A–G → CAPABILITY_BASELINE | in progress |
| R2.14 | Trace end-to-end workflows | inventories C, D | in progress |
| R2.15 | Document paths examined and paths inaccessible/unverified | CAPABILITY_BASELINE §"Not examined" | in progress |
| R2.16 | Identify dead code, competing implementations, contradictory instructions, ineffective flags, bypasses, obsolete safeguards | each inventory §findings → INVESTIGATION_REPORT | in progress |
| R2.17 | No implementation conclusions before the baseline is evidence-backed | phase gate | applied |

## §3 Research the highest international standards

| ID | Requirement | Evidence / where | Status |
|---|---|---|---|
| R3.1 | Research the seven topic areas | STANDARDS_RESEARCH.md | in progress |
| R3.2 | Anthropic, OpenAI, DeepMind, Microsoft, NIST, ISO, Fin, Sierra, Agentforce, Decagon | STANDARDS_RESEARCH.md | in progress |
| R3.3 | τ-bench-style tasks, trajectory testing, blind human assessment, reproducible evals | STANDARDS_RESEARCH.md + EXCELLENCE_SCORE.md | in progress |
| R3.4 | Separate science from marketing | tags (S)/(E)/(M) | in progress |
| R3.5 | Per practice: achieves / evidence / Neema equivalent / helps here / adopt simply | STANDARDS_RESEARCH.md §applies | in progress |

## §4 The ten advancements (each: initial evaluation · verified gaps · scoped improvements · regression tests · measured outcome)

| ID | Workstream | Status |
|---|---|---|
| R4.1 | Reliability, truth, customer trust (opt-outs, verification bypasses, fail-open, discounts, payment state, held replies, delivery uncertainty, identity merge; inbound reaches inbox; financial grounding) | NOT STARTED |
| R4.2 | Intent and contextual reasoning (extend customer-state, no competing engine) | NOT STARTED |
| R4.3 | Emotional intelligence (social judgment; human review of hard cases) | NOT STARTED |
| R4.4 | Sales psychology / consultative intelligence (no manipulation) | NOT STARTED |
| R4.5 | Onboarding (reuse what the customer said; fewer repeats) | NOT STARTED |
| R4.6 | Respectful closing (readiness vs time; paid conversion with experience) | NOT STARTED |
| R4.7 | Memory and context engineering (no blind shortening, no vector DB) | NOT STARTED |
| R4.8 | Cultural and multilingual excellence (native-speaker evaluation) | NOT STARTED |
| R4.9 | Autonomous commercial execution (final business states, not API 200s) | NOT STARTED |
| R4.10 | Continuous scientific evaluation (extend agent_eval.py; history; no uncontrolled prompt changes) | NOT STARTED |

## §5 Independent intelligence baseline

| ID | Requirement | Status |
|---|---|---|
| R5.1 | 300–500 cases covering the eleven listed categories | NOT STARTED |
| R5.2 | Real model against controlled data, sends disabled | BLOCKED (no key in session; box/CI run) |
| R5.3 | Objective assertions + human evaluation where judgment is required | NOT STARTED |
| R5.4 | Blind comparison: Neema vs skilled humans vs reference agent | NOT STARTED (needs owner-provided human raters/sellers) |
| R5.5 | Record inputs, model version, prompt revision, traces, outcomes, criteria, limitations | NOT STARTED |
| R5.6 | Grader independence (not solely the producing model) | design in EXCELLENCE_SCORE | NOT STARTED |

## §6 Excellence Score

| ID | Requirement | Status |
|---|---|---|
| R6.1 | 10 dimensions, weights as given | NOT STARTED |
| R6.2 | Per metric: methodology, denominator, sample size, evaluator, evidence source, uncertainty | NOT STARTED |
| R6.3 | NOT MEASURED where unreliable; no invented scores | applied |
| R6.4 | ≥10-point verified improvement on a held-out set | NOT STARTED |
| R6.5 | Investigate the six preliminary targets | NOT STARTED |
| R6.6 | Aggregate never excuses critical safety/financial errors | applied (gating rule in EXCELLENCE_SCORE) |

## §7 Executive performance dashboard

| ID | Requirement | Status |
|---|---|---|
| R7.1 | Thirteen visibility items | NOT STARTED |
| R7.2 | Baseline, current, trend, confidence where supported | NOT STARTED |
| R7.3 | NOT YET MEASURED + instrumentation needed; no fabricated values | NOT STARTED |

## §8 Controlled, verifiable changes

| ID | Requirement | Status |
|---|---|---|
| R8.1 | Investigate → evidence → root cause → smallest change → implement → test → compare → regressions → document | applied per workstream |
| R8.2 | No new models/prompts/DBs/services/state without comparative evidence | applied |
| R8.3 | Tests: normal, edge, adversarial, failure | per change |
| R8.4 | Production deploy, DB change, outreach activation, policy change need explicit owner approval | applied: nothing merged/deployed under this directive without the owner's word |

## §9 Prevent incomplete execution

| ID | Requirement | Status |
|---|---|---|
| R9.1 | This register, all columns | in progress |
| R9.2 | Independent verification pass after each phase | NOT STARTED |
| R9.3 | Durable checkpoints in project records | this folder, committed |
| R9.4 | Preserve exact state if the session ends | UNFINISHED_REGISTER |
| R9.5 | Record external dependencies precisely | UNFINISHED_REGISTER |

## §10 International comparison

| ID | Requirement | Status |
|---|---|---|
| R10.1 | Assess the four levels with equivalent tasks, information, scoring, controls | NOT STARTED |
| R10.2 | No "top ten" claim without peer group, method, evidence | applied |

## §11 Deliverables

| ID | Deliverable | File | Status |
|---|---|---|---|
| R11.1 | Verified Capability Baseline | CAPABILITY_BASELINE.md | NOT STARTED |
| R11.2 | Deep Investigation Report | INVESTIGATION_REPORT.md | NOT STARTED |
| R11.3 | Ten-Advancement Implementation Register | ADVANCEMENTS_REGISTER.md | NOT STARTED |
| R11.4 | Intelligence Benchmark Results | BENCHMARK_RESULTS.md | NOT STARTED |
| R11.5 | Customer Experience Assessment | in BENCHMARK_RESULTS + human ratings | NOT STARTED |
| R11.6 | Performance Dashboard | web view + API | NOT STARTED |
| R11.7 | Full Regression and Safety Report | REGRESSION_SAFETY_REPORT.md | NOT STARTED |
| R11.8 | Unfinished and Unverified Work Register | UNFINISHED_REGISTER.md | NOT STARTED |
| R11.9 | International Competitiveness Assessment | INTERNATIONAL_ASSESSMENT.md | NOT STARTED |
| R11.10 | Final Release Readiness Report | RELEASE_READINESS.md | NOT STARTED |
