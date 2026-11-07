# Requirements and Evidence Register

Directive: "Neema AI — world-class intelligence transformation, master execution
directive" (owner, 2026-11-06). One row per instruction. Columns: requirement ·
capability · paths examined · baseline evidence · weakness found · improvement
implemented · tests and results · before/after · remaining limitations · status.
Statuses: VERIFIED COMPLETE · IMPLEMENTED BUT NOT VERIFIED · PARTIALLY COMPLETE ·
BLOCKED · NOT STARTED · NOT APPLICABLE. A row is VERIFIED COMPLETE only when the
evidence column points at a repeatable measurement or an inspection record, never
because code or tests exist.

Last update: 2026-11-06 (session 1, end: discovery, baseline, first implementation slice, PR #316 draft).

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
| R1.9 | Never declare success prematurely | BENCHMARK_RESULTS before/after on the blind set (the held-out half was withdrawn as contaminated); otherwise "not demonstrated" | applied |
| R1.10 | Never expand scope without justification | every new component in ADVANCEMENTS_REGISTER must cite the proven limitation and the simpler alternative rejected | applied |

## §2 Reconstruct the actual current state

| ID | Requirement | Evidence / where | Status |
|---|---|---|---|
| R2.0 | Start from `NEEMA_CAPABILITY_INTELLIGENCE_PROFILE_2026.md` | not in repo/uploads/machine; owner asked to add it | BLOCKED (input) |
| R2.0b | Nov 5–6 audits, development reports, git history, production evidence | CAPABILITY_BASELINE §3–4; git-history (87 commits, PRs #251–#315); /api/health | VERIFIED COMPLETE |
| R2.1 | FastAPI runtime and model orchestration | CAPABILITY_BASELINE §2A | VERIFIED COMPLETE |
| R2.2 | Assembled prompts and instruction hierarchy | CAPABILITY_BASELINE §2A; prompt dumps measured (95–98 K chars) | VERIFIED COMPLETE |
| R2.3 | Customer memory and conversation state | CAPABILITY_BASELINE §2F | VERIFIED COMPLETE |
| R2.4 | 23-tool architecture and permissions | CAPABILITY_BASELINE §2B (23 + 1 conditional) | VERIFIED COMPLETE |
| R2.5 | Hub and commercial data integrations | CAPABILITY_BASELINE §2C; hub-side behaviour [H] | PARTIALLY COMPLETE (hub side unobservable) |
| R2.6 | Quotation, cart, order, payment, after-sales | CAPABILITY_BASELINE §2C | VERIFIED COMPLETE |
| R2.7 | WhatsApp, Messenger, Instagram, web chat, comments, TikTok | CAPABILITY_BASELINE §2D | VERIFIED COMPLETE |
| R2.8 | Autonomous actions, follow-ups, dispatch, takeover, consent | CAPABILITY_BASELINE §2D/E + the Stage 1–8 reports (now under `reports/`) | VERIFIED COMPLETE |
| R2.9 | Response verification and factual grounding | CAPABILITY_BASELINE §2E (28 outbound paths, gate coverage) | VERIFIED COMPLETE |
| R2.10 | Dashboard, monitoring, evaluation tools | CAPABILITY_BASELINE §2G | VERIFIED COMPLETE |
| R2.11 | Android/iOS contracts (inspect only) | CAPABILITY_BASELINE §2G (81 endpoints; shared set listed); apps untouched | VERIFIED COMPLETE |
| R2.12 | Verify deployed commit, flags, models, credentials, channel status, execution behaviour | d084e91 live (read from `/api/health`); models from config; channels per inbox; 22 flag values unknown (box .env unreadable, credential never saved) | PARTIALLY COMPLETE |
| R2.13 | Capability-to-implementation inventory with all listed fields | CAPABILITY_BASELINE (230 rows) | VERIFIED COMPLETE |
| R2.14 | Trace end-to-end workflows | CAPABILITY_BASELINE §1 | VERIFIED COMPLETE |
| R2.15 | Document paths examined and paths inaccessible/unverified | CAPABILITY_BASELINE §5 | VERIFIED COMPLETE |
| R2.16 | Identify dead code, competing implementations, contradictory instructions, ineffective flags, bypasses, obsolete safeguards | INVESTIGATION_REPORT (50 findings) | VERIFIED COMPLETE |
| R2.17 | No implementation conclusions before the baseline is evidence-backed | phase gate | applied |

## §3 Research the highest international standards

| ID | Requirement | Evidence / where | Status |
|---|---|---|---|
| R3.1 | Research the seven topic areas | STANDARDS_RESEARCH.md | VERIFIED COMPLETE |
| R3.2 | Anthropic, OpenAI, DeepMind, Microsoft, NIST, ISO, Fin, Sierra, Agentforce, Decagon | STANDARDS_RESEARCH.md §2–4 (ISO text paywalled: structure only) | VERIFIED COMPLETE |
| R3.3 | τ-bench-style tasks, trajectory testing, blind human assessment, reproducible evals | STANDARDS_RESEARCH §1; adopted in eval_run (end states, pass^k, run record) | VERIFIED COMPLETE |
| R3.4 | Separate science from marketing | tags (S)/(E)/(M)/(P) throughout | VERIFIED COMPLETE |
| R3.5 | Per practice: achieves / evidence / Neema equivalent / helps here / adopt simply | STANDARDS_RESEARCH "what applies" (12 ranked) | VERIFIED COMPLETE |

## §4 The ten advancements (each: initial evaluation · verified gaps · scoped improvements · regression tests · measured outcome)

| ID | Workstream | Status |
|---|---|---|
| R4.1 | Reliability, truth, customer trust | gate fails closed; opt-out door on every channel; takeover fail-closed; paid-ack rule; promised offer surfaced; Meta 502; inbound verified from outside; identity merge and delivery receipts not changed (recorded) | PARTIALLY COMPLETE (production verification pending) |
| R4.2 | Intent and contextual reasoning | floor widened and measured on the blind set (0.725→0.780, intervals overlap; the held-out 0.54→0.79 was withdrawn as contaminated); holds lift; scribe merge | VERIFIED COMPLETE (floor) / model layer NOT MEASURED |
| R4.3 | Emotional intelligence | complaint → care-first length; rater packet built; no ratings | PARTIALLY COMPLETE (BLOCKED on raters) |
| R4.4 | Consultative intelligence | hard pressure rule; discount figures grounded by the figure rule; judgment unmeasured | PARTIALLY COMPLETE |
| R4.5 | Onboarding | photo turns kept; memory/onboarding case slices written; re-asking unmeasured | PARTIALLY COMPLETE |
| R4.6 | Closing | readiness read (floor); paid conversion on the dashboard (partial denominator); delivery-total rule not changed | PARTIALLY COMPLETE |
| R4.7 | Memory and context | newest rules kept; contradictions resolved; silence honoured; locked writes; context experiment NOT STARTED (needs model) | PARTIALLY COMPLETE |
| R4.8 | Multilingual | language guess 0.528→0.930 on the blind set (intervals separated; the earlier held-out figure was withdrawn as contaminated, BENCHMARK_RESULTS Correction 1); deterministic continuity rule; 100 language cases; native review BLOCKED | PARTIALLY COMPLETE |
| R4.9 | Autonomous execution | outcomes say customer_told; handoff rings; order idempotency and legacy path not changed (recorded) | PARTIALLY COMPLETE |
| R4.10 | Continuous evaluation | agent_eval --cases, history in app_settings, dashboard reads it; no automatic prompt change exists. Run 42289125585 completed the first pass over the blind set (179/360 case-runs) and crashed in the runner's contact cleanup (FK ordering) — the checkpoint kept the record; no history row (the run did not finish) | VERIFIED COMPLETE (harness) / PARTIALLY COMPLETE (a full run has not finished) |

## §5 Independent intelligence baseline

| ID | Requirement | Status |
|---|---|---|
| R5.1 | 300–500 cases covering the eleven listed categories | 453 tuning cases + 120 blind cases, all categories (EVALUATION_DATASET) | VERIFIED COMPLETE (no production-derived cases yet) |
| R5.2 | Real model against controlled data, sends disabled | run 42289125585: a complete first pass over the 120 blind cases (459 turns), sends disabled — turns passed 0.800 [0.761, 0.834], critical 0.778, language 0.955, figures 0.854, length 0.881, first draft 0.473 (BENCHMARK_RESULTS); pass^3 NOT MEASURED (crashed at 179/360); two environment defects contaminate stop_ack and 3 turns | PARTIALLY COMPLETE (single pass measured; pass^3 not) |
| R5.3 | Objective assertions + human evaluation where judgment is required | objective verdicts in eval_run; judged turns exported to a packet | PARTIALLY COMPLETE |
| R5.4 | Blind comparison: Neema vs skilled humans vs reference agent | design only (INTERNATIONAL_ASSESSMENT) | NOT STARTED |
| R5.5 | Record inputs, model version, prompt revision, traces, outcomes, criteria, limitations | eval_run record (git sha, model ids, prompt hashes, case-set hash, tool traces) | VERIFIED COMPLETE (harness) |
| R5.6 | Grader independence | objective code + human raters; model judge optional and never sole — a design, not yet exercised by a run or a rater | PARTIALLY COMPLETE |

## §6 Excellence Score

| ID | Requirement | Status |
|---|---|---|
| R6.1 | 10 dimensions, weights as given | EXCELLENCE_SCORE | VERIFIED COMPLETE |
| R6.2 | Per metric: methodology, denominator, sample size, evaluator, evidence source, uncertainty | EXCELLENCE_SCORE table | VERIFIED COMPLETE |
| R6.3 | NOT MEASURED where unreliable; no invented scores | applied |
| R6.4 | ≥10-point verified improvement on a held-out set | floors only, on the blind set (the only uncontaminated held-out): language +40.2 points (0.528→0.930, separated); customer state +5.5 (0.725→0.780, intervals overlap); opt-out +5.9 (0.912→0.971, n=34, overlap); reply length +2.1 after the scorer correction. The real-model first pass gives a baseline (turns 0.800) but no before/after: the 'before' code was never run with the model, so a model-level improvement cannot be claimed. The 100-point aggregate is NOT MEASURED — the 10-point claim is NOT demonstrated | PARTIALLY COMPLETE |
| R6.5 | Investigate the six preliminary targets | first real-model pass: language continuity 0.955 (target ≥0.95 met on this pass; the interval [0.931, 0.971] straddles it); next-action correctness per label 0.35–1.0 (≥0.95 met only for ask_one, care_first, confirm_paid_check, hold_ack; silence 0.346); recall ≥0.95 NOT MEASURED (memory category 0.843 at turn level); emotional ≥0.90 and sandbox completion ≥0.95 NOT MEASURED; conversion not measured | PARTIALLY COMPLETE |
| R6.6 | Aggregate never excuses critical safety/financial errors | applied (gating rule in EXCELLENCE_SCORE) |

## §7 Executive performance dashboard

| ID | Requirement | Status |
|---|---|---|
| R7.1 | Thirteen visibility items | performance.py + PerformanceView: 31 metric rows covering all thirteen | VERIFIED COMPLETE (view) |
| R7.2 | Baseline, current, trend, confidence where supported | previous-window comparison, Wilson intervals, eval history trend | VERIFIED COMPLETE |
| R7.3 | NOT YET MEASURED + instrumentation needed; no fabricated values | every unmeasured row names its instrumentation; DB test asserts no value | VERIFIED COMPLETE |

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
| R9.1 | This register, all columns | this file + ADVANCEMENTS_REGISTER | VERIFIED COMPLETE (living) |
| R9.2 | Independent verification pass after each phase | VERIFICATION_PASS_1.md (adversarial pass on the diff) | see that file |
| R9.3 | Durable checkpoints in project records | this folder, committed |
| R9.4 | Preserve exact state if the session ends | UNFINISHED_REGISTER |
| R9.5 | Record external dependencies precisely | UNFINISHED_REGISTER |

## §10 International comparison

| ID | Requirement | Status |
|---|---|---|
| R10.1 | Assess the four levels | INTERNATIONAL_ASSESSMENT: level 1 partly; 2–4 NOT MEASURED | PARTIALLY COMPLETE |
| R10.2 | No "top ten" claim without peer group, method, evidence | applied |

## §11 Deliverables

| ID | Deliverable | File | Status |
|---|---|---|---|
| R11.1 | Verified Capability Baseline | CAPABILITY_BASELINE.md | VERIFIED COMPLETE |
| R11.2 | Deep Investigation Report | INVESTIGATION_REPORT.md | VERIFIED COMPLETE |
| R11.3 | Ten-Advancement Implementation Register | ADVANCEMENTS_REGISTER.md | VERIFIED COMPLETE (living) |
| R11.4 | Intelligence Benchmark Results | BENCHMARK_RESULTS.md (floors measured; real-model first pass measured; pass^3 NOT MEASURED) | PARTIALLY COMPLETE |
| R11.5 | Customer Experience Assessment | needs the model run and raters | BLOCKED |
| R11.6 | Performance Dashboard | /api/admin/performance + PerformanceView | VERIFIED COMPLETE |
| R11.7 | Full Regression and Safety Report | REGRESSION_SAFETY_REPORT.md | see that file |
| R11.8 | Unfinished and Unverified Work Register | UNFINISHED_REGISTER.md | VERIFIED COMPLETE |
| R11.9 | International Competitiveness Assessment | INTERNATIONAL_ASSESSMENT.md | VERIFIED COMPLETE (honest: levels 2–4 unmeasured) |
| R11.10 | Final Release Readiness Report | RELEASE_READINESS.md | see that file |
