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

# Switch-on and the next fixes — merged as #388 (main 5e13d15), 23 November 2026

On the owner's word ("build this in one go"). This section supersedes "nothing switched on" and the first three rows of "Not built in this round" above.

## Switched on (defaults in `core/config.py`)

| Setting | Value | Effect |
|---|---|---|
| `policy_mode` | `enforce` | Policies named in `policy_enforce` hold the message; all others still only record. |
| `policy_enforce` | `FIN-02,FIN-03,FIN-04,FIN-05,ORD-01,ORD-02` | Discounts, refunds/remakes/replacements, pay on delivery, payment at collection, confirmed orders. |
| `policy_guards_active` | on | Opt-out silences later sends (RTE-01); a human-held chat is not answered through Neema (RTE-02); no pause over a held chat. |
| `official_numbers_by_code` | on | Official-numbers line written by code on the first private reply. |
| `offer_price_after_grant` | on | Discount figure reaches the writer only after the offer step grants and records it. |
| `second_deferral_line` | on | Second "I'll get back to you" gets one short line. |
| `whatsapp_debounce_seconds`, `meta_debounce_seconds` | 60 | Messages within one minute are combined into one reply; ceiling `reply_window_max_seconds` = 120. |

The switch-on was made without reading the live Phase 1 record: `/api/admin/policy/report` needs a staff sign-in this work does not have. False-alarm counts on live traffic are therefore NOT YET MEASURED.

## Wording changed (owner's decisions)

- D5 repairs: 14 days from delivery, our items only, said plainly once; a colleague decides exceptions.
- D7 availability: "confirming with a colleague", a check is raised; never "out of stock".
- D8 check-ins: the instruction to book one the day before a deadline is removed; booked only when the customer names a time.

## Also built

- Policy step on staff-approved sends (`services/actions.py`), hub announcements, team answers, order creation.
- Guidance, directives and learned-rule changes are logged with who and when (D9).
- Draft approval is once-only; markdown is stripped on WhatsApp Cloud and web-chat sends.
- Unclaimed-order lookups run as lookup-only turns.

## Rollback

`POLICY_MODE=shadow` on the server returns every policy to record-only. Each other switch is its own setting and can be turned off alone.

## Still not built

| Item | Why |
|---|---|
| Photos and cards only after the reply passes (H2) | Sends are interleaved with the tool loop; needs a buffered-send change. |
| Repair rule checked against the purchase date | Needs the delivered date from the hub. |
| Remaining instruction conflicts (about 20 of X1–X22) | Each needs an owner decision or a model run. |
| Conversational quality in context | Not started. |
| "I've sent you a private message" claim check; bare numbers; two-way language check | Partial; the rest of findings 5, 7, 9. |

# The five remaining items — built 23 November 2026 (not merged)

Each item was re-examined before building. Where the audit's own recommendation did not survive that, the record says so.

## 1. Photos and cards only with a reply that passed (H2)

| | |
|---|---|
| Before | Cards, album photos and the measurement guide left during the turn. A reply then held left them delivered beside a holding line. |
| Now | A live turn queues them (`ToolContext.outbox`). They are delivered at the end of the turn, just ahead of the words, once the gate and the policy step have passed. A held reply withholds them and records `RTE-03`. |
| Kept | The writer is told the same thing as before, so its reply is unchanged. The order the customer sees (photos, then words) is unchanged. |
| Improved | The same cards asked for twice in one turn go out once. If nothing can be delivered at the end, the hub's own name, price and link are added to the reply as text — before, that fallback depended on the model. |
| Switch | `MEDIA_AFTER_CHECK` (on). Off = send at once, as before. |
| Limit | The check still reads the words, not the choice of cards. Cards are built by code from hub rows, so their facts are the hub's. |

## 2. The repair rule against the delivery date (H7, D5)

The earlier note "needs the delivered date from the hub" was wrong: the hub already tells us when an order is delivered (`order.delivered`). The time was being overwritten by later events.

| | |
|---|---|
| Now | The first delivered event stamps `order_events.state["delivered_at"]`, once. No migration. |
| On a repair or alteration message | The writer is handed what the record proves: inside the 14 days, outside, delivered with no date on record, or no order on record — and told not to state the window when the record cannot. |
| Older orders | Only the hub's last status time exists. It proves "outside" when it is itself older than 14 days, and nothing otherwise. Nothing is what the writer is told. |
| Sizing before a sale | "Too tight" counts as a repair only for a contact with a delivered order. |
| Record | `FUL-02` now also records a reply that offers a repair outright while the record says outside. Record-only. |
| `check_order_status` | Returns `delivered_on`, `days_since_delivery`, `repair_window` when known. |

## 3. A private message is spoken of only when one went (H5, X21)

The public reply is written before the private message is attempted, and the message may not go (opt-out, campaign post, refused send). After the attempt, a sentence claiming one is dropped when none went. A sentence claiming photos were sent becomes "I've sent you a private message with the link" — the private message never carries photos. Invitations ("DM us") are untouched. Recorded as `ACT-01`, outcome corrected. The two instruction texts that told the writer to say photos were sent now say the link is in the inbox.

## 4. Prices without a currency, and "free" (H9)

Record-only, as `FIN-11` and `FIN-12`. A number the words mark as a price ("is 4,200 each", "bei ni 4500") is judged by the reply gate's own standard for figures, so a correct total is not a finding. "Free" is a finding only when no source (the instructions, a tool result, a colleague, the customer) says that thing is free. Reading every bare number as money was rejected: counts, sizes, years and addresses would hold honest replies.

## 5. The language check, both ways (H15)

A reply plainly in French, Portuguese, Hindi or Swahili when nothing the customer wrote — this message or their recent ones — shows that language is corrected by one rewrite (soft: never holds). This is the miss of 20 November (an English comment answered in French). The existing direction now also runs under public comments, as a correction, never a hold.

## Conflicts

| | Resolution | State |
|---|---|---|
| X7 | The price check accepts the total of three or more named pieces when each is that row's own price. | Fixed |
| X9 | The audit said "use our rate". Wrong for currencies read from the public feed, where "today's rate" is true. The rewrite text now says "the rate given above" and leaves the name to the rate note. | Fixed |
| X10 | The order step names Mukuru only for its send markets; the payment correction text names no rail itself. | Fixed |
| X11 | Three texts said "no shop there". They now say we serve them from Nairobi and deliver. | Fixed |
| X12 | The audit said "keep the stock line only when the customer asked something". Rejected: two empty answers is a malfunction, and silence would drop a customer who stated an order. The line stays, and the team is rung so "let me check" has an owner. | Fixed differently |
| X20 | Half true: the offer is on the lines at order time, except made-to-order pieces, which a colleague prices. The instruction now says exactly that. | Fixed |
| X21 | See item 3. | Fixed |
| X1, X4, X13, X14, X15 | Decided by the owner earlier (D7, D1, D11, D8, D5). | Done in #388 |
| X2, X3, X5, X6, X8, X16–X19, X22 | Instruction against instruction. Each has a recommended resolution in `E_CONFLICT_REGISTER.md`. They change how the writer behaves, so they are not edited without a model run to measure them. | Waiting for a model run |

Also: the cassock follow-up is no longer added after a complaint or a decline.

## Conversational quality in context

Record-only (`CNV-01`, `-03`, `-04`, `-05`, `-06`). Each needs the context that makes it a finding: a welcome is fine first and found fifth; a list is fine when asked for; a price is fine in a sale and found in a complaint. They can never hold a reply, even with every policy enforced. A rewrite is to be earned by the measured rate, not by a phrase list. A second model reviewer on every turn was rejected: it would roughly double the reviewing cost before any rate is known.

## Not measured

No model run was made for this work. The deterministic parts are tested (28 tests). How often each new record fires on live traffic is NOT YET MEASURED.
