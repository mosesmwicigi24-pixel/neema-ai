# Neema outbound communication — expanded audit (read-only)

Date 2026-11-05 · live box fa177bb · nothing implemented, migrated or deployed.
Companion to the first audit (outreach-audit-2026-11-05.md); this one supersedes
its correction plan. All code references are to `apps/api/app/…` on `main`.

---

## 1. The complete messaging architecture

### 1.1 Every component that can put a message in front of a customer

| # | Component | When it fires | Composes with | Window / template | Guards it owns | Consults any other sender? |
|---|---|---|---|---|---|---|
| L1 | **Live turn, WhatsApp** — `services/wa_native.py` → `runtime.schedule_reply` → `runtime._run_and_send` | a customer message, after a 30 s debounce | full agent turn (`run_turn`, tools) | inside the window by definition | wamid dedup (`wa:native:seen`), `agent:seen` dedup (600 s), closer gate, pause keys, human-mode check, in-flight lock (#308), echo guard (10 min, word-for-word), `_still_ai` before send | — |
| L2 | **Live turn, Meta** — `routers/meta_webhook` → `schedule_meta_reply` → `_run_and_send_meta` | a Messenger/Instagram message, 12 s burst | same | same | same family | — |
| L3 | **Second message in one turn** — the cassock ladder (`runtime.py:2168–2184`, `:2553–2559`) | a cassock priced | code | — | once per customer per 30 d | — |
| L4 | **Hold line** — `runtime._send_hold_line` (`:2349`) | a live turn crashed | fixed text | — | once per thread per 2 h | — |
| R1 | **Missed-reply sweeper** — `services/reply_sweeper.sweep_missed_replies`, every 120 s | a thread whose newest row is an inbound ≥ 90 s old | full agent turn (retry of L1/L2) | ≤ 23 h | per-thread lock 300 s, in-flight check, silenced-since, 3 strikes then escalate | — |
| R2 | **Unclaimed human chats** — `services/unclaimed.py`, every 300 s | human-held, nobody picked up in 30 min | agent turn with a restricting note | — | once per customer message | — |
| S1 | **Planned actions** — `services/actions.process_due`, 60 s leader loop | `agent_actions` rows: `follow_up` (Neema's promise, +3 h), `customer_promise`, `quote_follow_up` (+4 h), `replenishment` (`schedule_check_in`), `fit_check` (+6 d) | agent turn with a "keep the commitment" note; quote nudges composed in code | free-form inside the window; **utility template** `WA_EVENT_TEMPLATE` outside it for `fit_check`/`replenishment`; otherwise parks for approval | quiet hours, human-held, flagged thread, deal > KES 50k, ≥2 sent per *deal*, wording repeat check, atomic `claim()` | reads only its own table |
| S2 | **Re-engage sweep** — `jobs/reengage.py`, 15:00 NBO daily (enabled, send mode) | we spoke last, quiet ≥ 3 h, inside the window | light/main model, no tools, JSON draft, quality gate | free-form only | once per customer message (redis), skips carts, orders, declines, handoff lines (en/sw/fr), planned/sent actions *after the last inbound* | partially (S1 rows, carts, orders) |
| S3 | **Cart recovery** — `jobs/cart_recovery.py`, 11:00 NBO daily (enabled) | cart with items, quiet ≥ 45 min, inside the window | agent turn (read-only) with a nudge note | free-form only | once per basket per 7 d | no |
| S4 | **Payment follow-up** — `jobs/payment_followup.py`, 10:00 NBO daily (enabled) | unpaid order with a link, ≥ 2 h old, inside the window | code | free-form only | hub re-checked live, once per order, one message per customer per run | no |
| S5 | **Seasonal outreach** — `jobs/seasonal_outreach.py` | manual / campaign | code + marketing template | template | its own | no |
| E1 | **Hub events** — `services/hub_events.handle_event` → `_celebrate` (paid / production / shipped / delivered) | hub webhook; quiet-hours deferred to 08:00 via a redis zset | read-only agent turn ("SYSTEM EVENT" note) | free-form inside the window, `WA_EVENT_TEMPLATE` outside it, else a human is told | `hubevent:seen:{id}` 7 d, `celebrated:paid:{order}` 24 h | no |
| E2 | **Missed-call message**, **recording notice** — `services/missed_call.py`, `recording_notice.py` | call events | code | — | cooldown 6 h | no |
| H1 | **Colleague reply / approve draft / media** — `services/conversation.py:481–830` | a person taps Send | the person | inside window; template otherwise refused | holder / super-admin rules (#305–#307) | **does not cancel any pending S1 row** |
| H2 | **"Team answer" compose** — `routers/admin.py:1760–1800` | a person types the fact Neema was waiting for | read-only agent turn | inside window only (409 otherwise) | — | no |
| H3 | **WhatsApp invite / follow-up template** — `routers/admin.py:2885–2930` | a person taps Invite | approved template `WA_INVITE_TEMPLATE` / `WA_FOLLOWUP_TEMPLATE` | template | — | no |
| A1 | **Approve a planned action** — `POST /admin/actions/{id}/approve` (web DealsView, Android DealsScreen) | a person taps Approve | the stored draft, or composed now | S1 rules | `claim()` | — |

Two uvicorn workers run every loop (`Dockerfile:48`, `--workers 2`); each loop
takes a redis leader/tick lock (`agentactions:leader`, `recoveryjobs:tick`,
`meta:missed:tick`, `agent:autorelease:tick`, `agent:unclaimed:tick`), so a loop
runs once per tick fleet-wide. Redis is `noeviction` and holds state, not cache.

### 1.2 Who has authority to send

Nobody and everybody. Each component decides for itself from its own view:
S1 from `agent_actions`, S2–S4 from their own redis guards, E1 from event
ids, L1 from the inbound message. There is no object that represents "what
Bethany House last said to this person, and why", and no row on `messages`
records which component sent an outbound (the `raw_meta` column exists and is
used only for the hold line, `runtime.py:2362`). The inbox therefore cannot
show staff *why* a message went out, and no sender can ask "has anyone
written to this customer today?".

### 1.3 How they interact today (and collide)

```
customer msg ─► L1 live turn ──► scribe (deals.scribe_update)
                   │                 ├─ own promise  → S1 follow_up (+3 h)
                   │                 ├─ customer day → S1 customer_promise
                   │                 └─ quote        → S1 quote_follow_up (+4 h)
                   ├─ tool schedule_check_in ────────► S1 replenishment (NO dedup)
                   ├─ tool check_availability ───────► internal note + team ping (no state)
                   └─ cart changes ──────────────────► S3 (reads the cart later)
hub order ───────► E1 celebrate ─► fit_check row ────► S1
quiet thread ────► S2 (15:00)   ◄─ sees S1 rows, carts, orders; not S3/S4 sends
cart ────────────► S3 (11:00)   ◄─ sees nothing else
unpaid order ────► S4 (10:00)   ◄─ sees the hub only
colleague ───────► H1           ─► nothing cancelled, nothing recorded for S1–S4
```

Collisions observed in the three threads (first audit §2, confirmed
mechanisms below): S1×3 + S3 on one morning (Judas); S1 quote nudge + S2 on
one day after the customer asked for time (Willy); S2 during an open
availability check in the wrong language (Pastor Emmanuel); S1×2 template
sends in one tick (Judas, Thursday).

### 1.4 Retries, duplicate events and overlapping executions — verified

| Mechanism | Where | Verdict |
|---|---|---|
| Meta redelivers a webhook | `wa_native._ingest_one` wamid guard (`wa:native:seen:{wamid}`, 24 h) + `schedule_reply` `agent:seen:{dedup}` (600 s) | duplicate inbound → one turn. OK |
| Two workers, same loop | redis leader/tick locks | OK |
| Two senders, one planned action | `actions.claim()` conditional UPDATE + commit (`actions.py:267–283`) | OK — only one claimant sends |
| Send interrupted mid-way | `_recover_interrupted` → `needs_approval` after 10 min (`:300`) | OK (human checks the thread) |
| **Graph call times out after Meta accepted** | `messaging._send_waba` uses `httpx.AsyncClient()` with the **default 5 s timeout** (`messaging.py:208`; verified `Timeout(timeout=5.0)`); a timeout raises, `process_due` sets the row back to `planned` and retries up to 3× (`actions.py:349–372`, `:468–472`); the live turn's sweeper retries the whole turn | **duplicate-send risk.** WhatsApp Cloud API has no idempotency key for `/messages`; a slow Graph response (>5 s) is read as a failure and the same text is sent again. Low frequency, real. |
| **Second customer message while a turn composes** | inbound rows take **Meta's timestamp** (`messaging.py:575`), outbound rows take the server clock; `_run_and_send` waits on the in-flight lock then runs `run_turn`, which loads history ordered by `created_at` and **re-appends the live message when the last history row is not a user row** (`runtime.py:1817–1820`) | **confirmed cause of the double replies** (Willy ~22:20, Pastor Emmanuel ~10:00): the model sees msg₂ *before* reply₁ in history and again as the live message after it, and answers it a second time. |
| Hub event duplicates | `hubevent:seen:{id}` + `celebrated:paid:{order}` | OK; deferred events bypass `seen` by design |
| Delivery / read receipts | WhatsApp `statuses` are dropped (`wa_native.py:20`, only call statuses are read, `whatsapp_webhook.py:240`) | no provider acknowledgement beyond the synchronous wamid; a rejected/undelivered message is invisible |
| Stale AI response | composing takes 5–60 s; S1 claims before composing only for the template path; `_still_ai` guards a human takeover, nothing guards "the customer wrote meanwhile" (quote rows excepted, `quote_followup.stale_reason`) | gap |
| Human reply vs pending nudge | H1 does not touch `agent_actions`; the thread flips to human-held so S1 parks rows in `needs_approval`; `auto_release` (45 min quiet) returns the thread to AI; parked rows stay parked | acceptable, but a colleague's reply never *cancels* a now-moot nudge |

---

## 2. Conversation intelligence — does Neema understand, or react?

### 2.1 What exists

Deterministic detectors, all keyword/regex, each owned by a different module:

| Detector | File | What it recognises |
|---|---|---|
| `customer_declined` | `services/declines.py` | flat "no", can't afford, not now |
| `detect_customer_promise` | `services/deals.py:72` | verb (confirm/get back/decide/pay/…) **and** a time word |
| `detect_own_promise` | `services/deals.py:58` | Neema's "I'll confirm/let me check" (English only) |
| `is_closer` / `is_silent_ack` | `agent/runtime.py:628–720` | "I'll get back to you", thanks, blessings (≤ 8 words) |
| `is_question`, `buying_signal` | `agent/cooling.py` | pacing |
| `is_handoff_line` | `jobs/reengage.py:106` | our own hand-off phrasing (en/sw/fr) |
| `thread_language` / `looks_swahili` | `jobs/reengage.py:126`, `agent/voice.py` | Swahili, French; everything else is "en" |
| `domain.assess` | `agent/domain.py` | off-topic goods |

Model-level understanding lives only inside the live turn (the 118 kB prompt,
`agent/prompt.py`) and is not written anywhere a scheduler can read, except
through the regexes above run over the reply/inbound text by the scribe.

### 2.2 The seven statements, run through the actual code

| Statement | declined | customer promise | closer | handoff | What happens today |
|---|---|---|---|---|---|
| "Let me compare prices." | no | none | no | no | treated as a buying signal (`buying_signal` true); nothing suppresses S1/S2/S3 |
| "I will get back to you." | no | none (no time word) | **yes** | yes (reengage's own-line regex) | live turn answers once (prompt block `prompt.py:1027`), then asks "is there a day we should check back?" → a `schedule_check_in` is likely; S2 would skip only if *Neema's* last line matched the handoff regex |
| "I need to consult my bishop." | no | none | no | no | nothing; S1 quote nudge still due in 4 h, S2 at 15:00 |
| "Please contact me on Thursday." | no | **none** ("contact me" is not in the verb list) | no | no | depends entirely on the model calling `schedule_check_in(on_day="thursday")`; if it does, a `replenishment` row fires Thursday 18:00 — as a replenishment template if the window is closed |
| "I'm waiting for confirmation." | no | none | no | no | nothing; no link to the open `check_availability` note |
| "I have already paid." | no | none | no | no | prompt rule `prompt.py:1372` makes the live turn call `check_order_status`; the payment sweep re-checks the hub live (`payment_followup.py:150`) — correct **only** when the payment reached the hub |
| "Please stop messaging me." | **no** | none | no | no | **nothing anywhere.** No opt-out detector, no flag, no prompt rule (only `pause_conversation` for off-topic drift, `prompt.py:1124–1151`). S1–S4 continue. |
| Willy's Swahili "I'll compare in Arusha and tell you" | no | none | no | no | nothing (observed) |
| Hindi "I'll ask the bishop and tell you" | no | none | no | no | language "en"; nothing |

Conclusion: today Neema's *replies* understand intent (the model), but her
*decisions to speak unprompted* are driven by elapsed time, cart contents and
regexes. Customer decisions ("compare", "consult", "stop"), pending tasks
("waiting for confirmation"), emotions and natural endings are not represented
as state anywhere a scheduler reads.

### 2.3 Greetings and language in composed follow-ups

Every composed follow-up (S1, S3, E1, H2) runs `run_turn(read_only=True)`
with the **full live prompt**, which includes THE CLOCK ("open the
conversation with the matching greeting", `prompt.py:496–500`) and the note
"this is a FRESH message". A model told "fresh message + here is the time of
day" greets again: hence three "Good morning"s. S2 has its own composer and
its own rules (`reengage.build_prompt`), a third voice.

---

## 3. The outreach-ledger proposal, reviewed critically

The first audit proposed a redis ledger + per-customer lock. Reviewed against
§1.4, that is not sufficient:

1. **A lock prevents simultaneity, not duplication over time.** Judas's rows
   fired minutes apart; a 120 s lock changes nothing. What is missing is a
   *single decision* per customer per intent, which needs the intents to be
   visible to each other — i.e. one queue, not five senders plus a ledger.
2. **Redis is state here but not a ledger of record.** It is `noeviction`
   and persisted, yet a redis-only "last outreach" is invisible to the inbox,
   to reports and to a human deciding whether to call. The record must be on
   the message row (`messages.raw_meta`, no migration) *and* on the intent
   row (`agent_actions`), which already has status, reason, draft, timestamps
   and a veto UI on web and Android.
3. **Idempotency must be at the intent, not the send.** The Cloud API offers
   no idempotency key. The only reliable protection is: one row per
   (conversation, kind) while open — enforced by the database, not by code
   that looks first and inserts second (two workers, two turns) — plus the
   existing atomic `claim()`.
   *Migration required and justified:* a partial unique index
   `agent_actions (conversation_id, kind) WHERE status IN ('planned',
   'needs_approval')`, after merging today's duplicates. Boot-time
   `MIGRATION_STATEMENTS` already carries `CREATE … IF NOT EXISTS`
   statements (`main.py:18–247`), so this follows the house pattern; the
   project has 41 alembic revisions and a fresh-DB replay in CI.
4. **Unknown send outcomes must never be retried blindly.** `_send_waba`
   needs an explicit timeout (30 s like `send_wa_template`) and a distinct
   outcome: *timeout after request sent* → the row goes to `needs_approval`
   "outcome unknown — check the thread", never back to `planned`. The live
   turn's sweeper retry is already bounded by the "latest row is inbound"
   recheck; the burst fix in §5 closes the remaining double.
5. **Stale responses.** Before any scheduled send: re-read the newest inbound
   id captured at compose start; if it changed, drop the composed text
   (`quote_followup.stale_reason` does this for one kind; it must be the
   dispatcher's rule for every kind).
6. **Provider acknowledgements.** Start storing WhatsApp `statuses`
   (sent/delivered/read/failed) against `waba_msg_id` — `raw_meta` on the
   existing row carries it; no migration. Without it, "the template was
   sent" cannot be distinguished from "Meta accepted then failed".
7. **Durable customer preferences** ("do not message me", "contact me on
   WhatsApp only", "Swahili") have no home. `Conversation` and `Person`
   have no such columns; a redis flag can be lost on a flush and is not
   reportable. *Migration justified:* `persons.contact_preferences JSONB`
   (opt-out, language, quiet preference) — one nullable column.

Verdict: a ledger alone would reduce but not remove the failures. The
reliable design is **one intent queue with database-enforced uniqueness, one
dispatcher that decides from context, and stamped message rows** — §6.

---

## 4. Communication designed around the customer, not timers

### 4.1 Classes of outbound message and when each is helpful

| Class | Examples | Helpful when | Silence is right when | Window rule |
|---|---|---|---|---|
| **A. Reply** | answer to a question | always, once, in their language | they sent a closer / ack; a colleague already answered | inside window by definition |
| **B. Promised information** | "let me confirm the gold embroidery" | *the moment the fact exists* (team answered → H2) | nothing new to say — never "still checking" twice | inside window free-form; outside: human sends or an approved template |
| **C. Customer-agreed check-in** | "contact me Thursday", "we'll need wafers in two weeks" | on the named day, once, referencing what they said; adapted if they wrote since | they already came back; the matter closed | outside window ⇒ **follow-up/utility template whose text fits a check-in**, else a human |
| **D. Buying decision pending** (quote given / cart built, silence) | Willy's trays, Judas's $335 | *once*, when the silence is meaningful (next working day, not 4 h), the customer has not asked for time, no promise and no availability check is open, inside the window | they asked for time; they consulted someone; two unanswered nudges already; a decline | free-form inside the window only (owner decision 1: no manufactured early nudges; outside it, nothing until they write or a genuine reason arises) |
| **E. Payment reminder** | unpaid order with link | once after grace, with the *same* link; again only with new information (price change, stock arriving, link expiring) | they said when they'll pay (wait for it); "already paid" pending; a complaint | inside window; outside it a human decides |
| **F. Order updates / payment confirmed** | paid, in production, shipped, delivered | always, immediately (deferred from quiet hours), never duplicated per event | — | template outside window (utility) |
| **G. Care** | fit check 6 days after delivery | once; care wording | the order had a complaint | utility template |
| **H. Complaint resolution** | — | human-led; Neema speaks only to acknowledge and route | never a sale into a grievance | — |
| **I. Campaign** | seasonal | explicit owner decision | — | marketing template |

Rules that follow from the table, not from a clock:
- One unprompted non-transactional message per customer per day; F never
  waits behind it, but two automated messages within the same minute to one
  customer are coalesced into one.
- D is one decision, not two: the quote nudge and the cart nudge are the
  same "they were about to buy" moment and must be one row per deal.
- A kept promise (C) outranks D and is cancelled by nothing but the
  customer's own change of plan.
- "Needs time" (compare, consult, decide next week, not ready) suspends D
  and E until the stated date or, unstated, until they write again; the
  live turn is told so and asks for a date at most once.
- An open B (availability / price check) suspends D and E and makes "shall
  I start the order for *that* item" off-limits until the answer arrives.
- "Stop messaging me" (any language) ends D, E, G, I permanently and
  routes A/F through a human; recorded on the person.

### 4.2 Transactional messages are never starved

F and B-with-an-answer are classified `transactional` and bypass the daily
cap and the needs-time hold; they still obey human-held, opt-out, the
per-customer in-flight lock and event dedup. Colleague messages (H1) are
never gated — they are the ground truth the gate reads.

---

## 5. Duplicated and conflicting intelligence — causes and precedence

| Symptom | Cause(s) with references | Precedence today | Resolution (no new layer) |
|---|---|---|---|
| Repeated greetings | composed follow-ups run the live prompt with THE CLOCK (`prompt.py:496`) under a "fresh message" note (`actions.py:156`, `cart_recovery.py:166`); S2 has a third composer | none — three composers, three rule sets | one composer note for all unprompted messages: "continuation of an open chat: no greeting if we spoke within 24 h, no re-welcome, their language, one sentence of why, at most one question"; THE CLOCK rule applies to the *first* message of a conversation only (already its text — make the composer note say so explicitly) |
| Several messages about one decision | S1 own-promise + S1 customer-promise + S1 check-ins + S1 quote + S3 cart + S2 all model "they were about to buy" separately; `upsert_follow_up` coalesces only deal rows; `schedule_check_in` never (`tools.py:2905–2957`); `process_due` sends every due row (`actions.py:371`) | none | one row per (conversation, kind) enforced by the index; D merged into one kind; S2 retired (owner decision 2); S3/S4 become planners that file rows |
| Selling during an open availability check | `check_availability` leaves a note and a ping but **no state** (`tools.py:2174–2245`); prompt says "CONTINUE the sale meanwhile … the order itself" (`prompt.py:1358–1366`, `1664–1680`); S2 strips notes from its transcript (`reengage.py:268`) | prompt rule wins, nothing on the scheduler side | record the open check on the deal (`deal.blocking`, exists) and clear it when a colleague answers (H2 / note reply); the dispatcher reads it; the prompt rule is reworded: continue with *other* items, never ask to start the order for the item under confirmation |
| Commitments scheduled more than once | `schedule_check_in` description "call it IN THE SAME TURN they name the time" (`tools.py:486`), prompt `960`, `1035`, `1083`; every turn re-reads the whole thread; no upsert | — | upsert (newest replaces), tool result says "already booked for <day>" so the model does not re-promise |
| Requests for time ignored | no detector for compare/consult/decide/not-ready; `_CLOSER_RE` catches only "I'll get back"; prompt block `1027–1046` then *asks for a date* and books it | prompt asks for a date; schedulers ignore the answer unless a time word is present | a per-turn **state note** written by the live turn (see §6.3) + deterministic floor (regex for the common phrases in en/sw/fr) → `deal.next_action = {"kind":"wait", "until":…}` |
| Unsuitable templates | one utility template for three purposes with different parameter contracts (`actions.py:122–152`, `hub_events.py:272–288`); `WA_FOLLOWUP_TEMPLATE` exists but is unused by automation; `[Oo]rder\s+(\w+)` regex; marker text stored instead of the body | — | a template registry: name → purpose → parameter builder → rendered body; a send is refused when the purpose does not match or a parameter is empty; the rendered body is what the inbox stores |
| Lost language continuity | `thread_language` knows sw/fr/en (`reengage.py:126`); `voice.py` has only `looks_swahili`; the live turn infers language per message; nothing stores the customer's language | prompt THE LANGUAGE (`1564`) per message | store `language` on the person (migration §3.7) written by the live turn's state note; every composer receives it; unsupported language ⇒ no automated message |
| Two replies to overlapping messages | Meta-timestamped inbound + server-timestamped outbound + history re-append (`runtime.py:1817–1820`) | — | when a waiting turn starts, pass the newest outbound time; if our reply went out *after* this inbound arrived, the turn gets a note "already answered unless something new" and the gate may return silence; alternatively fold the message into the running turn's debounce |
| Promise follow-up at +3 h regardless of wording | `PROMISE_FOLLOW_UP_HOURS = 3` (`deals.py:35`) | — | the promise follow-up is B: due when the team answers, with one honest "still on it" after a working day, then a human |

Conflicting instruction families inside the prompt itself (118 kB): 12 rules
mention greeting, 9 language, 7 "ONE question", 6 `check_availability`, 4
`schedule_check_in`, 4 "start your order / proceed". The precedence list at
`prompt.py:483–494` ranks money, brevity, complaint, answer-first, discovery,
extras — it does not rank *initiative* (when to book, when to nudge, when to
stay silent). Resolution: add one precedence line, "Initiative: a booked
check-in, an open team check or a customer's request for time outranks every
'advance the sale' rule", and move the four booking rules under it instead of
adding new ones.

---

## 6. One coherent experience — recommended architecture

**Principle:** planners plan, one dispatcher decides and speaks. No new
engine: `agent_actions` + `actions.process_due` become the single path for
every unprompted message; the live turn remains the single path for replies;
humans are never gated.

### 6.1 Components

1. **Intent queue** = `agent_actions` (exists). New `kind` vocabulary:
   `reply_owed` (B), `check_in` (C), `buying_follow_up` (D, replaces
   `quote_follow_up` + cart nudges), `payment_reminder` (E), `order_update`
   (F, filed by hub events, sent immediately), `care_check` (G, replaces
   `fit_check`). `created_by` carries the planner (`scribe`, `tool`,
   `hub`, `payments`, `human`). Uniqueness index per §3.3.
2. **Planners** (file rows, never send): the scribe (promises, quotes,
   needs-time), `schedule_check_in`, hub events, the payment sweep (becomes
   a planner at 10:00), the cart sweep (becomes a planner; files
   `buying_follow_up` on the deal, merging with the quote row). The 15:00
   re-engage sweep is **retired**; its one legitimate responsibility (a quiet
   thread after a quote) is already D.
3. **Dispatcher** = `process_due`, extended with `decide(conv, person,
   deal, action)` — one function, one log line, one reason. Inputs: person
   preferences (opt-out, language), the deal (`blocking`, `next_action`:
   wait-until, open team check), the last inbound/outbound (who spoke last,
   when, colleague or Neema), today's automated count from stamped rows,
   WhatsApp window state, template availability, human-held/paused, event
   class. Output: `send | suppress(reason) | defer(until) |
   needs_approval(reason)`. Every outcome is written to the row (status +
   reason), so the queue **is** the decision log; nothing is silent.
4. **Composer**: one note for all unprompted messages (continuation, no
   greeting within 24 h, their language, why-now in one sentence, ≤ 1
   question, never a stall), fed the same facts the dispatcher used; code
   composition retained where figures matter (D, E).
5. **Sender**: `_send_waba` with an explicit timeout and an *unknown*
   outcome; every outbound row stamped `raw_meta = {"kind": "outreach",
   "action_id", "class", "template": name|null, "rendered": body}`; WhatsApp
   `statuses` recorded on the row.
6. **Template registry**: purpose-keyed; refuses mismatches and empty
   parameters; renders the body the inbox shows.
7. **State note from the live turn** (§6.3) so the dispatcher understands
   what the model understood.

### 6.2 What the dispatcher knows (owner's list, mapped)

| Need | Source |
|---|---|
| Customer profile and preferences | `persons.contact_preferences` (new column), `users.name`, parish, country |
| Complete relevant context | last 40 messages (already loaded by the composer), the deal row |
| Order / quotation status | `order_events` + live hub status (`hub_client.fetch_order_status`), `deal.stage` |
| Outstanding commitments | `agent_actions` open rows + `deal.blocking` |
| Language and tone | person preference written by the live turn; `looks_swahili`/French detectors as fallback |
| Recent human and automated communications | stamped `messages` rows (sender, `raw_meta.kind`, time) |
| WhatsApp permissions / templates | `_within_window` + the template registry |
| Human intervention needed | `intercept_mode`, open flags, `needs_approval` outcomes |
| Does the message add value | the composer's facts vs. the last outbound (containment check exists, `actions._repeats_earlier`), the "why now" must name a fact newer than the last outbound |

### 6.3 Making intent visible: the per-turn state note

The live turn already reads the whole conversation with the full prompt. Add
one cheap structured step after each real turn (light model, no tools, same
pattern as `reengage._compose_llm`): `{"waiting_on": "customer|us|team|none",
"customer_asked_time_until": date|null, "customer_said": "compare|consult|
not_ready|paid|stop|closing|none", "language": "en|sw|fr|hi|…",
"open_item_check": "…"|null}`. Stored on `deal.next_action` / `deal.blocking`
and `persons.contact_preferences`. A deterministic floor (regexes in en/sw/fr
for *stop*, *paid*, *compare*, *consult*, *not now*) runs first so an opt-out
or a payment claim is never lost to a model hiccup. This replaces nothing; it
gives the schedulers what the model already knew.

### 6.4 Minimal changes list

| Change | Files | Migration |
|---|---|---|
| Unique open-intent index + merge duplicates | alembic + `main.py` boot statement | yes, small |
| `persons.contact_preferences JSONB` | alembic + model | yes, one column |
| `schedule_check_in` upsert + "already booked" result | `agent/tools.py` | no |
| Dispatcher `decide()` + per-conversation coalescing + unknown-send outcome | `services/actions.py`, `services/messaging.py` | no |
| Retire S2; S3/S4 → planners | `services/recovery_jobs.py`, `jobs/*` | no |
| Template registry + rendered body + refusal | new `services/templates.py`, callers | no |
| Burst-while-composing fix | `agent/runtime.py` (history/live-message handling), `wa_native` | no |
| State note + floor detectors | `services/deals.py` (scribe), new `services/intent.py` | no |
| Status webhook recording | `wa_native.parse_events`, `messaging` | no |
| Prompt: initiative precedence line, availability wording, one check-in | `agent/prompt.py`, tool descriptions | no |
| Trace CLI + standup line + health counts | `jobs/outreach_trace.py`, `jobs/self_qa.py`, `routers/health.py` | no |

---

## 7. Experience scenarios (regression set)

| Scenario | Neema should | If a message is needed, it says | Why |
|---|---|---|---|
| **Judas** — $335 quotation, friend may collect in Nairobi or DHL to Juba, "I'll check in Thursday", customer "Thank you very much." | Wednesday: **nothing** (one booked check-in exists for Thursday; a thank-you is a closer). Thursday evening: one message if the window allows free-form; if not, the approved follow-up template or a colleague — never the replenishment text. If he writes before Thursday, the check-in adapts or is dropped. | "Judas, as promised on Thursday: shall your friend collect from the Nairobi shop, or do we send to Juba by DHL? Your quotation stands until 17 November." | one commitment, kept once, in context; no cart nudge because the cart *is* the quotation |
| **Willy** — quoted $220 + $25, asks Ksh, then "I'll compare in Arusha and tell you" | answer the Ksh question once (done); on "I'll compare": acknowledge and **stop** — no quote nudge, no 15:00 check-in; the deal waits until he writes or a real change (price, stock) occurs | reply only: "Sawa, Rev. Dr. Ackyoo — bei zetu zinasimama; nitakuwa hapa ukiwa tayari." (one line) | respecting a stated intention is the sale-preserving move; a nudge seven hours later reads as pressure |
| **Pastor Emmanuel** — Hindi, cope $450, gold embroidery under availability check | reply in Hindi: price, photo, "we're confirming the embroidery with the workshop" — **without** "shall I start the order?" for that item; no automated message until the team answers; when the colleague answers, one Hindi message with the fact (H2) and then the close | H2: "पादरी इमैनुएल, कारखाने ने पुष्टि की है: सोने की कढ़ाई उपलब्ध है, Cope — Complete Set $450 में। क्या मैं आपके लिए ऑर्डर शुरू करूँ?" | the pending fact is the next message, nothing else is |
| Human takeover mid-composition | drop the composed reply (`_still_ai`, exists); a colleague's reply vetoes pending D/E rows for that conversation | — | the person owns the thread |
| Simultaneous messages (burst while composing) | the second turn knows our reply went out after their second message; answers only what is new, else silence | — | one answer per question |
| Duplicate scheduling (two `schedule_check_in` calls, two scribe passes) | one open row per (conversation, kind); the second call returns "already booked for Thursday" | — | DB-enforced |
| Failed dispatch (Graph 5xx) | row back to `planned`, retried on the next tick, 3 tries then human | — | bounded |
| Unknown dispatch (timeout) | row to `needs_approval` "outcome unknown — check the thread"; never auto-resent | — | no idempotency key exists |
| Language switching (customer moves from English to Swahili) | reply in the language of *that* message; composed follow-ups use the stored preference (last customer language); unsupported language ⇒ no automated message | — | continuity without guessing |
| Explicit opt-out ("please stop messaging me", "acha kunitumia ujumbe") | one short acknowledgement; person flagged; every unprompted class ends; order updates go via a human | "Understood — we won't message you. We're here whenever you need us." | respect first; the flag is durable |
| Completed purchase (paid) | deal won (exists); all open D/E rows vetoed; F messages only | "Payment received, thank you — production begins. Receipt: <link>" | after the yes, only service |
| Legitimate order update during the daily cap | sent immediately regardless of what else went today; coalesced with a same-minute automated message | — | transactional outranks the cap |
| Customer asks for one week | hold until the day; the live turn does not ask for a date again; on the day, one check-in (C) | "Hello Judas — a week on, as you asked: shall we go ahead with the 2 Aluminium Trays and 50 cups, or would you like anything changed?" | their timeline, kept |
| Awaiting stock confirmation, no team answer in a working day | one honest line (B), then a human is asked; no sales nudge | "Still confirming the ready piece with the workshop — I'll come back the moment I have it." | one stall, never two |
| Quotation updated after a row was planned | the newer quote replaces the row (exists for quotes); the composed text is rebuilt from the current quote | — | figures never drift |
| Template with an empty / unresolved parameter | refused before Meta; row to `needs_approval` with the reason | — | never nonsense to a customer |

---

## 8. Evidence-based implementation proposal

### 8.1 Confirmed root causes

1. `schedule_check_in` creates unbounded duplicate rows (`tools.py:2905–2957`); the prompt instructs repeated booking (`prompt.py:960, 1035, 1083`); `process_due` sends each due row (`actions.py:371–380`).
2. Deal-less rows escape every coalescing and counting rule (`actions.upsert_follow_up`, `needs_approval` MAX_AUTO_NUDGES, `actions.py:55–75, 118–121`).
3. The replenishment utility template is sent for a deciding customer with regex-derived parameters (`actions.py:122–152`, `:420–433`); the inbox stores a marker (`:149`, `hub_events.py:286`).
4. Three daily sweeps and the actions loop never consult each other (`recovery_jobs.py`, `reengage.why_not`, `cart_recovery.find_abandoned`, `payment_followup.find_unpaid`); all three are enabled in send mode on the box (health view).
5. Stated intentions are not detected or stored (`declines.py`, `deals.py:40–50, 72–120`; `runtime.py:628–650`).
6. Re-engage ignores open availability checks and non-sw/fr languages (`reengage.py:106, 126, 268`).
7. Double replies: Meta-timestamped inbound rows + history re-append (`messaging.py:575`, `runtime.py:1817–1820`).
8. Duplicate-send risk on slow Graph responses: 5 s default timeout + retry (`messaging.py:208`, `actions.py:468–472`).
9. No opt-out handling anywhere.
10. Composed follow-ups greet because they run the live prompt's clock rule as a "fresh message" (`prompt.py:496–500`, `actions.py:156`).

### 8.2 Unverified hypotheses (need the box)

- The exact kinds of Judas's three Wednesday rows (`agent_actions` for that conversation) and whether the 11:00 message is S3 (health says S3 sent 5 that day). → `SELECT kind, status, reason, due_at FROM agent_actions WHERE conversation_id = …`.
- That both template rows carry a `waba_msg_id` (delivered) and what the approved body of `orderupdate_category` reads. → the two `messages` rows + WhatsApp Manager.
- The burst sequence for Willy (22:20) and Pastor Emmanuel (10:00) in the API log (`tier2 replied to …` twice within a minute, preceded by a second `native:` ingest).
- Whether any customer has already asked Neema to stop and been ignored (search inbound text for stop/acha/usinitumie).

A read-only trace command (`python -m app.jobs.outreach_trace <number>`) is
part of phase 0 so these are answered from the box without SQL.

### 8.3 Conflicts and precedence (resolved, not stacked)

Stated in §5. The one new precedence line in the prompt and the single
dispatcher replace: the three composer voices, the two "one per deal" rules,
the three quiet-hour copies, the two template parameter contracts and the
per-job guards.

### 8.4 Risks

| Risk | Mitigation |
|---|---|
| Fewer follow-ups ⇒ fewer recoveries (quote nudges got 39 % replies in 72 h) | shadow mode first (decisions logged, not enforced, like `pacing_budget` today); compare "would have suppressed" against replies for a week; the owner reads the numbers before enforce |
| Index creation fails on existing duplicates | migration merges open duplicates per (conversation, kind) keeping the latest `due_at`, then creates the index; replayed in CI on a fresh DB |
| The state note misreads intent | deterministic floor for stop/paid; the dispatcher's suppressions are visible rows a person can approve |
| A transactional message is wrongly suppressed | class `transactional` bypasses cap/hold by construction; tested |
| Prompt edits regress replies | Paparazzi-style prompt tests exist (`test_prompt_audit_2026_11_05.py`); replay `agent_eval` on the box before enforce |

### 8.5 Tests (all automated)

Unit: `decide()` matrix (every class × every state); `schedule_check_in`
upsert; template registry refusal; `_send_waba` unknown outcome; intent
floor in en/sw/fr; burst note. DB (real Postgres, existing rigs): the unique
index under two concurrent inserts; three due rows → one send; a reply
seconds before due → vetoed; human reply vetoes D/E; paid → rows vetoed;
quiet-hours deferral of F; opt-out persists across restarts. Scenario
replays: the three screenshot threads reconstructed as fixtures with the
expected outputs of §7. Experience: `agent_eval` scenarios extended with
the seven statements.

### 8.6 Migrations and rollback

- M1 `agent_actions` partial unique index (+ merge). Rollback: drop index.
- M2 `persons.contact_preferences JSONB NULL`. Rollback: column stays, unused.
- Everything else behind `OUTREACH_MODE = shadow | enforce` (default
  `shadow`) and the existing `AGENT_INITIATIVE`, `RECOVERY_*` switches;
  rollback = flip the setting, no redeploy.

### 8.7 Safe sequence

0. **Now, config only (no code):** `RECOVERY_REENGAGE_ENABLED=false` on the
   box (owner decision 2 takes effect today); optional
   `RECOVERY_CART_ENABLED=false` until S3 becomes a planner.
1. **Stop the bleeding (one PR, low risk):** `schedule_check_in` upsert;
   per-conversation coalescing in `process_due`; no replenishment template
   for deal/check-in rows (→ `needs_approval` with the reason); template
   refusal + rendered body; `_send_waba` timeout + unknown outcome; burst
   note; opt-out floor; trace CLI. Tests for each. Deploy.
2. **Unified dispatcher in shadow:** `decide()` + stamped rows + M1 + M2 +
   S3/S4 as planners + S2 retired in code; `OUTREACH_MODE=shadow` logs
   "would suppress/defer" for a week; standup reports the counts.
3. **State note + prompt precedence + composer note.** Replay `agent_eval`
   on the box; owner reviews a day of drafts.
4. **Enforce.** `OUTREACH_MODE=enforce`; watch Reports → Pacing and the
   suppression reasons for a week; tune per class.

Approval requested for: the sequence above, the two small migrations, and
the per-class rules in §4.1.
