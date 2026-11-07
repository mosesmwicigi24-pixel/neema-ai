# Full Regression and Safety Report — slice 1 (2026-11-06)

Evidence that existing systems and customer protections remain intact after
the changes in PR #316 (branch `claude/where-are-we-bx9v9w`, base `main` at
ff8c3b5).

## 1. Test evidence

| Run | Scope | Result |
|---|---|---|
| Full API suite before any change (06 Nov, 13:0x UTC, ff8c3b5) | `pytest tests` | 3,065 passed, 1 xpassed |
| Full API suite after the floor change (W2), Postgres down mid-run | `pytest tests` | 35 failed / 431 skipped — **invalid run** (local Postgres had stopped; repeated) |
| Full API suite after W1 (gate/takeover/opt-out door) | `pytest tests` | 85 failed, 3,141 passed — **root cause found**: the takeover re-check failed closed on *any* exception, which muted every unit test whose fake session raises; narrowed to infrastructure errors (W1-5 amended); the 22 affected files re-run: 586 passed, 5 failed |
| The 5 remaining | `test_verification_stress` | two new gate rules (pressure, language) produced false holds on legitimate Swahili price lines and campaign discount replies — **caught by the existing stress tests**, both rules narrowed; 204 passed on re-run |
| Full API suite on 5cb9e2b (test pins) | `pytest tests` | 4 failed, 3,235 passed — the four (`test_verification_stress` ×3, `test_web_geo`) pass on their own on the next commit; attributed to running while files were being edited |
| Full API suite on 111ee6e (verification repairs) | `pytest tests` | 1 failed (`test_spend_meter`, passes alone — a second suite was running concurrently against the same services), 3,288 passed, 1 xpassed |
| Full API suite on bbe48cf (= af34fcf code: initiated-message rules, doors; merged as c8c3356) | `pytest tests` | 3,294 passed, 1 xpassed, 0 failed (10 min 18 s) |
| CI on 8cae9b7 (slice 2: behaviour tests, length scorer, blind exclusion, timing tests stub the hub) | GitHub Actions | CI and Build & Push green; the first head (ede8dee) failed only `test_a_fast_request_stays_quiet` (health waited 15 s on the hub from the runner — pre-existing, now stubbed) |
| CI on 4db8f55 (slices 2–3 final head, merged as 34d371e) | GitHub Actions | CI and Build & Push green |
| CI on 16e7a17 (slice 4 final head, merged as d084e91) | GitHub Actions | CI and Build & Push green |
| Full API suite on the merged main d084e91 (slices 1–4) | `pytest tests` | 3,313 passed, 1 xpassed, 0 failed (10 min 8 s) |
| CI on 6954268 (PR #319 final head, merged as c6455d8) | GitHub Actions | CI and Build & Push green |
| CI on 81f67db (PR #320 final head, merged as 7670de1) | GitHub Actions | CI and Build & Push green |
| Production after 7670de1 (~20:48 UTC) | `/api/health` from outside | status ok, replies ok, outreach shadow with no enforced rules |
| CI on 5b23827 (PR #321, docs only, merged as 09c80da) | GitHub Actions | first attempt: the ffmpeg apt step hit its 8-minute bound in both jobs before any test ran (a stalled mirror); one re-run of the failed jobs passed; Build & Push green |
| CI on a5b4dc1 (slice 5 first head) | GitHub Actions | API tests **red**: 12 test worlds that had never modelled the opt-out read (now a deferral, not a send) — fixed in ccc5d52 (CI green) |
| Full API suite on b002177 (slice 5 + pass-5 repairs) | `pytest tests` | 3,339 passed, 1 xpassed, **1 failed** (`test_the_engine_reads_grades_and_routes`, a source string naming the ungated complaint DM — fixed in 1365420), 10 min 18 s |
| CI on 362b1c1 (PR #322 final head, merged as df50f2f) | GitHub Actions | API tests, web, lint, import smoke green at attempt 1; the Migrations job's ffmpeg apt step stalled three times on its runner (the neighbouring job installed it in 46 s) and was re-run once → green at attempt 2 |
| Full API suite on 6d6d831 (slice 6 final: pass-6b repairs — silence marked for the sweep, a bare ok after our question gets a turn) | `pytest tests` with Postgres and redis | **3,349 passed, 1 xpassed, 0 failed** (10 min 24 s) |
| Full API suite on 4bf0f80 (slice 6: runner fixes, pass-6 repairs, closer silence, real-DB cleanup test) | `pytest tests` with Postgres and redis | **3,347 passed, 1 xpassed, 0 failed** (10 min 27 s) |
| Full API suite on b3507ba (closer silence before the contract updates) | `pytest tests` | 4 failed, 3,341 passed — the three gate tests that pinned "one warm line first" (updated in 30de288) and one more in the same family; superseded by the run above |
| CI on 38eb9ec (PR #323 final head, merged as ee1fe26) | GitHub Actions | green at attempt 1 — the Migrations job's apt step stalled on the default mirror once and succeeded after the mirror-list switch |
| Full API suite on 927e44a (slice 7: language metric, guesser, figure judge) | `pytest tests` with Postgres and redis | **3,366 passed, 1 xpassed, 0 failed** (11 min 34 s) |
| CI on 927e44a (PR #324, merged as 6f1060a) and on 07bece7 (PR #325, merged as c0c467d) | GitHub Actions | green at attempt 1, both |
| Production after 6f1060a then c0c467d (00:54 and 01:05 UTC, 7 Nov) | `/api/health` from outside | status ok, version c0c467d, replies ok, outreach shadow (planned 39, needs_approval 598, unknown 0; enforced rules none); review tallies 0 for the new day |
| Full API suite on 1979e28 (slice 7c: staged outage, safety labels) | `pytest tests` with Postgres and redis | **3,367 passed, 1 xpassed, 0 failed** (10 min 49 s) |
| CI on 1979e28 (PR #326, merged as 197704f) | GitHub Actions | green at attempt 1 |
| Production after 197704f (01:26 UTC, 7 Nov) | `/api/health` from outside | status ok, version 197704f, replies ok, outreach shadow |
| Full API suite on 2370777 (slice 8b) | `pytest tests` with Postgres and redis | **3,370 passed, 1 xpassed, 0 failed** (11 min 04 s). An earlier local run on a19b125 showed 7 failures while a second suite ran against the same local redis and Postgres at the same time; the two named failures pass alone, and CI (isolated) was green on a19b125 — concurrency artefacts, recorded here so they are not mistaken for a regression |
| CI on a19b125 (PR #328, merged as 1ca4ba2) and on 2370777 (PR #329, merged as b6cae00) | GitHub Actions | green at attempt 1, both |
| Production after 1ca4ba2 (02:04 UTC, 7 Nov) | `/api/health` from outside | status ok, replies ok, outreach shadow |
| Production after b6cae00 (02:10 UTC, 7 Nov) | `/api/health` from outside | status ok, replies ok, outreach shadow — the `payment_method` finding and the aligned judge are live |
| CI on e7464ea (PR #330, merged as 369e4b6) | GitHub Actions | green at attempt 1 |
| CI on 9a04495 (PR #334, merged as 420b5fc) | GitHub Actions | green at attempt 1 (the Migrations job replayed the chain to a9c1e3f5b7d9 on a fresh database; the drift check passed with an empty known-missing list) |
| Full API suite on 83cf55a (slice 9b: the runner's conversation row and stand-in, the new real-DB test, two safety labels) | `pytest tests` with Postgres and redis, alone on the services | **3,372 passed, 1 xpassed, 0 failed** (9 min 34 s) |
| New real-database test `tests/test_eval_runner_db.py` (slice 9b: the runner's opt-out door, end to end, alembic-built database) | pytest with local Postgres and redis | 1 passed (5 s); negative control by hand against the pre-9b runner: fails at `opted_out is True`, the two CI runs' failure. With `test_cooling_probe_db.py` and `test_migrations.py`: 3 passed |
| Harness and floor tests after the two label corrections (slice 9b) | `pytest tests/test_eval_harness.py tests/test_intelligence_floors.py` | 207 passed; `ruff check` clean on the changed files |
| Full API suite on 2ba43d6 (slice 10: the inbound heartbeat) | `pytest tests` locally | 2,943 passed, 1 xpassed, 0 failed, 436 skipped (the local Postgres and redis had stopped again — the real-database set skips without them); services restarted and that set re-run alone: **452 passed, 0 failed**. The 77 door/health tests pass; ruff clean |
| CI on 2ba43d6 (PR #342, merged as 78535d8) | GitHub Actions | green at attempt 1 |
| Production after 78535d8 (12:41 UTC, 7 Nov) | `/api/health` from outside | status ok, replies ok, outreach shadow; the `inbound` block present and empty at the restart (it counts from the first message accepted after it) |
| First live `inbound` readings (12:42–12:50 UTC, 7 Nov) | `/api/health` polled every two minutes from outside | empty (no channel stamped, `quiet_for_min` null) at 12:42, 12:44, 12:46, 12:48; at 12:50 `whatsapp` last_at 12:50, 2 in the rolling hour, `quiet_for_min` 0 — the door stamps live and the block reads back the way the tests say |
| CI on e87d6fc (PR #343, docs on top of merged slice 10) | `API tests (pytest)` run 42373668954 | **1 failed**, 2,941 passed, 437 skipped: `test_media_signed_urls.py::test_meta_links_carry_the_long_lifetime…` — not this PR's code (`media_urls.py` last changed in #309) and not a flake to re-run away: `_expiry` truncated `now` to the second, so a link signed 0.54 s after a 900 s bucket boundary expired 0.54 s short of its lifetime (one run in ~900 hits it; this one did). Fixed by rounding `now` up (`math.ceil`), pinned by a regression test that reproduces the exact CI assertion on the old code and passes on the new; the 22 media-link tests and the 5 heartbeat tests pass, ruff clean |
| **Incident: the Anthropic API balance ran out (~06:30 UTC, 7 Nov)** | `/api/health` from outside | 07:5x: `replies: failing, kind: credit, failed_last_hour 5, needs_a_human` — five customer turns failed and received the automatic holding line; the missed-reply sweep stood down by design. The owner topped up at ~08:00; **08:04 UTC `replies: ok`** (a completed turn cleared the state); the sweep then answered the waiting threads: gated replies 2 → 5 (+1 soft rewrite) between 08:05 and 08:09, flat after — the backlog cleared in five minutes, nothing held. No code change. The two evaluation runs in flight at the wall are recorded as VOID / partial in BENCHMARK_RESULTS |
| Production after 64b4b0e (08:08 UTC, 7 Nov) | `/api/health` from outside | status ok, version 64b4b0e (main's head; docs only), replies ok, outreach shadow |
| Production after b0e9eec (06:48 UTC, 7 Nov) | `/api/health` from outside | status ok, version b0e9eec, replies ok, outreach shadow — the `availability_claim` soft finding and the sharpened availability note are live |
| Full API suite on 86e03a1 (slice 9c: the `availability_claim` finding, the availability tool's note) | `pytest tests` with Postgres and redis, alone on the services | **3,374 passed, 1 xpassed, 0 failed** (9 min 31 s) |
| CI on 86e03a1 (PR #338, merged as b0e9eec) | GitHub Actions | green at attempt 1 |
| CI on 2f8661c (PR #336, merged as 19e4952) | GitHub Actions | green at attempt 1 (the database job now runs `tests/test_eval_runner_db.py`) |
| Production after 19e4952 (06:09 UTC, 7 Nov) | `/api/health` from outside | status ok, version 19e4952, replies ok, outreach shadow — slice 9b is an evaluation-runner change only; no live path moved |
| Production after 420b5fc (05:13 UTC, 7 Nov) | `/api/health` from outside | status ok, version 420b5fc, replies ok, outreach shadow — the container ran `alembic upgrade head` at start, so the `interceptaction` enum should now carry `flag` and `escalated`; the direct psql check is the owner's (OWNER_ACTIONS §4), the behavioural check is eval run 42341837242 (safety file, readable) |
| Production after 369e4b6 (02:18 UTC, 7 Nov) | `/api/health` from outside | status ok, replies ok, outreach shadow — slices 1–8c live |
| Production after ee1fe26 (~00:16 UTC, 7 Nov) | `/api/health` from outside | status ok, replies ok, outreach shadow (planned 39, needs_approval 598, unknown 0); review tallies reset for the new day |
| Production after df50f2f (~22:46 UTC) | `/api/health` from outside | status ok, replies ok, outreach shadow (planned 39, needs_approval 598, unknown 0) |
| Production after 09c80da (~21:58 UTC) | `/api/health` from outside | status ok, replies ok, outreach shadow (planned 39, needs_approval 598, unknown 0). The day's review tallies (passed 162 / rewritten 90 / soft 100 / held 3) include the owner's box evaluation run, which composes replies inside the same api container — 6 Nov production tallies are contaminated from ~21:00 UTC on |
| Production after c6455d8 (~20:27 UTC) | `/api/health` from outside | status ok, replies ok, outreach shadow with no enforced rules |
| Production after d084e91 (~19:55 UTC) | `/api/health` from outside | status ok, replies ok, review tallies populated, outreach shadow with no enforced rules |
| Production after 34d371e (~19:22 UTC) | `/api/health` from outside | status ok, replies ok, review tallies populated, outreach shadow with no enforced rules |
| Production after c8c3356 (~17:52 UTC) | `/api/health` from outside | status ok, replies ok, review tallies populated, outreach shadow with no enforced rules |
| Web | `pnpm exec tsc --noEmit` + `pnpm build` | passed (agent report) |
| Lint | `ruff check app tests` | 96 findings = the committed baseline (CI ratchet 115) |

## 2. Customer protections — checklist

| Protection | Before | After | Evidence |
|---|---|---|---|
| Opt-out honoured by every unprompted sender | yes (Stage 7) | yes, plus the sweeper's bridge | `test_outreach_stage1` opt-out test; `test_intelligence_w1_fail_closed` |
| Opt-out recognised at the door | WhatsApp only | WhatsApp, Messenger, Instagram, TikTok (relay + native via `schedule_meta_reply`), web chat | same |
| Opt-out never recorded from "stop sending the trays" | **recorded wrongly** | not recorded | `test_intelligence_floors` negatives |
| Held reply never sent | yes, unless the gate raised | yes, including when the gate raises | `test_held_reply_to_human_db`, `test_intelligence_w1_fail_closed` |
| Money figures only from hub rows | yes | yes (unchanged `figure` rule) | `test_price_truth`, `test_exact_prices`, `test_verification_stress` |
| Payment claim never thanked for | prompt + soft rule | hard rule | `test_intelligence_w1_grounding`, `test_official_payment_lines` unchanged |
| No manufactured urgency | prompt only | hard rule (urgency/scarcity words) | `test_intelligence_w1_grounding`; campaign replies still pass (`test_verification_stress` offer/percent-only) |
| A colleague is never talked over | re-check before send (fail-open) | re-check fails closed on DB errors; programming errors assume AI with a warning | `test_intelligence_w1_fail_closed` |
| Unknown delivery never resent | yes | yes (unchanged) | `test_outreach_stage1/6` |
| Promised discount honoured or surfaced | silently dropped on redis error | surfaced on the order note and to the model | `test_promotions` unchanged; source test |
| Language of the customer | soft model rule | plus a deterministic soft rule, narrowed to English-reading drafts | `test_intelligence_w2_w7`; `test_swahili_voice` unchanged |
| Hold states, team checks, paid-claim notes | yes | yes; team check survives the scribe; hold lifts on return | `test_outreach_stage3`, `test_deals`, `test_intelligence_w2_w7` |
| Outreach shadow mode, per-rule enforcement, backlog | unchanged | unchanged | `test_outreach_stage2/5/6` |
| Android / iOS contracts | — | no endpoint response shape changed; one endpoint added (`/admin/performance`) | G inventory shared-endpoint list |
| Database | — | no migration | `alembic` head unchanged |

## 3. Behaviour changes a person should know about

- A bare closer now gets silence from the model path too (the prompt says so; the loop honours an empty reply).
- Customers who write "contact me on Thursday", "let me revert", "Approved, send invoice", "Paid." are now read by the floor; holds and paid-claim notes will appear in more threads than before.
- The gate can now hold a reply because of a gate error; the colleague sees "reply gate could not run" in the flag.
- One fleet-wide prompt cache rewrite on first deploy (block 0 changed).

## 4. Known regression risks (open)

- The floor's wider readings fire on more messages; false positives on held-out were inspected but production phrasing is wider than the case set (watch the Pacing/Activity panels after deploy).
- The `pressure` and `language` rules were narrowed after the stress tests; the real-model run should confirm no false holds remain (`failure_kinds` in the run record).
