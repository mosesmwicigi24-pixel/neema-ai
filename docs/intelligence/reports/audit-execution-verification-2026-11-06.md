# Audit execution verification — 2026-11-06

**Scope of this check.** The two audit instructions of 2026-11-05 (the first brief at 15:25 UTC, the read-only expansion at 22:00 UTC) and the implementation brief at 22:18 UTC. All three were retrieved verbatim from this session's transcript on disk
(`/root/.claude/projects/-home-user-neema-ai/2c406dec-643d-5176-808d-0adf5b06cc5b.jsonl`, 8,208 records, intact from 2026-10-27) and saved beside this report
(`verify/audit-prompt-1.txt`, `verify/audit-prompt-2-expansion.txt`, `verify/implementation-brief.txt`). The audit reports as delivered are on disk unchanged since their write times (`outreach-audit-2026-11-05.md`, 15:34; `outreach-audit-expanded-2026-11-05.md`, 22:08).

**Method.** (1) Every tool call made between 15:25:44 and 22:18:31 UTC was extracted from the transcript (`verify/audit-window-inventory.json`): 61 calls — 57 Bash inspections, 2 scratchpad Writes (the two reports), 2 file sends, 0 Read/Grep tool calls, 0 subagents, 0 edits to the repository. (2) Each requirement below is matched to those calls, to the report text, and, where the gap could be closed safely now, to a fresh read-only check made today (marked **today**). (3) Nothing was modified for this verification: no file, no commit, no deploy, no configuration. The test runs below used the local scratch Postgres only.

A caution the owner should weigh first: the audit and the verification were done by the same agent. Where I could, I checked the transcript rather than my memory; where the transcript is the only witness, I say so.

---

## A. Original instruction compliance matrix

Status key: **COMPLETE** = executed with evidence · **PARTIAL** = executed in part · **NOT VERIFIED** = concluded without sufficient evidence · **N/A** = does not apply to this codebase · **NOT DONE**.

### A.1 First brief (15:25 UTC)

| # | Requirement | Status | Evidence / what was actually done | Outstanding |
|---|---|---|---|---|
| 1A | Judas: why multiple follow-up processes sent independently; failed to recognise a sent follow-up; promised day not respected | PARTIAL | Code mechanisms inspected and cited: `tools._schedule_check_in` (no upsert), `actions.upsert_follow_up` (deal rows only), `process_due` (sends every due row), the template branch (`_send_followup_template`), `cart_recovery` (health shows 5 sent that day). Report §2A says explicitly "I have no database access, so each screenshot message is attributed by its composition shape and the clock time of the path". | Attribution of each screenshot message to a path is a reconstruction from code + screenshot, **not** from logs or `agent_actions` rows. Listed as unverified in the expanded report §8.2. Still outstanding: run `python -m app.jobs.outreach_backlog` / `outreach_trace` on the box for the three numbers. |
| 1B | Willy: why the stated intention did not influence follow-up | COMPLETE (mechanism) / NOT VERIFIED (attribution) | Detectors inspected: `declines.customer_declined`, `deals.detect_customer_promise`, `runtime.is_closer`, `reengage.why_not` — run live in the audit window with a Python snippet (22:02:24) on the seven statements; "needs time" had no detector. The 08:20 message was matched word-for-word to `quote_followup.compose`; the 15:20 one to the re-engage composer. | Which path sent the 15:20 message is a code-shape match, not a log line. |
| 1C | Pastor Emmanuel: multiple paths; closing while availability pending | COMPLETE (mechanism) | `reengage.py` note exclusion (:268), handoff regex languages (:106), `thread_language` (:126); prompt lines 1358–1366 and 1664–1680 read; `check_availability` tool read (tools.py 2174–2245: leaves a note, no state). | Same attribution caveat. |
| 1D | Raw template rows: why; were they delivered | PARTIAL | Marker text located (`actions.py:149`), parameter regex (`[Oo]rder\s+(\w+)`), `save_outbound_message(waba_msg_id=…)` and `finish("sent")` semantics read; two other marker-writing senders found (`hub_events._celebrate`, `seasonal_outreach`). | "Delivered" was inferred from the acceptance semantics (a wamid is stored only when Meta accepted). Delivery receipts were not stored at the time; no record was read. NOT VERIFIED that the customer received the template. |
| 2 | Audit the implementation before changing: scheduling, cron/queues, n8n/Laravel, history, suppression, dispatch, rate limits, time zones, prompt hierarchy, multilingual, templates, cancelling replies | PARTIAL | Inspected (per the command log): `actions.py` (whole), `quote_followup.py` (whole), `hub_events.py` (selected), `reengage.py` (whole, in three reads), `cart_recovery.py`, `payment_followup.py`, `recovery_jobs.py` (whole), `deals.py`, `tools.py` (check-in, availability, follow-up), `prompt.py` (check-in, availability, greeting, precedence, paid, pacing blocks; structure by headers; rule-family counts), `runtime.py` (history loading, live-message append, `_run_and_send`, hold line, echo guard, closer, meta burst), `wa_native.py` (debounce, dedup, statuses), `messaging.py` (send, template, timestamps, timeout), `whatsapp_webhook.py` (statuses), `models/agent_action.py`, `models/deal.py`, `models/message.py`, `config.py` (follow-up/quiet/recovery settings), `admin.py` (team-answer, invite/follow-up template, approve), `conversation.py` (human sends vs pending rows), `reply_sweeper.py`, `declines.py`, `cassock_ladder.py`, `lead_signals.py`, `cooling.py`, `auto_release.py`, `main.py` (loops, locks, boot migrations), `docker-compose*.yml`, `Dockerfile` (workers), alembic heads, live `/api/health` (GET). | **n8n**: not inspected in the audit window — it had been removed from the repository that morning (PR #309); 8 remaining mentions today are the hub-bridge alias and comments (`main.py`, `self_qa.py`, `hub_bridge.py`, `config.py`), **today**. **Laravel**: N/A — there is no Laravel code in this repository; the hub is an external system I cannot read. **Time-zone handling**: read for `schedule_check_in` (Nairobi day maths) and quiet hours; not audited across every sender. **Queues/workers**: uvicorn `--workers 2` and the redis leader locks were read; there is no separate queue system. |
| 3A–C | Behavioural rules (one coordinated decision; intervals; respect intentions) | COMPLETE as design in the audit; implemented later in Stages 1–3 | Design in report §4 (first) and §3–§6 (expanded). | The brief's 48–72 h defaults were **not** implemented: superseded by the owner's decision 1 (no manufactured follow-ups; follow WhatsApp policy). The quote nudge stays at 4 h inside the window; "after two unanswered follow-ups pause" is enforced only for deal-bound rows (`needs_approval` counts `sent` rows per deal, `MAX_AUTO_NUDGES=2`; check-in rows carry `deal_id=None`, **today**) plus the Stage 2 one-per-day cap in shadow. PARTIAL. |
| 4 | Make conversations human (greetings, repetition, language, brevity) | PARTIAL | Repeated-greeting cause found (composed follow-ups run the live prompt's clock rule); language detectors inventoried. Implemented later: continuation note, greeting strip, stored language, precedence line. | "Appropriate response length, emotions, natural follow-up" were **not tested against real replies**; only prompt text and code paths. See §C. |
| 5 | Context-aware evaluation before any outbound; application-level controls | COMPLETE as design; implemented in Stage 2 (`decide()`, safety rules) | Report §4A/§6.1. | — |
| 6 | Protect existing functionality; trace the lifecycle; root causes; conflicts; no unnecessary migrations | PARTIAL | Lifecycle traced on paper (expanded §1.3 diagram); conflict report delivered (first §3, expanded §5). Migration decision argued (expanded §3.3: index justified, column avoided by using JSONB). | "Preserve working functionality" was verified by the existing suite only (3,048 tests green on the final tree), not by replaying production threads. |
| 7 | Automated tests for the eleven scenarios | PARTIAL — see §E table | 9 of 11 scenarios have an executed test today; "quotation updated after a follow-up was scheduled" relies on pre-existing `quote_followup` tests I reviewed but did not write; "scheduled job retried after a timeout" is covered for the unknown-outcome case, not for a generic job timeout. | — |
| 8.1 | Root-cause analysis with code references | COMPLETE (code) / NOT VERIFIED (runtime) | Expanded §8.1 lists ten causes with file:line. | Runtime confirmation needs the box. |
| 8.2 | Conflict report | COMPLETE | First §3, expanded §5. | — |
| 8.3 | Correction plan before implementing | COMPLETE | Expanded §6 and §8.7; owner approved. | — |
| 8.4 | Implementation without breaking functionality | COMPLETE (within tests) | Stages 1–6 merged; CI and full suite green at each merge. | Production behaviour on day 0 not yet observed beyond health counters. |
| 8.5 | Validation that the screenshot scenarios no longer repeat | PARTIAL | Judas, Willy, Pastor Emmanuel reconstructed as Postgres fixtures (`test_outreach_stage1_db.py`, `test_outreach_stage3_db.py`) and pass. | These are reconstructions from the screenshots, not replays of the real rows. |
| 8.6 | Monitoring of follow-up decisions | COMPLETE | `outreach_log.decision()` lines, row stamps, trace CLI, standup line, `/api/health → outreach` (live today). | — |

### A.2 Expansion (22:00 UTC, read-only)

| # | Requirement | Status | Evidence | Outstanding |
|---|---|---|---|---|
| 1 | Complete messaging architecture incl. the live turn, retries, webhooks, manual paths, overlaps; who has authority | PARTIAL | 17-row table (expanded §1.1), interaction diagram, retry/duplicate table (§1.4) with verdicts from read code: wamid dedup, leader locks, `claim()` UPDATE, `_recover_interrupted`, 5 s default timeout (verified by executing `httpx.AsyncClient().timeout`), Meta-timestamped inbound + history re-append. | **Pathways missed by the 17** (found **today**, see §B.3): comment engagement (public reply + private DM), web-chat replies, TikTok/ManyChat replies, the order-confirmation relay, call-permission interactive messages, tool-sent product cards/photos inside a turn, the opt-out acknowledgement (added by me in Stage 1). |
| 2 | Conversation intelligence on seven statements | COMPLETE | Detectors executed in-process on each statement (22:02:24); table in expanded §2.2. | The model's own understanding in a live turn was not exercised (no model calls in the audit). |
| 3 | Review the ledger critically: concurrency, consistency, idempotency, retries, acknowledgments, stale responses; migrations | COMPLETE | Expanded §3 with seven findings; led to the index migration and status recording. | — |
| 4 | Design around customer experience, classes of message | COMPLETE | Expanded §4.1/§4.2. | One deviation in Stage 1: a care row (fit check, payment reminder) merged behind a promise in the same tick is deferred to the next morning rather than sent at once; hub order updates are unaffected (they do not pass through the dispatcher). Documented in the Stage 1 report. |
| 5 | Duplicated and conflicting intelligence; resolve precedence | COMPLETE (analysis) / PARTIAL (resolution) | Expanded §5 table; rule-family counts (12 greeting, 9 language, 7 one-question, …) obtained by grep. | Resolution added one precedence rank (Stage 3) and did not remove the repeated rules; the Stage 3 report states this as a deviation from "remove rather than add". |
| 6 | One coherent decision/dispatch architecture | COMPLETE | Expanded §6; implemented Stages 2–3. | — |
| 7 | Test the experience: the three cases + takeover, simultaneous, duplicate scheduling, failed dispatch, language switch, opt-out, completed purchase, order updates | PARTIAL | Scenario table expanded §7 (what Neema should do/say/why). Executed tests: see §E. | "What it should say" was not evaluated by running the model; the words in §7 are my proposals. |
| 8 | Evidence-based proposal: confirmed causes, unverified hypotheses, precedence, architecture, CX, risks, tests, migrations, rollback, sequence | COMPLETE | Expanded §8.1–§8.7; the unverified list (§8.2) was stated at the time. | §8.2 items remain open (box access). |
| — | Owner decisions 1–3 | COMPLETE | Decision 1: no timer-driven first follow-up; decision 2: re-engage retired (Stage 2, module and tests deleted); decision 3: replenishment template never for a deciding customer (registry purposes). | — |
| — | Read-only during the expansion | COMPLETE | No commits 15:00–22:30 UTC on any branch (`git log --all --since/--until`, **today**); the 57 commands are `cat/sed -n/grep/ls/wc/awk`, `curl` GET of the public health endpoint, `python -c` importing modules and running pure detector functions, `alembic heads`. No pytest, no DB session, no writes to the repository. | — |

### A.3 Implementation brief (22:18 UTC) — execution status by stage

| Stage | Required | Delivered | Evidence |
|---|---|---|---|
| 1 A–G | duplicate commitments; duplicate live replies; uncertain send outcomes + statuses; template registry; repeated greetings; availability as state; opt-out | All seven | commits fcdd760…58cd89f; 35 unit + 6 Postgres tests; CI green 58cd89f |
| 2 | consolidation on `agent_actions`/`process_due`, reliable identity | Yes (semantic `dedupe_key`, partial unique index, migration verified on a scratch DB) | 731fa82, 6966080, 55c2658; 13 + 5 tests; CI green |
| 3 | state extraction, preferences, commitments, context-aware decisions, prompt precedence | Yes; prompt duplicates kept (see A.2 §5) | aa2b5a2; 51 + 5 tests; CI green |
| 4 | shadow verification without extra messages | Running: read-out live (213af6e), daily task scheduled, log started; day-0 tallies empty | `/api/health → outreach` today; `stage4-shadow-log.md` |
| 5 | controlled rollout: flags, monitoring, rollback; deploy/config need approval | Dashboard control (4bec7a6); every deploy merged on the owner's explicit words ("Merge and deploy, keep shadow for a week"; the #311 question answered "Yes"; "Commit and Merge and build when green"; "Merge and build") | transcript timestamps 05:36, 06:19–06:22, 07:19, 07:56 UTC |
| Per-stage deliverables | files/functions, root causes, decisions, tests, limitations, CX impact, migration/rollback, approvals | Stage 1, 2, 3, 5–6 reports delivered; Stage 4 summary due day 7 | scratchpad reports |

---

## B. Actual inspection inventory

### B.1 Audit window (from the transcript's 57 commands)
`apps/api/app/`: `services/actions.py` (full), `services/quote_followup.py` (full), `services/hub_events.py` (:70–100, :150–170, :173–300, :380–406, :455–566), `services/deals.py` (:20–130, :184–252), `services/recovery_jobs.py` (full), `services/messaging.py` (send/template/timestamp/timeout/save sections), `services/wa_native.py` (:40–80, :360–440, :470–625), `services/reply_sweeper.py` (sweep), `services/declines.py`, `services/cassock_ladder.py`, `services/lead_signals.py`, `services/auto_release.py`, `services/conversation.py` (grep for action handling), `agent/runtime.py` (history, live append, `_run_and_send`, hold line, echo, closer, meta burst, `_is_echo`), `agent/tools.py` (check-in, availability, follow-up, tool names), `agent/prompt.py` (headers; check-in, availability, greeting, precedence, paid, pacing, opt-out blocks), `agent/cooling.py`, `agent/domain.py` (grep), `jobs/reengage.py` (full), `jobs/cart_recovery.py` (:1–200), `jobs/payment_followup.py` (:1–50, :60–200), `jobs/seasonal_outreach.py` (grep), `models/agent_action.py` (full), `models/deal.py`, `models/message.py` (columns), `core/config.py` (grep), `routers/admin.py` (:1760–1800, :2885–2930, approve), `routers/whatsapp_webhook.py` (:236–250), `routers/meta_webhook.py` (grep), `main.py` (loops/locks/boot statements), `Dockerfile`, `docker-compose.yml`, `docker-compose.vps.yml`, `alembic heads`, `tests/_action_fakes.py`, `tests/test_actions.py` (names). Live: `GET /api/health` twice. Executed in-process: `customer_declined`, `detect_customer_promise`, `detect_own_promise`, `is_closer`, `is_handoff_line`, `thread_language` on the seven statements; `httpx.AsyncClient().timeout`.

### B.2 Not inspected in the audit window (relevant)
`routers/web_chat.py`, `routers/manychat.py`, `routers/tiktok_webhook.py`, `services/tiktok_native.py`, `services/meta_send.py` (comment replies), `runtime._run_comment_engage`, `services/missed_call.py` / `recording_notice.py` (listed from names only), `services/unclaimed.py` (named, not read), `services/wa_calling.py` (call-permission messages), `messaging._relay_order_confirmation`, `services/post_catalog.sweep_page_posts`, `tools._send_product_cards` (media sends), `agent/llm.py` (prompt caching), `services/copilot.py`, the Android app, the web app, the hub, the box's `.env`, the database, the logs.

### B.3 Closed today (read-only)
- **Send pathways not in the 17**, with how they are guarded:
  1. Comment engagement (`runtime._run_comment_engage` → `meta_send.reply_to_comment` / `send_private_reply`): a public reply and a private DM per new comment; deduped on the comment id upstream; not subject to the dispatcher (it is a reply to the customer's own comment). Not examined in the audit.
  2. Web-chat (`routers/web_chat.py`): `run_turn` with the full prompt; the reply travels in the HTTP response; no scheduler reaches it. Not examined.
  3. ManyChat/TikTok (`routers/manychat.py`, `routers/tiktok_webhook.py` → `schedule_meta_reply` → `tiktok_native.send_to_user`): live replies; no inbound row id is passed on TikTok (Stage 6 parity covers Messenger/Instagram only). Not examined.
  4. Order-confirmation relay (`messaging._relay_order_confirmation`, called once after a hub order is created, :924): transactional, one per order creation. Not examined; not stamped by `outreach_log`.
  5. Call-permission request (`wa_calling.request_call_permission*`, `messenger_calling.request_call_permission`): interactive messages sent by a person from the admin calls screen (`admin.py:3740–3812`). Human-initiated; not examined.
  6. Tool-sent product cards and photos inside a live turn (`tools.py:2824–2872`, `messaging` interactive product card :250–330): extra messages within one turn. Within L1/L2 but not individually examined.
  7. `wa_native._mark_read_and_typing`: a `/messages` POST that is a read receipt + typing indicator, not a message. Correctly not a pathway.
  8. `post_catalog.sweep_page_posts`: a `client.get` of the page's posts (reads, does not post). Not a pathway.
- **Database constraints** (**today**): the only uniqueness on messaging tables is `conversations(channel, external_id)`, `conversations.wa_id`, and the Stage 2 partial unique index on open `agent_actions`; `messages.waba_msg_id` is **not** unique (duplicate webhook rows are prevented by the redis wamid guard, not the database). No triggers in any migration.
- **Prompt assembly** (**today**): `build_system_prompt(country_iso="KE", currency="KES")` yields 95,313 characters (≈24k tokens); the system text is sent whole with prompt caching (`llm.py:116–120`), no truncation found in `runtime.py`/`llm.py`/`prompt.py`. Dynamic injections and caps: standing orders 600 chars + learned rules (1,800 combined cap, `prompt.py:216`), house voice (uncapped text from the settings table), deal guidance 400 chars, per-turn notes (overlap, verifier verdict, pacing, FX, link preview, customer state, product-image, refer, memory context, length and said-once notes). Precedence block read: money → brevity → complaint → answer first → what they said → discovery/close → extras.
- **Loops and locks** (**today**): seven background loops in `main.py` (meta enrich 900 s, transcript recovery 300 s, missed-reply 120 s, auto-release 300 s, unclaimed 300 s, hub deferred, actions 60 s, recovery) each under a redis `SET NX` tick/leader key; `actions.claim()` is a conditional `UPDATE … WHERE status IN (…)` + commit; 40 `nx=True` guard sites inventoried.
- **Production configuration readable from here** (**today**): `recovery_jobs.dry_run=false`; payment follow-up enabled at 10:00 NBO (0 planned today, 3 on 5 Nov); cart recovery enabled at 11:00 NBO (today: 6 candidates, 3 planned, 3 skipped — "sent" in that counter now means "planned", `cart_recovery.py:244`); outreach mode shadow, no rules enforced; 36 planned, 597 parked (by reason/age/kind as reported). The box `.env`, template approvals and model settings are not readable from here.

---

## C. Evidence validation

| Finding (as reported) | Basis | Class |
|---|---|---|
| `schedule_check_in` inserted a row per call; prompt asks for the call repeatedly | code read (`tools.py`, `prompt.py` lines) | inspected code |
| deal-less rows escaped coalescing and the nudge count | code read; **re-checked today**: `needs_approval` still counts per `deal_id` | inspected code |
| replenishment template with regex parameters; marker stored | code read | inspected code |
| three sweeps + actions loop never consult each other; all enabled in send mode | code read + live health | inspected code + runtime record |
| stated intentions not detected | detectors **executed** on the statements | reproducible (re-run possible) |
| re-engage ignored notes and non-sw/fr languages | code read (`reengage.py`, deleted in Stage 2; verified from git history) | inspected code |
| double replies: Meta timestamp + history re-append | code read (`messaging.py:575`, `runtime.py:1817–1820`) | inspected code; **runtime occurrence not proven** |
| 5 s default timeout + retry → duplicate risk | `httpx` default executed; retry path read | inspected code + executed check |
| no opt-out handling | grep across `app/` | inspected code |
| composed follow-ups greet again | code read (`prompt.py:496`, `actions.py:156`) | inspected code |
| the template was delivered to Judas | inferred from wamid semantics | **NOT VERIFIED** |
| the 11:00 Judas message was cart recovery; the 15:20 Willy/Emmanuel messages were re-engage | composition shape + health counts | **NOT VERIFIED** (plausible, unproven) |
| migration applies safely on the box | scratch-DB dry run; the API boots only after `alembic upgrade head` (`Dockerfile:48`) and the box is healthy on 5582965 | inspected code + runtime signal; the actual box log not read |

## D. Unverified assumptions (reclassified)

1. Functions assumed working: `_still_ai`, `_is_echo`, `claim()`, `_recover_interrupted`, the sweeper's 3-strike escalation — read in code, covered by pre-existing tests (`test_one_turn_at_a_time.py`, `test_holds_reach_a_person_db.py`, `test_hold_line_sweep_db.py`) that I reviewed by name only. NOT VERIFIED by me beyond the suite passing.
2. Previous fixes accepted: PR #308 in-flight lock, PR #305–#307 holder rules, PR #309 n8n removal — accepted from the repository state; not re-tested individually.
3. Database safeguards: the unique index — VERIFIED on a scratch DB and in CI's fresh-DB replay; its presence on the production database is inferred from a healthy boot, not read.
4. Prompt instructions assumed active: the DB-stored standing orders, learned rules and house voice on the box — content unknown; could contradict the file-level prompt. NOT VERIFIED.
5. Branches assumed unreachable: none claimed.
6. Legacy implementations assumed disabled: re-engage — deleted, not merely disabled (VERIFIED by `git`); seasonal outreach — assumed manual/campaign; not re-read today. NOT VERIFIED.
7. Scheduled jobs assumed coordinated: now through one dispatcher for planners; the hourly jobs inside `actions_loop` (self-QA, stylebook, post sweep, standup) do not message customers (post sweep reads, VERIFIED today).
8. Retries assumed non-duplicating: unknown-outcome path tested on fakes and Postgres for WhatsApp and (Stage 6) Meta; the sweeper's whole-turn retry still relies on "latest row is inbound" — reviewed, not tested by me.
9. Tests assumed to cover the full journey: they do not run the model; every "what Neema says" is a fixture or a fake composer.
10. Production configuration assumed to match source: only what `/api/health` exposes is confirmed; `.env` not readable.

## E. Omitted work

### WHAT I FAILED TO VERIFY, OVERLOOKED, OR DID NOT COMPLETE

| Gap | What would close it |
|---|---|
| The three incidents were never reconstructed from logs or rows; every attribution is a code-shape match | On the box: `python -m app.jobs.outreach_trace 211985555188 --days 14` (and the other two numbers); `grep "tier2 replied" api.log` around the double-reply times; WhatsApp Manager for the approved body of `orderupdate_category` |
| Seven send pathways were absent from the 17-row inventory (B.3 items 1–6, plus the opt-out acknowledgement I added) | Done today at the inventory level; each still needs a safeguards review: comment engagement (opt-out/pause consult?), TikTok inbound ids (parity), order-confirmation relay stamping |
| Prompt compliance was read from files, not from a captured production prompt; DB-stored directives/learned rules/house voice unknown | Read the three `app_settings` rows on the box (admin UI shows directives); capture one assembled system prompt from a staging turn |
| Conversational quality (length, emotion, language continuity, silence) was not tested by running the model | A replay of `agent_eval` scenarios on the box, or a staging run of the seven statements and the three threads with real model calls, reviewed by a person |
| Brief §7: "quotation updated after a follow-up was scheduled" — relied on pre-existing `quote_followup` tests reviewed by name; "scheduled job retried after a timeout" — covered only for the unknown-outcome case | Write the two explicit tests |
| Brief §3B intervals (48–72 h, pause after two unanswered) — superseded by owner decision 1 for timing; the "pause after two" rule still counts deal-bound rows only | Owner decision: extend `MAX_AUTO_NUDGES` to count by conversation (would also count check-ins) or keep as is |
| Time-zone handling audited only for check-ins and quiet hours | Review every `+ timedelta(hours=3)` site (grep today: present in actions, customer_state, deals, cart_recovery, hub_events) for DST-free correctness — Nairobi has no DST, so the fixed offset is correct; not every site was read |
| Meta (Messenger/Instagram) path audited for the burst mechanism only; TikTok/ManyChat/web chat not audited at all | Read `tiktok_webhook.py`, `manychat.py`, `web_chat.py` for dedup, pause, opt-out and human-held handling |
| Delivery of templates and of day-0 production messages not observed | Delivery statuses are now recorded (`raw_meta.delivery`); the trace CLI reads them on the box |
| The Android app was not inspected (by instruction it was not to be modified; its reading of the new API fields is unknown) | Open the app's conversation list/inbox code if the owner wants the fields shown |
| Audit read-only compliance for the **local** environment cannot be proven to the last byte: the command log is the witness; no file hashes were taken before the audit | Accept the command log (57 read-only commands) as the evidence, or re-audit from a fresh clone |

## F. Read-only compliance

- **Audit window (15:25:44–22:18:31 UTC, 5 Nov):** 57 Bash commands, all of the forms `cat`, `sed -n`, `grep`, `awk`, `ls`, `wc`, `curl` (GET, public health endpoint), `python -c` importing modules and calling pure functions, `alembic heads`; two `Write` calls, both to the scratchpad reports; no `Edit`, no `git` write, no `pytest`, no database session. `git log --all` shows no commit between 09:53 (+0300, PR #309) and 22:45 UTC (first Stage 1 commit, 27 minutes after the implementation brief). Production untouched: the live version stayed fa177bb until 06:07 UTC on 6 Nov.
- **Limitation:** no pre-audit checksum baseline exists, so "nothing modified" rests on the command log and git, not on a byte-level comparison.
- **After the window:** every repository change was authorised by the implementation brief; every merge/deploy by an explicit owner message (quoted in A.3); configuration on the box was never changed by me (no access); one production setting was changed by code default only (`OUTREACH_MODE=shadow`), as approved.
- **This verification:** read-only. Test runs used the local scratch Postgres.

## G. Outstanding verification requirements

1. Box-side reconstruction of the three incidents (trace CLI, logs) — proves or disproves the attributions.
2. Read the three DB-stored prompt inputs on the box (standing orders, learned rules, house voice) and one assembled prompt.
3. Safeguard review of the seven additional pathways (B.3) — opt-out, pause, human-held, dedup, stamping.
4. Model-in-the-loop experience test (staging or agent_eval replay) for the seven statements and the three threads.
5. Two missing explicit tests (quote updated after planning; generic job timeout retry).
6. Owner decision on the "pause after two unanswered" rule's scope.
7. Day-1+ shadow tallies and the parked-pile retire decision (Stage 4 continues).

## H. Final verdict

**PARTIALLY VERIFIED.**

Counting the 31 applicable requirement rows in A.1–A.2 (A.3 is implementation, not audit): 17 COMPLETE, 12 PARTIAL, 2 N/A (Laravel; n8n already removed) — no row is NOT DONE. The denominator is the requirement rows of the two audit briefs as I split them above; the criterion for COMPLETE is a tool call in the transcript that accessed the named implementation plus a report statement traceable to it. The substantial gaps are the runtime proof of the three incidents (never available from here), the seven send pathways missing from the inventory, and the absence of any model-in-the-loop test of the conversational requirements. Nothing I found today contradicts a reported root cause; several reported attributions remain plausible rather than proven, and the reports said so at the time.
