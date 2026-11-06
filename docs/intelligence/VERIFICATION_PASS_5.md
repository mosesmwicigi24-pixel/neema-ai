# Verification pass 5 — slice 5 (branch `claude/where-are-we-bx9v9w`, commits `a5b4dc1`, `ccc5d52`)

Adversarial, independent. The diff, the new test file, the register text
(ADVANCEMENTS "Slice 5 (2026-11-06)", the struck UNFINISHED rows) and the
code comments were treated as claims, not facts. Line numbers are from the
working tree at `ccc5d52`. Commands from `/home/user/neema-ai/apps/api` with
`python` (3.11) and the CI env vars; the implementer's full-suite run was
left alone (targeted files only).

Baseline: the six touched test files **103 passed**. The implementer's
harness (`v5-mutate.py`) re-run: **12/12 killed**, as reported. My own
harness (`scratchpad/v5/v5-verify-mutate.py`, 16 mutants, each restored
byte-exact from the in-memory copy and asserted): **13 killed, 3 SURVIVED**.
Probes under `scratchpad/v5/` (read-only against the tree; one opened a
real Postgres session). No commits, no pushes; the only network use was
`gh run list` on the branch.

**Tree note.** The review started on 16 modified + 1 untracked files
(`scratchpad/v5/status-before.txt`). Mid-review the implementer committed
them (`a5b4dc1`, then `ccc5d52`: five more test worlds given an autouse
`opt_out_state → "no"` fixture and two more `**kw` fakes; no `app/` change),
so `git status --short` is now empty. I verified `git diff cfbfe88..HEAD --
apps/api/app` is byte-for-byte the diff reviewed here, and that every
mutant was restored (the harness asserts it). I changed nothing.

## Findings

| # | finding | severity | evidence | recommended fix |
|---|---|---|---|---|
| 1 | **The retry cut can drop the price the gate would otherwise have caught; "the same settlement the first draft gets" does not hold.** `_settle_truncated` re-asks when the dropped tail carries a figure, currency or `?` (`_ANSWER_MARK_RE`, `runtime.py:1622`). `_reply_in_words` cuts with no such guard (`:1418-1422`). Probe: retry `"The stole comes in blue and gold. It costs KES 4,"` + `max_tokens` → `'The stole comes in blue and gold.'` — the price is gone and the tail matched `_ANSWER_MARK_RE`. Before slice 5 the same retry went out as written: `money_figures("…KES 4,")` → `[4.0]`, a figure not in the facts, which the gate's figure check holds for a person; the cut sentence carries no figure, passes the rules-only path (`review.py:1586`), and the customer who asked the price gets no price with nobody told. The gate has an "unanswered" rule only for *where* (`review.py:767`). Rare (two ceiling hits in one turn) but it converts a held reply into a sent, wrong one. | **S2** | `runtime.py:1412-1422, 1610-1630`; probe `v5/probe-retry-figure.py`; `review.py:118, 767, 1586` | In `_reply_in_words`, apply the first draft's rule: cut only when `not _ANSWER_MARK_RE.search(dropped)`; otherwise keep as written (so the gate's figure check still sees it) and mark `turn_facts["truncation"]`. Pin with the probe's input. |
| 2 | **`classify` no longer stands the sweep down for a fleet-wide database or gate failure, so every waiting thread burns three strikes in ~15 min and is handed to a human with the wrong reason.** `ai_down` returns None for `database`/`gate` (`agent_health.py:69-73, 170`), so `sweep_missed_replies` no longer returns early (`reply_sweeper.py:361`) and, on `went=False`, no longer gives the strike back (`:492-499`); after `tries > 3` the thread is escalated with "delivery keeps failing … check the page connection" (`:459-470`). For a *persistent partial* failure — exactly the pass-3b case (a relation missing after a bad migration, a revoked table grant: the gate or the turn raises every pass) — this is the outcome the stand-down's own comment was written to prevent (`:353-357`: "three strikes in fifteen minutes and handing them to a person with the wrong reason"). Before, the text rules paused it for an hour by accident. The register says only that the pause is gone; the consequence is not analysed or tested. A full outage is unaffected (the sweep's own query fails first). | **S2** | `agent_health.py:69-73, 165-171`; `reply_sweeper.py:353-364, 459-470, 491-499`; probe `v5/probe-classify.py` (`OperationalError → database, AI_DOWN=False`) | Give the strike back for a fleet-wide kind without pausing an hour: in the sweeper check `kind in AI_DOWN or kind in ("database", "gate")` for the give-back/stop (a small `FLEET_DOWN` tuple in `agent_health`), and name the real reason in the escalation text. Test: a turn raising `OperationalError` three passes running must not escalate. |
| 3 | **"Every Neema-initiated sender treats unknown as do-not-send" is proven by source strings, not behaviour, for six of eight senders.** Only cart recovery and the dispatcher have a behaviour test with an unreadable preference. Dropping `fail_closed=True` at `hub_events._celebrate` (**V7**) and `missed_call._follow_up` (**V8**) is caught *only* by `test_every_unprompted_sender_reads_the_opt_out_fail_closed` (a `needle in getsource` check) — the same shape pass 3b flagged twice. A refactor that keeps the string but moves it after the send, or reads through a differently named wrapper, passes. Also: the seasonal / payment / missed-call / recording-notice reads sit inside `except Exception: pass` blocks that fall through to the send when the *surrounding* read (the conversation lookup, the session open) fails — `missed_call.py:70-83` sends on a conversation-lookup error (the send needs no DB); `payment_followup.py:278-285` plans on a session-open error (mitigated: the dispatcher re-reads). The slice claims one posture; these are a second. | **S2** | `tests/test_intelligence_slice5.py:109-128`; harness V7/V8 ("killed" by the string test only); `missed_call.py:70-83, 99`; `payment_followup.py:278-285`; `recording_notice.py:112-124` | One behaviour test per sender with a `_BrokenDB` session (the cart test is the template); in `missed_call`/`recording_notice`/`seasonal`, make the `except` *skip* the send (log "preference unreadable — not sent") instead of `pass`. |
| 4 | **The dispatcher's deferral is unbounded, invisible and leaves the shared session poisoned for the next row.** (a) `continue` at `actions.py:739` runs before the tries counter (`:791-794`), so an unreadable row is retried every 60 s forever with no "parked after 3 tries" hand-off; before the slice the same row burned a try per tick and parked for a person after three. Mutant **V2** (defer also re-dues the row to tomorrow) **survives**: the test pins `status`/`reason`, not `due_at`, so "stays due for the next tick" is not proven. (b) The defer is an `ol.decision` log line only (`outreach_log.py:46-51`), not a `_shadow_count` tally, so the shadow report never shows it. (c) In production the read fails *inside the dispatcher's own session*: probe on the real DB — a caught `ProgrammingError` leaves the session in `InFailedSQLTransactionError`; the next statement raises `DBAPIError`. `continue` skips the per-row `rollback` (`:1030-1035`), so the **next** row in the tick fails on its first query ("planned action N failed"), burns a try, and only then is the session rolled back. Up to `limit=10` rows can head-of-line block every tick if the failure is persistent and row-independent. | **S2** | `actions.py:731-739, 791-808, 1030-1035`; harness V2 SURVIVED; probe `v5/probe-session-poison.py` (`first: ProgrammingError → database; second: DBAPIError … InFailedSQLTransactionError`) | `await db.rollback()` (best-effort) before the `continue`; count the deferral (`_shadow_count(redis, "defer_unreadable")`); bound it (a redis counter, then `needs_approval` with "opt-out preference unreadable N ticks — a person decides"); assert `due_at` unchanged in the test. |
| 5 | **The comment flow has a second private-message path that bypasses the new gate.** `_private_complaint_message` (`runtime.py:3771-3783`) sends a DM to a commenter whose complaint grades serious/grave (`:6000-6003`) with no opt-out read at all. The register's S3 ("one helper the comment flow must pass before `send_private_reply`") and the stage-7 claim "the comment DM stands down for an opted-out contact" are true of the engage DM only. Pre-existing, not introduced here, but the slice declares the gate complete. | S3 | `runtime.py:3771-3783, 5996-6003`; `send_private_reply` callers: `:3779, 6174` | Route the complaint DM through `_comment_dm_allowed` (an opted-out complainer gets the public empathy line, which already handles `private_sent=False`). |
| 6 | The call site's log says "opted out" when the read merely failed. `_comment_dm_allowed` returns False for both, and `_run_comment_engage` logs `"comment DM skipped … : opted out"` (`:6177-6178`) for both; the helper's own warning precedes it, so the log reads as a contradiction. | S3 | `runtime.py:1385-1387, 6177-6178` | Return a reason (`"opted_out"`/`"unreadable"`/`None`) or log "not sent (opted out or unreadable)". |
| 7 | **The "door's predicate" accepts formatting the storage normaliser does not strip.** `is_plausible_phone("254 700-000 001")` → True (`phone.py:236-241`), so `record_opt_out` resolves `("whatsapp", "254 700-000 001")` verbatim (`intent.py:116-131`), while `_normalize_wa_id` strips only `+` and edge whitespace (`messaging.py:46-48`). The slice's own rationale is "a future caller" passing a non-digit key; a formatted one now mints a *second* person for the same phone, where before it stayed redis-only. Also the redis key is written on the raw `key` (`intent.py:173`: `agent:optout:whatsapp:+254…`) while the fast-path read uses `conv.wa_id` (`254…`) — the normalisation is applied to the resolver, not to the cache key. No caller passes either shape today (the WhatsApp door forwards Meta's digits). | S3 | probe: `'254 700-000 001' True`, `'+254 (700) 000.001' True`; `intent.py:116-131, 173`; `messaging.py:46-48` | Normalise with the same function the door stores with (`_normalize_wa_id` plus the formatting strip, or `to_e164`) and use the normalised key for the redis write too. |
| 8 | The "redis only" log line is untested (mutant **V11**, line removed, **survives**), and `_is_database_error`'s psycopg branches are untested (**V9** survives). Both are claims in the register ("a key that cannot resolve logs 'redis only'"; "asyncpg / psycopg"). | S3 | harness V9, V11 | A `caplog` assertion in the resolver test; one `_Err.__module__ = "psycopg.errors"` case. |
| 9 | Register hygiene: the slice was recorded VERIFIED COMPLETE and committed (`a5b4dc1`) while **twelve** CI tests were red (the second commit's own message; CI run 42300494146 `failure`); the fix commit's run (42301421291) was still `in_progress` at the time of this pass. `/api/health` reports `needs_a_human: False` for a `database` kind (`health.py:44`), which is right for the AI-key remedy but means an hour-long DB outage shows as not needing a human on that endpoint (the self-check still alerts at `count >= 3`). | S3 | `gh run list`; `ccc5d52` message; `routers/health.py:34-44` | Record the red run in the register; consider a `needs_a_human` that covers `database`. |
| 10 | CI: `timeout-minutes: 16` covers 3 × (150 + 150 + 5) = 915 s with 45 s to spare for three `dpkg --configure -a` runs, which carry no `timeout` of their own — a dpkg that really has a half-configured ffmpeg to finish can take longer than 15 s, in which case the third attempt is cut by the bound (still bounded, which was the point). YAML loads; both jobs changed identically. | S3 | `.github/workflows/ci.yml:66-76, 167-177` | `sudo timeout 60 dpkg --configure -a \|\| true`, or `timeout-minutes: 18`. |

## Claims

| claim | verdict |
|---|---|
| S1 — `classify` reads the exception type first; SQLAlchemy / asyncpg / psycopg → `database`, `RuntimeError("reply gate error…")` → `gate`; neither ACTIONABLE / AI_DOWN; operator lines added | **Holds.** Probe: `OperationalError("…password authentication failed")` → `database` (its `str()` still → `auth`); `PendingRollbackError`, pool `TimeoutError`, `InterfaceError`, raw `asyncpg.InsufficientPrivilegeError` → `database`; `ConnectionRefusedError` → `other` (unchanged). All five `record_turn_failure` callers pass the exception object, never its text. `_is_database_error` module split is right for `asyncpg.exceptions`, `psycopg.errors`, `psycopg2.errors`. **Caveat (finding 2):** the sweep consequence for a persistent partial failure is worse, not analysed. |
| S1 — "a DB outage can no longer … pause the missed-reply sweep" | **Holds**, and that is the problem (finding 2). |
| S2 — `opt_out_state` three-valued; `opted_out(fail_closed=…)`; every Neema-initiated sender fails closed; the dispatcher defers, never vetoes/parks on an unreadable read | **Holds with caveats.** All eight senders in the register are covered; no other Neema-initiated sender exists (grep of every `opted_out(`/`send_to_channel(` caller: the remaining ones are replies to an inbound — hold lines, the opt-out ack, `unclaimed._send`, the comment DM — or human/admin sends; `payment_followup` and `cart_recovery` plan rows the dispatcher re-reads). The doors (`web_chat.py:222`, `manychat.py:155`, `runtime._handle_opt_out:2936`) keep the fail-open default correctly (they only decide whether to re-acknowledge). The old fail-open was not load-bearing: `_select_identity` is a plain select, every sender passes a real `Conversation`, and a `None` identity is a readable "no" (`intent.py:208-209`; mutant V5 killed). Caveats: findings 3 (string-only proof; the surrounding `except: pass` blocks), 4 (deferral unbounded, untallied, session not rolled back; `due_at` not pinned). |
| S3 — `_comment_dm_allowed` extracted; the flow raises `_OptedOut` when it returns False; no other DM path bypasses it | **Holds for the engage DM** (`_OptedOut` defined at `:5880`, used at `:6173`; the helper's late imports see the test's `AsyncSessionLocal` patch; V6 and V16 killed). **Does not hold** for the complaint DM (finding 5). Log wording: finding 6. |
| S4 — `_reply_in_words` cuts a `max_tokens` retry with `trim_truncated`; the "kept" case matches `_settle_truncated` | **Holds with a caveat.** `trim_truncated` is a module-level def (`:1590`) resolved at call time. The two non-truncation call sites (`:2375` empty draft, `:2412` iterations exhausted) now also cut a ceiling-hit retry — consistent posture, not a regression. "Kept as written" matches `_settle_truncated`'s `how == "kept"`. The `_ANSWER_MARK_RE` guard is missing (finding 1). |
| S5 — `_can_resolve` uses `is_plausible_phone` on the `+`-stripped key; resolves with `rkey`; "redis only" logged only when pid None, db present, not resolvable | **Holds** for the four inputs claimed (17-digit id False, `web_…` False, `+254…` True and resolved as `254…`, matching `_normalize_wa_id`); the log guard at `intent.py:121` is exactly that conjunction. **Caveat:** formatted numbers mint a duplicate; the redis key is not normalised (finding 7); the log is untested (finding 8). |
| S6 — "Are you there?" has no `_BUY_RE` match; removing the `"?"` branch fails the test | **Holds.** `buying_signal("Are you there?")` → False; `buying_signal("Where is your shop?")` → True (the pass-4 test indeed exercised the buying branch, as the slice says); M6 killed in both harness runs. |
| S7 — 16 min + `dpkg --configure -a` per attempt, both jobs; YAML valid | **Holds** (finding 10 is a margin note). Register status IMPLEMENTED BUT NOT VERIFIED is the honest one. |
| Test edits are completions, not weakenings | **Holds.** Every edited test already replaced `opted_out` with a fake returning a constant, so none proved anything about the real read; adding `opt_out_state → "no"` beside it, or `**kw` to the fake, is faithful. `_action_world` previously reached "no" only because `_FakeDB.execute` raised `IndexError` inside the old fail-open `except` — the new `_select_identity → None` patch makes that an honest readable "no". The five autouse fixtures in `ccc5d52` patch files that never mention opt-out otherwise (grep). The W2-3 test rename states the truth the pass-4 name did not. |

## Mutation results

Implementer's harness (`v5-mutate.py`, slice-5 file only, `-k` per mutant), re-run by me:

| mutant | result |
|---|---|
| M6 `"?"` branch removed | KILLED |
| S1 type branch removed · S1b gate prefix removed | KILLED · KILLED |
| S2 unknown→defer removed | KILLED |
| S3 comment gate fail-open · S3b session error → True | KILLED · KILLED |
| S4 retry trim removed | KILLED |
| S5 isdigit back · S5b no normalisation | KILLED · KILLED |
| S6 unknown read as no · S6b fail_closed ignored · S7 cart wrapper → False | KILLED (4 tests) · KILLED (3) · KILLED |

Mine (`v5/v5-verify-mutate.py`; each mutant run against all six touched files, `-x`):

| mutant | killed by | result |
|---|---|---|
| V1 actions: defer `continue` removed (falls through to compose/send) | `test_the_dispatcher_defers_a_row…` | KILLED |
| V2 actions: defer also re-dues the row to tomorrow (`due_at = now + 1 day; commit`) | — | **SURVIVED** (finding 4) |
| V3 actions: defer claims the row to `needs_approval` | dispatcher test | KILLED |
| V4 intent: `db is None` reads as "no" | `test_an_unreadable_preference_is_unknown_not_no` | KILLED |
| V5 intent: no person at all reads as "unknown" (over-closed: no early-funnel contact would ever be messaged) | `test_a_readable_no_is_still_no_for_a_sender` | KILLED |
| V6 runtime: comment call site inverted (DM when NOT allowed) | string assertion in `test_the_comment_dm_gate…` | KILLED (string only) |
| V7 hub_events: `fail_closed=True` dropped at `_celebrate` | `test_every_unprompted_sender_reads_the_opt_out_fail_closed` | KILLED (string only — finding 3) |
| V8 missed_call: `fail_closed=True` dropped | same string test | KILLED (string only — finding 3) |
| V9 agent_health: psycopg modules dropped from the driver check | — | **SURVIVED** (finding 8) |
| V10 agent_health: every `Exception` is a database error (provider errors would never trip AI_DOWN) | `test_a_driver_error_counts_as_database_by_module` | KILLED |
| V11 intent: the "redis only" info line removed | — | **SURVIVED** (finding 8) |
| V12 cart_recovery: `fail_closed` dropped (wrapper's `except` still True) | string test (`test_cart_recovery_skips…` passes: the query-error half falls to `plan` which fails on the broken session, so `skipped` differs — but `-x` stopped at the string test first) | KILLED |
| V13 runtime: retry cut applied whatever the `stop_reason` | `test_the_once_more_draft_is_cut…` | KILLED |
| V14 intent: `opted_out` defaults to `fail_closed=True` (doors over-closed) | `test_an_unreadable_preference_is_unknown_not_no` | KILLED |
| V15 intent: resolver called with the raw key, not `rkey` | `test_the_opt_out_resolver_uses_the_door_s_phone_predicate` | KILLED |
| V16 runtime: `_comment_dm_allowed` ignores the read (always True on a readable answer) | `test_the_comment_dm_gate…` | KILLED |

## Probes (scratchpad `v5/`, read-only against the tree)

- `probe-session-poison.py` (real Postgres): `first: sqlalchemy.exc ProgrammingError → classify: database`; `second: DBAPIError → database | … InFailedSQLTransactionError: current transaction is aborted…` — a caught read error poisons the dispatcher's session (finding 4c).
- `probe-retry-figure.py`: `_reply_in_words("…It costs KES 4,", max_tokens)` → `'The stole comes in blue and gold.'`; `ANSWER mark in dropped tail: True` (finding 1).
- `probe-classify.py`: the table in claim S1; `str()` of a gate error still reads `auth` (no caller passes text).
- `is_plausible_phone` on nine inputs (finding 7).
- `buying_signal("Where is your shop?") → True`, `("Are you there?") → False` (claim S6).

## Verdict

Slice 5 does what its six register rows say at the line level — every one of the implementer's twelve mutants dies, the type-first classifier, the three-state read, the comment-DM helper, the retry cut, the phone predicate and the W2-3 proof all behave as described, and the test edits are honest completions — but two of its claims are weaker than stated in ways that matter for deployment. The retry cut can silently drop the price the gate used to hold (finding 1), and removing the accidental hour-long sweep pause means a persistent partial database or gate failure now hands every waiting thread to a human within fifteen minutes with a wrong reason (finding 2); both are one-line fixes with a clear test. The dispatcher's deferral needs a rollback before `continue`, a bound and a tally (finding 4), and six of the eight fail-closed senders are proven only by a source-string search (finding 3). **Safe to merge after findings 1, 2 and 4(c) are fixed** — they are small, local and testable; the rest can follow as a slice-5b row in UNFINISHED. It should not be recorded as VERIFIED COMPLETE while CI for `ccc5d52` is still in progress and the first commit's run was red.

---

## Implementer's response (2026-11-06, same day, commit after `ccc5d52`)

Every finding was taken as true until the code said otherwise; all ten are
acted on. Mutation harness `v5-mutate.py` extended to 24 mutants (the
original 12 plus P1–P8 below): **24 killed**. The slice-5 test file is now 21
tests.

| # | Finding | Response |
|---|---|---|
| 1 | The retry cut can drop the price the gate would hold (`_ANSWER_MARK_RE` guard missing) | **Fixed.** `_reply_in_words` cuts only when the dropped tail carries no figure, currency or question; otherwise the draft goes out as written for the gate to judge — the same settlement as `_settle_truncated`. `test_the_once_more_draft_is_kept_when_the_dropped_tail_carried_an_answer` uses the pass's own probe text; mutant P1 (guard removed) killed. |
| 2 | `database` / `gate` no longer stand the sweep down; every waiting thread escalated in ~15 min with the wrong reason | **Fixed.** Both kinds are now in `AI_DOWN` *and* `ACTIONABLE`: the sweep stands down, `/api/health` says a person is needed with the right operator line, and the next completed turn clears the state like the other actionable kinds (`record_turn_success`). `test_a_database_or_gate_failure_stands_the_sweep_down_and_needs_a_person` (ai_down, needs-a-human membership, clear-on-success); mutants P2/P2b killed. This reverses the slice's first posture, which had fixed the *wrong reason* but not the *stand-down*. |
| 3 | Six of eight senders proven by source strings; the surrounding `except Exception: pass` in missed-call / recording-notice / seasonal / payment falls through to a send on a surrounding read failure | **Fixed in code; partly fixed in evidence.** All four surrounding excepts now skip (return False / `OPTED_OUT` / drop the row / `skipped`) with a warning that names the cause. Behaviour tests: payment follow-up (both the read's own fail-closed and the no-session except; mutant P4 killed). Seasonal, missed-call and recording-notice are still asserted at source level (the except branch's first statement is the skip, not `pass`) because their entry points need a Call / season fixture; **recorded in UNFINISHED** as the remaining string-level evidence, with hub_events's `fail_closed` (V7) and missed_call's (V8). |
| 4 | The deferral is unbounded, untallied, invisible to the shadow report, and leaves the session aborted for the next row; V2 (re-due to tomorrow) survived | **Fixed.** The defer branch rolls the session back, counts the try on the same `actions:tries:{id}` key the send path uses, parks the row for a person after three ("opt-out preference could not be read for 3 ticks — needs a human"), and tallies `defer_optout_unreadable` / `park_optout_unreadable` in the shadow count. `test_the_dispatcher_s_deferral_is_counted_rolled_back_and_parks_after_three` pins `due_at` unchanged, the try count, the rollback call and the fourth-tick park; mutants P3 (rollback removed), P3b (not counted), P3c (= V2, re-dued) killed. |
| 5 | The complaint DM bypasses the gate | **Fixed.** `_private_complaint_message` is sent only when `_comment_dm_allowed(redis, channel, ext)` allows it; an opted-out or unreadable commenter gets the public line only. Source-level test (the call is inside the gate); mutant P5 killed. |
| 6 | "opted out" logged when the read merely failed | **Fixed.** The call site logs "opted out, or the preference could not be read"; the helper's own warning names which. |
| 7 | `is_plausible_phone` accepts formatting the storage normaliser does not strip → a second person; the redis key written on the raw `+` key | **Fixed.** The resolver key is the digits only (`+`, spaces, dashes, dots, parentheses removed) and the redis fast-path key is written on that same key for WhatsApp. `test_a_formatted_number_resolves_to_one_person_and_one_redis_key` ("+254 700-000 001" → one resolve on "254700000001", one key `agent:optout:whatsapp:254700000001`); mutants P6, P6b killed. |
| 8 | "redis only" log untested (V11); psycopg branches untested (V9) | **Fixed.** `caplog` assertion on the "redis only" line (P7 killed); `test_psycopg_errors_count_as_database_too` covers `psycopg.errors` and `psycopg2.errors` (P8 killed). |
| 9 | Recorded VERIFIED COMPLETE while CI was red; `needs_a_human` false for a database kind | **Recorded and fixed.** REGRESSION_SAFETY_REPORT now carries the red run 42300494146 (twelve test worlds that had never modelled the read; fixed in `ccc5d52`) and the slice's status in ADVANCEMENTS is restated as IMPLEMENTED BUT NOT VERIFIED until the suite and CI on the final head are green. `needs_a_human` is derived from ACTIONABLE, so a database kind now reads true (finding 2). |
| 10 | 45 s margin for three `dpkg --configure -a` runs | **Fixed.** `sudo timeout 60 dpkg --configure -a \|\| true` in both jobs (worst case 3 × 365 s = 1,095 s against the 16-minute = 960 s bound — the third attempt can still be cut, which is the bound doing its job; the first two complete). |

Mutation table, pass-5 repairs (harness `v5-mutate.py`, run after the fixes):

| mutant | result |
|---|---|
| P1 retry answer-guard removed | killed |
| P2 `database` out of AI_DOWN · P2b out of ACTIONABLE | killed · killed |
| P3 defer rollback removed · P3b not counted · P3c re-dued to tomorrow (V2) | killed · killed · killed |
| P4 payment surrounding except passes | killed |
| P5 complaint DM ungated | killed |
| P6 formatting not stripped · P6b redis on the raw key | killed · killed |
| P7 "redis only" log removed (V11) · P8 psycopg dropped (V9) | killed · killed |
| the original twelve (M6, S1–S7) | all killed |
