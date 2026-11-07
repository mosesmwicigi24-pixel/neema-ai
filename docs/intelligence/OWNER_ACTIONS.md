# What only the owner can do — and exactly how

Everything below is blocked on access or a decision the implementer does not
have. Each item says what it unblocks and the exact step.

## 0. The API balance is exhausted (2026-11-07, ~06:30 UTC) — the live agent is down on it

Every model call returns `400 … Your credit balance is too low` since about
06:30 UTC. The box uses the same balance: the next customer message fails
until it is topped up (health will read `replies: failing, needs_a_human`).
The second blind pass^3 (run 42339309914) is VOID from model turn 794 on; the
slice-9c safety run lost its last four turns.

**Where the ~$137 went (estimate from the run records; the CI runs keep no
token log — the Console's Usage page has the exact split):** about 4,000
model turns of evaluation since 6 Nov 20:31 — the first blind pass that
crashed (~740 turns), your own box run (~400), the blind pass^3 (1,257), the
sales and safety readable runs (428), three safety-file runs (~310), and the
second pass^3's 794 turns before the wall. A turn is ~3 producer calls on
Sonnet 5.5 carrying the ~24k-token system prompt (cached) plus the Sonnet 5
reviewer and a Haiku pass: 3–4 cents. Live customer replies are a rounding
error (one gated reply today).

**Standing word (owner, 2026-11-07, 07:1x UTC): "Stop the evaluation run until I will ask. Stop all the passes until requested by me."** No evaluation run, pass^1 or pass^3 is dispatched, by hand or otherwise, until the owner asks. Verified at that time: no run in progress or queued; the eval workflow starts only by hand (no schedule, no push trigger); CI never calls the model; the only scheduled task on this account is the read-only shadow health read-out.

1. **Top up** (Plans & Billing). Nothing is dispatched until you say so.
2. **Set an evaluation budget.** For scale: a safety-file run ≈ $4; a sales
   run ≈ $11; a blind pass^1 ≈ $15; a blind pass^3 ≈ $45.
3. **Levers, none applied:** pass^1 for routine checks and pass^3 only for
   the headline; the workflow's `only` input to re-run just the cases a fix
   touches; trimming the system prompt (the dominant token on every call,
   production included).
4. **Exact production spend** (your box run and live traffic) on the box:
   `docker compose -f docker-compose.yml -f docker-compose.vps.yml exec -T db psql -U neema -d neema -c "select date_trunc('day', created_at) d, model, count(*) calls, sum(prompt_tokens) prompt, sum(cached_tokens) cached, sum(completion_tokens) completion, round(sum(cost_usd),2) usd from ai_usage where created_at > now() - interval '3 days' group by 1,2 order by 1,2;"`

## 1. Run the real-model evaluation (unblocks 7 of the 10 score dimensions)

**Update 20:00 UTC:** the repository secret is saved (thank you). The first
run crashed at start-up in the runner itself (not all database models were
registered); PR #319 fixes it, and the run on the fixed branch is already in
progress. Nothing more is needed from you for this item unless that run fails.

Pick one:

- **On the box** (the key is already in the api container's environment):
  ```
  cd /home/neema/neema-ai && sudo scripts/eval-blind.sh
  ```
  Takes the 120 blind cases through the real prompt, model, catalogue, cart
  and gate three times (sends sandboxed; no customer is messaged). Results
  land in `eval-out/` — copy the three files into `docs/intelligence/results/`
  (or send them to the next session) and the summary goes into
  BENCHMARK_RESULTS.md "Real-model baseline".
- **In GitHub**: add the repository secret `ANTHROPIC_API_KEY` (Settings →
  Secrets and variables → Actions), then run the workflow **Agent eval
  (model in the loop)** from the Actions tab. The results are the run's
  artifact `agent-eval-results`.

## 2. Save the dashboard credential (unblocks production-derived cases and the live flag values)

From a browser (the phone app only shows Allow/Deny): open this session,
approve the secure-form request for `neema.bethanyhouse.co.ke`, and enter
the dashboard login. Nothing is pasted in chat. This lets the session read
`/api/admin/conversations` (anonymised cases), `/api/admin/outreach/trace`
and `/api/admin/settings/prompt-inputs` (the 22 flag values).

## 3. Name people (unblocks the human-rated dimensions)

- Two raters for the rater packet (team members, not the developers) and a
  date; the packet is produced by step 1.
- Native speakers for the Swahili, French, Portuguese and Sheng cases
  (30–40 items each).

## 4. Decisions waiting in the registers

- The `/api/health` hub wait (one function; production behaviour).
- **A check promised yesterday that still cannot be done (the hub down):
  hand the thread to a person, or keep it and ping the team?** The safety
  case `safe-032` is labelled "hand to a colleague"; the system's
  `check_availability` tool is designed NOT to park the thread ("a thread
  parked in human mode is one nobody answers") — it records the demand,
  drops a 🔎 note in the thread, pings the team and keeps the customer. The
  model does the second on every run. Say which is right: if the design,
  the label changes to `answer` with the team check required; if the
  label, the tool (or the prompt) must hand over when the same check was
  already promised. Nothing changes until you say (slice 9c R1).
- **Chinese, Arabic and other unsupported languages: a person, or an answer
  in their language?** The prompt today says a customer writing another
  language gets their own language, and the model does that (it answered a
  Chinese and an Arabic enquiry with hub prices). The safety cases were
  written the other way: hand such a chat to a colleague. Say which; the
  labels or the prompt line follow.
- **Whether an explicit "I want a person" hands the thread over before the
  model runs.** A deterministic detector (English, Swahili, French,
  Portuguese forms of "talk to a real person / put me through / can someone
  call me / am I talking to a robot") fires on 0 of 1,656 non-hand-over
  turns across both case sets. It would force human mode — Neema stops
  replying on that thread until a person does — and it covers 1 of the 5
  measured hand-over failures (the other 4 are judgement calls: bank
  details, supplier documents, an account, artwork). Say "build the person
  door" and it ships; otherwise the model keeps the decision.
- **Whether the reply gate's language finding becomes hard.** Today an
  English draft answering a Swahili / Hindi / French / Portuguese line gets a
  rewrite request and, if the rewrite is still English, goes out with a note.
  Over the whole first real-model pass the finding fired 4 times, all correct,
  0 false. Hard would mean: still English after the rewrite → the hold DM (in
  Swahili where the customer wrote Swahili) and a flagged colleague, never an
  English reply to a Swahili customer. Say "make the language finding hard"
  and it ships with the next slice; otherwise it stays soft.
- An index on `messages.waba_msg_id` and a DB idempotency key for orders
  (migrations).
- Whether a DB error during Meta comment capture should make Meta redeliver.
- Whether the Business / Neema / Integrations settings panels get a server side.
- The four open outreach decisions carried from earlier stages.
- `NEEMA_CAPABILITY_INTELLIGENCE_PROFILE_2026.md` — add it under `docs/` if it exists.

## After the first real-model pass (2026-11-06, 23:00 UTC)

1. **Check the production enum** (read-only, 10 seconds). On the box:

   ```sh
   docker compose -f docker-compose.yml -f docker-compose.vps.yml exec -T db \
     psql -U neema -d neema -c "select enum_range(null::interceptaction);"
   ```

   If the list lacks `flag` or `escalated`, every opt-out record, held-reply
   flag and escalation write on the box has been failing silently (each is
   wrapped in a try) — and, until slice 8 R1 is live, a live turn's
   thread probe could abort the turn the same way the evaluation runs'
   turns aborted (reproduced; the probe is a SELECT on those labels). That
   production replies are flowing suggests the box HAS the labels; this
   command is the proof. **Approved and shipped (2026-11-07):** migration
   a9c1e3f5b7d9 adds both labels (`ADD VALUE IF NOT EXISTS`, idempotent);
   the box applies it at the next container start. Run the command once
   after the deploy to confirm the list now has `flag` and `escalated`.
   The safety-file run after the deploy (42341837242) could NOT stand in
   for this check: its seven opt-out turns failed for a reason inside the
   evaluation runner (slice 9b), and the run never reached the enum. This
   line stays the only direct proof on the box; CI's new real-database
   test proves the write on a database built from the migration chain.
2. **(The CI pass^3 is in: 54/120 = 0.450, BENCHMARK_RESULTS.)** **Send the box run's files** (`eval-out/agent-eval-blind-7670de1-*.json` and `.log`) — they are the second independent measurement, on the production database.
