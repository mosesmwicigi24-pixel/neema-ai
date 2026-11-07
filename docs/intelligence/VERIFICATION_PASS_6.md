# Verification pass 6 — slice 6 (branch `claude/where-are-we-bx9v9w`, commit `85e83de`)

Adversarial, independent. The diff (`git show 85e83de -- apps/api`), the two new
tests, the register text (ADVANCEMENTS "Slice 6", the two struck UNFINISHED rows),
the commit message and the code comments were treated as claims, not facts. Line
numbers are from the working tree at `85e83de`. Commands from
`/home/user/neema-ai/apps/api` with `python` (3.11) and the CI env vars; the
implementer's full-suite run was left alone (targeted file only:
`tests/test_eval_harness.py`, 20 passed at baseline).

Probes under `scratchpad/v6/` (read-only against the tree). Two needed a real
Postgres schema: the local `neema` database is EMPTY (0 tables), so I created a
scratch database `v6probe`, ran `alembic upgrade head` into it (head
`e8a1c3d5f7b9`, 42 revisions) — the same thing `tests/test_migrations.py` does —
and dropped it at the end. Mutants (`v6/v6-mutate.py`, `v6/v6-mutate-b.py`): each
written from an in-memory copy, pytest run, the original restored byte-exact in a
`finally` and asserted; no git checkout/stash/reset. No commits, no pushes, no
network.

**Tree note.** `git status --short` was empty when this pass began. Mid-pass the
implementer worked on the next slice in the same tree (`cooling.py`, `runtime.py`,
`eval_floors.py`, two tests, three docs, one untracked results file appeared as
modified) and had committed them by the time this pass ended, so `git status
--short` is empty again at hand-off. None of those files were touched by me; the
three files this pass mutated (`agent_eval.py`, `eval_run.py`,
`test_eval_harness.py`) are byte-identical to HEAD throughout (asserted after every
mutant and again at the end). The scratch database `v6probe` was dropped.

Versions: `sqlalchemy[asyncio]==2.0.35`, `asyncpg==0.29.0` (both pinned in
`requirements.txt`, so CI runs the same driver; CI Python is 3.12, local 3.11).

## Findings

| # | finding | severity | evidence | recommended fix |
|---|---|---|---|---|
| 1 | **R1's diagnosis is false; the fix works for a different reason than stated.** The commit, the docstring (`agent_eval.py:200-205`), ADVANCEMENTS R1, the struck UNFINISHED row and the test docstring all say the person was deleted "in the same flush as the identity" / "the unit of work had emitted the person delete first". The log says otherwise: the constraint that fired is `identifiers_person_id_fkey` (`…run42289125585.log:749, 868`), and the pre-slice code never deleted `identifiers` at all (`v6/agent_eval_before.py`). SQLAlchemy's unit of work already orders the Identity delete before the Person delete through the `Person.identities` relationship. Real-DB proof (`v6/probe-cleanup-db.py` on the migrated scratch DB, person+identity+identifier+user+message seeded): **old code → `IntegrityError` on `identifiers_person_id_fkey`** (crash reproduced); **old code + one `delete(Identifier)` line and NO flushes → clean, every row gone**; new code → clean; **new code minus BOTH flushes → clean** (autoflush on the next `execute(select…)` emits the pending deletes). So the two `flush()` calls the slice is named for are not load-bearing, and the test pins their positions as if they were (mutants M2/M5 are "killed" but are behaviourally equivalent). | **S2** | `agent_eval.py:200-205, 217-225`; log `:749, 868`; probe output in `v6/probe-cleanup-db.txt` | Correct the four texts: "the identifiers rows were never deleted"; keep the flushes if wanted but say they are belt-and-braces; drop "the unit of work had emitted the person delete first". |
| 2 | **"VERIFIED COMPLETE (behaviour test on a recording session)" rests on a fake that sees statement prefixes only.** `_Sess.execute` dispatches on `str(stmt).lower().startswith(...)`/`in` (`test_eval_harness.py:312-325`), so every predicate is invisible. Mutants that survive the whole file: **M11** `delete(Identifier).where(Identifier.person_id != pid)` (deletes every OTHER person's identifiers, leaves this one → the original crash returns); **M12** `delete(Message).where(Message.wa_id != wa_id)` (wipes every other contact's messages); **M13** person deleted even when another identity still references it; **M14** identity lookup ignoring the channel. The test proves the call sequence and the swallow; it does not prove the fix. The real-DB probe in finding 1 is the only behavioural proof the slice has, and it lives in my scratchpad. | **S2** | `v6/v6-mutate-b.py`: 4/4 SURVIVED (`20 passed`); `test_eval_harness.py:299-350` | Add a `*_db.py` test (the CI "Security + calling guarantees on a real database" step runs that family): seed person+identity+identifier+user+message, call `_cleanup_contacts(None, [wa])`, assert all five rows gone and a sibling contact's rows untouched; a second case where another identity references the person → person and identifiers stay. |
| 3 | **R2's mitigation does not fit the run's own data; its coverage is overstated.** `_recover_from_failed_turn` runs only in the `except` of a RAISING `run_turn` (`eval_run.py:478-481`). In the partial record the four `InFailedSQLTransactionError` turns were preceded by: blind-047 t0 **passed** (8.56 s), blind-075 t2 **passed** (5.1 s), blind-055 t1 **failed on language, no error** (10.63 s), and only blind-047 t1 raised. So the helper would have fired before **one of four** casualties (blind-047 t2); the three first casualties are untouched. The test's docstring ("after a failed turn … the next turn's connection is clean") and the UNFINISHED row ("mitigated") describe the one case, not the symptom. Root cause: the register says "not proven" — correct, and stronger than it reads: I could not reproduce ANY pool carry-over with the pinned driver (`v6/probe-pool.py`, 8 scenarios on the app's QueuePool: swallowed error + context exit; swallowed error + commit; leaked session + gc (SQLAlchemy terminates it with a warning); `wait_for` cancellation mid-statement, with and without reuse; task cancel mid-statement; cancel on the first statement ×30; two coroutines on one session — **all eight: next session CLEAN**). Reading: the failing statement is the first of a fresh session (`[SQL: SELECT pe…` = `persons`, 0.02–0.03 s), the pool rotates FIFO and `run_turn` opens nested sessions while `db` is checked out, so ≥2 connections exist and a poisoned one surfaces a few checkouts later — consistent with "the previous turn passed". Where the poison enters is not shown by anything in the code I can find (no bare `AsyncSessionLocal()`, no `driver_connection`/`raw_connection`, no `gather` on a shared session in the turn path; the two `begin_nested()` uses are context-managed). | **S2** | `eval_run.py:375-390, 478-481`; partial JSON (`v6/probe-pool.txt`, the "prev:" lines); `v6/probe-pool.py` output | Make the guard unconditional and self-diagnosing: a pool `checkout` listener on `engine.sync_engine` that checks `dbapi_connection._connection.is_in_transaction()` (asyncpg) and raises `DisconnectionError` (the pool then hands out a fresh one) with a log line naming the event — this catches the poison whichever session created it; and retry a turn once on `InFailedSQLTransactionError` so the measurement is not lost. Reword the test name/docstring and the UNFINISHED row to "limits a poisoned connection to one casualty". |
| 4 | **Cleanup does not delete the conversation, so repeats are not "clean" and one objective check is vacuous on repeats 2–3.** `_cleanup_contacts` deletes messages, user, identity, identifiers, person (`agent_eval.py:208-227`); `conversations` (wa_id-keyed, `person_id` SET NULL), `intercepts`, `deals`, `agent_activities`, `customer_history` (PK = wa_id), `order_events` survive (no `delete(Conversation)` anywhere in `app/jobs/` but `fix_phantoms.py`). After an escalation in repeat 1, `conv.intercept_mode` stays `human`; `check_turn` passes "escalate" turns when `intercept_mode == "human"` regardless of tools (`eval_run.py:199`), and the runtime's takeover read (`runtime.py:~2803`) sees a human-held thread. The docstring's "Delete every row a run created" is false and "the next repeat simply reuses the rows" is presented as harmless. Data (n = 2 escalate cases seen in both repeats: blind-046, blind-052) both improved in repeat 2 — suggestive, not proof. Pre-existing, but the slice re-asserts the claim and pass^3 is the headline metric. | S3 (S2 if pass^3 is reported from this runner) | `agent_eval.py:196-227`; `eval_run.py:199, 487`; `v6/probe-pool.txt` ("escalate cases seen in both repeats") | Delete the conversation and its intercepts/deals/agent_activities for the throwaway contact (all are wa_id- or conversation-keyed; FK order: intercepts → deals → agent_activities → conversation), or reset `intercept_mode`/`intercept_since` per repeat; note the caveat in BENCHMARK_RESULTS until then. |
| 5 | The CI "model/schema drift" step cannot see this class of bug: `test_migrations.py` compares `get_table_names()` and column NAMES only (`:60-67`) — no enum labels, no FK `ondelete`, no uniqueness, no column types. The enum has been wrong since `c3a9a8e5f2be` created it with four values; `f0a1b2c3d4e5` added `pause`; nothing added `flag`/`escalated` (confirmed on the migrated scratch DB: `{intercept,release,transfer,approve_draft,pause}`), while seven modules write them (`intent.py:165`, `unclaimed.py:125`, `public.py:238`, `conversation.py:343,352`, `messaging.py:685`, …). The eval workflow builds its DB with `alembic upgrade head` (`agent-eval.yml:64`), so the premise of R3 holds. | S3 | `tests/test_migrations.py:55-69`; `alembic/versions/c3a9a8e5f2be_initial_tables.py:130`; scratch DB `enum_range` | Extend the drift test: for every `sa.Enum` in `Base.metadata`, compare its labels with `pg_enum` for that type name; one loop, catches this for good. |
| 6 | The held migration is sane: revision `a9c1e3f5b7d9`, `down_revision = "e8a1c3d5f7b9"` = current head (`alembic heads`), `autocommit_block()` (same shape as `f0a1b2c3d4e5`), `ADD VALUE IF NOT EXISTS` idempotent on PG 16, `downgrade` a no-op with the reason. Only note: when it lands, `OWNER_ACTIONS:60` already carries the read-only `enum_range` check. | — | scratchpad `migration-held/…`; `OWNER_ACTIONS.md:60` | none |
| 7 | Hygiene: `logging.getLogger("neema.eval")` inline at `agent_eval.py:230` while `_log` exists at `:40`; `_recover_from_failed_turn` disposes `app.database.engine` only — a second engine exists in `app/core/database.py` (used only by `seeds.py`, not in the turn path), worth deleting rather than remembering. | S3 | `agent_eval.py:40, 230`; `app/core/database.py:4` | use `_log`; remove the second engine. |

## Claims

| claim | verdict |
|---|---|
| R1 — identity → flush → identifiers → flush → person, one transaction per contact | **Holds as code** (`agent_eval.py:208-227`; M6 "one transaction for all" killed). The order satisfies every constraint on `persons` in the migrated schema (`pg_constraint`): RESTRICT `identities_person_id_fkey`, `identifiers_person_id_fkey`; CASCADE `person_merges_{primary,secondary}_person_id_fkey`; SET NULL on the other 12 (`agent_activities, calls, deals, demand_signals, conversations, customer_history, messages, order_events, users, persons.merged_into_id, production_enquiries, recovery_sends`). The flushes are redundant (finding 1). |
| R1 — a failing contact is rolled back, logged, skipped | **Holds.** `AsyncSession.__aexit__` → `close()` releases the connection and the pool's `reset_on_return="rollback"` issues ROLLBACK (scenarios A/B: the next session is clean); M4 (re-raise) killed. `except Exception` does not swallow `CancelledError`. |
| R1 — fixes the `identifiers_person_id_fkey` crash | **Holds** — proven on a real schema by my probe, not by the slice's test (findings 1, 2). |
| R1 — "the unit of work had emitted the person delete first" | **False** (finding 1). |
| R1 — the Message delete frees the user row | **Holds.** No table references `users.id` (`pg_constraint` where `confrelid='users'` → none; grep of models and migrations agrees); `users.wa_id` is unique; `users.person_id` is SET NULL. |
| R1 — the fake session proves the order | **Proves the call sequence only**; blind to predicates (M11–M14 survive) and to whether the sequence suffices on Postgres. A wrong order cannot pass (M1 killed), but a wrong `where` can. |
| R2 — `_database.engine` is the sessions' engine; dispose leaves the sessionmaker usable | **Holds.** `AsyncSessionLocal` is bound to `engine` at import (`app/database.py:4-14`); the helper reads `database.engine` at call time, so the test's monkeypatch reaches it (M7 killed). `Engine.dispose()` closes checked-in connections and does `self.pool = self.pool.recreate()` (SQLAlchemy 2.0.35 source), so later sessions get a new pool. |
| R2 — safe to dispose mid-run | **Holds.** The runner is sequential; at the except branch the only checked-out connection is `db` itself, which `dispose` leaves alone ("checked out … will not be closed") and `__aexit__` returns to the old, now-orphaned pool. The `box` sandbox is tool stubs, redis is not pooled here; the only `create_task` paths in the turn (photo check, push) are not exercised by text cases. |
| R2 — "a pooled connection carried the aborted transaction into a fresh session" | **Plausible only as a description of the symptom**, not as a mechanism: no reproducible carry-over path with the pinned driver (8 scenarios), and the mitigation's trigger precedes 1 of the 4 instances (finding 3). The register's "root cause not proven" is right; "mitigated" is too strong. |
| R3 — no migration adds `flag`/`escalated`; the code uses both; CI cannot catch it; held migration sane | **Holds on all four** (findings 5, 6). |
| Measurement — the headline numbers | **All reproduced exactly** from `…partial179of360.json` with `summarise(repeat==1 results, repeat=1)`, no case text printed: turns 367/459, critical 133/171, language 405/424, figures 164/192, length 385/437, internal-talk 434/437, first draft 212/448; next-action (answer 133/146, ask_one 26/27, quote 88/116, hold_ack 61/65, care_first 9/9, confirm_paid_check 22/22, escalate 10/15, silence 18/52, stop_ack 0/7); by language (en 287/343 … mixed 3/3); failure kinds (answered a closer 33, language 19, no price 16, opt-out not recorded 7, figure 7, required text 5, did not hand 5, turn raised 3, no reply 3); 92 failing turns; and the combined 179 case-runs (578/701, 200/246, 634/659, 265/308, 598/673, 317/689). No mismatch. |

## Mutation results

Mine (`v6/v6-mutate.py`, `v6/v6-mutate-b.py`; each against `tests/test_eval_harness.py`, restored byte-exact and asserted):

| mutant | killed by | result |
|---|---|---|
| M1 identity delete moved after the person delete | `test_cleanup_deletes_the_person_only_after…` | KILLED |
| M2 first `flush()` removed | same | KILLED — **equivalent mutant**: clean on the real DB (finding 1) |
| M3 identifiers delete removed | same | KILLED |
| M4 `except` re-raises | same | KILLED |
| M5 second `flush()` removed | same | KILLED — equivalent mutant (finding 1) |
| M6 one transaction for all contacts (context manager hoisted) | same | KILLED |
| M7 `engine.dispose()` removed | `test_a_failed_turn_rolls_back_and_drops_the_pool` | KILLED |
| M8 `db.rollback()` removed | same | KILLED |
| M9 helper call removed from `run_cases` | same (source-string assertion) | KILLED (string only) |
| M10 helper re-raises on rollback failure | same | KILLED |
| M11 `delete(Identifier).where(person_id != pid)` | — | **SURVIVED** (finding 2) |
| M12 `delete(Message).where(wa_id != wa_id)` | — | **SURVIVED** |
| M13 person deleted although another identity references it | — | **SURVIVED** |
| M14 identity lookup ignores the channel | — | **SURVIVED** |

Real-DB variants (`v6/probe-cleanup-db.py`, scratch DB at head): old → IntegrityError (crash reproduced, all rows left); old + `delete(Identifier)` only, no flushes → clean; new → clean; new minus both flushes → clean.

## Verdict

The slice fixes the crash it set out to fix — the real-DB probe reproduces run 42289125585's `identifiers_person_id_fkey` failure with the pre-slice code and shows the new code removing every row — but for a different reason than every text in the commit says: the identifiers were never deleted, the unit of work was ordering the identity before the person all along, and the two flushes the slice is named for are redundant with autoflush. R1's "VERIFIED COMPLETE" is carried by a recording-session test that sees statement prefixes only, so four predicate mutants (including one that reintroduces the crash) pass it; the behavioural proof exists only in this pass's scratchpad and should become a `*_db.py` test. R2 is honestly marked "root cause not proven", but its mitigation fires only after a raising turn while three of the four observed casualties followed turns that did not raise, and none of eight driver-level scenarios reproduces a pool carry-over on the pinned SQLAlchemy/asyncpg — so expect the symptom to recur on the next run; a checkout-time `is_in_transaction()` guard plus one retry would both diagnose and contain it regardless of origin. R3 is accurate throughout and the held migration is correct against the current head. Every published measurement re-derives exactly. The cleanup still leaves the conversation and its intercepts behind, which makes the hand-off check vacuous on repeats 2–3 — worth closing before pass^3 is reported.

---

## Implementer's response (2026-11-06, same day)

| # | Finding | Response |
|---|---|---|
| 1 | R1's diagnosis was false: the crash was the never-deleted `identifiers` rows, not flush order; the two flushes are redundant (equivalent mutants) | **Accepted and corrected.** The flushes are removed; the docstring, ADVANCEMENTS R1, the UNFINISHED row and the test docstring now state the true mechanism. The commit message of 85e83de cannot be rewritten (no history rewriting); this table is the correction of record. |
| 2 | The recording-session test cannot see a wrong predicate (M11–M14 survived) | **Fixed.** `tests/test_eval_cleanup_db.py` runs the cleanup against a real Postgres: contact A's every row goes, contact B's person stays because a Messenger identity still points at it, a Messenger identity with A's digits is untouched (the channel matters), an unrelated contact is untouched. The recording-session test keeps only the shape and says so. |
| 3 | R2's mitigation fires only after a raising turn; three of the four casualties followed non-raising turns; carry-over not reproducible; "mitigated" overstated | **Accepted.** A pool `checkout` guard (`_guard_pool_checkout`, installed by `run_cases`) invalidates any pooled connection that is still inside a transaction, whatever the cause; the rollback-on-error helper stays. Status restated: the guard holds the symptom; the root cause is **unproven** and recorded in UNFINISHED. |
| 4 | Conversations survive the cleanup, so repeats are not clean and the hand-off check is vacuous on repeats 2–3 | **Fixed.** The conversation row is deleted (intercepts and activity cascade); deals and the SET-NULL rows keep a null conversation. Proven by the real-DB test. |
| 5 | The CI drift test compares table and column names only; enum labels unchecked | **Recorded** in UNFINISHED (a `pg_enum` comparison in `test_migrations.py`), to land with the held enum migration. |
| 6 | Held migration sane | — |
| 7 | Inline `getLogger`; a second engine in `app/core/database.py` | **Fixed** (`_log`); the second engine is recorded in UNFINISHED (used by seeds only). |
