# Stage 1 — immediate corrections (development branch only)

Branch `claude/where-are-we-bx9v9w` on top of main fa177bb. **Not deployed, no
migration, no live configuration touched.** Draft PR for review.

## 1. Files and functions changed

New modules
- `app/services/templates.py` — the template registry: `for_purpose`, `validate_params`, `render`, `send`, `meta`, `order_number_param`, `first_name_param`, `TemplateRefused`.
- `app/services/intent.py` — opt-out floor: `is_opt_out` (en/sw/fr/es/pt/de/hi), `record_opt_out`, `opted_out`, `preferences`, `acknowledgement`.
- `app/agent/composer.py` — `CONTINUATION_NOTE`, `strip_repeated_greeting`, `recently_spoke`.
- `app/services/outreach_log.py` — `stamp()` for outbound rows, `decision()` log lines, message classes.
- `app/jobs/outreach_trace.py` — `python -m app.jobs.outreach_trace <number>`.

Changed
- `app/services/messaging.py` — `_post_graph` with `httpx.Timeout(30, connect=10)`; `SendOutcomeUnknown`; `_send_waba`/`send_wa_template` use it; `record_delivery_statuses`.
- `app/services/wa_native.py` — `parse_statuses`; `handle_webhook` records statuses; every inbound row's id chosen up front (`row_id`) and carried through `_enqueue`/`_drain`/`_reply_after_debounce` as `inbound_ids`.
- `app/agent/runtime.py` — `run_turn(inbound_ids=…)`, `_history(exclude_ids=…)`, `_answered_after`, `OVERLAP_NOTE`; `_run_and_send` records an unknown outcome instead of raising; `schedule_reply` opt-out door + `_handle_opt_out`.
- `app/agent/tools.py` — `schedule_check_in`: `about` parameter, `check_in_about`, one open row per (conversation, purpose), "already booked" result; `check_availability` writes the team check to the deal and tells the model not to close on the item.
- `app/services/actions.py` — `ROUTINE_KINDS`, `message_class`, `template_purpose`, `withdraw_routine`, `_contact_name`; `_send_followup_template` through the registry (raises instead of swallowing); `_compose_follow_up` continuation voice + greeting strip; `_send` stamps rows and surfaces unknown outcomes; `process_due`: one message per customer per tick, opt-out, open team check, template purposes, unknown-outcome parking, decision log.
- `app/services/deals.py` — `team_check_open`, `open_team_check`, `clear_team_check`, `TEAM_CHECK_DAYS`.
- `app/services/hub_events.py` — opt-out → human; registry-rendered template rows; stamps; continuation voice for announcements; unknown outcome recorded.
- `app/services/conversation.py` — after a colleague's reply: `clear_team_check` + `withdraw_routine`.
- `app/routers/admin.py` — team-answer endpoint: stamps, closes the check, withdraws nudges, continuation voice.
- `app/jobs/cart_recovery.py`, `payment_followup.py`, `reengage.py` — opt-out skip, stamped rows; cart composer uses the continuation voice.
- `app/agent/prompt.py` — three edits (closing on an unconfirmed item ×2, one check-in per matter).
- `app/core/config.py` — `wa_event_body`.
- Tests: `tests/test_outreach_stage1.py` (35), `tests/test_outreach_stage1_db.py` (6, real Postgres), fakes updated in `_action_fakes.py`, `test_actions.py`, `test_companion_upsell.py`, `test_hub_events.py`, `test_relationship_loops.py`, `test_wa_native.py`.

## 2. Root causes addressed (audit numbering)

| # | Root cause | Correction |
|---|---|---|
| 1 | `schedule_check_in` added a row per call | upsert by (conversation, purpose); the tool answers "already booked" so the model confirms instead of re-promising; prompt and tool description say so |
| 2 | deal-less rows escaped coalescing | `process_due` sends at most one sales/promise message per customer per tick; extras merged (vetoed with reason), care rows deferred to morning |
| 3 | replenishment template for a deciding customer, scraped parameters, marker text in the inbox | registry: purpose-keyed templates, parameter validation, rendered body stored, `kind=template` meta; a deciding customer outside the window holds for a person unless `WA_FOLLOWUP_TEMPLATE` is approved |
| 5 | stated intentions unrecognised | **opt-out only in this stage** (deterministic, multilingual, durable); "needs time / comparing / consulting" is Stage 3 |
| 6 | re-engage ignored open availability checks | the check is now deal state; the scheduler holds sales follow-ups while it is open; re-engage retirement is Stage 2 |
| 7 | double replies (Meta timestamps + history re-append) | inbound row ids travel with the turn; excluded from history, appended once; overlap note tells the model it may answer with nothing |
| 8 | 5 s default timeout + retry | explicit timeout; unknown outcome recorded and parked, never resent; delivery statuses recorded on the row |
| 9 | no opt-out | floor + durable preference on `persons.state.contact_preferences` + Activity flag + redis; every unprompted sender checks it; one acknowledgement in their language |
| 10 | composed follow-ups greeted again | one continuation note for every composer; deterministic greeting strip within 24 h |

Not in this stage: the unified dispatcher, re-engage retirement, cart/payment as planners, the per-turn state note, language preference storage, the prompt precedence line (Stages 2–3).

## 3. Design decisions and alternatives

- **Commitment identity = (conversation, purpose), not (conversation, kind)** — the owner's concern about the proposed unique index. A purchase-decision check-in, a supplies check-in and a delivery check-in are different commitments and stay separate; the same purpose booked twice is one. Rows booked before purposes existed (`replenishment` + "Customer-agreed check-in") are read as purchase decisions. DB-level enforcement (a `dedupe_key` column + partial unique index) is deferred to Stage 2 with the migration; within a turn the in-flight lock already serialises the tool, and the actions loop is leader-locked, so the application-level upsert is sound today.
- **Merge vs defer per tick** — sales and promise rows merge (the Judas case: three rows, one matter); care about an order (fit check) defers to the next morning rather than being lost.
- **Unknown outcome ⇒ park, never retry** — Meta's `/messages` has no idempotency key; the only safe reaction to "no answer after the write" is a visible row for a person. Connect failures stay retryable.
- **Identity by row id, not timestamps** — the inbound row's uuid is chosen before it is stored and rides the debounce buffer; nothing compares clocks except the overlap note's "did our reply land after this arrived", which is a fact about our own rows.
- **Durable preferences without a migration** — `persons.state` (JSONB, exists) holds `contact_preferences`; redis mirrors it for the hot path and re-warms from the person. A dedicated column remains an option in Stage 2 if reporting needs it.
- **Prompt: three surgical edits**, no new block. The precedence rewrite is Stage 3.
- **Statuses on the row** (`raw_meta.delivery`) rather than a new table: one place for staff and the trace to read.

## 4. Tests executed

- `tests/test_outreach_stage1.py`: 35 passed (registry, send classification, statuses, overlap plumbing, composer, check-in upsert, scheduler coalescing/opt-out/team-check/template hold, opt-out, trace).
- `tests/test_outreach_stage1_db.py` on a real Postgres: 6 passed — Judas Thursday (one row; nothing sent without an approved follow-up template; the follow-up template text once when approved), Judas Wednesday (three due rows → one message, greeting dropped), Pastor Emmanuel (team check holds every sales follow-up; colleague's answer closes it), overlap (second message seen once with the note), opt-out in Swahili (acknowledged once, durable, every path stands down), delivery statuses + duplicate webhook.
- Touched suites: actions, companion upsell, hub events, relationship loops, cart recovery, payment follow-up, re-engage, deals, wa_native, agent recovery, meta audit, deferral: green after updating fakes to the new call shapes.
- Full API suite: CI on 58cd89f green on every check (API tests, Migrations fresh-DB replay with the Postgres suites, import smoke, lint, web). The first CI run (fcdd760) failed only on test fakes that did not accept the new keywords; fixed in 97abc5e and 58cd89f with no behaviour change. The local Postgres run overlapped with Stage 2 edits and is superseded by CI.
- ruff: 98 (baseline 115, unchanged by this work). `import app.main`: ok.

## 5. Known limitations and remaining risks

- The Meta (Messenger/Instagram) live turn does not yet carry inbound ids or the unknown-outcome handling (`_run_and_send_meta`); the WhatsApp path does.
- The inbox renders a template row's text but does not yet show a "template" tag (web/Android work; `raw_meta.kind="template"` is there to read).
- Without `WA_EVENT_BODY` configured, a template row stores "[WhatsApp template «name» sent] first_name: … · order_number: … · status: …" — honest, not the customer's exact words. The owner should paste the approved body into `WA_EVENT_BODY` ({1}{2}{3}).
- Opt-out detection is deterministic and conservative; a phrasing outside the patterns reaches the model only. Stage 3 adds the model-written state note on top.
- Re-engage, cart and payment sweeps still run as independent senders (now opt-out-aware and stamped). Owner decision 2 (retire re-engage) is a one-line config change today (`RECOVERY_REENGAGE_ENABLED=false`) and a code retirement in Stage 2.
- The greeting strip handles the greetings seen in production (en/sw/fr/hi); an unseen opener passes through.

## 6. Customer-experience impact (when deployed)

- One commitment, kept once; no second "Good morning".
- No replenishment text to someone deciding on a purchase; nothing nonsensical from a template.
- No second answer to a message that arrived while Neema was typing.
- "Please stop messaging me" is honoured, in their language, for good.
- An item the workshop is still confirming is never pushed to "shall I start the order?".
- Fewer messages overall; the ones that go say why they are sent.

## 7. Migration and rollback

- No migration. No new tables or columns.
- Rollback = revert the PR. Data written meanwhile (`raw_meta` stamps, `persons.state.contact_preferences`, `deals.next_action.team_check`) is inert to the previous code.
- Live configuration unchanged. Recommended step 0 on the box when you approve: `RECOVERY_REENGAGE_ENABLED=false`; optional `WA_EVENT_BODY` with the approved template text.

## 8. Decisions requested

1. Approve the Stage 1 PR for merge and deploy (the deploy itself is a separate approval, as you asked).
2. Step 0 config on the box: disable the re-engage sweep now?
3. `WA_FOLLOWUP_TEMPLATE`: approve a follow-up template in WhatsApp Manager so a deciding customer's check-in can go when the window has closed; until then those rows wait for a person (visible in Deals → Needs approval).
4. Stage 2 identity: a `dedupe_key` column + partial unique index on open `agent_actions` (one reversible migration) — go ahead when Stage 2 starts?
