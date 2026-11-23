# Prioritised plan after Phase 1

Each step is built record-only first, then switched on by the owner one policy at a time after its false-alarm count is read.

## Phase 1 (this change) — architecture, record-only

Done: see `F_IMPLEMENTATION_RECORD.md` and `G_VERIFICATION_REPORT.md`.

## Phase 2 — read the record, then switch on the critical policies

| Step | What | Needs |
|---|---|---|
| 2.1 | Leave Phase 1 live for a few days. Read `/api/admin/policy/report`: findings per policy and route. Read each finding's excerpt for false alarms. | Deploy on the owner's word |
| 2.2 | Switch on the route guards (`policy_guards_active`). | Owner's word |
| 2.3 | Switch on the critical policies one at a time: FIN-03, FIN-04, FIN-05, ORD-02, then FIN-02, then ORD-01. | Owner's word per policy; false alarms read first |

## Phase 3 — the remaining critical findings (need code, not just a switch)

| Finding | Work | Layer |
|---|---|---|
| C3 Discount quoted without the grant | Do not hand the model the offer price until the offer step has run; remove "gone quiet" as a reason to play the offer (owner's policy 1). | Search tool and offer tool |
| C6 Official numbers | Write the first-greeting line from configuration in code, not by instruction. | Reply assembly |
| C8 Failed order described as placed | Covered by ORD-02 once enforced; also substitute the fixed failure line when the order step errors. | Order tool and reply |
| C10 Complaint as a tracked case | The bell is in. Add a tracked commitment with an owner and a state, so an unanswered complaint is chased like a money hold. | Complaint tool, commitments |
| C11 Near-match price counted as verified | A row marked "partial" does not count as a verified price. | Search tool and price check |
| C1 Price, item, link and language on messages Neema starts | Run the gate's deterministic rules on initiated messages, record-only first. | Dispatcher and hub announcements |

## Phase 4 — high-risk findings

| Finding | Work |
|---|---|
| H2 Photos sent before the reply is checked | Queue cards during the turn; send them only once the reply passes. |
| H3 Templates to a chat a colleague holds | Read human mode before the window check. |
| H4 and conflicts X1, X6, X9–X11 | Make the correction texts agree with the instructions (needs decision 7). |
| H5 Promises to act | Extend ACT-01 to check-ins and "I've sent you a private message". |
| H7 Repairs | Needs decision 5 and a purchase-date source. |
| H8, H9 Stale and bare figures | Require a fresh look-up before a price is repeated; read bare numbers beside a product name. |
| H10, H11 Pause and unsolicited check-ins | Refuse a pause on a complaint or open order; a check-in needs a time the customer named (decision 8). |
| H12, H13 Unclaimed answer and staff one-tap sends | Read-only turn for unclaimed answers; once-only key on approve. |
| H14, H15 Plain text and language | Strip marks on every channel; language check both ways and on comments. |
| H16 Staff-typed text in the instructions | Admin-only; links typed there are not trusted (decision 9). |

## Phase 5 — conversational quality

Naturalness is evaluated in context and corrected by one focused rewrite, never by phrase bans: repeated greetings, re-asked questions, stacked paragraphs, menus, selling into a complaint, pressure after a decline. The record-only length and pacing measures already exist and feed this.

## Status, 23 November 2026

Phases 1 and 2 are live (#387, #388): the six critical policies are enforced, the route guards and the three wording switches are on. Next, in order: read `/api/admin/policy/report` for false alarms on the enforced policies; photos only after the reply passes; the repair rule against the hub's delivered date; the remaining conflicts; conversational quality.
