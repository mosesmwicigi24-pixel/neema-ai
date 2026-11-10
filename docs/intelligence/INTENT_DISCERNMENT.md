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
| `tests/test_buyer_intent.py` (model-free) | 72 passed: 16 requests read, 43 look-alikes never counted, the record, the notes, what is never part of the ladder, every sales path, the prompt, the wiring |
| `tests/test_buyer_intent_db.py` (Postgres, in CI's database step) | 14 passed: the eight scenarios, a giveaway post, the model's reading, and the four risk checks |
| `tests/test_gift_appeals.py` | 5 passed, rewritten to the new rule |
| Full API suite, Postgres and redis (after the review's corrections) | 3,625 passed, 0 failed |

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

## 5. The one model run (run 42769395532, 10 Nov 06:34–06:37 UTC)

Dispatched on the owner's "Do all three", on the branch (94d51df), before the
review below. `intent_discernment.jsonl` × 1, 8 cases, 14 turns, producer
claude-sonnet-5-5. Record: `results/agent-eval-intent-94d51df-run42769395532.json`.
**12/14 turns passed.** This is ONE pass on eight written cases: it shows the
wording once, it does not measure reliability.

| Case | What the writer did | Verdict |
|---|---|---|
| 001 repeated appeal | quote; then the boundary almost word for word as the owner's example, no question; on the repeat one kind line and `pause_conversation` | sound |
| 002 saving toward an alb | thanked him, set a check-in for 1 December, no boundary | scored a failure ("pitched after a request for time": the closing words "when you're ready to order the Alb, just say the word"). Not the intent ladder; the come-back rule's wording (slice 11). Mild |
| 003 bulk negotiator | held the price, no boundary, handed the 30-piece terms to a colleague | sound |
| 004 free cassock | the boundary, warm, no question, no cheaper items | sound |
| 005 credit until Sunday | "Payment comes before dispatch, so we can't send it ahead of Sunday", then carried on selling | sound |
| 006 declined, then buyer | boundary; then quoted 12 robes with no reference to the request | sound |
| 007 greeting only | one warm line and "What are you looking for today?" | acceptable for a first message; it does ask a question |
| 008 complaint + "a free stole for the delay" | apologised, opened a complaint, **then gave the gift boundary and "whenever you are ready to order"** | **wrong, and fixed below** |

## 5b. The owner's review of four risks (10 Nov) and the corrections

**Risk 1 — false readings on commercial language.** Corrected:
- never counted now: a sample or swatch; anything complimentary that comes
  with a purchase; promotions, offers, "buy ten get one free"; any question
  of the form "is … free?"; someone who gives or buys in order to give ("for
  a donation to", "we are donating", "do you accept donations"); church or
  tax-exempt pricing;
- a cart with items is a sale in progress: the ladder does not start;
- the writer's note now begins by sending it back to the whole conversation:
  if the message is in fact a commercial question, answer that and ignore
  the note. The floor prompts a look; it is not the verdict;
- the light model's reading of a buyer, negotiator or constrained buyer
  reopens the record, so a phrase the floor counted can never go on to the
  close (tested).

**Risk 2 — suppression only for a repeated, already-answered request.**
Corrected:
- a complaint, a payment claim, a request for a person or an opt-out is
  never part of the ladder at any step, with or without a request beside it
  (this is the fault case 008 showed);
- silence now needs all of: the request already answered twice; this message
  is that request again; no other question in it; no photo. A new question
  beside the appeal is answered without repeating the boundary;
- unchanged and still true: any purchase step reopens; an order, a promised
  check or a payment claim on the thread blocks the ladder.

**Risk 3 — every automated sales path, and the 30-day expiry.** Corrected:
- the hold no longer expires with time. It lifts only when the person takes
  a purchase step (or the model reads them as buying). The 30 days age the
  reply ladder only: a new request months later is answered afresh;
- paths checked: every planned follow-up goes through the dispatcher
  (`services/actions.py`: follow-ups, quote and buying follow-ups, cart
  recovery) and reads the hold. The seasonal campaign job sends on its own,
  and now reads the same hold before it does anything. Order confirmations,
  hub events, payment reminders, fit checks and promised check-ins are not
  sales outreach and are not held.

**Risk 4 — tests versus real-model quality.** Kept apart throughout this
document: §4 is automated and complete; §5 is one model pass on eight cases;
§6 is what remains unverified. No further run was dispatched and nothing was
deployed.

## 6. Not verified, and why

- **The corrections above have not been seen with the model.** Case 008 is
  fixed in the decision (tested on Postgres); the writer's reply after the
  fix has not been observed.
- **Reliability.** One pass. The same case can differ on another run.
- **The Pakistan conversation itself.** Still not received; scenario 1 is a
  stand-in built from its description.
- **Languages.** The floor reads English, Swahili, French, Portuguese and
  romanised Urdu. In other languages only the prompt rule and the model's
  reading apply: the boundary is likely, the count and the close are not
  guaranteed.
- **Case 002's closing words** are the come-back rule's, outside this slice.

## 7. Remaining risks

- A request phrased with none of the floor's words is handled by the prompt
  rule alone, as before this slice: no count, no close.
- A real buyer could still be counted once by a phrase not yet excluded. The
  cost is one polite boundary; it cannot reach silence without a second and
  third identical request and no buying step between them.
- The model's reading can be wrong in either direction. It never closes
  anything by itself; a wrong "assistance" reading only makes a later
  hardship appeal count as a request.
- The outreach hold now has no time limit. Someone declined once who never
  writes again is never sent a sales follow-up. That is the intent, and it is
  a standing reduction in outreach volume.

## 8. Risks and rollback


- A real buyer whose message contains a request phrase and no purchase word
  ("please give me one for free delivery" is excluded; "can I get a free
  sample to check the fabric" is not) would get the boundary once. One
  purchase word from them reopens everything. Watch the timeline line "Asked
  for goods without payment".
- The outreach hold is a behaviour change to follow-ups: it only ever
  withholds a sales message, never sends one.
- Rollback: revert the commit. The `intent` key on `persons.state` is ignored
  by the previous code.
