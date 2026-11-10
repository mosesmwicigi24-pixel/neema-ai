# Intent discernment and graceful close — slice 19 (2026-11-10)

The owner's directive "NEEMA — Intent Discernment & Graceful Close". Built on
a branch and **not deployed**: the directive says to report before deployment.
No evaluation run was dispatched (the owner's word of 9 Nov: "Don't run
validation"). No migration: the record is JSONB on `persons.state`.

## 1. What was already there (investigated before any change)

| Piece | Where | What it did |
|---|---|---|
| Gift and hardship rule (the Bangladesh thread, 2026-08-08) | `agent/prompt.py` | Decline once and "open the honest smaller door" (a smaller size, fewer pieces); on insistence one scripture blessing, then `pause_conversation` |
| `pause_conversation` | `agent/tools.py` | A two-hour pause in redis; a buying signal lifts it |
| Pacing | `agent/cooling.py` | Chat with nothing to sell in it goes brief, then one warm close and a cool-off; a buyer is never paced |
| Closer gate | `agent/cooling.py`, `runtime.py` | "Thanks", "ok", an emoji: one warm line, then silence |
| Customer state (Commercial EI, slices 3 and 11) | `services/customer_state.py` | A floor and a light-model note per turn: asked for time, comparing, consulting, paid claim, complaint, closing, stop; holds on the deal; the come-back rule |
| Payment rules | `agent/prompt.py` | Payment is completed before delivery; they may pay little by little |
| Outreach dispatcher | `services/actions.py` | Holds unprompted sales messages while a customer asked for time |

## 2. Conflicts and gaps found

1. **The old rule answered a donation request with cheaper items** ("open the
   honest smaller door"). The directive forbids that for someone clearly
   asking for a donation. Resolved: the budget door stays for a buyer who is
   short of money and asks what fits; it is removed from the gift boundary.
2. **Nothing was remembered.** The whole protocol lived in the model's
   reading of one conversation, and the pause lasted two hours. The next
   morning the same appeal began the same exchange. There was no record of
   intent and no count of boundaries given.
3. **Insistence was the model's call.** Whether a message was the first
   request or the fourth was not decided anywhere; a long appeal chain could
   be answered every time.
4. **A scripture blessing was mandatory** on the second reply. The directive
   asks for one brief acknowledgment. Resolved: one brief line; a blessing is
   allowed, a second one is not.
5. **Credit was not distinguished from begging** anywhere in words. The
   payment rule answered it correctly, but the gift rule's example list did
   not say that "pay on Sunday" is a buyer's question. Now stated.
6. **Follow-ups ignored intent.** A sales follow-up could go to someone who
   had only ever asked for free goods.
7. **The customer-state note had no reading of intent as a whole.**

No conflict was found with debounce, image consolidation, country greetings,
payment routing, the cart, pricing, fulfilment or human hand-off: none of
those paths is touched.

## 3. What changed

**`services/buyer_intent.py` (new).**
- A neutral record, `persons.state["intent"]`: reading (buyer, constrained,
  negotiator, assistance, social, unclear), confidence, source, date, a short
  reason, the boundary count, and a capped history. Reversible; nothing is
  erased; never shown to a customer.
- A floor for the explicit request ("for free", "donate", "sponsor our
  church", "naomba zawadi", "bure", "gratuitement", "muft") and, more
  important, everything that is not one: a discount, a price, paying on
  Sunday, credit, "is delivery free", a gift bought for someone, someone who
  wants to donate, "I can't afford it now".
- The ladder, decided before any model call:
  1. first request: the writer is told to give the one kind boundary;
  2. the same request again: one brief line, and the request is closed;
  3. after that: no automatic reply to that request.
  A hardship appeal alone never starts the ladder. It counts only while a
  request is already on the record.
- Never applied when: the message has any purchase step; the thread has an
  order, a payment claim or a promised check open; the post is a giveaway.
- A purchase step from the same person reopens the record at once ("Now
  asking to buy" on the timeline). A boundary older than 30 days is history.

**`agent/runtime.py`.** One step after pacing in the live turn, all channels.
Fails open.

**`services/customer_state.py`.** The light-model note gains `intent` and
`intent_reason`, read from the whole conversation. Stored as evidence; it
never closes anything by itself.

**`services/actions.py`.** A routine sales follow-up waits (re-checked
weekly) while the record reads assistance with a boundary given. Promises,
orders, payments and delivery messages are not held. Tallied as
`hold_intent` beside the other holds.

**`agent/prompt.py`.** The gift rule rewritten: how to tell a buyer, a
constrained buyer, a negotiator, social talk and an unclear case apart; the
one boundary with the owner's example; one brief line on a repeat; no
invented programmes; no judging of circumstances; a new short rule on natural
endings and what is never closed on.

## 4. Tests

| | Result |
|---|---|
| `tests/test_buyer_intent.py` (model-free) | 54 passed: 17 requests read, 28 look-alikes never counted, the record, the notes, the prompt, the wiring |
| `tests/test_buyer_intent_db.py` (Postgres, in CI's database step) | 10 passed: the eight scenarios, a giveaway post, the model's reading |
| `tests/test_gift_appeals.py` | 5 passed, rewritten to the new rule |
| Full API suite, Postgres and redis | 3,603 passed, 0 failed |

The eight scenarios, as decided before the model speaks:

| # | Scenario | Outcome |
|---|---|---|
| 1 | Repeated hardship appeals and a request for a gift (stand-in for the Pakistan thread) | price answered normally; hardship alone: nothing; request: boundary; repeat: one line, closed; third and fourth: silence |
| 2 | Pastor saving toward an alb | never touched; no record |
| 3 | Bulk-order negotiator | never touched; no record |
| 4 | Free cassock for ministry | the one boundary; a thank-you afterwards is answered without repeating it |
| 5 | Credit until Sunday | never touched; the payment rule answers |
| 6 | Declined, later a buyer | boundary, one line, silence; then a price enquiry is answered and the record reads buyer |
| 7 | Greetings and blessings only | never touched |
| 8 | Unresolved promised check or delivery problem | never closed on, even with an explicit request beside it |

## 5. Not verified, and why

- **The words of the replies.** Whether the writer's boundary reads warm and
  brief needs the model. Eight cases are written
  (`jobs/eval_cases/intent_discernment.jsonl`, 14 turns) and **not run**.
  One run would cost well under 2 USD at the recorded rate.
- **The Pakistan conversation itself.** It was not attached to the
  directive; scenario 1 is a stand-in built from its description.
- **The floor is English, Swahili, French, Portuguese and romanised Urdu
  only.** A request in another language is read by the model note and the
  prompt rule, not by the floor.

## 6. Risks and rollback

- A real buyer whose message contains a request phrase and no purchase word
  ("please give me one for free delivery" is excluded; "can I get a free
  sample to check the fabric" is not) would get the boundary once. One
  purchase word from them reopens everything. Watch the timeline line "Asked
  for goods without payment".
- The outreach hold is a behaviour change to follow-ups: it only ever
  withholds a sales message, never sends one.
- Rollback: revert the commit. The `intent` key on `persons.state` is ignored
  by the previous code.
