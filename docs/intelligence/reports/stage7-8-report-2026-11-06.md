# Stages 7 and 8 — the verification's corrections, and the access gaps

Both merged to main on 2026-11-06 at the owner's word. Stage 7 (PR #314 →
da18323) went live at 10:29 UTC. Stage 8 (PR #315 → ff8c3b5) merged at
~13:00 UTC; the box result is in the shadow log. `OUTREACH_MODE` stays
shadow; no rule is enforced. No migration, no configuration change, Android
untouched.

## 1. Where they come from

The FINAL AUDIT EXECUTION VERIFICATION (two passes, read-only, in
`audit-execution-verification-2026-11-06.md` and `…-v2-…`) found:

- eight send pathways that the original audit's inventory of 17 did not
  cover, five of which could message a customer without the opt-out check;
- my own Stage 1 claim "every unprompted sender checks the opt-out" was
  overstated (the test covered four senders);
- TikTok inbound rows carried no id into the overlap guard;
- the hub's order-confirmation relay was not stamped, so the trace called it
  a "live reply";
- a paid order withdrew the plain follow-up but not the buying follow-up;
- three items that could not be verified from this session: the box-side
  trace of the three incidents (Judas, Willy, Pastor Emmanuel), the stored
  prompt inputs, and a model-in-the-loop replay.

Stage 7 is the first five. Stage 8 is the last.

## 2. Stage 7 — files and what each corrects

| File | Correction |
|---|---|
| `app/jobs/seasonal_outreach.py` | opted-out contacts filtered out of the seasonal sweep before a row is planned |
| `app/services/missed_call.py` | opt-out lookup before the cooldown key; an opted-out caller gets no missed-call text |
| `app/services/recording_notice.py` | `OPTED_OUT` result; the notice is not sent to an opted-out contact |
| `app/agent/runtime.py` (`_run_comment_engage`) | opt-out check before `send_private_reply`; `_OptedOut` ends the engagement without a DM |
| `app/routers/tiktok_webhook.py` | the row id is minted first and passed as `inbound_id`, so TikTok gets the same overlap guard as WhatsApp and Meta |
| `app/services/messaging.py` (`_relay_order_confirmation`) | stamped `order_confirmation` / transactional, so the trace and the inbox badge name it |
| `app/services/actions.py` (`withdraw_routine`) | kinds now `follow_up`, `quote_follow_up`, `buying_follow_up` |
| `app/services/hub_events.py` | a paid order calls `withdraw_routine(why="order paid")` — every routine row, not one kind |
| `tests/test_outreach_stage1.py` | the opt-out test now asserts every unprompted sender, including the four Stage 7 added |
| `tests/test_outreach_stage7.py` (7), `tests/test_outreach_stage7_db.py` (2) | new |

## 3. Stage 8 — the three access gaps, from the dashboard side

| Gap | What exists now | Status today |
|---|---|---|
| Box-side trace of the incidents | `GET /api/admin/outreach/trace?handle=&days=` — `jobs/outreach_trace.collect()` as JSON: thread with origin stamp and delivery per outbound row, planned actions in every status, deal holds and team checks, contact preferences, customer state, redis guards. Admin-only, contact masked, read-only. | **endpoint live with ff8c3b5; read blocked on a credential** (below) |
| Stored prompt inputs | `GET /api/admin/settings/prompt-inputs` — standing orders, learned rules, house voice as fed to the prompt, with sizes against their caps, plus the assembled base-prompt size. Admin-only. | same |
| Model-in-the-loop replay | `jobs/agent_eval.py` EXPERIENCE set (the three threads and the seven statements) with transcript checks; `.github/workflows/agent-eval.yml` runs it by hand against a throwaway Postgres and redis and keeps the transcript. | **dispatched once (run 42222102230): stopped at its guard — `ANTHROPIC_API_KEY` is not a repository secret.** No model call was made. |

Supporting piece: `POST /api/auth/login-basic` reads the same username and
password from an `Authorization: Basic` header and returns the same tokens
as the normal login (access token 480 min), so a credential held by the
session's secrets proxy can mint a token without the password ever being
typed into a chat.

Tests: `tests/test_outreach_stage8.py` (4), `tests/test_outreach_stage8_db.py`
(3: trace over real rows, prompt inputs, Basic login through the real
router). Full suite before merge: 3065 passed, 1 xpassed. ruff 96 (ratchet
115). CI and Build & Push green on 81cdbfd.

## 4. What the owner has to do for the last three reads

The three permissions were authorized in chat, but each needs one action
outside this session:

1. **Dashboard admin login (for the trace and the prompt inputs).** The
   secure credential form for `neema.bethanyhouse.co.ke` was shown twice and
   nothing was saved. On a phone the prompt shows only Allow / Deny, and
   Allow saves nothing. Open this session at claude.ai/code in a browser or
   the desktop app and save the dashboard username and password in the form
   (type: Basic), or add it under the environment's settings as a network
   secret for that host. Never paste it into the chat.
2. **`ANTHROPIC_API_KEY` repository secret (for the replay).** GitHub →
   neema-ai → Settings → Secrets and variables → Actions → New repository
   secret. Then the workflow "Agent eval (model in the loop)" can be run from
   the Actions tab, or I run it. The alternative that needs no secret in
   GitHub is on the box:
   `docker compose -f docker-compose.yml -f docker-compose.vps.yml exec -T api python -m app.jobs.agent_eval`
   — paste the transcript (no numbers beyond the three test ones appear).
3. Nothing further is needed for the deploy itself.

## 5. Design decisions

- **Read-only endpoints, admin-only.** `_admin_only` on both; neither writes
  a row, and the trace masks the handle in its heading the way the CLI does.
- **Basic login is the same function, not a second password store.** It
  decodes the header and calls the existing check; a wrong pair fails the
  same way. It exists only so a proxy-held secret can authenticate.
- **The eval refuses to run without a key** rather than failing deep inside
  a model call, and it uploads the transcript whether or not it passes.
- **No retroactive stamp of old relay rows.** Rows sent before da18323 still
  trace as "live reply"; the report notes the date rather than rewriting
  history.

## 6. Still open (unchanged owner decisions)

- "pause after two unanswered" — scope not yet decided.
- the 360 parked rows older than 30 days — `python -m app.jobs.outreach_backlog --retire-older-than 30` when the owner says so.
- Android inbox fields (customer state, badge) — API exposes them; app untouched by instruction.
