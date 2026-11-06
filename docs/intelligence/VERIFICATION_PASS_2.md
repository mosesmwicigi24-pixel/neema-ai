# Verification pass 2 — slice 2 (branch `claude/where-are-we-bx9v9w` after main `c8c3356`)

Adversarial, independent. Code read and run; docs and commit messages not trusted.
Scope as briefed: the six claimed changes in commits `c8c3356..13e7cb8` (plus the
docs/results files). Note: the branch moved while this pass ran (`9c50c02`,
`22de88b`, `0a6745d` landed on top); those commits were NOT verified here beyond
checking they did not alter the in-scope code (they add `trim_truncated` and
memory changes in other hunks). Line numbers below are from the tree at `0a6745d`.

All commands run from `/home/user/neema-ai/apps/api` with the scratchpad venv
(`$V`) and `env.sh` sourced.

## Findings

| # | finding | severity | evidence | recommended fix |
|---|---|---|---|---|
| 1 | The model-in-the-loop runner can no longer reach the blind set at all. `eval_run.run_cases` calls `eval_cases.load()` (default sweep, blind excluded) and then filters with `--only <id prefix>`; `agent_eval --cases` offers only `--held-out/--dev/--only/--limit`, no `--file`. Before this slice, `--only blind-` selected the 120 blind cases; now it yields "no cases selected". The docs name the blind column as "the only number this programme claims as held-out" and call the dev/held-out split contaminated, yet the real-model baseline command in BENCHMARK_RESULTS.md line 171 (`agent_eval --cases --held-out`) can only score the contaminated split. | S2 | `app/jobs/eval_run.py:359` (`cases = eval_cases.load()`); `app/jobs/agent_eval.py` argparse (no `--file`); probe: `[c['id'] for c in eval_cases.load() if c['id'].startswith('blind-')]` → `[]`; `docs/intelligence/BENCHMARK_RESULTS.md:171` | Add `--file blind_heldout.jsonl` (or `--blind`) to `agent_eval --cases` → `run_cases(file=...)` → `eval_cases.load(file)`, mirroring `eval_floors --file`; update the documented real-model command to use it. |
| 2 | `eval_cases.load()` docstring says blind cases are scored "only when their file is named explicitly", but the rule implemented is `include_blind = pattern != "*.jsonl"`. Any other wildcard includes them: `load("*.json*")` → 573 cases, 120 blind; `load("[a-z]*.jsonl")` → 573/120; `load("blind*.jsonl")` → 120/120. `load("*.jsonl")` passed explicitly is consistent with the default (453/0). No current caller passes such patterns, so no leak today. | S3 | `app/jobs/eval_cases/__init__.py:72`; probe output above | `include_blind = not any(ch in pattern for ch in "*?[")` (a literal file name only), or require `include_blind=True` for any glob; add a test for `load("*.json*")`. |
| 3 | The comment-redelivery test cannot see the dedupe query's WHERE clause: `tests/test_meta_webhook._FakeDB.execute` returns `existing_mid` for any statement. Mutating the production query to compare the DM channel (`Message.channel == channel`, i.e. `"messenger"` instead of `"facebook"`) or to drop the `waba_msg_id` match entirely leaves the test green. The production SQL is in fact correct (see confirmed claims), but the test only proves "a non-None scalar skips the comment". | S3 | mutation M7b and M7c below: `SURVIVED (test passes)`; `tests/test_meta_webhook.py:48-49` | Have `_FakeDB.execute` record the statement and assert on the compiled WHERE (channel literal = `comment_channel`, `waba_msg_id = comment_id`), or compare `stmt.compile(literal_binds=True)` text in the new test. |
| 4 | DB-error semantics of the new dedupe query: an exception from `db.execute` propagates out of `_capture_comment_events`, is caught by the webhook handler's second `try/except`, logged, and the request is acked 200 — the comment is lost silently, NOT 502'd. This is the SAME contract as before the change (the first DB touch was `resolve_or_create_person` a few lines later, inside the same try/except), so no regression; but note the asymmetry the comment itself acknowledges: a DM capture failure 502s for redelivery, a comment capture failure is acked. Additionally the redis `nx` mark is set BEFORE the durable store, so a comment whose DB write fails is also skipped by the fast path for 7 days if Meta ever re-sent it. Both pre-existing. | S3 | `app/routers/meta_webhook.py:122-125` (handler), `:752-758` (redis mark before DB), `:765-770` (new query, no try/except) | If comment loss should match the DM door, raise/502 on comment capture failure too (and set the redis mark only after `db.commit()`); otherwise document that comments are at-most-once. |
| 5 | Instagram comments and Instagram DMs share `channel="instagram"`, so the dedupe `WHERE channel='instagram' AND waba_msg_id=<comment_id>` would also match a DM row whose `mid` equals the comment id. IG DM mids are opaque base64 strings and IG comment ids are numeric, so a collision is not realistic; Facebook comments (`"facebook"`) vs Messenger DMs (`"messenger"`) cannot collide at all. | S3 | `meta_webhook.py:739` (`comment_channel`), `:272-279` (DM dedupe), compiled SQL in confirmed claims | None required; if desired add `Message.direction == inbound` and/or a `comment_context IS NOT NULL` guard. |
| 6 | `messages.waba_msg_id` has no index (only `ix_messages_conversation_id_created_at`; no alembic `create_index` on it). The new comment dedupe adds one unindexed `SELECT … WHERE channel=… AND waba_msg_id=… LIMIT 1` per comment, on top of the existing identical DM dedupe. Fine at today's volume, a sequential scan per event as `messages` grows. | S3 | `app/models/message.py:35-36,51`; `grep -rn create_index.*waba_msg_id alembic/versions` → none | Add a migration `CREATE INDEX ix_messages_channel_waba_msg_id ON messages(channel, waba_msg_id)`. |
| 7 | One flaky observation, not a code defect: during the first combined run, `test_a_draft_cut_by_the_token_ceiling_ends_on_a_whole_sentence` (introduced in `22de88b`, which landed mid-pass) failed once; the test is pure and passed on every re-run (×7 orderings). The failure coincided with `runtime.py` being edited/committed concurrently in the working tree. | S3 | first run: `1 failed, 254 passed`; identical re-run: `255 passed` | None; re-run CI on the final tree. |
| 8 | `served_model()` now applies `str()` at the usage-logging call site where the old inline code passed the raw attribute (`getattr(llm, "last_model", None) or getattr(llm, "_model", None) or settings.tier2_model`). For the real `AnthropicLLM` both are `str` (`app/agent/llm.py:188,241`), so behaviour is identical; only a non-string fake would differ (none found in tests). | S3 | diff hunk at `runtime.py:2437`; `grep -rn "last_model\s*=" tests` → only string literals | None. |

## Claims confirmed (tried to break, could not)

**Claim 1 — the two runtime helpers change nothing.** Diffed `git show c8c3356:apps/api/app/agent/runtime.py` against `length_target_for` / `served_model`.
- `length_target_for`: old code called `_cs_floor(user_text)` with possibly `None`; new calls `_cs_floor(t)` with `""`. `customer_state.floor` does `" ".join((text or "").split())` and returns `None` for both (`customer_state.py:169-171`), so identical. `is_closer`, `_GREETING_RE.match`, `looks_negative` all received `user_text or ""` before and `t` now — identical. Same `try/except` wrapper at the call site (`runtime.py:2137-2146`); `_len_target` still `{}` on failure.
- `served_model` in `_gate_turn_reply` (`:1428`): old `str(getattr(llm,"last_model","") or getattr(llm,"_model","") or "")` vs new `str(getattr(..., None) or getattr(..., None) or "")` — `""` and `None` are both falsy in the `or` chain, so identical output for every input.
- `served_model` at usage logging (`:2437`): same fallback order (`last_model` → `_model` → `settings.tier2_model`); only `str()` coercion added (finding 8).

**Claim 2 — only the reply-length metric moves, and the before/after numbers are real.**
- `python -m app.jobs.eval_floors --all/--dev/--held-out` and `--file blind_heldout.jsonl` on the current tree reproduce every number in Correction 2's table exactly: all 453 cases, said 422/491, lang 342/355, opt_out 40/42, length_kind 677/1196; dev 214/228, 196/197, 11/12, 342/596; held-out 208/263, 146/158, 29/30, 335/600; blind 358/459, 414/445, 33/34, 221/459.
- The committed `docs/intelligence/results/floors-rescored-{all,dev,held-out,blind}.json` are equal to my runs in `metrics`, `misses` and `coverage` (Python `==` on the parsed dicts: all four `True`).
- "Before": monkeypatching `eval_floors._runtime_target` back to the old mirror (verbatim from `c8c3356`) and scoring the same case sets gives length_kind 657/1196, dev 328/596, held-out 329/600, blind 218/459 — exactly the "before" figures — and said/lang/opt_out unchanged (422/491, 342/355, 40/42 etc.). No other metric moves.
- "The published 'after' runs predate the blind file": `floors-after-*.json` were committed in `4365d3f` at 16:15:03Z with 430/203/227 cases; `blind_heldout.jsonl` first appears in `e9d2e19` at 17:03:51Z. Confirmed.

**Claim 3 — blind cases are out of the dev/held-out split.** `load()` → 453 cases, 0 blind; `split()` of that → no blind in either half. Callers: `eval_floors._cli` (`load(args.file)` only when `--file` is given, else `load()`), `eval_run.run_cases` (`load()`), `tests/test_intelligence_floors.py:174` (`load("developer_negatives.jsonl")`), `tests/test_eval_harness.py`. No caller reads `blind_heldout.jsonl` by any other path (`grep -rn blind_heldout app tests`). The duplicate-id check runs before the blind skip, so ids stay unique across both sets. Over-restriction rather than leakage is the only defect (finding 1); the wildcard inconsistency (finding 2) has no caller today. Explicit `load("*.jsonl")` behaves like the default.

**Claim 4 — the comment dedupe is correct.** Comment rows are stored with `channel=comment_channel` and `waba_msg_id=c["comment_id"]` (`meta_webhook.py:822-828`), and the new query uses the same `comment_channel` and `comment_id`. Compiled SQL captured by a recording fake DB, for `object=page` and `object=instagram` payloads respectively:
`SELECT messages.id FROM messages WHERE messages.channel = 'facebook' AND messages.waba_msg_id = 'c9' LIMIT 1` and
`… WHERE messages.channel = 'instagram' AND messages.waba_msg_id = 'c9' LIMIT 1`.
A legitimately new comment cannot be skipped: the only row that matches is one with the same comment id in the same channel, and `_parse_comment` only accepts `verb == "add"` (`:692-693`), so edits/removes never reach the query. Facebook comment ids live in `"facebook"`, Messenger mids in `"messenger"` — no cross-match. A DB error is acked exactly as before (finding 4).

**Claim 5 — the timing fixture intercepts the real path.** `settings.catalog_source` defaults to `"hub"` (`config.py:391`); `/api/health` → `price_audit.health_summary(redis=None)` (no cache) → `messaging.catalog_items` → `from app.core.hub_client import fetch_hub_catalog` executed at call time (`messaging.py:485-486`), so a module-attribute monkeypatch is what the import resolves. Empirical probe with `mock.patch.object(hub_client, "fetch_hub_catalog", stub)` → stub hit, warning "hub catalogue unavailable (stubbed) — serving local table this turn", fallback returned. Timing: with the fixture `tests/test_response_timing.py` runs in ~0.3 s; with the `monkeypatch.setattr` line removed (mutation M8) the same 4 tests take **9.51 s** in this sandbox (the hub host is unreachable here; 15 s timeout on a dropping host as the docstring says) and still pass here only because the proxy fails faster than the test's budget.

**Claim 6 — the new tests exercise production code.** See mutation table: every production mutation targeted by a new behaviour test was killed, including the subtler ones (lock taken but returned row ignored, M2c; lock failure no longer swallowed, M3; configured model preferred, M5; call site regressed to `settings.tier2_model`, M5b; harness back to the mirror, M9). `lock_for_write` is imported function-locally (`intent.py:111`, `customer_state.py:426`), so `monkeypatch.setattr(state_lock, "lock_for_write", …)` genuinely intercepts.

## Mutation-test results

Script: `/tmp/claude-0/-home-user-neema-ai/2c406dec-643d-5176-808d-0adf5b06cc5b/scratchpad/mutate.py` (mutate → run → reverse-replace restore → byte-equality and `git diff --quiet` check per file; all "restored | clean").

| mutation | file | test | result |
|---|---|---|---|
| M1 drop `or (_cs_floor(t)…) == "complaint"` from `length_target_for` | runtime.py | w2_w7::test_a_complaint_read_by_the_floor_earns_the_care_first_length | KILLED |
| M2a remove `lock_for_write` call in `customer_state.apply` | customer_state.py | w2_w7::test_state_writes_take_the_row_lock | KILLED |
| M2b remove `lock_for_write` call in `intent.record_opt_out` | intent.py | same | KILLED |
| M2c call the lock but write to the stale row (`await lock…` without assignment) | customer_state.py | same | KILLED |
| M3 lock failure no longer swallowed (`except ValueError`) | intent.py | w2_w7::test_an_opt_out_still_lands_when_the_lock_cannot_be_taken | KILLED |
| M4 `_merge_next_action` team_check branch → `if False` | deals.py | w2_w7::test_the_scribe_keeps_the_team_check_when_the_customer_names_a_day | KILLED |
| M5 `served_model` prefers `_model` over `last_model` | runtime.py | w2_w7 + cost_overhaul::test_usage_logs_the_model_that_actually_served | KILLED (2 failed) |
| M5b `_served = settings.tier2_model` at the call site | runtime.py | same two | KILLED by cost_overhaul (source pin); w2_w7 helper test passes, as designed |
| M6 blind skip → `if False` in `eval_cases.load` | eval_cases/__init__.py | eval_harness::test_the_default_sweep_leaves_the_blind_set_out | KILLED |
| M7a comment dedupe `if dup is not None` → `if False` | meta_webhook.py | inbound_social::test_a_redelivered_comment_is_not_answered_twice_without_redis | KILLED |
| M7b dedupe compares `channel` (DM channel) instead of `comment_channel` | meta_webhook.py | same | SURVIVED (finding 3) |
| M7c dedupe drops the `waba_msg_id == comment_id` term | meta_webhook.py | same | SURVIVED (finding 3) |
| M9 `eval_floors._runtime_target` back to the old mirror | eval_floors.py | w2_w7::test_a_complaint_read_by_the_floor… (`_runtime_target(text) == target`) | KILLED |
| M8 remove the hub stub line (timing only) | test_response_timing.py | the file | 4 passed in 9.51 s vs ~0.3 s with the stub |

Baseline before mutations: `pytest tests/test_intelligence_w2_w7.py tests/test_eval_harness.py tests/test_inbound_social.py tests/test_response_timing.py tests/test_cost_overhaul.py tests/test_reply_length.py tests/test_intelligence_floors.py tests/test_meta_webhook.py` → 255 passed in ~2.5 s (one transient failure on the first run, finding 7).

Tree state at the end: `git status --short` empty (the uncommitted `memory.py` / `test_agent_memory.py` edits seen mid-pass belonged to a concurrent session and were committed by it as `0a6745d`; nothing of mine remains).

## Verdict

Slice 2 holds up under adversarial checking: the two runtime helpers are behaviour-preserving (the one visible difference, `None` into `customer_state.floor`, is absorbed by `floor` itself), the Correction 2 numbers reproduce exactly from the current code and from the old mirror, the committed result files match a fresh run byte-for-byte on metrics and misses, the blind set is genuinely out of the tuning split, the comment dedupe queries the same channel and id the row is stored with, the timing fixture reaches the function-local import and removes ~9–15 s of hub wait, and 11 of 13 targeted production mutations are killed by the new behaviour tests. Nothing blocks merge. Two things should be fixed before the next slice leans on them: the model-in-the-loop runner has lost every way to run the blind set (S2 — the only held-out number the programme claims cannot be produced for the real-model run as documented), and the comment-redelivery test's fake DB cannot tell a correct dedupe predicate from a wrong one (two surviving mutants). The remaining notes — wildcard patterns bypassing the blind exclusion, acked-and-lost comments on a DB error (pre-existing), the shared `instagram` channel, and the unindexed `waba_msg_id` — are hygiene rather than defects in what this slice claims.


## Implementer's response (same day)

| Finding | Response |
|---|---|
| S2 #1 runner cannot reach the blind set | **Fixed.** `agent_eval --cases --file blind_heldout.jsonl` → `run_cases(file=…)` → `load(file, include_blind=True)`, ignoring the split. The documented real-model command now names the blind set (BENCHMARK_RESULTS, EVALUATION_DATASET). |
| S3 #2 pattern loophole | **Fixed.** `load()` leaves blind cases out for every pattern unless `include_blind=True`; both scorers' `--file` pass it. Test pins `load("*.json*")` and a bare `load("blind_heldout.jsonl")`. |
| S3 #3 fake DB blind to the predicate | **Fixed.** The redelivery test's fake compiles the statement and answers only when the channel and the comment id both match; a row on the DM channel with the same id is not a duplicate; an Instagram comment is looked up on "instagram". |
| S3 #4 DB error → comment acked and lost | **Recorded** (pre-existing contract; the first DB touch in that try was already the person resolve). UNFINISHED_REGISTER. |
| S3 #5 IG comments and DMs share "instagram" | **Recorded** (theoretical; id formats differ). |
| S3 #6 `messages.waba_msg_id` unindexed | **Recorded** — an index is a migration (owner approval). UNFINISHED_REGISTER. |
| S3 #7 transient failure during a concurrent edit | Noted; passes on re-run; the file was being written at the time. |
| S3 #8 `str()` at the usage call site | No change needed. |
