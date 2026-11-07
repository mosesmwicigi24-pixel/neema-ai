# What only the owner can do — and exactly how

Everything below is blocked on access or a decision the implementer does not
have. Each item says what it unblocks and the exact step.

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
   wrapped in a try). Approving the one-line migration (`ADD VALUE IF NOT
   EXISTS`, idempotent, no table rewrite) fixes it; say "approve the enum
   migration" and it ships with the next slice.
2. **Send the box run's files** (`eval-out/agent-eval-blind-7670de1-*.json` and `.log`) — they are the second independent measurement, on the production database.
