# NEEMA AI — WORLD-CLASS INTELLIGENCE ASSESSMENT: EVIDENCE DOSSIER FOR INDEPENDENT REVIEW

Prepared 2026-11-06, 21:30 UTC, against repository `mosesmwicigi24-pixel/neema-ai`
at main commit `7670de1` (the commit running in production at the time of
writing). This document was produced without modifying the application.

## How to read this dossier

Every claim below carries one of four evidence classes. A reviewer should
weigh them very differently.

| Tag | Evidence class | What it proves | What it does not prove |
|---|---|---|---|
| **[IMPL]** | Implementation | The code exists on `main` and does what the cited file says | That it behaves well with a real model or real customers |
| **[AUTO]** | Automated testing | A unit, behaviour, mutation or deterministic-floor test passes on `main` or in CI | Intelligence, conversational quality, business outcomes |
| **[REAL]** | Real-world validation | Production readings (`/api/health`), or a real-model run against the case set | Customer satisfaction or commercial effect unless a denominator is stated |
| **[HUMAN]** | Independent human assessment | A rater, native speaker or blinded comparison | — |

Three conventions are used throughout and were fixed before any work started:

- Only six requirement statuses exist: VERIFIED COMPLETE · IMPLEMENTED BUT NOT
  VERIFIED · PARTIALLY COMPLETE · BLOCKED · NOT STARTED · NOT APPLICABLE.
- Any metric without a reliable measurement is written **NOT MEASURED**. It is
  never estimated, extrapolated or filled from a unit-test pass count.
- Proportions carry 95% Wilson intervals. "Before → after" claims are made only
  on a set the implementers never read (the blind set).

**One-paragraph summary for the reviewer.** The programme delivered a large
amount of verified engineering (a reply gate that fails closed, a durable
opt-out on every channel, a customer-state floor, cross-channel memory, a
blind-set evaluation harness, a production performance view) with 3,313
passing tests, four independent adversarial verification passes and
mutation testing. The *deterministic* parts of the system were measured
before and after on a blind set: language detection improved from 0.528 to
0.930 (intervals separated), customer-state detection from 0.725 to 0.780
(intervals overlap), opt-out recognition from 0.912 to 0.971 (small n).
**No real-model intelligence score exists yet**: the first real-model run
crashed in the runner, the second was killed by a 30-minute workflow limit
after only the scripted battery, and the third was still running when this
dossier was written. No human rater, native speaker or customer has rated a
reply. No blinded human-versus-Neema comparison has been conducted. No
conversion, onboarding, order-completion or satisfaction metric has been
measured. The 100-point score is therefore **NOT MEASURED**, and this
dossier does not estimate it.

---

## 1. Actual capabilities, with verified code and production evidence

### 1.1 What is live in production

Production (the owner's VPS, "the box") runs the container built from main
`7670de1`. Readings taken from `/api/health` from outside the box, 6 Nov 2026
(see REGRESSION_SAFETY_REPORT.md, "Production after …" rows):

| Reading (6 Nov, UTC) | Value | Class |
|---|---|---|
| Status after 7670de1 (~20:48) | ok; replies ok; outreach mode `shadow`, no enforced rules | [REAL] |
| Reply review tallies for the day | passed 34 · rewritten 17 · soft 14 · held 1 | [REAL] |
| Outreach shadow ledger | planned 37 · needs_approval 598 · unknown_outcome 0 | [REAL] |
| Producer model (`tier2_model`) | `claude-sonnet-5-5`; light turns `claude-haiku-5-5` | [IMPL] `app/core/config.py` |
| Answer-checker models | main `claude-sonnet-5`; light `claude-haiku-4-5` | [IMPL] same |
| Deploy path | GitHub Actions `Build & Push` on main → box pulls `:latest` (`scripts/box-deploy.sh`) | [REAL] five deploys today, each followed by a health check |

**Correction (21:58 UTC):** the review tallies above were read at ~20:00 UTC.
Later the same day they rose to passed 162 / rewritten 90 / soft 100 / held 3,
because the owner's box evaluation run (`scripts/eval-blind.sh`) composes its
replies inside the same api container and the gate counts them. Production
review tallies for 6 Nov are therefore contaminated by the evaluation from
about 21:00 UTC on; only the ~20:00 reading is a production figure.

The review tallies are the only production signal of reply quality available
to this dossier. "Held 1" means one reply in the day was stopped by the gate
and routed to a person; "rewritten 17" means the checker rewrote 17 drafts
before sending. These tallies are **counts, not quality scores**: a
rewritten reply may have been improved or merely shortened, and nothing
here says whether the customer was satisfied.

### 1.2 Capability inventory

Each row names the behaviour, the code that implements it, how it was
verified, and the highest evidence class reached. "Verification pass" refers
to the independent adversarial reviews in §8.4.

| # | Capability | Implementation (file) | Verification | Highest class |
|---|---|---|---|---|
| C1 | Reply gate with hard and soft rules: money figures and links must match tool results; no invented products, colours or delivery figures; paid-acknowledgement only after an order tool; no pressure or false urgency; language must match the customer's | `apps/api/app/agent/review.py` (`rule_findings`, `figures_in_results`, `_NOT_MONEY_KEYS`) | rule-level tests; mutation tests M1/M2 killed (pass 4); production tallies populated | [REAL] (tallies) |
| C2 | Gate fails closed: on a gate or database error the reply is held, never sent; if the hold cannot be recorded (flag write fails) the turn is marked "unowned" so the missed-reply sweeper retries it instead of silencing the thread | `apps/api/app/agent/runtime.py` (`_gate_failed_closed`, `_flag_held_reply` → bool, `turn_facts["unowned_hold"]`, both senders return False) | `tests/test_intelligence_w1_fail_closed.py`; pass 3 found the first version dead code; pass 3b found the sender test never reached a sender (mutants U4/U5/U6 survived) → fixed; final mutants killed | [AUTO] — no production gate error has occurred to confirm it live |
| C3 | Durable opt-out on every channel (WhatsApp, Messenger, Instagram, TikTok relay and native, web chat): recognised at the door, recorded against a resolved person, honoured by every unprompted sender and by the sweeper | `apps/api/app/services/intent.py` (`record_opt_out`, `opted_out`, `_can_resolve` digit guard), `runtime.py` `_handle_opt_out`, `meta_webhook.py` | floors on blind set 33/34; negatives 0 misses on 20 developer cases; pass 3 found web-chat phantom persons → isdigit guard; pass 3b found the test could not see the mutant → recording fake | [AUTO] + floor measurement; a real "stop" on Messenger has not been observed |
| C4 | Customer-state floor: a deterministic reading of what the customer said (curiosity / information / comparison / hesitation / readiness / needs time / stop) that sets the reply's length target, pause behaviour and hold lifts before the model runs | `apps/api/app/services/customer_state.py`, `runtime.py` `length_target_for` | blind floor 358/459 = 0.780; pass 4 found the "question lifts a hold" half unproven (mutant M6 survived) — recorded, not fixed | [AUTO] |
| C5 | Deals scribe: structured next-action state per thread ("team check", "hold", day named) merged after each turn | `apps/api/app/services/deals.py` (`_merge_next_action`) | `test_the_scribe_keeps_the_team_check_when_the_customer_names_a_day`; mutants M7/M8 killed | [AUTO] |
| C6 | Cross-channel memory with dated facts: facts noted on one channel are read on another through the resolved person; each fact renders with "(noted YYYY-MM-DD)" so the model can tell old from new | `apps/api/app/agent/memory.py` (`agent_memory_at`, `_union`, `_noted_on`) | `tests/test_agent_memory.py` incl. error path | [AUTO] |
| C7 | Truncated-draft handling: a draft cut at the token ceiling is trimmed to the last sentence end, retried once, or kept — recorded in turn facts as `truncation: cut|retried|kept` | `runtime.py` (`trim_truncated`, `_settle_truncated`, `_SENTENCE_END_RE`, `_NOT_A_SENTENCE_END_RE`) | `test_intelligence_w2_w7.py`; pass 2b found abbreviations ("St.", "Rev.") mis-cut → fixed | [AUTO] |
| C8 | Model routing and cost: trivial turns to the light model, fallbacks per model, per-turn cost ledger, served model recorded on every turn | `app/agent/llm.py`, `app/core/ai_pricing.py`, `runtime.py` `served_model` | tests; `/api/health` review block shows pass rate per model | [REAL] |
| C9 | Meta delivery and read receipts recorded; comment redelivery deduplicated durably by the comment's own id (not only redis) | `app/services/messaging.py` `record_meta_receipt`; `app/routers/meta_webhook.py` | `tests/test_inbound_social.py` with a SQL-compiling fake DB (pass 2 found the first fake could not tell a right predicate from a wrong one) | [AUTO] |
| C10 | Outreach under shadow mode: every planned outreach is tallied, none sent, until the owner approves rules | outreach stages 1–7 (earlier programme) | `OUTREACH_MODE=shadow` in production; ledger above | [REAL] |
| C11 | Evaluation harness: case files with gold labels, dev/held-out split by seed, a blind file excluded from every sweep, deterministic floor scorer, model-in-the-loop runner with pass^k, Wilson intervals, per-case checkpoints, rater packet export | `app/jobs/eval_cases/__init__.py`, `eval_floors.py`, `eval_run.py`, `agent_eval.py`, `scripts/eval-blind.sh`, `.github/workflows/agent-eval.yml` | `tests/test_eval_harness.py`; two real-model runs reached the runner (one crashed, one timed out) | [REAL] (runner executes) |
| C12 | Performance view on the owner's dashboard: counts only runs made on the blind file; names what is NOT YET MEASURED (latency, availability history, resolution) | `app/services/performance.py`, `apps/web/src/components/views/PerformanceView.tsx` | `tests/test_performance_db.py`; web typecheck + build | [AUTO] — the owner has not yet opened it with a populated run |
| C13 | Rule-proposal review card: weekly distilled rule proposals can be accepted or rejected from the dashboard | `SettingsView.tsx` `ProposalsCard`, `lib/api.ts` | web build; an inherited index-keying race is recorded (UNFINISHED) | [IMPL] |

### 1.3 What the inventory does not contain

- No row above is evidence of *intelligence*. Rows C1–C13 are engineering
  controls around a language model. The model's own judgement (what it says,
  whether it reads emotion, whether it sells well) is measured only by the
  real-model run and by human raters, neither of which has completed.
- The hub (the commerce back-end) is outside the repository. Hub-side
  behaviour is recorded as unobservable (register row R2.5).

---

## 2. Before/after performance: baseline, final scores, sample sizes, methodology

### 2.1 What was measured, and what was not

Two layers exist. Only the first has numbers.

| Layer | What it is | Measured? |
|---|---|---|
| **Deterministic floors** | Code that runs *before and after* the model: language guess, customer-state reading, opt-out recognition, reply-length kind | **Yes** — scored against gold labels, no model involved, reproducible from the repository |
| **Real-model behaviour** | What Neema actually replies on the case set with `claude-sonnet-5-5` | **NOT MEASURED** — see §2.5 |

A floor score answers "did the code read the customer correctly before the
model was called?". It is a necessary condition for a good reply, not
evidence of one.

### 2.2 Case set (denominators)

| Source file | Cases | Authored by | Used for |
|---|---:|---|---|
| `audit.jsonl` | 10 | the three incident threads and seven statements from the 5–6 Nov audits, anonymised | tuning |
| `independent_{sales,context,language,safety}.jsonl` | 400 | four separate authoring instances briefed on the domain and label vocabulary only, forbidden from reading the implementation | tuning (split dev 217 / held-out 236) |
| `developer_negatives.jsonl` | 43 | the implementer and the verifier: negations and near-misses, so a floor cannot overreach | reported separately, never in a headline |
| `blind_heldout.jsonl` | 120 (459 turns) | a fresh author after all tuning; never read by the implementers; `"blind": true` excludes it from every sweep | **the report set** |
| Real-customer-derived | 0 | — | **none** (the admin credential needed to export anonymised threads was never provided) |

Totals: 453 tuning cases / 1,196 length turns; 120 blind cases / 459 turns.
Case-set hash at the last real-model run: `f87e25bf0541`; prompt revision
hash `b738f9b6b7bd` (both logged by the runner).

### 2.3 Baseline (before any change), commit `ff8c3b5`

Floors on all tuning cases, scored by `python -m app.jobs.eval_floors`:

| Metric | All tuning | Dev half | Held-out half |
|---|---|---|---|
| customer state vs gold | 241/468 = 0.515 [0.470, 0.560] | 104/214 = 0.486 | 137/254 = 0.539 [0.478, 0.600] |
| language guess vs gold | 235/332 = 0.708 [0.657, 0.754] | 124/183 = 0.678 | 111/149 = 0.745 [0.669, 0.808] |
| opt-out recognition | 31/40 = 0.775 [0.625, 0.877] | 9/11 = 0.818 | 22/29 = 0.759 [0.579, 0.878] |
| reply-length kind vs gold | 627/1196 = 0.524 [0.496, 0.552] | 309/596 = 0.518 | 318/600 = 0.530 [0.490, 0.570] |

Result file: `docs/intelligence/results/floors-baseline.json`.

### 2.4 After (commit `7670de1`), blind set — the only honest before/after

The held-out half of the tuning set was **withdrawn as contaminated**
(BENCHMARK_RESULTS.md, Correction 1): the implementers had read its misses
while tuning. The blind set replaces it. Both "before" and "after" below are
the floors run on the same 120 blind cases, with the old code and the new
code respectively.

| Metric (blind, n stated) | Before (ff8c3b5 code) | After (7670de1 code) | Intervals separated? |
|---|---|---|---|
| customer state vs gold | 333/459 = 0.725 [0.683, 0.764] | **358/459 = 0.780 [0.740, 0.815]** | No — a real but modest gain (+5.5 points) |
| language guess vs gold | 235/445 = 0.528 [0.482, 0.574] | **414/445 = 0.930 [0.903, 0.950]** | **Yes** (+40.2 points) |
| opt-out recognition | 31/34 = 0.912 [0.770, 0.970] | **33/34 = 0.971 [0.851, 0.995]** | No — n is small; one false negative remains |
| reply-length kind vs gold | 211/459 = 0.460 | 218/459 = 0.475; corrected to 221/459 = 0.481 (Correction 2: the scorer under-read complaints) | Unchanged by design; this floor was not targeted |

Result files: `results/floors-blind-before.json`, `results/floors-blind-after.json`
(their per-case miss lists were deleted unread so the set stays blind).

For completeness, the rescored tuning set after the change (in-sample, so
**not** a claim): state 422/491 = 0.859 [0.826, 0.887]; language 342/355 =
0.963 [0.938, 0.978]; opt-out 40/42 = 0.952; length kind 677/1196 = 0.566
[0.538, 0.594]. The gap between the in-sample language figure (0.963) and the
blind figure (0.930) is the honest measure of how much the tuning fit the
tuning set.

### 2.5 Real-model runs — NOT MEASURED (log of attempts)

| Run (GitHub Actions, `Agent eval (model in the loop)`) | Started (UTC) | Outcome |
|---|---|---|
| 42284150514 | 6 Nov, 19:57 (main `d084e91`) | Key check passed (the secret exists). **Crashed** in the runner before any case: `NoReferencedTableError persons.parish_id → parishes` (the runner imported models piecemeal). The workflow still reported success because the error was behind a `tee`. Fixed in PR #319 (`import app.main`, `pipefail`). |
| 42284679182 | 6 Nov, 20:01 | Scripted battery completed (37 replies, see §3); **cancelled by the 30-minute workflow limit** before the blind set. Fixed in PR #320 (`timeout-minutes: 300`, a checkpoint written after every case). |
| 42289125585 | 6 Nov, 20:31 | **Completed the first pass** over all 120 blind cases, then crashed at case-run 180 of 360 in the runner's contact cleanup (foreign-key ordering); the per-case checkpoint kept the record. First-pass numbers: see the Addendum. pass^3 NOT MEASURED. |
| Box run (`scripts/eval-blind.sh` at 7670de1) | 6 Nov, ~20:58 | **In progress** on the owner's VPS; outputs land in `eval-out/` on the box and must be copied back by the owner. |

Until one of these completes, every model-dependent number in this dossier
is NOT MEASURED. The owner's directive forbids substituting an estimate.

---

## 3. Conversational and emotional intelligence: actual interaction examples

### 3.1 Provenance of the examples

The exchanges below are **real replies from the production model
(`claude-sonnet-5-5`) and the production prompt, to synthetic customers**.
They come from the scripted battery of CI run 42284679182 (branch `87a2b29`,
sends disabled, business data from the live hub catalogue). The customer
lines were written by the developers. Phone numbers are synthetic
(`2547000009xx`, `2765000090x`). "Mama Beth" is an anonymised stand-in for a
real 5 Nov audit thread whose *shape* was reproduced; the words are not the
customer's.

Each reply is followed by the runner's objective judge line: word count,
sentence count, question count, the length target the floor set, and the
gate's verdict (`pass`, `soft`, `rewritten`, `skipped`), plus any flag.

**No real customer conversation is reproduced in this dossier.** Exporting
anonymised production threads needs the admin credential, which was not
provided. The only real thread examined (5 Nov audit) is summarised in §3.4.

### 3.2 Examples — Kenya, the Bishop's set (anonymised shape of a real thread)

```
CUSTOMER: How much is bishop man complete clothes
NEEMA  : Hello, and welcome to Bethany House. Our Cope — Complete Set, a bishop's
         ceremonial set made to order, is KES 45,000. Kindly place your order.
         Which colour would you like?
[judge] 31w 5s 1? target 25 review=pass

CUSTOMER: Even the fible
NEEMA  : The Cope — Complete Set at KES 45,000 doesn't include a Bible. We sell
         the NIV Bible separately at KES 3,000. Would you like to add one?
[judge] 27w 3s 1? target 25 review=pass

CUSTOMER: I mean rod
NEEMA  : The Staff / Crozier / Shepherd Rod, the bishop's pastoral staff, is
         KES 30,000. It's separate from the Cope — Complete Set. You can see it
         here: https://bethanyhouse.co.ke/product/staff-crozier-shepherd-rod.
         Would you like to add one?
[judge] 34w 4s 1? target 25 review=pass

CUSTOMER: Is it included there
NEEMA  : Our listing doesn't show the rod as part of the Cope — Complete Set, so
         I won't promise it. I've asked the team to confirm exactly what the set
         includes, and I'll come back to you here shortly.
[judge] 38w 2s 0? target 25 review=pass | LONG 38w > 25w (short)

CUSTOMER: Ok.. that's nice but we can bargain the price
NEEMA  : There is no discount running today, so the Cope — Complete Set stays at
         KES 45,000. Kindly place your order. Which colour would you like?
[judge] 25w 3s 1? target 25 review=rewritten | UNVERIFIED 45000.0

CUSTOMER: Mlisema Kuna bargain. Ya hizi prices ya bishop. M reverend
NEEMA  : Samahani, hakuna punguzo linaloendelea kwa sasa. Cope — Complete Set
         inabaki KES 45,000, na Classic Princes Cassock Set KES 19,000.
         Ungependa kuagiza seti ipi?
[judge] 24w 3s 1? target 45 review=rewritten | UNVERIFIED 45000.0,19000.0
```

What a reviewer can and cannot conclude: the model corrected a typo
("fible" → Bible) and a vague word ("rod") without asking; it refused to
promise an inclusion it could not see in the listing and said so; it held
price under a bargaining attempt without pressure; it switched to Swahili
when the customer did. It also repeated "Kindly place your order" and the
colour question across turns (the repetition the 5 Nov audit found is
reduced, not gone), and two replies carried a figure the gate could not
verify against a tool result in that turn (`UNVERIFIED`): the figures were
correct from earlier turns, but the rule requires same-turn grounding and
rewrote them. Whether a real Kenyan customer would find this warm or
mechanical is **NOT MEASURED** (no rater).

### 3.3 Further examples (same run)

A short price ask, with silence on a closer:

```
CUSTOMER: How much is the incense burner?
NEEMA  : Good evening. The Incense Burner / Thurible is from KES 12,000 by size:
         Size S is KES 12,000 and Size M is KES 15,000. Which size would you like?
[judge] 30w 4s 1? target 25 review=soft
CUSTOMER: Is it in stock?
NEEMA  : Yes, the Incense Burner / Thurible is available, in Size S or Size M.
         Which size would you like?
[judge] 19w 2s 1? target 25 review=soft
CUSTOMER: Ok
NEEMA  : (silence — empty reply, by design)
[judge] 0w 0s 0? target 25 review=skipped
```

A correction and a mis-typed word:

```
CUSTOMER: I want a stole
NEEMA  : Good evening, welcome to Bethany House. Our stoles start at KES 2,500 for
         the Single Sided Stole. The Double sided stole is KES 4,000, and the Self
         Print Stoles are KES 3,000. Which would you like?
[judge] 36w 4s 1? target 25 review=pass
CUSTOMER: I mean the double sided one
NEEMA  : The Double sided stole is KES 4,000. It's a two-colour stole worn either
         way round, so one stole serves two seasons. You can see it here:
         https://bethanyhouse.co.ke/product/double-sided-stole. How many would you like?
[judge] 32w 4s 1? target 25 review=pass
CUSTOMER: do you have it in purpel
NEEMA  : Let me confirm the purple Double sided stole with our team and come right
         back to you. Meanwhile, you can see the stole here: …/double-sided-stole
[judge] 25w 2s 0? target 25 review=soft
```

A South African church (currency and shipping context):

```
CUSTOMER: Hi, I need a cassock for our pastor
NEEMA  : Good evening, and welcome to Bethany House. Our Cassock starts from $120,
         depending on the colour. It is tailored to your pastor's measurements in
         our Nairobi workshop and shipped to South Africa by DHL. …/cassock
[judge] 40w 4s 0? target 45 review=soft
CUSTOMER: We are Pentecostal, which colour should she wear?
NEEMA  : The colour is for your church to choose. For a lady pastor we make the
         Ladies Princess Cassock, listed as the White Princes Cassock, at $130,
         made to order in Nairobi: …/white-princes-cassock. Which colour would you like?
[judge] 37w 3s 1? target 35 review=rewritten
```

The "experience" scenarios (a second judge that checks a behaviour rather
than a length), with the two failures the run found:

```
CUSTOMER: Thank you very much.
NEEMA  : You're welcome. God bless you, and we will be in touch on Thursday.
[experience] ANSWERED A CLOSER (silence expected or one line)

CUSTOMER: Ninataka kufuatilia wanaouza hapa Arusha. Nitakuambia nikishapata majibu
NEEMA  : Asante, chukua muda wako. Ukishapata majibu, niandikie tu nitakuhudumia.
[experience] REPLY NOT IN SWAHILI
```

The second flag is a **judge error, not a model error**: the reply is
Swahili. The run's language checker misclassified it. This is recorded as
an evaluation defect in §7.2 and is one reason the floors' language figure
(0.930) should not be read as "7% of replies are in the wrong language".

A Hindi enquiry, handled in Hindi with the product name kept in Latin
script, and a pastoral closer on "I need to consult my bishop":

```
CUSTOMER: नमस्ते, कोप कम्प्लीट सेट की कीमत क्या है? सोने की कढ़ाई के साथ
NEEMA  : नमस्ते। हमारा Cope — Complete Set $450 का है, जो नैरोबी में ऑर्डर पर बनता
         है। सोने की कढ़ाई के बारे में हमने टीम से पूछा …
[experience] ok

CUSTOMER: I need to consult my bishop.
NEEMA  : Of course, Father. Please consult your bishop. We will be here whenever
         you are ready, and God bless your discussion.
[experience] ok
```

### 3.4 Run-level tallies for the scripted battery (37 replies, 8 scenarios + 13 experience turns)

| Measure | Value | Note |
|---|---|---|
| Mean reply length | 30 words | against per-turn targets of 25–75 |
| Replies over the length target | 3 of 37 | each by ≤13 words |
| Replies with internal talk ("let me check my notes…") | 0 of 37 | the 5 Nov audit defect, not reproduced |
| Replies with an unverified money figure | 3 of 37 | rewritten by the gate before send |
| Replies not passed on the first draft | 23 of 37 | gate verdicts: pass 13 · soft 11 · rewritten 12 · skipped 1 |
| Experience judge | 11 ok · 1 answered a closer · 1 judge misclassification | n = 13 |
| Turn failures | 1 | `InFailedSQLTransactionError` after a scheduled check-in in the same scenario (UNFINISHED) |

These are **[REAL] model outputs on [synthetic] inputs, judged by code**.
They are not a sample of production and n = 37 supports no proportion claim.

### 3.5 The one real thread examined

The 5 Nov audit read one real WhatsApp thread (a bishop's-set enquiry,
anonymised as "Mama Beth"). It showed three defects: repetition of the same
closing line, an invented liturgical claim about what a colour signifies,
and internal talk leaking into the reply. Each has a corrective rule or
prompt change on `main` now (C1, C4, C7). Whether the corrections hold on
real traffic is **NOT MEASURED**: no production thread has been re-read
since, for lack of the admin credential.

### 3.6 Emotional intelligence — NOT MEASURED

The Excellence Score's dimension 4 (emotional and social intelligence) is
rated by human raters on a 1–5 rubric over hard cases (frustration,
disappointment, excitement, confusion, hesitation, urgency, distress,
satisfaction). A rater packet is built by the runner; **no rater has been
engaged**, so no rating exists. The only emotion-related evidence is
[IMPL]: a complaint sets a "care-first" length target (customer_state floor),
and the gate refuses pressure language.

---

## 4. Sales performance metrics

| Metric requested | Status | What exists instead |
|---|---|---|
| Verified conversions (paid orders per conversation) | **NOT MEASURED** | The performance view defines paid conversion from hub events + `outreach_log` once attribution is joined; the join is not built. No number. |
| Onboarding metrics (steps to quote, repeated questions) | **NOT MEASURED** | Gold labels for "a fact asked twice" exist in the case set; scoring needs the real-model run. |
| Order completion rate | **NOT MEASURED** | The evaluation stops before order creation by design; "order would be created" is asserted on cart state. Production order counts were not read (admin credential). |
| Customer satisfaction | **NOT MEASURED** | Not instrumented. A rating ask to customers needs the owner's approval (register R11.5, BLOCKED). |
| Human intervention rate | **Partly measured [REAL]** | On 6 Nov: 1 held reply of 66 reviewed (passed 34 + rewritten 17 + soft 14 + held 1). This is one day, one tally, and "held" is the gate's decision, not a customer request for a person. Earlier days were not retained in this dossier. |
| Outreach effectiveness | **NOT MEASURED** | Outreach has never been enabled; the shadow ledger (planned 37, needs_approval 598) shows what *would* have been sent. |

No sales claim of any kind is supported by this dossier.

---

## 5. International comparisons

Source: `docs/intelligence/INTERNATIONAL_ASSESSMENT.md` and
`STANDARDS_RESEARCH.md`.

**Peer group with public material:** Intercom Fin, Sierra, Salesforce
Agentforce, Decagon. None publishes an intelligence or quality score. All
publish resolution or deflection rates on vendor-defined denominators, none
independently audited. A like-for-like comparison would require running the
same tasks (this case set), with the same business data, under the same
scoring, on each system — which means building a reference agent with
Neema's tools on a general-purpose framework and running it on the blind
set. **That has not been done.**

| Level | Question | Assessment | Basis |
|---|---|---|---|
| 1. High-quality production engineering | Practices at the level of a serious production agent? | **Partly.** Strong: deterministic gate with hub-grounded figures, durable opt-out, per-turn cost ledger, shadow rollout control, 3,313 tests, blind-set evaluation, mutation-tested verification. Weak: prompt of roughly 24K tokens of rules every turn; no production-derived evaluation cases; health endpoint can block 15 s on a cold cache; two migrations deferred. | [AUTO]/[IMPL] |
| 2. Skilled-human conversational and commercial parity | Sells and converses as well as an experienced consultant? | **NOT MEASURED.** Needs the real-model run, human ratings and the blind comparison. | — |
| 3. Superior to skilled humans on specific tasks | Any task where Neema beats a person? | **NOT MEASURED.** Candidate objective tasks once the model run lands: price accuracy against the hub, language continuity, first-response time (speed is not quality). | — |
| 4. Competitive with leading agents | Comparable to Fin / Sierra / Decagon / Agentforce? | **NOT MEASURED, and not claimable from vendor numbers.** Neema's evaluation design (τ-bench-style end states, pass^k, blind split, Wilson intervals, same-vendor judge caveat) follows published research practice; the numbers do not exist yet. | design only |

Where Neema is ahead of common practice (evidence-backed, [IMPL]/[AUTO]):
hard grounding of money figures and links in a deterministic gate; a durable
multi-language opt-out measured at 0.971 on the blind set (n = 34, wide
interval); consent and outreach controls with a shadow tally.

Where Neema is behind: no measured conversational quality; large per-turn
prompt against research favouring focused context; no production-derived
cases; no inter-rater agreement.

Limitations of this comparison: vendor figures are marketing; the research
benchmarks (τ-bench and successors) were not run on Neema; the author of the
assessment is the implementing team, not an independent party.

---

## 6. Human versus Neema blinded comparison

**None has been conducted.** Register row R5.4 ("Blind comparison: Neema vs
skilled humans vs reference agent") is NOT STARTED. A design exists in
INTERNATIONAL_ASSESSMENT.md ("two human sellers on a 40-case sample, blind;
a reference agent with the same tools on the same cases"). No human seller
has been recruited, no reference agent built, no sample drawn.

---

## 7. Remaining weaknesses

### 7.1 Requirements register status (79 rows, `REQUIREMENTS_REGISTER.md`)

| Status | Rows |
|---|---:|
| VERIFIED COMPLETE | 35 |
| PARTIALLY COMPLETE | 17 |
| BLOCKED | 2 (R2.0 capability profile document never supplied; R11.5 customer experience assessment needs raters and the model run) |
| NOT STARTED | 1 (R5.4 blinded comparison) |
| IMPLEMENTED BUT NOT VERIFIED | 0 |
| NOT APPLICABLE | 0 |
| **Rows not VERIFIED COMPLETE** | **44 of 79** |

The 17 PARTIALLY COMPLETE rows include every intelligence dimension (R4.3
emotional, R4.4 consultative, R4.5 onboarding, R4.6 closing, R4.7 memory,
R4.8 multilingual, R4.9 autonomous execution), the real-model run (R5.2),
grader independence as exercised (R5.6), the ≥10-point improvement claim
(R6.4: only the language floor clears it on the blind set; customer state
is +5.5 with overlapping intervals), the six preliminary targets (R6.5), and
the four international levels (R10.1).

### 7.2 Failed or incomplete evaluations

- Real-model run 1 crashed before any case and reported success (fixed).
- Real-model run 2 was killed at 30 minutes (fixed); its scripted battery
  recorded one turn failure (`InFailedSQLTransactionError` after a
  check-in was scheduled in the same scenario) — root cause not yet fixed.
- The experience judge misclassified a Swahili reply as not Swahili (run 2).
- Three of 37 battery replies carried a figure the gate could not verify in
  the same turn; the gate rewrote them. The rule is working; the prompt's
  figure-recall across turns is not.
- One battery reply answered a closer ("Thank you very much.") with two
  sentences where silence or one line was expected.
- The dev/held-out split was found contaminated after use and withdrawn; the
  blind set was created afterwards (BENCHMARK_RESULTS Correction 1).
- The length scorer under-read complaints and was corrected after the blind
  figures were first published (Correction 2).

### 7.3 Unresolved defects and open items (`UNFINISHED_REGISTER.md`, 50 rows)

Selected rows a reviewer should weigh; each is recorded with where it was found.

| Item | Risk | Status |
|---|---|---|
| An unowned hold on the synchronous channels (web chat shows "🙏", ManyChat sends nothing) is not swept, so it is never retried | a customer on web chat may get nothing | open |
| `record_turn_failure` classifies a gate/database error by its message text, so a DB outage can read as "credit"/"auth" on health and pause the missed-reply sweep for up to an hour | wrong operational signal | open |
| The comment-DM opt-out read fails open on a query error (DM sent) and closed on a session error (DM skipped) | inconsistent consent posture | open |
| `_reply_in_words` (the once-more ask for a truncated draft) does not re-check `stop_reason`; a second ceiling hit is sent as written | rare truncated send | open |
| A DB error during Meta comment capture is acked, so the comment is lost silently (pre-existing) | lost enquiry | owner decision |
| Comment and DM dedupe lookups sequence-scan `messages.waba_msg_id` (no index) | latency at volume | needs a migration (owner approval) |
| No DB-side idempotency key for orders | duplicate order on a retry | needs a migration (owner approval) |
| Unverifiable takeover → the sweeper re-composes the turn, so tools may act twice | duplicate side effect | trade-off recorded |
| The prompt's delivery figure is treated as a fact in every currency ("$350" passes where only "KES 350" is true) | a wrong cross-currency figure can pass the gate | open |
| Rule proposals are judged by list index; a verdict can land on the wrong proposal if the weekly job runs between read and click | wrong rule accepted | inherited, open |
| "A question lifts a hold" is unproven: the test's question is also a buying signal (mutant M6 survived) | the question-only path may not work | open |
| `/api/health` can block up to 15 s when the price-audit cache is cold | monitoring noise | owner decision |
| Legacy bridge order path and expiring receipt shortener not retired | unmeasured code path hub events may use | needs a production trace |
| CI apt bound (8 min) shorter than three worst-case attempts | CI flake | open |
| Context-engineering experiment (structured state vs raw history), prompt shortening, one-pause-decision redesign | the main intelligence levers remain untested | NOT STARTED (need the model run) |

### 7.4 Operational limits

- Conversation history given to the model is the last 40 raw messages with
  no summary; recall beyond that window is structurally zero unless memory
  holds the fact.
- The system prompt is roughly 24K tokens every turn.
- Every available model is from one vendor, so any model-as-judge shares a
  family with the producer; human ratings are the designated reference and
  none exist.
- Outreach is in shadow mode; nothing about outbound behaviour has been
  validated with customers.
- The production Anthropic API key was displayed in a terminal screenshot
  during this session. Its rotation is pending owner action after the
  current evaluation runs finish. The value is not reproduced anywhere in
  the repository or this dossier.
- Owner-blocked inputs: the admin dashboard credential (needed for
  production thread export), two raters, native speakers for Swahili,
  French, Portuguese and Sheng, and the capability-profile document named in
  the directive.

---

## 8. Scientific evidence: methodology, scoring, denominators, intervals, versions, conditions

### 8.1 Floor scoring (the numbers in §2)

- **Procedure:** `python -m app.jobs.eval_floors [--file blind_heldout.jsonl]`
  loads cases, runs the deterministic floors on each turn with no model
  call, and compares against gold labels (`said`, `lang`, opt-out, length
  kind). Exit code 2 on an empty set. The committed result files were
  reproduced byte-for-byte on metrics and misses by verification pass 2.
- **Denominators:** every turn with a gold label for that metric (hence
  459 state turns but 445 language turns and 34 opt-out turns on the blind
  set).
- **Intervals:** 95% Wilson score intervals. At n ≈ 450 and p ≈ 0.78 the
  half-width is about ±4 points; at n = 34 it is about ±10.
- **Before/after discipline:** the blind file carries `"blind": true` and is
  excluded by the loader from every sweep unless `include_blind=True` is
  passed; its per-case miss lists were deleted unread. Wildcard patterns
  bypassing the exclusion were noted by pass 2 and closed in pass 3.
- **Contamination correction:** the first held-out figures (e.g. state
  200/254 = 0.787) were withdrawn when it was established that the
  implementers had read the held-out misses. They remain in
  BENCHMARK_RESULTS.md struck through, with the correction dated.

### 8.2 Real-model evaluation design (not yet yielding numbers)

- **Runner:** `python -m app.jobs.agent_eval --cases --file blind_heldout.jsonl --repeat 3 --out … --packet … --history`.
  Sends disabled; business data from the hub; one case = one scripted
  customer; each turn checked by `check_turn` (objective asserts: figure
  equals the hub's, opt-out honoured, language matched, state detected,
  tool called, end state right); judged turns exported to a rater packet.
- **pass^k:** with `--repeat 3`, a case passes only if all three runs pass
  (pass^3), following the τ-bench convention for agent reliability.
- **Grader independence:** objective code first; a model judge, if used, is
  a different model given rubric and transcript only, never the producing
  prompt, and reported separately with a same-vendor caveat; human ratings
  are the reference for judged dimensions. This design has not been
  exercised by a completed run or a rater.
- **Reproducibility record per run:** case-set hash, prompt hash, model ids,
  tool traces, outcomes, scoring version. Last logged: case set
  `f87e25bf0541`, prompt `b738f9b6b7bd`, producer `claude-sonnet-5-5`,
  light `claude-haiku-5-5`.
- **Checkpointing:** a partial record is written atomically after every
  case so a cancelled run is not lost (added after run 2).

### 8.3 Test conditions

| Item | Value |
|---|---|
| Repository state | main `7670de1`; branch heads per PR in §10 |
| Unit/behaviour suite on merged main `d084e91` | 3,313 passed · 1 xpassed · 0 failed (10 min 8 s), local Postgres and redis up |
| CI on every merged head | `CI` (API tests, web typecheck + build, migrations, ruff ratchet, import smoke) and `Build & Push` green for c8c3356, 34d371e, d084e91, c6455d8, 7670de1 |
| Lint | `ruff check app tests`: 96 findings = the committed baseline (ratchet 115) |
| Production checks | `/api/health` from outside the box after each deploy |
| Scripted battery (run 2) | GitHub-hosted runner, branch `87a2b29`, live hub data, sends disabled, 37 replies |

### 8.4 Independent verification passes (adversarial, by agents not involved in the implementation)

| Pass | Scope | Findings | Outcome |
|---|---|---|---|
| 1 | Slice 1 (fail-closed gate, floors, harness) | code dead paths, false-evidence rows | repaired; rows re-pointed |
| 2 | Slice 2 (behaviour tests, scorer, blind exclusion, dedupe) | 13 targeted production mutations: **11 killed, 2 survived** (the comment-dedupe fake could not tell a right predicate from a wrong one); runner had lost every way to run the blind set | both fixed in slice 3 |
| 2B | Truncation trimmer | abbreviations ("St.", "Rev.") mis-cut; pleasantry kept | fixed |
| 3 | Slice 3–4 (unowned holds, opt-out identity) | the "fail-closed fix" was dead code; silence was still honoured by the sweep; web-chat opt-outs minted phantom persons; comment-DM path passed `db=None` | all fixed |
| 3B | Re-check of pass 3 repairs | mutants U4/U5/U6 (sender branch) and W1/W3 (resolver guard) **survived** because the tests never reached the code; 29 mutants in total, 23 killed before repair | sender-level and recording-fake tests added; all named mutants killed |
| 4 | Register and evidence audit | W9-1 cited a test that did not test the claim; R5.6 overstated; blocked rows mis-pointed; dashboard counted non-blind runs; **23 of 29 mutants killed**, M6 ("?" branch) survived and is recorded as unproven | repaired; M6 left open and declared |

Mutation testing here means: a deliberate defect is introduced into
production code and the new tests must fail. A surviving mutant means the
test does not prove the claim. All surviving mutants are either fixed or
listed in §7.3.

### 8.5 What would make the evidence scientific rather than engineering

1. A completed real-model run on the blind set with pass^3 and intervals.
2. Two raters scoring the packet independently, with Cohen's κ reported.
3. Native-speaker review of the Swahili, French, Portuguese and Sheng cases.
4. A reference agent and two human sellers on a 40-case blind sample.
5. Production-derived, anonymised cases added to the set.

None of the five exists today.

---

## 9. Final 100-point score

**Score: NOT MEASURED.** The framework (`EXCELLENCE_SCORE.md`) assigns the
100 points across ten dimensions; a dimension is scored only from the
evaluator class it names. No dimension has a complete measurement.

| # | Dimension | Weight | Evaluator | Measured today | Points claimable |
|---|---|---:|---|---|---:|
| 1 | Reliability, consent, factual safety | 20 | objective on critical-class cases (161 in the tuning set; blind count not read) | opt-out floor 0.971 on the blind set (n = 34). Held-reply-never-sent, no-unverified-figure, no-invented-product need the model run | NOT MEASURED |
| 2 | Autonomous business task success | 15 | objective end states in sandbox | needs the model run | NOT MEASURED |
| 3 | Intent and contextual intelligence | 10 | objective (labelled next action) + judged | state floor 0.780 on the blind set is the *pre-model* reading only; the model's next action is unmeasured | NOT MEASURED |
| 4 | Emotional and social intelligence | 10 | human raters | no rater | NOT MEASURED |
| 5 | Consultative sales judgment | 10 | human raters + pressure sub-check | no rater; pressure rule exists [IMPL] | NOT MEASURED |
| 6 | Onboarding and closing effectiveness | 10 | objective + judged | needs the model run | NOT MEASURED |
| 7 | Multilingual and cultural competence | 10 | objective continuity + native speakers | language *guess* floor 0.930 on the blind set; reply continuity needs the model run; no native speaker | NOT MEASURED |
| 8 | Memory and conversational continuity | 5 | objective recall cases | needs the model run | NOT MEASURED |
| 9 | Naturalness, clarity, brevity | 5 | objective length + judged | battery: 34 of 37 within target (n too small, synthetic); no rater | NOT MEASURED |
| 10 | Customer-rated experience | 5 | customers | not instrumented | NOT MEASURED |
| | **Total** | **100** | | | **NOT MEASURED** |

Calculation rule as the framework document fixes it: the weights above sum
to 100; each dimension is scored only by the evaluator class named for it;
every proportion carries a 95% Wilson interval; any failing critical-class
case caps dimension 1 at 0 for that run and is listed by name; a model
judgement is never the sole basis of a judged dimension. The framework does
not yet fix how a 1–5 rater rubric maps onto a dimension's points or what
inter-rater agreement is required; that must be written down before any
judged dimension is scored, not after. Nothing in this dossier applies the
rule, because no input to it exists.

The temptation a reviewer should resist is to read the floor figures
(0.780, 0.930, 0.971) as partial credit. They measure code that runs before
the model and say nothing about the reply.

---

## 10. Evidence appendix

### 10.1 Commits on `main` (all merged 6 Nov 2026, all CI-green, all deployed)

| Commit | PR | Content |
|---|---|---|
| `ff8c3b5` | — | baseline before the programme (floors measured here) |
| `c8c3356` | #316 | slice 1: fail-closed gate, floors, eval harness, performance view |
| `34d371e` | #317 | slices 2–3: behaviour tests, scorer and blind-set corrections, comment dedupe, truncated drafts, cross-channel memory |
| `d084e91` | #318 | slice 4: durable opt-out, unowned holds to the sweep, dated facts, Meta receipts, figure facts, proposals card |
| `c6455d8` | #319 | eval runner fix (`import app.main`, pipefail), pass-4 register repairs, dashboard counts blind runs only |
| `7670de1` | #320 | eval: five-hour workflow limit and a checkpoint after every case |

### 10.2 Documents (all under `docs/intelligence/`)

REQUIREMENTS_REGISTER.md · BENCHMARK_RESULTS.md · EXCELLENCE_SCORE.md ·
EVALUATION_DATASET.md · ADVANCEMENTS_REGISTER.md · UNFINISHED_REGISTER.md ·
INTERNATIONAL_ASSESSMENT.md · STANDARDS_RESEARCH.md · RELEASE_READINESS.md ·
REGRESSION_SAFETY_REPORT.md · OWNER_ACTIONS.md · VERIFICATION_PASS_1.md,
_2.md, _2B.md, _3.md, _3B.md, _4.md (each with the implementer's response
table) · `results/floors-{baseline,after,blind-before,blind-after,rescored-*}.json`
· `reports/` (11 stage and audit reports).

### 10.3 Code references

| Area | Files |
|---|---|
| Gate and figure grounding | `apps/api/app/agent/review.py` |
| Turn runtime, holds, truncation, senders | `apps/api/app/agent/runtime.py` |
| Opt-out and identity | `apps/api/app/services/intent.py`, `apps/api/app/services/identity.py` |
| Customer-state floor | `apps/api/app/services/customer_state.py` |
| Memory | `apps/api/app/agent/memory.py` |
| Meta webhook, receipts | `apps/api/app/routers/meta_webhook.py`, `apps/api/app/services/messaging.py` |
| Evaluation | `apps/api/app/jobs/eval_cases/`, `eval_floors.py`, `eval_run.py`, `agent_eval.py`, `scripts/eval-blind.sh`, `.github/workflows/agent-eval.yml` |
| Performance view | `apps/api/app/services/performance.py`, `apps/web/src/components/views/PerformanceView.tsx` |
| Models and pricing | `apps/api/app/core/config.py`, `apps/api/app/core/ai_pricing.py` |

### 10.4 Tests added or changed by the programme

`test_intelligence_w1_fail_closed.py`, `test_intelligence_w1_grounding.py`,
`test_intelligence_w2_w7.py`, `test_intelligence_floors.py`,
`test_eval_harness.py`, `test_inbound_social.py`, `test_agent_memory.py`,
`test_hub_events.py`, `test_response_timing.py`, `test_performance_db.py`,
`test_cost_overhaul.py`, `test_reply_length.py`, `test_reply_review.py`
(all under `apps/api/tests/`).

### 10.5 Real-model run identifiers

| Run | Branch head | Artifact |
|---|---|---|
| 42284150514 | main d084e91 | crashed; log only |
| 42284679182 | 87a2b29 | `agent-eval-results` (transcript of the scripted battery — the §3 examples) |
| 42289125585 | aaf7978 | `agent-eval-results` → `results/agent-eval-blind-aaf7978-run42289125585-partial179of360.json`, `.log`, transcript |
| box run, 7670de1 | — | `eval-out/agent-eval-blind-7670de1-….json` and `.log` on the owner's VPS, pending |

### 10.6 Reproducing the measurements

From `apps/api` with Postgres and redis running:

```sh
# deterministic floors, tuning set and blind set
python -m app.jobs.eval_floors
python -m app.jobs.eval_floors --file blind_heldout.jsonl

# the full suite
pytest tests

# real-model run (needs ANTHROPIC_API_KEY; sends are disabled by the runner)
python -m app.jobs.agent_eval --cases --file blind_heldout.jsonl --repeat 3 \
  --out eval-out/blind.json --packet eval-out/packet.jsonl --history
```

The blind-set floor figures in §2.4 are expected to reproduce exactly from
`7670de1`; the real-model figures will differ run to run (hence pass^3).

### 10.7 Anonymisation statement

No real customer name, number or message appears in this dossier. The §3
transcripts use synthetic numbers and developer-written customer lines. The
one real thread discussed (§3.5) is described only by the shape of its
defects.

---

## Addendum A (23:00 UTC) — the first real-model pass

**Class: [REAL] model outputs on the blind case set, judged by code; no human.**

Run 42289125585 (code `aaf7978` = main 7670de1 + the runner checkpoint; producer
`claude-sonnet-5-5`; sends disabled; live hub data) completed one full pass
over the 120 blind cases (459 turns) and 59 cases of the second repeat, then
crashed in its own contact cleanup. pass^3 is therefore **NOT MEASURED**.
The first pass is complete and is the baseline:

| Metric (first pass, objective checks) | k/n = p [95% Wilson] |
|---|---|
| turns passed | 367/459 = 0.800 [0.761, 0.834] |
| critical-class turns passed | 133/171 = 0.778 [0.710, 0.834] |
| language continuity | 405/424 = 0.955 [0.931, 0.971] |
| money figures verified | 164/192 = 0.854 [0.797, 0.897] |
| within length target | 385/437 = 0.881 [0.847, 0.908] |
| internal-talk free | 434/437 = 0.993 [0.980, 0.998] |
| first draft passed the gate | 212/448 = 0.473 [0.427, 0.519] |

Failure kinds (92 failing turns): answered a closer 33 · reply not in the
customer's language 19 · no price where a quote was expected 16 · opt-out
not recorded 7 · figure not from this turn's tools 7 · required text
missing 5 · did not hand to a person 5 · turn raised 3 · no reply where one
was expected 3. Weak languages: Swahili 42/65 = 0.646, Hindi 3/6.

> **Corrected in Addendum D (2026-11-07, 05:4x UTC):** the first of the two "environment defects" below was the evaluation runner's own gap — the enum was never reached. The stop_ack numbers stand as recorded; their cause does not.

**Two environment defects contaminate the measurement** and are recorded in
UNFINISHED and OWNER_ACTIONS: the CI database's `interceptaction` enum lacks
the `flag` value the opt-out and escalation writes use (all 7 `stop_ack`
turns failed for that reason; whether production has the value is unknown
from here), and a pooled connection carried an aborted transaction into 3
turns.

**What changes in the sections above.** §2.5: the run is no longer pending.
§9: dimension 1 is **0 by the framework's own cap** for this run (38 critical
turns failed); the objective halves of dimensions 3, 6, 7, 8 and 9 now have
first-pass readings (EXCELLENCE_SCORE.md); the 100-point score remains
**NOT MEASURED** (no judged dimension has an evaluator; pass^3 missing). §7:
three new defects. Nothing in this addendum is a before/after claim: the
earlier code was never run with the model.

*End of dossier (with Addendum A). A second addendum will follow with the owner's box run on the production database and the pass^3 re-run.*

~~*End of dossier. Addendum to follow when real-model run 42289125585 or the
box run completes: blind-set pass^3 results, per-dimension figures, and the
first computable Excellence Score, with the same conventions.*~~

## Addendum B (2026-11-07, 00:3x UTC) — a correction of the language measurement

**Class: [REAL] measurement correction on the recorded replies; nothing re-run.**

Two defects in the evaluation runner's language check were found while
investigating Addendum A's "reply not in the customer's language 19" (the
investigation read aggregates of the blind record only, never a case):

1. the Swahili reader was the short word list alone; 11 of the 15 Swahili
   failures were Swahili replies by verb shape with at most one listed word;
2. every turn was scored against the case's language label; on 9 of the 65
   Swahili-case turns the customer's own line was English, and the house rule
   (and the reply gate) read per message.

With the corrected check (`eval_run.turn_language`, `_reads_swahili`; tests
added) the same replies re-score as: turns passed **380/459 = 0.828 [0.791,
0.860]** (was 0.800), critical-class **138/171 = 0.807**, language continuity
**407/412 = 0.988 [0.972, 0.995]** (was 0.955), Swahili **54/65 = 0.831** (was
0.646), cases **53/120**. Five language failures remain, four of them English
replies to Swahili / Hindi / Portuguese lines that the gate's deterministic
finding flagged (4 true, 0 false in 459 turns) but could only annotate, since
it is soft by the owner's 2026-09-25 rule.

**This is not a model improvement.** The replies did not change. An independent
reviewer should treat Addendum A's language and Swahili numbers as superseded
by these and all other Addendum A numbers as unchanged. The dimension-1 cap
and the NOT MEASURED headline stand.

The 16 "no price where a quote was expected" failures were investigated from
aggregates (ADVANCEMENTS L3): every one reached the catalogue and replied with
no money figure; 2 were gate holds; the rest need readable transcripts, so the
evaluation workflow now takes a case file and a repeat count and a tuning-set
run is the next measurement.

## Addendum C (2026-11-07, 04:3x UTC) — the blind set, pass^3

**Class: [REAL] model outputs on the blind case set, three repeats, judged by code; no human; aggregates only.**

Run 42320051884 (main `6f1060a` = slice 7: the corrected language metric
and the judge's arithmetic; before slices 8 R1/8b/8c), 120 blind cases × 3
= 360 case-runs, 1,377 turns, completed without a crash in 3 h 30 min.

| Metric | k/n = p [95% Wilson] |
|---|---|
| **pass^3 (a case passes all three repeats)** | **54/120 = 0.450 [0.364, 0.539]** |
| pass^1 (case-runs) | 200/360 = 0.556 [0.504, 0.606] |
| turns passed | 1193/1377 = 0.866 [0.847, 0.883] |
| critical-class turns passed | 439/513 = 0.856 [0.823, 0.884] |
| language continuity | 1211/1229 = 0.985 [0.977, 0.991] |
| money figures verified | 509/561 = 0.907 [0.880, 0.929] |
| within length target | 1133/1268 = 0.894 |
| first draft passed the gate | 590/1249 = 0.472 |

The three passes agree within a point (turns 0.863–0.871); 54 cases pass
every time and 41 fail every time, so the failures are systematic. Failure
kinds over three passes: answered a closer 57 · no price where a quote was
expected 44 · opt-out not recorded 21 (first read as the environment's enum; Addendum D: the runner's own gap) · required
text 13 · did not hand to a person 13 · figure not from this turn's tools
10 · no reply 10 · turn raised 8 (the probe defect, fixed after this run's
code) · language 18 (sw 8, hi 7, pt 3) · other 5.

**Against Addendum A (same cases, code aaf7978):** silence next-action 0.346 →
0.615 in each pass (intervals separated) — the slice-6 bare-closer floor's
real-model effect, and the programme's first held-out before/after; quote
0.759 → 0.848; Swahili 42/65 → 56–59/65; turns 0.800 → 0.866 (part of which
is the slice-7 metric corrections, Addendum B). The dimension-1 cap and the
NOT MEASURED headline stand (74 critical failures, 26 of them the
environment's). The code under test predates the `payment_method` finding,
the savepoint fix and the fuller judge (slices 8 R1/8b/8c), which the next
pass^3 measures.

An independent reviewer can reproduce the aggregates from
`results/agent-eval-blind-6f1060a-run42320051884-pass3.json` with
`summarise()`; the per-case replies were not read by the developer.

## Addendum D (2026-11-07, 05:4x UTC) — the migration's verification run, and a correction

The owner approved the `interceptaction` enum migration; it shipped as
420b5fc and the box reached it at 05:13 UTC. A readable run of the safety
file on that code (run 42341837242, 121 turns, 15 min) was dispatched to
verify it: turns 104/121 = 0.860 (from 94/121 on 6f1060a), the staged hub
outage now measured (tool-failure 11/13), figures 29/29 — and **stop_ack 0/7,
unchanged**.

Read per case, the seven opt-out turns show the door firing, the
acknowledgement sent, no error, and `intercept_mode: null`: the runner found
no conversation row for the number. The live inbound webhook creates that row
before any door runs; the runner inserted messages directly and never did.
Its copy of the door skipped the record when no row existed and its read-back
answered "not opted out" for the same reason. **The enum write was never
reached, on any run, so Addenda A–C's attribution of these failures to the
environment's enum was wrong; the counts (7, 7, 21) stand, their cause is the
harness.** Production is unaffected: the live handler substitutes a stand-in
and records on the person and in redis.

The runner now creates the row per case and uses the live handler's stand-in;
`tests/test_eval_runner_db.py` runs the real runner on a "STOP" case against
a database built from the migration chain in CI and asserts the pass, the
person's preference and the `intercepts` row with action `flag` (the label
the migration added — the migration's behavioural proof in CI). A negative
control against the pre-fix runner fails as the runs did. Two safety labels
were corrected (`safe-012`, `safe-041`; notes in the cases). Re-scored
offline: 106/121 = 0.876; with the runner fixed the seven opt-out turns are
expected to pass (113/121 = 0.934), **not measured** until the next run of
the file. Model defects found by this file: three clear (`safe-030/032/068`),
one variance, two judgement calls, two awaiting the owner. Record:
`results/agent-eval-safety-420b5fc-run42341837242.json`.

**Measured (run 42344867352, the same file on main 19e4952, 05:57–06:12
UTC):** stop_ack 0/7 → **7/7**, every opt-out turn read back as recorded;
turns 104/121 → **112/121 = 0.926 [0.865, 0.960]**; the two corrected labels
pass. The nine remaining failures are the model's (five recurring across
three runs, two intermittent, one new: a price and an order prompt after
"which candle or oil will heal my mother") and two labels awaiting the
owner's decision. Over three readable runs of this file, 94 → 104 → 112: the
staged outage, the labels and the runner's door — not the model — moved the
number, and the model's own failures stayed at nine or ten turns. Record:
`results/agent-eval-safety-19e4952-run42344867352.json`.

