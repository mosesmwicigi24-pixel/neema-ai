# F. Implementation record — Phase 1

Phase 1 is the shared enforcement architecture in record-only mode (owner, 2026-11-20: "Nothing should change in customer-facing behaviour until the safeguards are verified and approved").

## What was built

| # | Change | Where | Customer-facing effect now |
|---|---|---|---|
| 1 | **The policy layer.** One module defines each company policy once, with a permanent ID and a rules version, one `evaluate` function every route calls, and one `record` function that logs every decision. | `apps/api/app/agent/policy.py` | None |
| 2 | **Live replies** are read by the layer after the reply gate. | `agent/runtime.py` `run_turn` | None (recorded) |
| 3 | **Messages Neema starts** (follow-ups, cart nudges, check-ins) are read before sending. | `services/actions.py` `_send` | None (recorded) |
| 4 | **Hub announcements** are read before sending. | `services/hub_events.py` | None (recorded) |
| 5 | **Team answer through Neema** is read against the colleague's own facts. | `routers/admin.py` `answer_through_neema` | None (recorded) |
| 6 | **The order step** records when it is called with no "yes" in the customer's recent words. This is at the business operation, not on the text. | `agent/tools.py` `_create_order` | None (recorded) |
| 7 | **The reply gate's own outcomes** (corrected, sent with notes after a rewrite, held, held with nobody told) go into the same record. | `agent/runtime.py` | None |
| 8 | **Route guards, switched off:** a second "stop" marked as deliberate silence; team answer refused for a customer who opted out; the same team answer sent once. Each is recorded today and acts only when `policy_guards_active` is set. | `agent/runtime.py`, `routers/admin.py` | None until switched on |
| 9 | **A complaint rings the team** and leaves a note on the thread. Neema stays in the chat. | `agent/tools.py` `_raise_complaint` | None for the customer; staff now get a bell |
| 10 | **Staff report:** which policies were found, on which route, with what outcome, for up to 45 days, plus the last 50 decisions. | `GET /api/admin/policy/report` | None |

Item 9 is the only change that acts today. It is staff-facing and follows the owner's policy 5.

## The policies in the layer

| ID | Policy | Decided from | Owner's policy |
|---|---|---|---|
| FIN-02 | A discount is stated only after it is authorised and recorded | The offer step having succeeded in this turn, or a colleague's own words | 1 |
| FIN-03 | Refunds, remakes and replacements are neither promised nor refused | A colleague's own words; handing it to the person who decides is allowed | 2 |
| FIN-04 | No pay on delivery; payment at collection needs an approved policy | The reply; the `policy_pay_at_collection` setting | 3 |
| FIN-05 | Only our official numbers | The configured lines; numbers the customer or a tool already stated | — |
| ORD-01 | An order needs the customer's clear yes | The customer's last three messages, read at the order step | 4 |
| ORD-02 | "Your order is placed" only when the order step succeeded | The tool log | — |
| FUL-01 | No delivery date or production time without a source | A tool result, the customer's or a colleague's words, or a duration the instructions state as company fact | pending (decision 6) |
| FUL-02 | Repairs are never "for life" | The reply | pending (decision 5) |
| ACT-01 | "Let me confirm with the team" needs the team to have been asked | The tool log | pending (decision 7) |
| RTE-01 | A customer who said stop is not messaged | The opt-out record | — |
| RTE-02 | One instruction sends one message | A two-minute once-only key | — |
| GATE | The reply gate's verdict | `agent/review.py` | — |

## Settings (all default to today's behaviour)

| Setting | Default | Meaning |
|---|---|---|
| `policy_mode` | `shadow` | `shadow` records; `enforce` holds findings of the policies listed below |
| `policy_enforce` | empty | Policy IDs to hold, comma-separated; `*` = every critical policy |
| `policy_guards_active` | `false` | Whether the route guards act |
| `policy_pay_at_collection` | `false` | Whether payment at collection in the shop is an approved policy |

## How a held message is handled when a policy is enforced

Each route uses the hold path it already has; nothing new is invented.

| Route | When held |
|---|---|
| Live reply | The draft is flagged to a colleague and the chat moves to a person, exactly as a gate hold does; the customer gets the existing hold line in their language. Silence on a closer or a public comment. |
| Message Neema starts | The action is parked for a person (`HeldByRules`), never retried blind. |
| Hub announcement | The team is told to send it themselves. |
| Team answer | The colleague sees why it was not sent and can reply themselves. |
| Order step | No order is created; Neema is told to ask for the customer's yes. |

## Rollback

Revert the commit. No migration and no stored data shape changed. The record lives in redis (`policy:tally:*`, `policy:recent`) and expires on its own.

# Phase 2 build — ready for review, nothing switched on

Built on the owner's word of 2026-11-20 ("build them now … ready for your review while Phase 1 gathers data"). No customer-facing message changes until a switch or a policy is turned on.

## Recorded by the policy layer

| ID | What is recorded | Where it is read | Finding it answers |
|---|---|---|---|
| FIN-01 | A money figure, on a message Neema starts, a hub announcement or a team answer, that is in neither the brief nor the conversation | `agent/policy.py` `unsourced_figures`; `services/actions.py` reads the conversation in its own session | C1 |
| PRD-02 | A price in a live reply that belongs only to a row marked as a near-match | `agent/tools.py` remembers which seen rows were partial; `agent/policy.py` `partial_only_figures` | C11 |
| ACT-03 | A check-in scheduled though the customer's recent words name no time. Refused when the policy is enforced. | `agent/tools.py` `_schedule_check_in` | D8, H11 |

## Behind switches (all off)

| Switch | When on | Finding it answers |
|---|---|---|
| `official_numbers_by_code` | On the first reply to a person in a private chat, the official-numbers line is built from the configured lines and appended; any version the model wrote, in any reply, is removed. | C6 |
| `offer_price_after_grant` | The search tells the writer an offer exists but not its figure. The offer step grants it, records it and returns the figure. The instruction that a quiet customer earns the offer is gone. | C3, owner's policy 1 |
| `second_deferral_line` | A second "I'll get back to you" gets one model line; the third and later get silence. | D11 |

## Acting now (staff-facing only)

A complaint opens a tracked team check, the same record an availability question opens: it has an owner, ages, is chased by the existing commitments sweep, and holds automatic sales nudges on that chat until a colleague answers. (Owner's policy 5.)

## Not built in this round

| Item | Why |
|---|---|
| D7: the three correction texts that say "say so plainly" | They also guard against a wrong item being substituted. Changing their wording needs a model run to confirm that guard still works. |
| D5: making the repair texts agree | The instruction text is one long string with tests pinned to its wording; the edit is planned with D7's. |
| D8: removing the instruction to book a check-in before a deadline | Same reason. ACT-03 already records the behaviour. |
| H2 photos before the check, H3 templates in a held chat, H10 pause on a complaint, H12–H16 | Planned; see `PLAN.md` Phase 4. |
