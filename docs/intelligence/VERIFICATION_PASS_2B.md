# Verification pass 2b — the four commits after `13e7cb8` (branch `claude/where-are-we-bx9v9w`, tree `81a26b2`)

Adversarial, independent. Code read and run; docs and commit messages not trusted.
Scope as briefed: `9c50c02` (docs), `22de88b` (`trim_truncated`), `0a6745d`
(Meta turn reads the linked WhatsApp user's facts), `81a26b2` (eval `--file`,
loader loophole, dedupe test reads its statement). Pass 2's scope is not
repeated. Line numbers are from the tree at `81a26b2`.

All commands run from `/home/user/neema-ai/apps/api` with the scratchpad venv
(`$V`) and `env.sh` sourced. Baseline before any mutation:
`pytest tests/test_intelligence_w2_w7.py tests/test_agent_memory.py tests/test_eval_harness.py tests/test_inbound_social.py tests/test_meta_webhook.py tests/test_agent_flow.py` → **87 passed**.
Tree state at the end: `git status --short` empty; the temporary worktree used
for finding 10 was removed (`git worktree list` shows only the main tree).

## Findings

| # | finding | severity | evidence | recommended fix |
|---|---|---|---|---|
| 1 | **The sentence-boundary regex treats abbreviations and list numbers as sentence ends, so the "cut back to a whole sentence" can send a reply that is worse than the untrimmed draft.** `_SENTENCE_END_RE = [.!?…][quotes]*(?=\s\|$)` — any full stop followed by whitespace is a boundary. Probe (`trim_truncated` on max_tokens-shaped drafts): `"Your parish is St. Peter's, Nakuru, and the cope will"` → **`"Your parish is St."`**; `"Delivery to Mt. Kenya region takes two"` → **`"Delivery to Mt."`**; `"We have many colours, e.g. red, green and"` → `"We have many colours, e.g."`; `"Available:\n1. Cope\n2. Stole\n3. Chas"` → `"Available:\n1. Cope\n2. Stole\n3."` (cut=True, ends on a dangling list number); `"Available:\n1. Cope\n2. Stole\n3."` → returned unchanged with cut=False (the dangling "3." counts as "already a whole sentence"). `"Rev. Fr."` happens to be saved only by the 12-char floor. The decimal case in the test (`"2.5"`) is protected by the lookahead; `10.30 am` and `P.O. Box` pass only because the stop sits before a space. | S2 | `app/agent/runtime.py:1514` (regex), `:1517-1534`; probe output in "Attack log" below | Treat a stop preceded by a known abbreviation (`St`, `Mt`, `Rev`, `Fr`, `Dr`, `Mrs`, `e.g`, `i.e`, `etc`, `no`, `vs`, a single capital letter) or by `\n\s*\d+` (a list number) as not a boundary; require the boundary to be followed by whitespace **and** either end-of-text, an upper-case/digit/quote/emoji, or a newline; treat a draft whose last line is `^\s*\d+\.$` as truncated with no usable boundary. Add these shapes to the trimmer test. |
| 2 | **The cut can remove the one sentence that answered the question and keep the pleasantry.** `"Thanks for asking, Moses. The cope set is KES 45,000 and ships in a"` → `"Thanks for asking, Moses."` (keep=25 ≥ 12 and ≥ 67//3=22, so the rule allows it); `"Asante kwa swali lako Moses! The cope set is KES 45,000 and ships in a"` → `"Asante kwa swali lako Moses!"`. The untrimmed draft at least carried the price. The trimmed reply is what the gate sees (`runtime.py:2331`, `reply` flows into `_gate_turn_reply`), and the gate has no deterministic completeness/"answers the question" rule (`grep -in "incomplete\|unfinished\|mid-sentence" app/agent/review.py` → none); on `read_only`/`scribe_only` turns nothing reviews it at all. | S2 | probe output below; `runtime.py:1530-1534`, `:2328-2345` | Keep the "a third must remain" rule but also require the kept text to retain at least one money figure / product name that the dropped tail carried when the customer's message asked a price/availability question (cheap: `review.money_figures(kept)` vs `money_figures(dropped)`), otherwise do not cut and let the gate's rewrite path (which already has the facts) produce the reply; or on `max_tokens` prefer one `_reply_in_words`-style continuation call with the facts over cutting. |
| 3 | The trimmer's two thresholds and the regex's whitespace lookahead are not pinned by the test: mutating `keep < 12` → `keep < 1` (R4) and `len(t) // 3` → `len(t) // 10` (R5) both **survive**, because the test's only "too little would remain" case (`"Ok. " + "x"*200`, keep=3) is caught by either threshold; dropping the `(?=\s\|$)` lookahead (R8, "a decimal is a boundary") **survives** because the test's decimal case (`"It is 2.5 metres long and"`, keep=7) is rescued by the 12-char floor, not by the regex. A decimal later in a longer draft would be cut mid-number under R8. | S3 | mutation table below | Add one case per threshold where only that threshold binds (e.g. `"Yes. We have it."+` long tail for the 12-char rule; a 30-char sentence followed by a 120-char tail for the one-third rule) and a decimal case past 12 chars (`"The cope is KES 45,000 and 2.5 metres long and"` must stay uncut). |
| 4 | `stop_reason` is inspected only on the in-loop text path. The for-`else` branch (`runtime.py:2314-2320`, ran out of iterations: `reply = resp.text or await _reply_in_words(...)`) and `_reply_in_words` itself (`:1346-1372`, returns `(resp.text or "").strip()`) never look at `stop_reason`, so a max_tokens draft from either path goes out untrimmed and unrecorded. Also `turn_facts["truncated"]` has no reader anywhere (`grep -rn truncated app` → only the two lines that set it), so the eval harness and the activity trail cannot see it. | S3 | `runtime.py:1346-1372`, `:2314-2320`, `:2268-2269` | Apply `trim_truncated` in `_reply_in_words` (return `(text, cut)` or trim inside) and in the for-`else` branch; surface `truncated` in `eval_run`'s per-turn record and the usage row so the frequency is measured. |
| 5 | **Which WhatsApp user's facts a Meta turn reads is arbitrary when two Users share a Person.** `users.person_id` is indexed, not unique (`app/models/user.py:15`; `User.__table__.c.person_id.unique → None`), and a person merge repoints every moved wa_id's `User` row to the primary (`app/services/merge.py:29` `_WA_MODELS = [User, …]`, `:68-73`), so a customer with two WhatsApp numbers has two Users on one Person. The new lookup is `SELECT … FROM users WHERE users.person_id = … LIMIT 1` with **no ORDER BY** (compiled in the probe), so Postgres returns whichever row the plan reaches first; the other number's facts are never read. | S3 | `app/agent/memory.py:163-165`; probe output below | Read all linked users (`.scalars().all()`) and merge each, or `ORDER BY last_message_at DESC NULLS LAST` and document "most recent number wins". |
| 6 | The two cross-store merges de-duplicate by exact string while the writer (`_merge`) de-duplicates case-insensitively, so a fact stored once per store in different case appears twice in the prompt: Person `"Prefers black cassocks"` + User `"prefers black cassocks"` → `Known facts:\n- Prefers black cassocks\n- prefers black cassocks`. Same on the pre-existing WhatsApp side (`memory.py:156`). | S3 | `memory.py:66-74` vs `:156`, `:167`; probe output below | Use the same case-insensitive (and whitespace-normalised) test in both readers; factor it out of `_merge`. |
| 7 | `test_a_messenger_turn_reads_the_linked_whatsapp_users_facts` cannot see the predicate or the error path. Its fake DB returns the queued result for any statement, so comparing the wrong column (`User.id == store.id`, M2; `User.wa_id == store.id`, M2b) **survives**; and it never raises on the lookup, so narrowing the `except Exception` to `except ValueError` (M3) **survives** — the "best-effort" half of the claim is untested. (Note, same as pass 2's finding 4 for `_recent_orders_summary`: on a real asyncpg session a failed SELECT leaves the transaction aborted, so "a DB error cannot break the turn" holds only for the memory block itself; the next statement in the same session fails until a rollback. Pre-existing pattern.) | S3 | mutation table below; `tests/test_agent_memory.py:159-180` | Make the fake compile the statement (as `test_inbound_social._RowDB` now does) and assert `users.person_id = <person id>`; add a case where `execute` raises and the person's own facts still come back. |
| 8 | **Nothing pins `include_blind=True` on either scorer's `--file`, and losing it is silent.** Dropping it in `eval_floors._cli` (E1) or `eval_run.run_cases` (E2) survives the whole `test_eval_harness.py` (15 passed). Live, with E1 applied: `python -m app.jobs.eval_floors --file blind_heldout.jsonl` prints `case set: 0 cases / 0 turns (file:blind_heldout.jsonl)` and exits **0**. A `--file` that does not exist behaves the same (`load("nonexistent.jsonl")` → `[]`, exit 0; `run_cases(file="nonexistent.jsonl")` → "no cases selected", returns None). A CI step or a human reading only the exit code would take an empty blind run as a pass. | S3 | mutation table; E1 live run below; `app/jobs/eval_floors.py:115`, `app/jobs/eval_run.py:363-365` | Make `load(pattern)` raise when a literal filename (no glob metachar) matches no file; make both CLIs exit non-zero on zero cases; add a test that calls `eval_floors._cli`/`run_cases` selection with `--file blind_heldout.jsonl` and asserts 120 cases (the pass-2 probe pattern: fake key + a sentinel in `contact_for`). |
| 9 | `run_cases(file=…)` silently ignores `--held-out`/`--dev`, and the run record keeps the ignored label: `record["selection"] = selection` (`eval_run.py:391`, also copied into the history row at `:538`) with no `file` key. `agent_eval --cases --file blind_heldout.jsonl --held-out` therefore produces a record whose `selection` says `"held-out"` while it scored the blind set (`"all"` when no split flag is given). The only trace of what was run is `case_set` (a hash) and `cases: 120`. | S3 | probe below (`{'file': 'blind_heldout.jsonl', 'selection': 'held-out'}` → loads the blind file); `eval_run.py:391, 538` | Record `"selection": f"file:{file}"` when `file` is set (mirroring `eval_floors`' label) and refuse `--file` together with `--held-out/--dev` in argparse (`mutually_exclusive_group`). |
| 10 | **The "aggregate-only" blind runs are not aggregate-only on disk.** BENCHMARK_RESULTS says "both runs below are aggregate-only (`--file`, no misses printed)" and "the remaining misses are not inspected, by design", but `eval_floors --json` writes every miss with the customer's words regardless of `--misses` (`eval_floors.py:95` `out = {"metrics": …, "misses": misses}`), and the committed files carry them: `results/floors-blind-before.json` **587** misses, `floors-blind-after.json` **374**, `floors-rescored-blind.json` **371**, each `{id, turn, metric, expected, got, text}` (e.g. `blind-001` turn 0 `"Hi, do you have cassocks?"`). The protection is a discipline, not a mechanism; the blind phrasings and their failing metrics sit in the repo next to the tuning tests. | S3 | `app/jobs/eval_floors.py:95-131`; counts above | Have `--file` on a blind file (or any case with `"blind": true`) drop `misses` from the JSON unless `--misses` is passed explicitly; rewrite the three committed files without `misses`; say in BENCHMARK_RESULTS that the files were aggregate-only from this point. |
| 11 | Docs still carry the withdrawn held-out split as the frame or the number. `docs/intelligence/BENCHMARK_RESULTS.md:72-73` "Tuned on the development half only; **the held-out half is the report**"; `:78` `**136/149 = 0.913 [0.856, 0.948]**` and `:79` `**28/29 = 0.966 [0.828, 0.994]**` are still bold with intervals (only the customer-state cell at `:77` is marked "withdrawn: in-sample"; `:82` says "the 'after' column is not clean" one line later); `:83` "The gap between dev (0.95) and held-out (0.79) … is the honest measure". `docs/intelligence/INTERNATIONAL_ASSESSMENT.md:16` "running it on the held-out half" and `:41` "1. The real-model run on the **held-out half** (pass^3, intervals)" name the contaminated split as the next defensible step, contradicting the same commit's change of the documented command to `--file blind_heldout.jsonl`. `docs/intelligence/REQUIREMENTS_REGISTER.md:26` R1.9 "BENCHMARK_RESULTS before/after on a held-out set" marked **applied**. `docs/intelligence/EVALUATION_DATASET.md:50` still offers `--held-out` as a peer alternative to `--file blind_heldout.jsonl` without a caveat. No `0.79`, `0.91`, `+24.8`, `+16.8`, `+20.7` survives as a claim in REQUIREMENTS_REGISTER or INTERNATIONAL_ASSESSMENT (`:68`, `:74`, `:30` cite them only as withdrawn). | S3 | file:line as listed; `grep -nE "0\.79\|0\.91\|0\.966\|\+24\.8\|\+16\.8\|\+20\.7\|held-out"` over the four files | Un-bold `:78-79` and add "withdrawn: in-sample" to each; change `:72-73` to "the held-out half was the report until Correction 1"; INTERNATIONAL_ASSESSMENT `:16`/`:41` → "the blind set"; R1.9 evidence → "on the blind set"; EVALUATION_DATASET `:50` → `--held-out` "(tuning split, not a claim)". |
| 12 | The `agent_eval --cases --file … --limit 1` check in the brief is vacuous: `run_cases` tests `settings.anthropic_api_key` **before** any case is loaded (`eval_run.py:347-349`), so reaching "ANTHROPIC_API_KEY is not set" proves nothing about `--file`. Selection was verified separately with a fake key and a sentinel (confirmed claims, 3). | S3 | `eval_run.py:347-365` | Load and select cases before the key check (the key is only needed to run them), so a dry `--file` invocation prints the case count. |

## Claims confirmed (tried to break, could not)

**Claim 1 — `trim_truncated` and its use in `run_turn`.**
- Rule as claimed: nothing is cut when the draft already ends on a boundary (`ends[-1] == len(t)`), when there is no boundary, when fewer than 12 chars would remain, or when less than a third (`keep < len(t)//3`) would remain; otherwise `t[:keep].rstrip()` with `cut=True` (`runtime.py:1517-1534`). The nine shapes in the test and `run_turn` with a fake writer on `max_tokens` vs `end_turn` behave as the commit says.
- Where the cut text goes: the trimmed `reply` is the variable the gate receives (`:2331`), that the photo-refer swap, cassock ladder, length record and said-once read (`:2347-2400`), and that `run_turn` returns. `messages` keeps the untrimmed `assistant_content` (`:2255`, appended before the trim) but `messages` is not persisted after the loop and the gate's transcript is `turn_messages = list(messages)` taken before the loop (`:2244`), so no stale draft reaches storage or the reviewer. `trim_truncated` never returns an empty string from a non-empty draft, so the `if not reply` silence/`_reply_in_words` branches below it are unaffected.
- `LLMResponse` always carries `stop_reason`: dataclass default `"end_turn"` (`app/agent/llm.py:28`); `AnthropicLLM.complete` sets `r.stop_reason = resp.stop_reason or "end_turn"` after both fallbacks (BadRequest → fallback model; `refusal` → fallback model; `:243`); `_blocks_to_response` (tool_use path) returns the default and is then overwritten; `FakeLLM` returns `"tool_use"` for tool rounds and the default for text (`:305-317`). No other `complete` implementation exists in `app/` (`grep -rn "async def complete" app` → only llm.py and `password_reset.complete_reset`). `getattr(resp, "stop_reason", "")` at `:2259` also tolerates test fakes without the field.
- Emoji endings, Swahili/French punctuation, quotes and brackets, multi-paragraph drafts and URLs behave sensibly (attack log below): `"… KES 2,500 🙏 Je, ungependa"` → left alone (no boundary); `"Bonjour ! … 45 000 KES. Nous avons aussi"` → cut at `KES.`; `'She said "we need it by Sunday." The cope … and we'` → cut after the closing quote; `"(KES 45,000.) ships in a week. The stole is"` → cut after `week.`; a three-paragraph draft is cut at the end of its last whole paragraph sentence; `neema.co.ke/catalog` is not a boundary. The abbreviation/list shapes are finding 1; the answer-dropping shape is finding 2.
- `tier2_max_tokens` is 4096 (`app/core/config.py:419`), so a text-path `max_tokens` stop is rare in production; findings 1–2 are about what happens when it does.

**Claim 2 — a Messenger/Instagram turn reads the linked WhatsApp User's facts.**
- `select` and `User` are imported at module top (`memory.py:14`, `:20`). The lookup is inside `try/except Exception: pass` (`:160-170`); probe: `execute` raising `RuntimeError("boom")` on the user lookup → the person's own facts come back and the orders/measurements lookups still run (`['users', 'order_events', 'identities']`).
- No loop or double read: the WhatsApp branch (`store` is a `User`) reads the Person; the `elif isinstance(store, Person)` branch (Meta) reads the User. A WhatsApp turn never enters the reverse lookup (probe: `whatsapp, no person` → `['order_events', 'users']`, the second being the measurements read). Exact duplicates are dropped (`ctx.count("St Peter's") == 1` in the test holds); case variants are not (finding 6).
- Keys unchanged: `person_id = store.id` for Meta, `_recent_orders_summary(db, wa_id, person_id=…)` keys on `OrderEvent.person_id` (stamped on every order row, `app/agent/tools.py:1549`, and repointed on merge, `merge.py:29,68`); measurements go through `mm.get_measurements(db, wa_id, channel)`; parish through `parish_of_person(db, store.id)`. None of those lines moved in the diff. Instagram takes the same path as Messenger (probe).
- Mutation M1 (merge removed) is killed; M2/M2b/M3 survive (finding 7); M4 (`elif` → `if`) survives but is an equivalent mutant (`isinstance(User(), Person)` is False).

**Claim 3 — the eval loaders and the two `--file` paths.**
- `eval_floors --file blind_heldout.jsonl` → `120 cases / 459 turns (file:blind_heldout.jsonl)`, said 358/459 = 0.780, exactly the published blind "after"/"rescored" numbers. `--all` → 453 cases / 1243 turns; `--dev` → 217 / 616; `--held-out` → 236 / 627 (sum 1243; 217 + 236 = 453 as EVALUATION_DATASET says).
- No blind leak by any pattern: `load("*.jsonl")`, `load("*.json*")`, `load("[a-z]*.jsonl")` → 453 cases, 0 blind, 0 from `blind_heldout.jsonl`; `load("blind*.jsonl")` and `load("blind_heldout.jsonl")` → `[]`; `split(load())` → dev 217 / held 236, 0 blind in either; `load(include_blind=True)` → 573; every case in `blind_heldout.jsonl` is flagged `blind` and no case outside it is. Mutant E3 (loophole restored) is killed by `test_the_default_sweep_leaves_the_blind_set_out`.
- `run_cases` selection, exercised past the key check (fake key, `contact_for` replaced by a sentinel, `eval_cases.load` wrapped): `file="blind_heldout.jsonl", limit=1` → `load("blind_heldout.jsonl", include_blind=True)`, first id `blind-001`; `file=…, only="blind-01"` → first id `blind-010`; `file=…, only="sales-0"` → "no cases selected" (the `--only` prefix filter applies after the file, as documented); `selection="held-out", only="blind-"` (the pass-2 S2 reproduction) → still "no cases selected", i.e. the split can no longer reach the blind set by accident. The CLI `agent_eval --cases --file blind_heldout.jsonl --limit 1` (with `ANTHROPIC_API_KEY` unset) prints the "not set" line and exits 0 — but see finding 12 for why that alone is not evidence.

**Claim 4 — the comment-redelivery test now reads the statement.** All five predicate mutants are killed: S7b (compare the DM `channel`), S7c (drop the `waba_msg_id` term), S7d (compare `external_id` instead of `waba_msg_id`), S7e (compare the post id), S7f (drop the channel term). The test's `_RowDB.execute` compiles with `literal_binds` and answers only when both `messages.channel = '<ch>'` and `messages.waba_msg_id = '<id>'` appear (`tests/test_inbound_social.py:149-165`); the Instagram leg checks `'instagram'`.

**Claim 5 — the blind "before" number is real.** Reproduced in a throw-away worktree at main `ff8c3b5` with the `111ee6e` scorer and loader copied in, as BENCHMARK_RESULTS describes: `said 333/459 = 0.725 [0.683, 0.764]`, `lang 235/445 = 0.528 [0.482, 0.574]`, `length_kind 211/459 = 0.460`, `opt_out 31/34 = 0.912 [0.77, 0.97]` — every figure in the "Before (main)" column and in `results/floors-blind-before.json`. The register's `+40.2` (language) and `+5.5` / `+5.9` therefore rest on numbers that reproduce. What the docs still say wrongly is finding 11.

## Attack log — `trim_truncated` (probe `$V - <<EOF` with the shapes below)

```
abbrev e.g.                  cut=True  -> 'We have many colours, e.g.'
St. Peter's                  cut=True  -> 'Your parish is St.'
Rev. Fr.                     cut=False -> 'Rev. Fr. Otieno ordered the same set last'
numbered list mid            cut=True  -> 'Available:\n1. Cope\n2. Stole\n3.'
numbered list ends on 3.     cut=False -> 'Available:\n1. Cope\n2. Stole\n3.'
price mid-list               cut=True  -> '- Cope KES 45,000.\n- Stole KES 2,500.'
emoji end                    cut=False -> 'Karibu sana! Bei ya stola ni KES 2,500 🙏 Je, ungependa'
emoji after period           cut=True  -> 'Bei ya stola ni KES 2,500.'
french space-!               cut=True  -> 'Bonjour ! Le prix de la chape est de 45 000 KES.'
markdown bold                cut=False -> 'The cope set is **KES 45,000.** We also have the matching stole in'
url mid                      cut=True  -> 'See neema.co.ke/catalog for the full range.'
quote                        cut=True  -> 'She said "we need it by Sunday."'
bracket                      cut=True  -> 'The cope set (KES 45,000.) ships in a week.'
multi-para                   cut=True  -> 'Karibu! Thanks for asking.\n\nThe cope set is KES 45,000 and ships in a week.'
pleasantry then answer cut   cut=True  -> 'Thanks for asking, Moses.'
greeting then answer cut     cut=True  -> 'Asante kwa swali lako Moses!'
decimal                      cut=False -> 'It is 2.5 metres long and'
decimal end                  cut=False -> 'It is 2.5 metres long. The width is 1.'
time 10.30                   cut=True  -> 'We open at 10.30 am.'
etc.                         cut=True  -> 'We stock copes, stoles, chasubles etc.'
Mt. Kenya                    cut=True  -> 'Delivery to Mt.'
question only                cut=True  -> 'Ungependa rangi gani?'
ellipsis                     cut=False -> 'Hmm... the cope set is KES 45,000 and ships in'
no. 5                        cut=True  -> 'Order no. 5 is ready.'
P.O. Box                     cut=True  -> 'Send to P.O. Box 123, Nakuru.'
curly quote                  cut=True  -> 'It’s called “The Easter Set.”'
dash list no punctuation     cut=False -> 'Prices:\n- Cope KES 45,000\n- Stole KES 2,500\n- Chasuble KES'
newline-only boundary        cut=False -> 'Price is KES 2,500\nShall I add'
```

## Memory probe (`memory.build_memory_context`, fake store = a Person with `["Prefers black cassocks"]`)

```
SQL: SELECT users.id, … FROM users WHERE users.person_id = %(person_id_1)s::UUID LIMIT %(param_1)s   (no ORDER BY)
users.person_id unique? None  index True
case variant   -> 'Known facts:\n- Prefers black cassocks\n- prefers black cassocks'  calls ['users','order_events','identities']
lookup error   -> 'Known facts:\n- Prefers black cassocks'                              calls ['users','order_events','identities']
instagram      -> same as messenger
whatsapp       -> no reverse lookup                                                   calls ['order_events','users']
```

## E1 live (include_blind dropped from `eval_floors --file`, then restored byte-exact)

```
rc 0
case set: 0 cases / 0 turns (file:blind_heldout.jsonl); sources {}; critical 0
restored: True
```

## Mutation-test results

Script: `/tmp/claude-0/-home-user-neema-ai/2c406dec-643d-5176-808d-0adf5b06cc5b/scratchpad/mutate2.py` (mutate → run the named tests → reverse-replace restore → byte-equality and `git diff --quiet` per file). Every row ended "restored | clean". One earlier attempt at R2 used a non-unique replacement and was restored with `git checkout -- app/agent/runtime.py` (the file held no other change); the run below is the clean one.

| mutation | file | test | result |
|---|---|---|---|
| R1 `run_turn`: `trim_truncated` call removed | runtime.py | w2_w7::test_the_turn_cuts_a_max_tokens_draft_and_records_it | KILLED |
| R2 `run_turn`: `turn_facts["truncated"]` not set | runtime.py | same | KILLED |
| R3 `run_turn`: trim on any `!= "end_turn"` stop | runtime.py | both new tests | SURVIVED (equivalent for the test's two stops; informational) |
| R4 trim: min-length 12 → 1 | runtime.py | w2_w7::test_a_draft_cut_by_the_token_ceiling… | **SURVIVED** (finding 3) |
| R4b trim: min-length 12 → 30 | runtime.py | same | KILLED |
| R5 trim: a third → a tenth | runtime.py | same | **SURVIVED** (finding 3) |
| R5b trim: a third → a half | runtime.py | same | KILLED |
| R6 trim: "already whole" check removed | runtime.py | same | KILLED |
| R7 regex: closing quotes/brackets not allowed after the stop | runtime.py | same | KILLED |
| R8 regex: whitespace lookahead removed (decimal = boundary) | runtime.py | same | **SURVIVED** (finding 3) |
| R9 trim: returns the untrimmed text with cut=True | runtime.py | both new tests | KILLED (2 failed) |
| M1 memory: linked user's facts not merged | memory.py | test_agent_memory::test_a_messenger_turn_reads_the_linked_whatsapp_users_facts | KILLED |
| M2 memory: wrong column `User.id == store.id` | memory.py | same | **SURVIVED** (finding 7) |
| M2b memory: wrong column `User.wa_id == store.id` | memory.py | same | **SURVIVED** (finding 7) |
| M3 memory: lookup error no longer swallowed (`except ValueError`) | memory.py | same | **SURVIVED** (finding 7) |
| M4 memory: `elif` → `if` (reverse lookup also on WhatsApp) | memory.py | same | SURVIVED — equivalent mutant (store is a `User` on WhatsApp) |
| S7b dedupe compares the DM channel | meta_webhook.py | inbound_social::test_a_redelivered_comment_is_not_answered_twice_without_redis | KILLED (was SURVIVED in pass 2) |
| S7c dedupe drops the `waba_msg_id` term | meta_webhook.py | same | KILLED (was SURVIVED in pass 2) |
| S7d dedupe compares `external_id` instead | meta_webhook.py | same | KILLED |
| S7e dedupe compares the post id | meta_webhook.py | same | KILLED |
| S7f dedupe drops the channel term | meta_webhook.py | same | KILLED |
| E1 `eval_floors --file`: `include_blind=True` dropped | eval_floors.py | tests/test_eval_harness.py | **SURVIVED** (finding 8; live effect: 0 cases, exit 0) |
| E2 `eval_run --file`: `include_blind=True` dropped | eval_run.py | tests/test_eval_harness.py | **SURVIVED** (finding 8) |
| E3 loader: blind skipped only for the default pattern (pass-2 loophole back) | eval_cases/__init__.py | tests/test_eval_harness.py | KILLED |

Tally: 24 mutants; 14 killed, 2 equivalent (R3, M4), 8 genuine survivors (R4, R5, R8, M2, M2b, M3, E1, E2) — all test gaps, none a production defect by itself.

## Verdict

The four commits do what they say at the level the brief asked about: the trimmer cuts on `max_tokens` only, the gate and everything downstream see the trimmed text, `stop_reason` is present on every `LLMResponse` path including the two fallbacks, the Meta turn reads the linked user's facts best-effort without a loop and without moving the orders/measurements/parish keys, the loader keeps blind cases out of every pattern, both scorers reach the blind set through `--file` (120 cases / 459 turns, the published numbers, and the blind "before" column reproduces from main `ff8c3b5`), and the five predicate mutants of the comment dedupe are now killed. What does not hold is the quality of the cut itself: the sentence regex treats `St.`, `Mt.`, `e.g.`, `etc.` and a list number as sentence ends, so on a truncated draft the customer can receive "Your parish is St." or a list ending in a dangling "3.", and a pleasantry-first draft is cut down to the pleasantry with the price gone — two S2s in the one new behaviour that reaches customers, bounded in frequency by the 4096-token ceiling. The remaining findings are test gaps (the trimmer's thresholds and lookahead, the memory fake that cannot see the predicate or the error path, the unpinned `include_blind=True` on both `--file` paths, whose loss yields a silent zero-case run with exit 0), two labelling/process holes (a blind run's record says "held-out"/"all"; the "aggregate-only" blind result files carry every miss with the customer's words), and four doc lines that still frame the contaminated split as the report. Nothing blocks merge; findings 1–2 should be fixed before the trimmer is relied on, and finding 8 before any CI step trusts a blind-set exit code.


## Implementer's response (same day)

| Finding | Response |
|---|---|
| S2 #1 abbreviations and list numbers read as sentence ends | **Fixed.** `_sentence_ends` rejects a stop after an abbreviation (St., Mt., Rev., Fr., Dr., e.g., etc., months…), an initial, or a 1–3 digit list number. Tests on each. |
| S2 #2 the cut keeps the pleasantry and drops the answer | **Fixed.** `_settle_truncated`: when the dropped tail carried a figure, a currency or a question — or there was no whole sentence to keep — the turn asks once for the reply in words (the loop's own `_reply_in_words`) before settling for the cut or the draft as written. The facts record `truncation: cut|retried|kept`. Test through `run_turn`. |
| S3 thresholds and lookahead unpinned | **Fixed.** Tests pin the 12-character and one-third rules and the whitespace lookahead. |
| S3 for-else branch never inspected stop_reason | **Fixed.** Same settle on the ran-out-of-iterations branch. |
| S3 `_reply_in_words` ignores stop_reason | Recorded (its own text is not re-checked; a second ceiling hit is sent as written). |
| S3 memory `LIMIT 1` without order | **Fixed.** Newest `updated_at` wins. |
| S3 readers dedupe exact, writer case-insensitive | **Fixed.** `_union` compares as the writer does. |
| S3 memory fake blind to predicate and error path | **Fixed.** The fake compiles the statement (`users.person_id = …`) and a raising fake shows the person's facts survive a DB error. |
| S3 `include_blind=True` unpinned on the `--file` paths | **Fixed.** `select_cases(file=…)` tested; the floors CLI tested through `_cli` on the blind file (120 cases). |
| S3 empty run exits 0 | **Fixed.** Both scorers exit 2 on zero cases. |
| S3 blind run recorded as held-out/all, no `file` key | **Fixed.** `selection: file:<name>` and a `file` key in the record. |
| S3 "aggregate-only" blind JSONs carry every miss with the case text | **Fixed.** The floors scorer withholds misses for a blind file unless `--misses`; the three committed blind result files had their `misses` arrays removed without being read. |
| S3 four doc lines still frame the contaminated split as the report | **Fixed** (BENCHMARK_RESULTS "After W2" header and the two bold cells; INTERNATIONAL_ASSESSMENT twice; REQUIREMENTS_REGISTER R1.9; EVALUATION_DATASET command). |
| S3 `agent_eval --file --limit 1` key-line check vacuous | Noted; selection is tested directly. |
