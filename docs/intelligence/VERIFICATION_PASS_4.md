# Verification pass 4 — the registers as they stand on `origin/main` d084e91 (2026-11-06)

Adversarial, independent. Scope: every VERIFIED COMPLETE row in
`docs/intelligence/REQUIREMENTS_REGISTER.md`, every "VERIFIED COMPLETE" /
"fixed" entry in `docs/intelligence/ADVANCEMENTS_REGISTER.md`, and the five
deliverables named in the brief. Branch `claude/where-are-we-bx9v9w` (14d2df8)
differs from `origin/main` (d084e91) only in two docs files (`git diff --stat`:
REGRESSION_SAFETY_REPORT.md +1, RELEASE_READINESS.md +5/−3). All commands from
`/home/user/neema-ai/apps/api` with the scratchpad venv (`$V`) and `env.sh`.
Network: `curl …/api/health` once; `gh run list`/`gh run view` on the repo's own
runs. No commits, no pushes; every mutation restored byte-exact (sha-256
asserted in the harness); `git status --short` empty at the end. The blind
set's text and misses were never printed or read (the scorer withholds them by
default and my aggregator strips list-valued keys).

## Baselines on the current tree

| Run | Result |
|---|---|
| Full API suite, `pytest tests -q -p no:cacheprovider` | **3,313 passed, 1 xpassed, 0 failed** (10 min 13 s; Postgres up, Redis down — no test needed it) |
| The eleven cited intelligence/eval/social/performance test files | 306 passed |
| `pnpm exec tsc --noEmit` (apps/web) | exit 0 |
| `ruff check app tests` (venv ruff 0.6.9, CI's pin) | 97 findings; `.ci/ruff-baseline.txt` = 115 (ratchet holds; the report's "96" is one off) |
| Live box `GET /api/health` | `status ok`, `version 34d371e…` (slices 2–3), `agent.replies ok`, `review.held 1` with no `gate_error` finding, spend by model populated |
| GitHub Actions | `16e7a17` (slice-4 head): CI and Build & Push **success**; `d084e91` on main: Build & Push **in_progress** at the time of the check (so "deploy in flight" is exact) |

## Measurement reproduction (the scorer, aggregate only)

`$V -m app.jobs.eval_floors {--file blind_heldout.jsonl | --all | --dev | --held-out} --json …`, compared with the committed files on every metric's `all` row (k, n, p, ci95):

| Selection | Committed file | Reproduced? |
|---|---|---|
| blind (120 cases / 459 turns / 48 critical) | `floors-rescored-blind.json` | **yes, identical**: said 358/459 = 0.780 [0.740, 0.815]; lang 414/445 = 0.930 [0.903, 0.950]; opt-out 33/34 = 0.971 [0.851, 0.995]; length 221/459 = 0.481 [0.436, 0.527] |
| blind | `floors-blind-after.json` | identical on said/lang/opt-out; length 218/459 (pre-Correction-2, as the file's date and the doc say) |
| all (453) | `floors-rescored-all.json` | **identical** (422/491, 342/355, 40/42, 677/1196) |
| dev (217) | `floors-rescored-dev.json` | **identical** (214/228, 196/197, 11/12, 342/596) |
| held-out (236) | `floors-rescored-held-out.json` | **identical** (208/263, 146/158, 29/30, 335/600) |
| blind **before** — `git archive ff8c3b5 apps/api/app` into the scratchpad + the scorer, loader and blind file from e9d2e19 (the blind file is byte-identical on HEAD) | `floors-blind-before.json` | **identical**: said 333/459 = 0.725 [0.683, 0.764]; lang 235/445 = 0.528 [0.482, 0.574]; opt-out 31/34 = 0.912 [0.770, 0.970]; length 211/459 = 0.460 |

The historical `floors-baseline-*` / `floors-after-*` files (case set v1, 430
cases, 1,220 turns, 161 critical) match every number quoted in
BENCHMARK_RESULTS §Baseline and §After-W2, including Correction 2's four
deltas (657→677, 329→335, 328→342, 218→221) and the 430+23 = 453 arithmetic.
Those tables are withdrawn as held-out claims in the doc itself and were not
re-run (they need the v1 case files).

## Row-by-row audit

Columns: row · claim · evidence checked · holds? · honest status if different · note.

### REQUIREMENTS_REGISTER — rows marked VERIFIED COMPLETE

| Row | Claim | Evidence checked | Holds? | Honest status | Note |
|---|---|---|---|---|---|
| R2.0b | audits, reports, git history, production evidence reconstructed | CAPABILITY_BASELINE §3–4 exist; `/api/health` read | partly | VERIFIED COMPLETE | "87 commits, PRs #251–#315" is not checkable here: the clone is shallow (142 commits reachable) and merge subjects reach #247. Not false, not verifiable from the repo. |
| R2.1 | FastAPI runtime and orchestration inventoried | CAPABILITY_BASELINE §2A (19 rows, file:line) | yes | — | inspection record |
| R2.2 | prompt measured 95–98 K chars | `build_system_prompt` on HEAD: KE/KES 95,636; US/USD 96,926; ZM/ZMW 96,270 | yes | — | doc's 95,313 was pre-W7-3; within the stated range |
| R2.3 | memory and state inventoried | §2F (15 rows) | yes | — | |
| R2.4 | 23-tool architecture + 1 conditional | `tools.TOOLS` has 23 entries | yes | — | the conditional one not counted here |
| R2.6 | commercial workflows | §2C (22 rows) | yes | — | |
| R2.7 | channels | §2D (16 rows) | yes | — | |
| R2.8 | autonomous actions, consent | "§2D/E + Stage 1–8 reports" | partly | VERIFIED COMPLETE, evidence pointer to fix | the Stage 1–8 reports are **not in the repository** (they are scratchpad files `stage*-report-*.md`); only §2D/E is durable evidence |
| R2.9 | 28 outbound paths, gate coverage | §2E (17 rows) | yes (inspection) | — | the "28" was not independently re-counted |
| R2.10 | dashboard, monitoring, eval tools | §2G | yes | — | |
| R2.11 | Android/iOS contracts, 81 endpoints | §2G; apps untouched (`git diff` shows no app changes) | yes (inspection) | — | 156 route decorators in `app/routers`; the 81 is the shared subset per the doc, not re-derived |
| R2.13 | inventory with all fields, "230 rows" | 11 tables, 219 table lines → **197 data rows** | partly | VERIFIED COMPLETE | the row count is overstated by ~33 (or counts headers); cosmetic |
| R2.14 | end-to-end traces | §1 (1.1–1.9) | yes | — | |
| R2.15 | paths examined / not examined | §5.1–5.2 | yes | — | |
| R2.16 | dead code, contradictions… "50 findings" | INVESTIGATION_REPORT: exactly 50 numbered findings | yes | — | |
| R3.1 | seven topic areas | STANDARDS §1–9 | yes | — | |
| R3.2 | ten named sources, ISO structure only | §2.1–2.4, §3.1–3.2, §4 (vendors named 11×) | yes | — | |
| R3.3 | τ-bench practice adopted in eval_run | `eval_run.py`: end-state verdicts, `pass^{repeat}` / `pass^1` (l.336–337), run record | yes | — | harness only; never run with a model (as stated elsewhere) |
| R3.4 | science vs marketing tags | (S)/(E)/(M)/(P) throughout | yes | — | |
| R3.5 | 12 ranked practices | §"What applies": 12 items | yes | — | |
| R4.2 | floor measured on the blind set 0.725→0.780 | reproduced both ends (table above) | yes | VERIFIED COMPLETE (floor) — as written | the measurement is verified; the improvement is **not** interval-separated, and the row says so |
| R4.10 | agent_eval --cases, history row, dashboard reads it | `eval_run._append_history` writes `eval_history`; `performance._eval_metric` reads it; `test_an_eval_history_row_turns_the_eval_metrics_measured` passes on Postgres | yes | — | see S3-10: the dashboard row carries `selection` but the basis string and the "previous" comparison ignore it |
| R5.1 | 453 tuning + 120 blind cases, all categories | loader: 453 non-blind (audit 10, independent 400, developer 43) + 120 blind; all 25 defined categories covered | yes | — | "the eleven listed categories" cannot be checked without the directive text |
| R5.5 | run record: git sha, model ids, prompt hashes, case-set hash, traces | `eval_run.py:398–404`: `git_sha`, `case_set`, `models{producer,light,reviewer,…}`, `prompt_revision{prompt_py, directives, learned_rules, house_voice}`, per-turn `tools` | yes | VERIFIED COMPLETE (harness) — as written | |
| R5.6 | grader independence | design text in EXCELLENCE_SCORE; nothing run | design only | **PARTIALLY COMPLETE** (or NOT STARTED) | "VERIFIED COMPLETE (design)" is not one of the six statuses' meanings: a design is not a measurement or an inspection of behaviour |
| R6.1 | 10 dimensions, weights as given | weights 20+15+10+10+10+10+10+5+5+5 = 100 | yes | — | |
| R6.2 | per-metric methodology, denominator, n, evaluator, source, uncertainty | table has evaluator/denominator/sample/source/status; methodology and Wilson uncertainty in the prose | yes (inspection) | — | |
| R7.1 | 31 metric rows covering 13 items | `performance.py`: **30** distinct metric keys | partly | VERIFIED COMPLETE (view) | one off; the "thirteen" cannot be checked without the directive |
| R7.2 | previous window, Wilson, eval trend | `_wilson`, `previous=`, `_trend`, `eval_history` present; `test_performance_db` on Postgres | yes | — | |
| R7.3 | NOT YET MEASURED rows name instrumentation, never a value | `_not_measured()` sets `value=None` + `instrumentation`; DB test asserts both | yes | — | |
| R9.1 | this register, all columns | the file | yes | — | status-word discipline is uneven: "applied", "see that file" are used on 20+ rows instead of the six statuses |
| R11.1 / 11.2 / 11.3 / 11.8 / 11.9 | deliverable files exist and say what the row says | read | yes | — | R11.9: see S3-7 on one comparative sentence |
| R11.6 | Performance Dashboard | `/api/admin/performance` + `PerformanceView.tsx`; DB test; tsc clean | yes | VERIFIED COMPLETE (view) would be more exact | UNFINISHED still lists "the owner opens it" as pending verification |

### ADVANCEMENTS_REGISTER — VERIFIED COMPLETE entries

| Row | Claim | Evidence checked | Holds? | Honest status | Note |
|---|---|---|---|---|---|
| W1-9 | paid-ack hard rule; negation/condition guarded; every mode | `test_intelligence_w1_grounding.py` (behaviour through `rule_findings`); mutants M1 (any order tool allows thanks) and M2 (negation guard dropped) **killed** | yes | — | |
| W2-3 | a question or a buying signal lifts a hold; behaviour test on `apply()` | `test_apply_lifts_a_hold_when_the_customer_asks_a_question`; M5 (buying-message term removed from `apply`) killed; **M6 (the `"?"` branch of `_buying_message` removed) survived** | partly | VERIFIED COMPLETE for the buying-signal half; the *question* half is unproven | the test's "question" ("How much is the stole?") is also a buying signal, so a bare question ("Are you open Sunday?") is never exercised |
| W2-4 | scribe keeps a team check and a hold; `scribe_update` tested | `_merge_next_action` + `test_the_scribe_keeps_the_team_check_when_the_customer_names_a_day`; M7, M8 killed | yes | — | |
| W3-1 | complaint → care-first length; harness scores the same function | `test_a_complaint_read_by_the_floor_earns_the_care_first_length`; M9 (complaint term dropped from `length_target_for`) killed | yes | — | |
| W8-1 | deterministic language finding, soft | `test_language_continuity_is_checked_without_the_model_reviewer`; M3, M4 killed | yes | — | |
| W7-6 | both state writers lock and write the re-read row; unlocked fallback tested | `test_state_writes_take_the_row_lock`, `test_an_opt_out_still_lands_when_the_lock_cannot_be_taken`; M10 (stale row written), M11 (lock not taken) killed | yes | — | |
| W7-2 | newest learned rules survive the cap | `test_the_standing_orders_cap_keeps_the_newest_learned_rules`; M12 killed | yes | — | |
| **W9-1** | "the hub-event tests assert `customer_told` on every branch" | `_celebrate` has **7** return sites; `customer_told` is asserted in only two shapes across the whole tests tree (freeform `True` ×3, the final notified_human `False` ×2); **M13 (unknown delivery → True), M14 (template → False), M15 (opted-out → True), M16 (rules-held → True) all survived** the three relevant files | **no** | **PARTIALLY COMPLETE** (2 of 7 branches verified) | the claim as written is false |
| W10-3 | `served_model` behaviour test + usage-row pin | `test_usage_logs_the_model_that_actually_served`, `test_cost_overhaul.py:23–26`; M17 killed | yes | — | the usage-row half is a source-string pin, and the entry says so |

### ADVANCEMENTS_REGISTER — "fixed" entries

| Row | Claim | Evidence checked | Holds? | Honest status | Note |
|---|---|---|---|---|---|
| W1-14 | Neema-initiated messages meet the rules: dispatcher `_send`, after-sale announcement, sweeper bridge; "Tests: test_intelligence_w1_grounding.py" | dispatcher: behaviour test, **M29 killed**. Announcement + bridge: `test_the_announcement_and_the_bridge_hold_on_the_rules` is `inspect.getsource` string pins; **M28 (the announcement's `if _issues["hard"]` guard removed → a rule-held announcement is sent) survived** three files | partly | IMPLEMENTED BUT NOT VERIFIED for the announcement and the bridge | pass-1 finding 12 removed source-string evidence from four rows but left this one |
| W1-2 (1.4) | opt-out door reads words with a photo attached | `test_the_opt_out_door_reads_the_words_even_with_a_photo_attached` runs green | yes (not mutated) | — | |
| Finding 12 | four rows now have behaviour tests | confirmed above (W3-1, W7-6, W10-3, W2-4) | yes | — | |
| Scorer correction | harness calls `runtime.length_target_for`; rescored files | `eval_floors._runtime_target` imports it; rescored files reproduced exactly | yes | — | |
| Blind isolation | loader leaves `"blind": true` out by default | `test_the_default_sweep_leaves_the_blind_set_out`; M22 (exclusion removed) killed | yes | — | |
| W1-15 dedupe | comment deduped on its own row before store/engage | `test_a_redelivered_comment_is_not_answered_twice_without_redis` reads the compiled statement; M23 (different id looked up) killed | yes | — | |
| W7-4 second half | truncated draft trimmed; `_settle_truncated` | trimmer tests + `run_turn` with a fake writer run green | yes (not mutated) | — | |
| W7-5 first half | Messenger turn reads the linked WhatsApp user's facts, newest row | `test_a_messenger_turn_reads_the_linked_whatsapp_users_facts`; M24 (`asc()` instead of `desc()`) killed | yes | — | |
| W5-3 | dated facts, refreshed on restatement, pruned with the cap | `test_a_fact_carries_the_day_it_was_noted_and_a_restatement_refreshes_it`; M19 (dates of capped-off facts kept) killed | yes | — | |
| W10-3 second half | proposals Settings card, first caller of D4 endpoints; typecheck clean | `SettingsView.tsx` `ProposalsCard` → `settingsApi.getProposals`; `crm.py:1307,1323`; `tsc --noEmit` exit 0 | yes | — | |
| W10-2 | reference-only panels, "Managed on the box" | 6 occurrences in `apps/web/src`; tsc clean | yes (inspection) | — | |
| W1-1 (amended) | flag reports landing; unowned outcome; senders leave the thread unmarked | `test_the_flag_reports_landed_only_after_the_commit`, `test_both_senders_leave_an_unowned_hold_unmarked`; pass-3b survivors U4/U5 re-run as **M25/M26: killed**; U9 as M27: killed | yes | — | pass-3b's S2 #1 is genuinely closed |
| W1-16 | opt-out from a contact with no person makes one; web keys never resolve | both tests; pass-3b survivor W1 re-run as **M21: killed** | yes | — | pass-3b's S2 #2 is genuinely closed |
| W1-10 | Meta receipts stamped by watermark, never lowered | `test_a_meta_delivery_receipt_stamps_the_outbound_rows_it_covers`; M20 killed | yes | — | |
| W1-15 figures | ids/counts/sizes are not money facts | `test_a_tools_ids_counts_and_sizes_are_not_money_facts`; M18 killed | yes | — | |

## Deliverable audits

**(1) BENCHMARK_RESULTS.md.** Every number in the blind-set table and in
Correction 2 reproduces from the committed files and from a fresh run of the
scorer on HEAD (table above); the "before" column reproduces from
`ff8c3b5`'s code with that day's scorer. The coverage figures (120 / 459 /
48; 430 / 1,220 / 161; 453) match the files. The baseline and after-W2
tables match their files and are correctly marked withdrawn. No discrepancy.

**(2) EXCELLENCE_SCORE.md and the dashboard.** No dimension carries a number;
every "NOT MEASURED" is honest and the dashboard's `_not_measured` rows carry
`value=None` and an instrumentation string (asserted on Postgres). Two
staleness issues, not fabrications: §"How a score is produced" still says
before/after numbers "come from the held-out half", which Correction 1
withdrew (S3-5); and the dashboard's instrumentation hint, the UNFINISHED
command and `performance.py:181` all say `--held-out`, the half
EVALUATION_DATASET calls "for diagnosis only" (S3-6). R6.5's "(0.930 floor on
the blind set)" cites the language-*guess* accuracy as the measure for
language *continuity* (reply in the customer's language) — a different
quantity (S3-8).

**(3) INTERNATIONAL_ASSESSMENT.md.** Levels 2–4 are NOT MEASURED, no ranking
is claimed, the 0.971 opt-out figure is quoted with its n and caveat, "3,100+"
tests holds (3,314 collected). One sentence is stronger than its evidence:
"Neema's evaluation design (… held-out split, …) matches the published
research practice better than the vendors' published claims do" — a
comparative verdict with no measurement behind it, and it lists the held-out
split as a strength when the record itself says that split is contaminated
(S3-7).

**(4) RELEASE_READINESS.md.** "34d371e live at ~19:22" — true now (the box
reports 34d371e). "d084e91 merged … deploy in flight" — true (Build & Push on
main in progress at the time of the check; the box has not yet moved). CI green
on 16e7a17 — true. "3,294 passed" was the count at bbe48cf; HEAD gives 3,313.
Stale text: the title and first line still say "slice 1"; "What ships … Web:
one new view" describes PR #316 only (slices 2–4 added the proposals card and
the panel changes) (S3-9); "a model key on the box" is listed as an owner
action while OWNER_ACTIONS says the key is already in the api container (and
`/api/health` shows live model spend) — the action is to *run* it (S3-9).
REQUIREMENTS R2.12 still says "ff8c3b5 live" (S3-9).

**(5) UNFINISHED_REGISTER.md.** Open items confirmed open: the
`messages.waba_msg_id` index (no alembic revision), the `/api/health` hub wait
(`health.py:108` → `price_audit.health_summary`, cached an hour), the real-model
run (the `agent-eval` workflow on ff8c3b5 failed on an empty
`ANTHROPIC_API_KEY`). Missing: pass-3b findings 6 (CI `timeout-minutes` vs the
3 × 305 s arithmetic, dpkg after SIGTERM) and 8 (`_can_resolve` narrower than
the doors' plausibility check, no log when redis-only) are marked "Recorded" in
the pass-3b response table but appear nowhere in the register (S3-2). Partly
done but not struck: "The blind set must be scored before any held-out claim"
(it has been) shares a row with the still-open runner channel parameter (S3-3).
Nothing done is wrongly listed open; W7-4's "code + source test" wording is
accurate for the first half.

## Findings

| # | Sev | Finding | Evidence |
|---|---|---|---|
| S1-1 | **S1** | **W9-1 is VERIFIED COMPLETE on a false evidence statement.** "The hub-event tests assert `customer_told` on every branch": `_celebrate` returns at seven sites; tests assert the key only on the freeform branch and the final notified_human branch. Four branch mutants survived every test that touches the function. | `apps/api/app/services/hub_events.py:269, 293, 302, 311, 331, 336, 345`; `tests/test_hub_events.py:100, 196`; `tests/test_human_agent_window.py:269, 301, 321`; harness M13–M16 SURVIVED (`p4/mutations.txt`). Honest status: PARTIALLY COMPLETE. |
| S2-1 | S2 | **W1-14's announcement hold is unproven.** The entry presents the dispatcher, the after-sale announcement and the sweeper bridge as fixed and tested; only the dispatcher has a behaviour test. Removing the announcement's `if _issues["hard"]` guard (a rule-held announcement goes to the customer) survives the suite's three relevant files; the only test is an `inspect.getsource` pin. | `apps/api/app/services/hub_events.py:284–291`; `tests/test_intelligence_w1_grounding.py:151–154`; M28 SURVIVED, M29 KILLED. Honest status: dispatcher VERIFIED COMPLETE; announcement and bridge IMPLEMENTED BUT NOT VERIFIED. |
| S2-2 | S2 | **R5.6 "VERIFIED COMPLETE (design)".** A design is neither a repeatable measurement nor an inspection of behaviour, which is the register's own stated bar for the word. | `docs/intelligence/REQUIREMENTS_REGISTER.md` §5 R5.6. Honest status: PARTIALLY COMPLETE (design written, nothing run). |
| S3-1 | S3 | W2-3's "question lifts the hold" half is untested: the test's question is also a buying signal, so deleting the `"?"` branch survives. | `apps/api/app/services/customer_state.py:487–498`; `tests/test_intelligence_w2_w7.py:25–30, 160–173`; M6 SURVIVED |
| S3-2 | S3 | Pass-3b findings 6 and 8 are "Recorded" in the response table but absent from UNFINISHED_REGISTER. | `VERIFICATION_PASS_3B.md:104, 106`; `grep -i "isdigit\|plausib\|timeout-minutes\|dpkg" UNFINISHED_REGISTER.md` → nothing |
| S3-3 | S3 | UNFINISHED row 6/13 half-done and not struck (blind set has been scored). | `UNFINISHED_REGISTER.md:127` (file line 64 in the concatenated read) |
| S3-4 | S3 | R2.8 cites "Stage 1–8 reports" that are not in the repository (scratchpad only); the durable evidence is §2D/E alone. | `REQUIREMENTS_REGISTER.md` R2.8; `grep -rl "Stage 7" docs/*.md` → none |
| S3-5 | S3 | EXCELLENCE_SCORE's method section still says before/after numbers come from the held-out half, withdrawn by Correction 1. | `EXCELLENCE_SCORE.md:12–16` |
| S3-6 | S3 | The real-model command is given as `--held-out` in UNFINISHED and in the dashboard's instrumentation hint, while EVALUATION_DATASET/BENCHMARK make `--file blind_heldout.jsonl` the report. | `UNFINISHED_REGISTER.md:73`; `apps/api/app/services/performance.py:181` |
| S3-7 | S3 | INTERNATIONAL_ASSESSMENT level-4 cell: an unmeasured comparative claim ("matches the published research practice better than the vendors' published claims do") that lists the contaminated held-out split as a strength. | `INTERNATIONAL_ASSESSMENT.md:93` (concatenated line) |
| S3-8 | S3 | R6.5 cites the language-guess floor (0.930) as "language continuity measurable now"; the guesser's accuracy is not reply-language continuity. | `REQUIREMENTS_REGISTER.md` R6.5; `EXCELLENCE_SCORE.md` targets table |
| S3-9 | S3 | Stale live-state text: RELEASE_READINESS title/first line "slice 1", "Web: one new view", "a model key on the box" (the box has one — the action is to run it); REQUIREMENTS R2.12 "ff8c3b5 live" (box is at 34d371e). | `RELEASE_READINESS.md:1–3, 52, 61`; `REQUIREMENTS_REGISTER.md` R2.12; `/api/health` |
| S3-10 | S3 | The dashboard marks an eval-history row "measured" whatever its `selection` (held-out, dev, blind): the basis string omits the selection and `previous` compares the latest row with the first row regardless of selection, so a contaminated held-out run and a blind run would be shown as a trend. | `apps/api/app/jobs/eval_run.py:545–546` (row carries `selection`); `apps/api/app/services/performance.py:168–177` |
| S3-11 | S3 | Count drift in the registers: CAPABILITY_BASELINE "230 rows" (197 data rows); R7.1 "31 metric rows" (30 keys); REGRESSION "96 ruff findings" (97 on HEAD with CI's ruff 0.6.9; ratchet 115 holds); W2-1 "118 parametrised cases" (166 collected now). | counts above |
| S3-12 | S3 | Status-word discipline: "applied", "see that file", "(living)", "(design)", "(harness)", "(view)" are used on ~25 rows where the six statuses were mandated. | `REQUIREMENTS_REGISTER.md` §1, §2.17, §6.3/6.6, §8, §9, §10.2, §11.7/11.10 |
| S3-13 | S3 | Source-string pins remain the only test for several IMPLEMENTED BUT NOT VERIFIED rows (W7-4 first half, W9-2, W5-2, W1-2 placement, W1-7, W1-13). Their statuses are honest; noted so nobody promotes them on the strength of those tests. | `tests/test_intelligence_w2_w7.py:18–23, 46–55`; `tests/test_intelligence_w1_fail_closed.py:58, 91–131`; `tests/test_intelligence_w1_grounding.py:73, 80` |

## Claims confirmed (tried to break, could not)

- **Every number in BENCHMARK_RESULTS reproduces**, including the blind
  "before" from `ff8c3b5` and the four rescored selections on HEAD, to the
  last digit of k, n, p and both interval ends. The blind file is unchanged
  since it was scored (byte-identical to e9d2e19). The loader's blind
  exclusion is real (M22 killed).
- **The full suite is green on the current tree** (3,313 passed, 1 xpassed).
- **The pass-3b test gaps are closed**: the three sender mutants (U4/U5) and
  the resolver-guard mutant (W1) that survived then are killed now (M25, M26,
  M21), and the gate-flag mutant U9 stays killed (M27).
- **Behaviour, not source, backs W1-9, W2-4, W3-1, W8-1, W7-6, W7-2, W10-3,
  W5-3, W1-10, W1-15 (both halves), W7-5, W1-16 and W1-1**: 18 targeted
  production mutants across those rows all killed.
- **The dashboard's "NOT YET MEASURED" is honest** on a real Postgres: every
  such row has `value=None` and names its instrumentation; nothing in
  EXCELLENCE_SCORE carries a number.
- **The live claims in RELEASE_READINESS are true** as of this check: the box
  runs 34d371e, replies ok, no `gate_error` in the review tally, outreach not
  claimed otherwise; slice 4's head passed CI; its main build was in flight.
- **The web typecheck is clean**; the proposals card and the reference-only
  panels exist as described.
- **The agent-eval workflow is BLOCKED for the stated reason**: the ff8c3b5
  run failed on an empty `ANTHROPIC_API_KEY`.

## Mutation tally

Harness: `/tmp/claude-0/-home-user-neema-ai/2c406dec-643d-5176-808d-0adf5b06cc5b/scratchpad/p4/mutate.py`
(exact single-occurrence replace, `pytest -q -p no:cacheprovider -x` on the
named files, byte-exact restore asserted by sha-256). Output:
`/tmp/claude-0/-home-user-neema-ai/2c406dec-643d-5176-808d-0adf5b06cc5b/scratchpad/p4/mutations.txt`.
Run after the full suite had exited, so no live pytest could import a mutated module.

**29 mutants: 23 killed, 6 survived.**

| Survivor | Row | What it proves |
|---|---|---|
| M6 `_buying_message`: `"?"` branch removed | W2-3 | the question half is untested (S3-1) |
| M13 unknown delivery → `customer_told: True` | W9-1 | branch unasserted (S1-1) |
| M14 template send → `customer_told: False` | W9-1 | branch unasserted (S1-1) |
| M15 opted-out branch → `customer_told: True` | W9-1 | branch unasserted (S1-1) |
| M16 rules-held branch → `customer_told: True` | W9-1 | branch unasserted (S1-1) |
| M28 announcement's rules guard removed | W1-14 | announcement hold is source-pinned only (S2-1) |

Killed: M1, M2 (W1-9); M3, M4 (W8-1); M5 (W2-3); M7, M8 (W2-4); M9 (W3-1);
M10, M11 (W7-6); M12 (W7-2); M17 (W10-3); M18 (W1-15 figures); M19 (W5-3);
M20 (W1-10); M21 (W1-16); M22 (blind isolation); M23 (W1-15 dedupe); M24
(W7-5); M25, M26, M27 (W1-1); M29 (W1-14 dispatcher).

## Verdict

The registers can be trusted for what they measure and for most of what they
mark verified: every benchmark number reproduces exactly (including the blind
"before" rebuilt from main's old code), the full suite is green on d084e91,
the live-state claims are true as of this check, the NOT MEASURED discipline
holds, and 23 of 29 production mutants aimed at the VERIFIED COMPLETE rows
were killed by behaviour tests — including the three test gaps pass 3b opened.
They cannot be trusted word-for-word: one VERIFIED COMPLETE row (W9-1) rests
on an evidence statement that is simply false (four of seven `customer_told`
branches are unasserted and their mutants survive), one "fixed" entry (W1-14)
presents a source-string pin as the test for the after-sale announcement
hold, and one row (R5.6) applies "VERIFIED COMPLETE" to a design. The rest of
what I found is register hygiene — two pass-3b items marked recorded but not
recorded, stale slice-1 wording, a held-out/blind inconsistency in three
places, and small count drift — none of which changes a measured number or a
customer-facing behaviour. One late finding is outside the documents but inside main: the real-model
workflow on d084e91 shows a green run that executed no model (the stage
crashed on mapper registration behind an un-piped `tee`), and the key the
registers call the blocker now exists as a repository secret — so the
BLOCKED rows name the wrong dependency, and the Actions tab over-claims
where the documents do not. Downgrade W9-1 to PARTIALLY COMPLETE, split
W1-14's status, restate R5.6, re-point the BLOCKED rows at the runner crash
(and land the branch's workflow fix on main), and record the two missing
pass-3b items, and the registers would say exactly what the code and the
results files support.

## Addendum — the branch moved during the audit

The audit above was made on the working tree at `14d2df8` (code identical to
`origin/main` d084e91; docs-only diff). While it ran, another session
advanced `claude/where-are-we-bx9v9w` by four commits (b6649a7, be0acca,
9c377b2, 87a2b29). None are on `origin/main`, which is still d084e91, so the
code findings stand unchanged. What the new commits claim, checked:

- "Full suite on the merged main d084e91: 3,313 passed, 0 failed" — **true**
  (my own run: 3,313 passed, 1 xpassed, 0 failed).
- "Slice 4 live on the box at ~19:55 UTC" — **true now**: a second
  `/api/health` read at ~20:00 UTC returns `version d084e91…`, `replies ok`;
  Build & Push on main completed **success**. The earlier "deploy in flight"
  was accurate at its time; S3-9's stale-text points (title "slice 1", "Web:
  one new view", "a model key on the box", R2.12 "ff8c3b5 live") remain.
- 9c377b2 / 87a2b29 change `app/jobs/agent_eval.py`, the `agent-eval`
  workflow and `test_eval_harness.py` — post-audit, not on main, not audited
  here beyond noting they exist.
- **S2-3 (main's workflow, found late): the `Agent eval (model in the loop)`
  run on d084e91 (run 42284150514, `workflow_dispatch` 19:57 UTC) reports
  `success` but ran no model.** Its "Refuse to run without a key" step
  passed — so the `ANTHROPIC_API_KEY` repository secret **now exists** (the
  ff8c3b5 run had failed on that step) — and the blind stage then died at
  start-up: `sqlalchemy.exc.NoReferencedTableError: Foreign key associated
  with column 'persons.parish_id' could not find table 'parishes'` right
  after printing `case set f87e25bf0541 · 120 cases × 3 · producer
  claude-sonnet-5-5 · git d084e91`; no results artifact exists. On main the
  step runs `python … | tee …` without `pipefail`, so the crash is swallowed
  and the job is green. The branch's 9c377b2 ("the runner registers every
  model; the workflow fails when a stage crashes") is the fix and is **not
  on main**. Consequences for the registers: (a) "BLOCKED on a model key"
  (R5.2, R4.10, UNFINISHED row 1, OWNER_ACTIONS §1, RELEASE_READINESS owner
  items) is stale — the blocker is now the runner's mapper registration, not
  the key; (b) anyone reading the Actions tab sees a green real-model run
  that never happened — the worst shape of over-claim for this programme,
  even though no document cites it yet. Honest status of R5.2: BLOCKED
  (runner crash), not BLOCKED (key).


## Implementer's response (same day)

| Finding | Response |
|---|---|
| S1-1 W9-1 evidence false (2 of 7 branches asserted) | **Fixed.** Four more branches behaviour-tested (opted-out, rules-held, unknown delivery, template); the register row now states exactly that. |
| S2-1 W1-14 announcement hold pinned by a source string | **Fixed.** The rules-held announcement branch is in the same behaviour test (a "thank you for your payment" draft on a shipped event is held; nothing is sent; a person is told). |
| S2-2 R5.6 VERIFIED COMPLETE for a design | **Restated** PARTIALLY COMPLETE. |
| S2-3 the model workflow's green run that ran no model; BLOCKED rows naming the key | **Fixed.** PR #319 (runner registers every model; pipefail on both stages) is open and the run on the fixed branch is in progress; R5.2, R4.10, UNFINISHED, OWNER_ACTIONS and RELEASE_READINESS now say so. |
| S3 W2-3 question-only half | ~~**Fixed** (test on "Where is your shop?")~~ — **that fix was ineffective**: "shop" is in `cooling._BUY_RE`, so the test still passed through the buying-signal branch and M6 survived. Fixed in slice 5 (2026-11-06) with "Are you there?" (no buying word); M6 killed. |
| S3 pass-3b #6 and #8 absent from UNFINISHED | **Recorded.** |
| S3 R2.8 cites scratchpad-only reports | **Fixed.** The eleven Stage and audit reports are now under `docs/intelligence/reports/`. |
| S3 EXCELLENCE method text / `--held-out` commands / INTERNATIONAL wording / R6.5 wording | **Fixed** (blind set everywhere a report is meant; the language GUESS named as such). |
| S3 stale live text (RELEASE_READINESS, R2.12) | **Fixed** (slices 1–4, d084e91). |
| S3 dashboard marks any eval row measured and trends mixed selections | **Fixed.** Only `file:blind…` runs count; the trend compares blind runs only. |
| S3 count drift (CAPABILITY_BASELINE rows, metric rows, ruff, floors tests) | **Recorded** — counts in prose are dated snapshots; the files are the source. |
| S3 non-status words on ~25 register rows ("applied", "see that file") | **Recorded** for the next register pass; the six statuses are the rule. |
| S3 remaining source-string pins on IMPLEMENTED BUT NOT VERIFIED rows | Correctly labelled; left as is. |
