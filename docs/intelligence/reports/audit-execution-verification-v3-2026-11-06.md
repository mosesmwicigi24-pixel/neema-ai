# Final audit execution verification — v3 (after Stages 7 and 8)

Supersedes the G and H sections of `audit-execution-verification-v2-2026-11-06.md`.
Sections A–F of v2 stand as written; this pass records what the two
correction stages changed about the outstanding list, and what remains. It
changes no production state. Stage 7 (da18323) is live; Stage 8 (ff8c3b5)
is merged and deploying at the time of writing.

## G. Outstanding verification requirements — status

| # | v2 item | Now |
|---|---|---|
| 1 | Box-side reconstruction of the three incidents | **Tooling live, read not yet run.** `GET /api/admin/outreach/trace` (ff8c3b5) returns the same facts as the box CLI, admin-only. The read needs the dashboard admin credential in the session's secure form; the form was shown twice and nothing was saved (see "What the owner has to do"). Attributions remain plausible, not proven. |
| 2 | The three stored prompt inputs and an assembled runtime prompt | **Tooling live, read not yet run.** `GET /api/admin/settings/prompt-inputs` (ff8c3b5). Same credential. The assembled base prompt was measured from files in v2 (95,313 chars, no truncation); the live inputs' sizes against their caps are what this read adds. |
| 3 | Opt-out enforcement on S5 (seasonal), E2 (missed call), X1 (comment DM); decision on R2 (recording notice) | **Done in Stage 7, live.** All four now check the person's opt-out before sending; R2 included on the safer reading (a recording notice is still an unprompted message). Test: `test_outreach_stage1.py` opt-out case now asserts every unprompted sender; `test_outreach_stage7.py` 1–3. |
| 4 | Safeguard review of X1, X3 (TikTok ids), X4 (order-confirmation stamping) | **Done in Stage 7, live.** X1 as item 3; X3 the TikTok row id now reaches the overlap guard (`test_tiktok_hands_the_row_id_to_the_turn`); X4 the relay is stamped `order_confirmation`/transactional (`test_the_order_confirmation_relay_is_stamped`). Rows sent before da18323 still trace as "live reply". |
| 5 | Model-in-the-loop experience test | **Harness live, run blocked.** `agent_eval.py` EXPERIENCE set + `experience_checks`; workflow `agent-eval.yml`. Dispatched once on main (run 42222102230): stopped at its own guard because `ANTHROPIC_API_KEY` is not a repository secret. No model call made, nothing sent. |
| 6 | Explicit tests: job-timeout retry; quotation updated after planning; all open rows vetoed on paid; takeover mid-composition | **Three of four exist.** `test_a_send_that_keeps_failing_is_retried_three_times_then_parked`; `test_a_newer_quotation_replaces_the_planned_nudge` (DB); `test_a_paid_order_withdraws_sales_nudges_but_keeps_the_customers_check_in` (DB) + the unit twin. **Takeover mid-composition is not covered** by a dedicated test; the colleague-reply withdrawal (`test_a_colleagues_reply_withdraws_routine_nudges_and_closes_the_check`) covers the dispatcher side only, not a human reply landing while the model is composing. Remains open. |
| 7 | Owner decision: scope of "pause after two unanswered" | **Open.** |

## I. Read-only compliance of this pass

This pass ran: the local suite (3065 passed, 1 xpassed), CI, one squash merge
of #315 on the owner's "merge and deploy when green", one dispatch of the eval
workflow (which exited at its guard), two `request_credential` prompts
(nothing saved), and health reads of the box. No admin endpoint was called,
no row written, no customer messaged.

## H. Final verdict

**PARTIALLY VERIFIED** — moved, not closed. Of the seven outstanding items,
two are done and live (3, 4), one is three-quarters covered by tests (6), and
the three that decide between "plausible" and "proven" (1, 2, 5) now have a
path that needs no SSH, but each still waits on one action only the owner can
take: saving the dashboard credential in the secure form, and adding the
`ANTHROPIC_API_KEY` repository secret (or running the eval on the box). The
verdict becomes VERIFIED COMPLETE only when the three reads have been run and
their findings reconciled against the audit's incident attributions.

## What the owner has to do

1. Open this session at claude.ai/code in a browser or the desktop app, and
   when the credential form for `neema.bethanyhouse.co.ke` appears, save the
   dashboard admin username and password (type: Basic). On a phone the prompt
   is Allow/Deny only and Allow saves nothing. Alternative: add it as a
   network secret for that host in the environment's settings. Never in chat.
2. GitHub → neema-ai → Settings → Secrets and variables → Actions → add
   `ANTHROPIC_API_KEY`. Then run "Agent eval (model in the loop)" from the
   Actions tab, or tell me to. Alternative on the box:
   `docker compose -f docker-compose.yml -f docker-compose.vps.yml exec -T api python -m app.jobs.agent_eval`
   and paste the transcript.
3. Decide item 7, and whether to retire the 360 parked rows older than 30 days.
