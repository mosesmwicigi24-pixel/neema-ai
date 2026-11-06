# Neema outreach audit — 2026-11-05 (read-only, no code changed)

Live box at fa177bb. Evidence: the three screenshots, the code on main, and
/api/health (recovery switches and run history). I have no database access, so
each screenshot message is attributed by its composition shape and the clock
time of the path that produces it; where two paths could produce it I say so.
`python -m app.jobs.outreach_trace <number>` (part of the correction plan)
will print the exact rows.

## 1. Every path that can message a customer unprompted

| # | Path | Trigger | Own guards | Knows about the others? |
|---|---|---|---|---|
| 1 | `services/actions.py` `process_due` (60 s loop) | `agent_actions` rows: `follow_up` (Neema's own promise, +3 h), `customer_promise` (customer named a day), `quote_follow_up` (+4 h after a quote), `replenishment` (`schedule_check_in` tool), `fit_check` (+6 d after delivery) | quiet hours 20:00–08:00 NBO, 24 h window, human-held, flagged thread, deal > KES 50k, ≥2 sent **per deal**, `_repeats_earlier` wording check | No. Counts only rows on the same deal; rows with `deal_id=None` (every `schedule_check_in` and fit check) never count |
| 2 | `jobs/reengage.py` 15:00 NBO (**enabled, send mode**: 7, 8, 5 sent on 3–5 Nov) | we spoke last, customer quiet ≥ 3 h, inside 24 h window | once per customer message (redis), skips carts, orders, planned/sent actions since last inbound, declines, handoff lines (en/sw/fr) | Partly: looks at `agent_actions`, not at cart/payment sends |
| 3 | `jobs/cart_recovery.py` 11:00 NBO (**enabled**: 10, 5, 3 sent) | cart with items, quiet ≥ 45 min, inside window | once per basket per 7 d | No |
| 4 | `jobs/payment_followup.py` 10:00 NBO (**enabled**: 3, 0, 3 sent) | unpaid order with link, ≥ 2 h | once per order, hub re-checked | No |
| 5 | live turn (`_run_and_send`) | customer message | debounce 30 s, in-flight lock (#308), closer gate | — |
| 6 | `services/unclaimed.py` | human-held, nobody picked up in 30 min | once per customer message | — |
| 7 | `hub_events` celebrations, missed-call, recording notices | hub / call events | own | transactional |

Nothing joins 1–4. There is no per-customer "last automated message" anywhere,
no per-customer lock across paths, no daily cap, and no record on the
`messages` row of which path sent it (so the inbox cannot show it either).

## 2. The screenshot cases

### Case A — Judas Othow (+211 985 555 188)

Timeline (Nairobi, from the relative times at 18:21):
- Tue 3 Nov: customer "Thank you very much." Neema: "I'll check in with you on Thursday".
- Wed 4 Nov morning: three composed check-ins minutes apart ("Good morning, Judas. I'm checking in on your quotation…", "Judas, I'm following up as agreed…", "Good morning, Judas. There's no rush on our side…"), then at ~11:00 "Good morning Judas, your selection is 2 Aluminium Trays, 50 Silver Communion Cups… $335… go ahead?".
- Thu 5 Nov 18:0x: two rows "[template orderupdate_category] replenishment on sent" / "… on your supplies", one minute apart.

Root causes, with code:
1. **Several planned-action rows for one conversation, each sent on its own.**
   `tools._schedule_check_in` (tools.py:2905) adds a new `AgentAction(deal_id=None,
   kind="replenishment")` on every call with no look-up of an existing one. The
   prompt tells the model to call it "the MOMENT they name any time"
   (prompt.py:1035), "on the day before their date" (prompt.py:960) and again
   for supplies (prompt.py:1083), and every turn re-reads the thread, so a
   named day is booked again in the next turn. `actions.upsert_follow_up` does
   coalesce — but only rows that carry a `deal_id` (the scribe's own-promise /
   customer-promise rows). `process_due` (actions.py:371) then takes up to 10 due
   rows ordered by `due_at` and sends each one; the only repetition check is
   wording (`_repeats_earlier`), and a model asked to "keep the commitment"
   three times writes three different sentences — the third one literally
   apologises ("There's no rush on our side").
   The Thursday 18:00 pair is the clearest proof: `schedule_check_in(on_day=
   "thursday")` lands at 18:00 Nairobi exactly (tools.py:2925, `hour_utc=15`),
   and two rows came due in the same tick.
2. **The 11:00 message is `cart_recovery`** (health: enabled, 5 sent on 4 Nov).
   It checks its own basket guard only (cart_recovery.py:160–200); it never
   asks whether anything else was sent to this customer that day.
3. **The Thursday promise was kept by the wrong mechanism.** The customer's
   last message was > 24 h old, so `process_due` took the template branch
   (actions.py:420–433): `_send_followup_template` sends the UTILITY template
   `orderupdate_category` with body parameters `[first name, number, phrase]`
   where `phrase` is hard-coded replenishment text ("about time for the next
   round? Reply here and we'll plan your delivery") and `number` comes from
   `re.search(r"[Oo]rder\s+([A-Za-z0-9-]+)", action.reason)` — which matched
   the word after "order" in the reason text ("sent") or fell back to "your
   supplies". Judas, deciding on a $335 quotation, received a replenishment
   check-in about "order sent", twice.
4. **The inbox shows the marker, not what the customer got.** The row text is
   `f"[template {name}] {kind} on {number}"` (actions.py:149) — the real body
   is only known to Meta. Staff cannot see what was sent.
5. **"I'll check in on Thursday" was respected — but nothing stopped the
   Wednesday rows.** `deals.detect_own_promise` deliberately excludes "check
   in" (deals.py:31), so no extra 3-hour row was planned for that sentence;
   the Wednesday rows are earlier bookings (a customer-promise row from the
   scribe and/or `schedule_check_in` calls for "tomorrow"). Nothing re-plans
   or cancels older rows when a newer, later promise is made for the same
   conversation (`upsert_follow_up` only replaces rows on the same deal).

Was the template delivered? `save_outbound_message(..., waba_msg_id=…)` stores
Meta's message id only when Meta accepted it; `finish(..., "sent")` runs only
on success. Two rows → two accepted sends. The trace tool will show the ids.

### Case B — Willy K. Ackyoo (+255 754 648 158)

- ~22:20 Wed: two different replies to one customer question (both "we price in
  USD… Golden Communion Tray $220, Anointing horn $25").
- 08:20 Thu: "Habari 🙏 Nafuatilia tu bei niliyokutajia… Nikuwekee? (Just
  following up… shall I reserve them for you?)" — this is
  `quote_followup.compose` word for word (quote_followup.py:200–214): planned
  4 h after the quote, pushed past quiet hours to 08:00.
- 08:3x Thu: customer: he will check prices in Arusha and come back
  ("Nitakuambia nikishapata majibu"). Neema acknowledged.
- 15:20 Thu: "Habari Willy, ulikuwa unaangalia Golden Communion Tray ($220) na
  Anointing horn ($25). Ungependa kuagiza ipi kati ya hizo?" — `reengage`
  (15:00 run, 5 sent), its Swahili composer, greeting by the WhatsApp profile
  first name "Willy" while the thread calls him "Rev. Dr. Ackyoo".

Root causes:
1. **The stated intention is not recognised anywhere.** `declines.customer_
   declined` only matches a flat no / can't afford (declines.py); `deals.
   detect_customer_promise` needs a time word (deals.py:40–50) — "I'll tell
   you when I have the answers" has none. So "needs time" produces no hold,
   and `reengage.why_not` (reengage.py:285–330) sees only "we spoke last,
   quiet 6 h, inside the window" → go. The quote follow-up sent at 08:20 does
   not count for reengage's `_followed_up` because it was sent *before* the
   customer's 08:3x message.
2. **Three automated or semi-automated messages in one day** (quote nudge,
   reply, re-engage) because no path knows the others sent.
3. **The double reply** is not produced by any scheduled path (the cassock
   ladder second message, runtime.py:2168–2184, applies to cassocks only).
   The likely mechanism: the customer sent a second message while the first
   turn was composing; inbound rows take Meta's send timestamp
   (messaging.py:575) so it sorts above the first reply in the thread; the
   second turn waited for the in-flight lock (#308) and then answered the same
   question again. Confirm from the box log for that number; the correction
   below guards it either way.

### Case C — Pastor Surdas Emmanuel (+91 90983 46693)

- ~10:00 Thu: `check_availability` note ("gold embroidery"), photo card, Hindi
  reply ending "Shall I start this set for you?", second Hindi message ("usually
  ready in ~4 days. When do you need it by?").
- 15:20 Thu: English "Jai Masih Ki, Pastor Emmanuel 🙏 I'm writing about the
  Cope — Complete Set at $450… Would you like me to start the order?" —
  `reengage` again.

Root causes:
1. **Re-engage cannot see a pending availability check.** The internal note is
   `media_type="note"` and is excluded from its transcript (reengage.py:268);
   the hold line it looks for (`_HANDOFF_RE`, reengage.py:106) knows English,
   Swahili and French words only, and Neema's "we've asked the workshop, will
   tell you when the answer comes" was in Hindi.
2. **Language.** `thread_language` returns "en" for anything not Swahili or
   French (reengage.py:126), so a Hindi thread gets an English check-in, and
   the quality gate accepts it because "en" is what it was asked for.
3. **Closing while confirming.** The prompt says to keep selling while the
   team confirms (prompt.py:1358–1366, 1664–1680: "CONTINUE the sale meanwhile
   … the order itself"). The model read that as "ask to start the order for
   the very item under confirmation".
4. **Second Hindi message in the same window**: same burst mechanism as Case B
   (or a second customer message); not a scheduled path.

### Case D — raw template rows

See A.3/A.4. Produced by `actions._send_followup_template`; the customer
receives the approved template body with `{{1}}` = first name, `{{2}}` =
"sent" / "your supplies", `{{3}}` = the replenishment phrase. The inbox stores
only the marker. Two further template senders store the same marker shape:
`hub_events._celebrate` (hub_events.py:286) and `seasonal_outreach` (:277).

## 3. Conflict report — overlapping and competing implementations

1. Five independent senders (actions, reengage, cart_recovery, payment_followup,
   unclaimed) with five separate guards; none consults a shared record.
2. Two different "one per deal" rules: `actions.upsert_follow_up` (deal rows)
   vs none for `schedule_check_in` / fit-check rows (`deal_id=None`). The
   `MAX_AUTO_NUDGES=2` gate counts `sent` rows per deal, so check-ins are
   never counted.
3. Two "did the customer already answer?" checks that look at different
   anchors: reengage counts sent actions *after the last inbound*; actions
   counts sent rows *ever on the deal*.
4. Three different quiet-hour implementations (`hub_events.is_quiet_hours`,
   `reengage.within_quiet_hours`, `cart_recovery.within_quiet_hours`,
   `payment_followup.within_quiet_hours`) with the same 08–20 constants.
5. Two template senders with different parameter contracts for the same
   `WA_EVENT_TEMPLATE` (`hub_events` passes `[first, number, brief]`, actions
   passes `[first, number, phrase]`), and a third template
   (`WA_FOLLOWUP_TEMPLATE`, admin.py:2899) meant for exactly the "customer
   went quiet" case but unused by every automated path.
6. Prompt vs scheduler: the prompt insists on booking a check-in whenever a
   time is named and on asking for a time whenever the customer defers
   (prompt.py:1028–1046); the scheduler has no de-duplication for those
   bookings. The prompt's "no chase the next day — the scheduled check-in is
   how we return" is undone by reengage and cart_recovery, which the prompt
   does not know exist.
7. Timing conflict with the brief's 48–72 h default: every free-form path is
   bound to Meta's 24 h customer-service window, so a first follow-up at 48 h
   can only go as an approved template (`WA_FOLLOWUP_TEMPLATE` is still
   unapproved per the owner's pending list).

## 4. Correction plan (smallest safe set, no migration)

A. **One outreach ledger** — new `services/outreach.py`:
   - `decide(db, redis, conv, source, kind)` → allow / suppress / defer with a
     reason. Checks in order: human-held / paused / closed; per-customer lock
     (redis `SET NX`, 120 s) so two workers or two paths cannot send at once;
     customer wrote since the trigger; "needs time" hold (C); quiet hours;
     at most ONE routine sales outreach per customer per Nairobi day; at least
     `outreach_first_hours` (default 48) after the customer's last message
     for the first routine follow-up and `outreach_next_hours` (72) after
     the previous one; stop after `outreach_max_unanswered` (2) in a row.
     Kinds: `routine` (quote nudge, re-engage, cart nudge, fit check),
     `promise` (a day the customer or Neema named — exempt from the interval
     rules, still one per day and still cancelled by a reply), `transactional`
     (payment reminder, order celebration, unclaimed answer — exempt from the
     sales rules, still locked and logged).
   - `record(...)` stamps the sent row's `raw_meta` with
     `{"kind": "outreach", "source": …, "action_id": …}` (column exists —
     no migration) and appends to a redis decision log per customer.
   - Wired into `actions.process_due` (before composing — saves the model
     call), `reengage._handle`, `cart_recovery._handle`,
     `payment_followup`, `unclaimed`, `hub_events._celebrate`.
B. **Coalesce planned actions per conversation.** `schedule_check_in` upserts
   one open check-in per conversation (a newer date replaces the older);
   `process_due` groups due rows by conversation and sends one, marking the
   rest `merged`. A reply from the customer vetoes `follow_up` /
   `customer_promise` / `quote_follow_up` rows (today only the quote one);
   a named-day promise survives a reply but is re-composed with the new
   context.
C. **Customer intention.** `services/intent.py` `needs_time(text)` for
   "I'll get back / let me compare / discuss with / decide next week / not
   ready / nitakuambia / nitarudi / kulinganisha / je reviens" etc. The scribe
   sets a hold (named date if any, else 7 days) that suppresses every routine
   outreach and vetoes pending routine rows; the live turn is told the hold
   exists so it does not ask for a date again. Surfaced in the inbox row as
   "asked for time until <date>".
D. **Templates.** A deciding customer's check-in outside the window uses
   `WA_FOLLOWUP_TEMPLATE` when configured and otherwise waits for a human
   (`needs_approval`) — never the replenishment phrase. The order number is
   taken only from a real order-number pattern, else omitted. The stored row
   carries the full rendered body (new settings `wa_event_body` /
   `wa_followup_body` with `{1}{2}{3}` placeholders, mirrored from WhatsApp
   Manager) and `raw_meta.kind="template"`; a send with an empty or
   unresolved parameter is refused before Meta is called. The inbox renders
   it as a message with a small "template" tag.
E. **Re-engage.** Skip when a `check_availability` note is open in the last
   24 h; skip threads whose language is not en/sw/fr instead of writing
   English; use the name the thread uses; obey the ledger.
F. **Live turn.** When a second burst arrives while a turn is composing and
   the running turn's reply goes out after that message arrived, the follow-on
   turn is told so and may answer with nothing; a live reply that repeats the
   previous outbound (the actions' containment check) is held.
G. **Prompt.** "One check-in per conversation; if one is booked, do not book
   again." "While the team confirms an item, continue with other items but
   never ask to start the order for the item under confirmation." "One
   greeting per day." The schedule_check_in tool description says the same.
H. **Monitoring.** `neema.outreach` log line per decision; redis decision log
   per customer; `python -m app.jobs.outreach_trace <number>` (last 7 days of
   outbound rows with source, plus pending actions and holds); a standup line
   "N automated follow-ups sent yesterday, M suppressed (reasons)";
   `/api/health` counts.
I. **Config** (all with the brief's defaults, all changeable without a
   deploy): `outreach_first_hours=48`, `outreach_next_hours=72`,
   `outreach_max_unanswered=2`, `outreach_daily_cap=1`,
   `outreach_needs_time_days=7`.

Decisions needed from the owner before implementing:
1. First follow-up timing on WhatsApp: 48 h means the first nudge can only go
   as an approved template (window closed). Until `WA_FOLLOWUP_TEMPLATE` is
   approved, that means no automated first follow-up on WhatsApp at all.
   Alternative: one in-window nudge at ~20 h (end of the customer's first
   day), then the template path at 72 h once approved.
2. Keep the 15:00 re-engage sweep at all? With A–E it would rarely fire
   (it needs 48 h quiet, which is outside the window). I recommend retiring
   it into the ledger-driven quote/promise follow-ups.
3. The replenishment template for deciding customers: stop entirely (D) —
   confirm.

## 5. Tests to add (brief §7)
Three rows due at once → one send; unanswered follow-up → next only after
72 h and never a third; "give me a week" → hold until then, live turn does
not re-ask; "comparing prices" (sw/en) → hold; reply seconds before a due
row → vetoed; open availability check → re-engage and quote nudge skip;
Swahili/Hindi/French/English language routing; a job retried after timeout
→ lock + idempotent; two workers → one send; quote updated after planning
→ newer replaces; template with unresolved/empty placeholder → refused and
never sent.
