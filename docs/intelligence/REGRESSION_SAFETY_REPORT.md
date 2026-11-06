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
