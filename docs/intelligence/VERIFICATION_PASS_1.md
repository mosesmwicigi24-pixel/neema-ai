# Independent verification pass 1 — the intelligence branch against main

Date: 2026-11-06. Scope: `git diff origin/main...HEAD -- apps/api/app apps/web/src`
(commits 56141c6 … 6ced544), read in full, plus ADVANCEMENTS_REGISTER,
INVESTIGATION_REPORT and BENCHMARK_RESULTS. Read-only: nothing in the code
was changed. Every "reproduced" line below was run with the scratchpad venv
from `apps/api` (dummy `DATABASE_URL`/`SECRET_KEY`; no database, no model).

Tags: **[C]** confirmed at file:line or by a reproduced output · **[H]**
hypothesis consistent with the code, not reproduced. Severity: **S1** customer
harm, consent, money or a wrong headline number · **S2** wrong behaviour likely
in ordinary traffic · **S3** cost, quality, maintainability.

The one-paragraph verdict: the code changes are mostly sound in direction, but
three of them widen regexes far past the measured problem and now misfire on
ordinary buying messages (a 7-day hold on "No rush, go ahead and make it"; a
held reply on "once your payment is confirmed we start production"; a held
reply on "no hurry, take your time"); the held-out floor number is not clean
(the tuning read held-out phrasings and the held-out half contains 16 of the
20 developer negatives); and the real-model runner scores an empty reply —
an exception, a held draft, a wrongful silence — as a pass on 875 of 1,220
turns. None of this is deployed; all of it is fixable before it is.

---

## 1. Missed execution paths

| # | Finding | Tag / Sev | Evidence | What I would change |
|---|---|---|---|---|
| 1.1 | **The takeover re-check is still absent on the synchronous channels.** W1-5 made `_still_ai` fail closed, but `_still_ai` is only called from `_run_and_send` and `_run_and_send_meta`. Web chat and the ManyChat relay compose with `run_turn` and return the reply in the HTTP response with no re-check at all; INVESTIGATION 1.5 named this ("re-check on sync channels") and the register's W1-5 entry does not mention it. The Meta Page-Inbox `is_echo` → human-turn change (same row) is also not in the diff. | [C] S2 | `routers/web_chat.py:237`, `routers/manychat.py:172`; `runtime.py` callers of `_still_ai` at 2699 and 3028 only | Re-read `conv.intercept_mode` after `run_turn` in both routers before returning the reply; record the `is_echo` gap as a separate open row. |
| 1.2 | **`paid_ack` and `language` do not run on the comment→DM leg.** Both rules are gated on `mode == "dm"` (`review.py:1219`, `1225`). The private reply sent after a public comment reuses the comment-mode answer: `dm_text = _dm_text(plain_public_voice(answer), …)` then `send_private_reply(...)` (`runtime.py:5997–6005`). So a payment acknowledgement or a wrong-language reply composed under a post reaches the DM unchecked. The register calls W1-9 "a hard gate rule" without this qualification. | [C] S2 | `review.py:1219–1231`; `runtime.py:5997, 6005` | Run `paid_ack` in both modes (a public "thank you for your payment" is worse, not better); run `language_mismatch` on the DM leg against the commenter's text. |
| 1.3 | **Neither new gate rule runs on Neema-initiated messages.** `_gate_applies` returns False for any text starting `(`/`[` with "internal" / "not a customer message" (`runtime.py:1160–1170`), and `_compose_announcement` runs `read_only=True` (`hub_events.py:179–190`), which skips the gate entirely (`runtime.py:2270`). Cart recovery, follow-ups (`actions.py:450`), the sweeper bridge and announcements therefore never meet `paid_ack` or `pressure`. Pre-existing design, but "hard gate rule" in the register should read "on inbound replies only". | [C] S3 | as cited | Register wording; optionally run the rules-only pass (no reviewer) on read-only compositions, since they are deterministic and free. |
| 1.4 | **The Meta opt-out door, like WhatsApp's, is `media is None` only.** "Stop messaging me" with a photo attached (or a Messenger image + caption) skips the door and reaches the model. | [C] S3 | `runtime.py:3102` (`if media is None and _intent.is_opt_out(text)`) | Check `is_opt_out(text)` regardless of media; only the closer gate needs the media guard. |
| 1.5 | **Fail-closed takeover = silent wait + a full re-composition.** On `_still_ai() is None` the WhatsApp sender returns False with no hold line and no flag; the missed-reply sweep (`_SWEPT` includes whatsapp, `reply_sweeper.py:35`) later re-runs the whole turn — a second model call and a second pass through tools that already acted in the first composition (`create_order`, `send_product_cards`; W1-6 accepted that they act before the gate). The None case fires exactly when the database is flaky, which is also when the redis idempotency key is the only guard on a double order. | [C] S2 | `runtime.py:2699–2701`, `3028–3030`; `reply_sweeper.py:327–480` | Persist the composed reply (or at least `facts["tools"]`) before the re-check so the retry can send rather than re-compose; or re-check once more after a short sleep before giving up. Put the trade-off in the register. |
| 1.6 | **Meta 502 redelivers comments too, and comment dedupe is best-effort.** `_capture_comment_events` runs after `_capture_events`; a 502 from the latter makes Meta redeliver the whole payload; the comment path dedupes on redis only ("best-effort", `meta_webhook.py:751`). With redis down a public comment can be answered twice. | [C] S3 | `meta_webhook.py:113–127`, `751` | Dedupe comments on the DB (comment id on the row) as messages are deduped on `waba_msg_id`. |
| 1.7 | **The fail-closed gate's own flag is best-effort.** `_gate_failed_closed` wraps `_flag_held_reply` in try/except and still returns the hold line ("one of our team will come back to you") when flagging fails. The most likely cause of a gate exception is the database (every rule is pure; the reviewer model call is already caught at `review.py:1480–1482`), so the hold line goes out precisely when nobody can be told. | [C] S2 | `runtime.py:1216–1241` | When the flag fails, prefer silence + a redis note the sweeper reads over a promise nobody owns; or at least `escalate_to_human` via redis. |
| 1.8 | **`_PROMO_TOOLS` names two tools that do not exist.** Only `apply_offer` is registered; `check_offer`/`current_offer` are not in `_HANDLERS`. Harmless today but the exemption list reads as broader than it is. | [C] S3 | `tools.py:3292–3294`; `review.py:836` | Trim to `{"apply_offer"}` or derive from `_HANDLERS`. |

## 2. Untested assumptions — what rests on `inspect.getsource`

Behaviour tests exist for: `_gate_failed_closed` in isolation (with `db=None`), `_still_ai` (both branches), `schedule_meta_reply`'s door (fakes), `paid_ack_without_source`, `manufactured_pressure`, `language_mismatch`, `_merge_next_action`, `_cap_standing_orders`, `_buying_message`, the floor regexes (118 cases), the harness.

Resting **only** on a source-string assertion (`inspect.getsource(...) in src`):

| Register row | Status claimed | Test | Note |
|---|---|---|---|
| W1-1 call site | IMPLEMENTED | `test_the_gate_call_site_no_longer_falls_through_to_the_send` | no test runs `run_turn` with a raising gate |
| W1-5 both senders | IMPLEMENTED | `test_both_senders_treat_an_unverifiable_takeover_as_not_sent` | string only |
| W1-2 web/ManyChat door | IMPLEMENTED | `test_web_chat_and_the_tiktok_relay_record_an_opt_out_before_the_model` | string only; neither router is exercised |
| W1-2 sweeper bridge | IMPLEMENTED | `test_the_sweepers_cross_channel_bridge_honours_the_opt_out` | string only |
| W1-7 promised offer | IMPLEMENTED | `test_the_order_tool_surfaces_an_unread_promised_offer` | string only |
| W1-13 Meta 502 | IMPLEMENTED | `test_the_meta_door_answers_502_when_capture_fails` | string only |
| W7-4 empty reply = silence | IMPLEMENTED | `test_the_turn_honours_an_empty_reply_on_an_overlap_or_a_closer` | string only |
| **W2-3** hold lifts | **VERIFIED COMPLETE** | `test_a_question_or_a_buying_signal_lifts_a_hold` | `_buying_message` tested; its wiring into `apply` is a string check — no test calls `apply` with a held deal |
| **W2-4** scribe keeps team check | **VERIFIED COMPLETE** | `test_the_scribe_keeps_a_team_check…` | `_merge_next_action` tested; `scribe_update` calling it is not |
| W9-2 handoff rings | IMPLEMENTED | `test_the_handoff_tool_rings_the_team` | string only |
| W5-2 photo row | IMPLEMENTED | `test_a_caption_less_photo_is_a_turn_in_history` | string only |
| **W3-1** complaint length | **VERIFIED COMPLETE** | `test_a_complaint_read_by_the_floor_earns_the_care_first_length` | string only — "target computed" is not shown by any test |
| **W7-6** row lock | **VERIFIED COMPLETE** | `test_state_writes_take_the_row_lock` | string only; the `except: pass` around the lock means an unlocked write is also "complete" |
| **W10-3** served model | **VERIFIED COMPLETE** | `test_usage_logs_the_model_that_actually_served` | string only |
| **W9-1** `customer_told` | **VERIFIED COMPLETE** | none in the diff | no test at all |

[C] S2 for the five rows marked VERIFIED COMPLETE: the register's own vocabulary says verified means a behaviour test. I would downgrade them to IMPLEMENTED BUT NOT VERIFIED or add the tests (each is a 10-line async test with a fake session).

## 3. Shadow-only or advisory protections presented as effective

| # | Finding | Tag / Sev |
|---|---|---|
| 3.1 | **`language` is soft**: a soft finding earns one rewrite and then the best hard-clean draft goes out "with notes" (`_gate_turn_reply`, `runtime.py:1451–1463`). It can never hold. "VERIFIED COMPLETE at rule level" is true; the live effect is "one rewrite attempt". Register should say so. | [C] S3 |
| 3.2 | **W1-7 is a note, not a guard.** The unread promise becomes an order-note string, a `next_step` sentence to the model and a log line (`tools.py:1458–1470, 1597–1601`). No gate rule reads `offer_unverified`; if the model states the total as final anyway, nothing stops it, and no team note is filed (unlike the international-order branch just below it). | [C] S2 — add a `_team_note` in the same branch and a `figure`-rule allow-list entry that forbids a "total" when `offer_unverified` is in this turn's results |
| 3.3 | **W9-1 `customer_told`** is returned and read by nothing yet (the register admits it). | [C] S3 |
| 3.4 | **The fail-closed gate has no breaker.** Any bug in the new rule code (`rule_findings` is called unguarded inside `review_reply`) now holds every reply on every channel and moves every thread to human, where before it sent the draft. The right direction, but a fleet-wide incident with no circuit breaker and no alert beyond a per-turn warning line. | [H] S2 — count `held/gate_error` per hour in `agent_health` and page on it |

## 4. Unintended bypasses and regressions from the diff (reproduced)

All of 4.1–4.4 were run with `floor()` / `is_opt_out()` / `is_closer()` /
`guess_language()` on the branch; the "main" column in 4.5 used
`origin/main`'s `customer_state.py` loaded side by side.

### 4.1 The floor now reads buying messages as holds and claims [C] S1/S2

A `needs_time`/`consulting`/`comparing` reading with no named date puts the
deal on a **7-day hold** (`apply` → `_default_until`, `customer_hold_days=7`,
`customer_state.py:362–365, 417–424`) with `deal.blocking = "Asked for time —
until …"`; a `paid_claim` opens a deal as "holding" (`deals.py:239`) and sets
`blocking = "Says they have paid — awaiting the hub's confirmation"`. W2-3
lifts a hold on the next question or buying signal, which softens but does
not remove the damage (the dispatcher has already skipped that window).

| Customer sentence | floor → | matched | Should be |
|---|---|---|---|
| `No rush, go ahead and make it` | needs_time | "No rush" | ready |
| `No rush on the delivery, I will take 2` | needs_time | "No rush" | ready |
| `Hold on, I am sending the photo now` | needs_time | "Hold on" | none |
| `Ngoja nitume picha` / `Subiri kidogo` | needs_time | "Ngoja" / "Subiri" | none (chat fillers) |
| `Let me check the colour options you have` | needs_time | "Let me check …" | none |
| `Let me confirm the address: it is Thika` | needs_time | "Let me confirm …" | none |
| `Call me on 0722123456` / `Reach me at 0712345678` | needs_time | "Call me on" / "Reach me at" | none |
| `Text me the details on WhatsApp` | needs_time | "Text me the details on" | none |
| `Message me in English please` | needs_time | "Message me in" | none |
| `Not today, tomorrow please` (a delivery date) | needs_time | "Not today" | none |
| `The budget is not approved yet` | **ready** | "approved" | needs_time |
| `The bishop has not approved it` | **ready** | "approved" | consulting |
| `Send me the invoice once the bishop approves` | ready | "Send me the invoice" | consulting |
| `Continue with the gold trim` | ready | "Continue" | none |
| `Sent you the measurements` | **paid_claim** | "Sent" | none |
| `Here is the screenshot of the cassock I want` | **paid_claim** | "Here is the screenshot" | none |
| `See the screenshot of the design I like` | paid_claim | "See the screenshot" | none |
| `Nimetuma picha ya kasoki` / `Nimetuma vipimo` | **paid_claim** | "Nimetuma" | none (sent a photo / measurements) |
| `Tell them the price is fine` | consulting | "Tell them" | ready |
| `Please tell him I will collect on Monday` | consulting | "tell him" | none |
| `Take it to the church office` | consulting | "Take it to the church" | none (a delivery instruction) |
| `Waiting for the church van to collect` | consulting | "Waiting for the church" | none |
| `What do I tell the bishop about delivery?` | consulting | "tell the bishop" | a question (consulting is never softened by "?") |
| `Still waiting for the bishop's approval` | complaint | "Still waiting" | consulting |
| `I have been waiting to buy this for years!` | complaint | "been waiting" | ready-ish |
| `The box has 50 wafers, I need 2 boxes` | complaint | "The box has 50" | none |
| `This is the third time I am ordering from you, love it` | complaint | "third time" | none |
| `I ordered last year and you delivered on time, I want the same` | complaint | "I ordered last year and you" | none |
| `Have you not received my payment?` | complaint | "not received" | paid_claim |

Root causes, each [C]: `_NEEDS_TIME_RE` gained bare `hold on`, `ngoja`,
`subiri`, `no rush`, `not today`, `let me (check|confirm|…)\b[^.?!]{0,40}` and
`(call|text|message|reach) (me|us)… (on|in|at|by|…)` with no time hint
required (`customer_state.py:46–61`); `_READY_RE` gained bare `approved` and
`continue` (`:106–113`); `_PAID_RE` gained `^sent\b`, `nimetuma`,
`(here is|see|attached) … screenshot` and `sent (via|by|through) \w+`
(`:80–91`); `_CONSULT_BODY` gained `him|her|them|church|team|family|members`
and the trigger list gained `tell|inform|take (it|this) to|wait(ing)? for`
(`:68–75, 76–86`); `_COMPLAINT_STRONG_RE` gained `still waiting`, `been
waiting`, `third time`, `the box has \d+`, `i ordered \w+ … and you`
(`:120–134`). The "strong complaint outranks everything" precedence then
hides the payment claim in "Have you not received my payment?".

What I would change: require a time hint for the imperative `contact me…`
forms (as `_CUSTOMER_PROMISE_RE` already does); drop bare `hold on`, `ngoja`,
`subiri`, `no rush`, `not today`, `continue`, `approved` (keep `approved` only
anchored: `^approved\b`); restrict `_PAID_RE`'s bare `sent`/`nimetuma` to a
whole-message match (`^(ok|done|yes)?\s*(paid|sent|nimetuma)[.!]?$`) and
require a money word after `sent via/by`; drop `him|her|them|church|team|
family|members` from `_CONSULT_BODY` unless the trigger is `ask|consult|check
with|confirm with`; let `?` soften `consulting` as it does the others; make
`not received my payment` a paid-claim marker that beats the complaint rule.

### 4.2 The new hard gate rules hold correct replies [C] S1

`paid_ack` and `pressure` are **hard**: two hard-flagged drafts → `held` →
the hold line and the thread moved to human (`runtime.py:1466–1486`).

| Draft reply | `paid_ack_without_source` | `manufactured_pressure` |
|---|---|---|
| `We have not received your payment yet — could you share the M-Pesa code?` | **True** | — |
| `Once your payment is confirmed, we start production.` | **True** | — |
| `Your order ships as soon as the payment has been received.` | **True** | — |
| `We received your M-Pesa? Not yet — the team checks and confirms here.` | **True** | — |
| `No hurry, take your time.` | — | **"hurry"** |
| `Please do not hurry, the offer is open all month.` | — | **"hurry"** |
| `The last one we sent you was purple, same again?` | — | **"last one"** |
| `In the last few days we restocked the gold cope.` | — | **"last few"** |
| `The last unit of the previous batch was sold; a new batch arrives Monday.` | — | **"last unit"** |
| `Only 2 left in stock in size 46` with a `search_catalog` row carrying `stock: 2` | — | **"Only 2 left"** (only `apply_offer` exempts) |

The first four are the canonical correct answers to "how do I pay" / "have
you got it", and the register's own W1-9 example ("the team will match it to
your order") is a different sentence from the one the model will usually
write. `_PAID_ACK_RE` has no negation guard (`review.py:789–794`), unlike the
floor's `_PAID_NEG_RE`. `_PRESSURE_RE` matches bare `hurry` and `last
(one|few|unit)s?` with no "left/remaining" requirement (`review.py:823–827`),
and runs in comment mode too (`review.py:1230`, reproduced: a comment reply
"The last few we had sold out…" → `['pressure']`).

What I would change: a negation/condition guard on `paid_ack` (`not|haven't|
once|as soon as|when|until|yet` within 6 words before the match, mirroring
`_PAID_NEG_RE`); in `_PRESSURE_RE` require `hurry` to be imperative
(`^hurry|hurry[,!]|hurry up`, never after `no|don't|not`) and `last X` to be
followed by `left|remaining|in stock|available`; and keep both rules **soft
for the first 48 hours of live traffic** with the verdict tally watched, since
the stress tests that narrowed `figure`/`language` did not cover these.

### 4.3 Opt-out false positives of the kind neg-009 fixed [C] S1

| Customer sentence | `is_opt_out` | Why |
|---|---|---|
| `Please stop messaging me about the cups, I want the trays` | **True** (recorded for a year) | the fix covered `stop sending <object>` but `stop messaging me` + context is unguarded (`intent.py:31`) |
| `Remove me from the group` | **True** | `remove (me|my number)` with no "list/messages" requirement |

Both silence a buying customer for 365 days (`OPT_OUT_TTL`). Add the same
object guard the `sending` branch got, and require `remove me` to be followed
by `from (your|the) (list|messages|contacts|number)`.

### 4.4 `_ACK_RE` silences a complaint dressed as thanks [C] S2

`thanks? for (the|your|that|this)? \w+` makes **any** "Thanks for X" a closer.
Reproduced: `Thanks for the delay` → closer, `Thanks for nothing` → closer
(floor → `closing`, not `complaint`). With the new prompt line "a bare thanks
gets NOTHING back", a sarcastic customer is answered with silence, and on the
second one the closer gate skips the model entirely. Whitelist the object
(`invoice|quote|help|reply|update|info|price|details|time|patience`) instead
of `\w+`.

### 4.5 The language guess flips Swahili speakers to English [C] S2

`guess_language` now returns `en` whenever any English word remains after one
Swahili token (`customer_state.py:252–281`). `apply` overwrites
`contact_preferences.language` on every reading (`:395–398`), and that
preference chooses the language of every automated message (reminders,
follow-ups, hold lines).

| Message | main | branch |
|---|---|---|
| `Sawa size 42` | sw | **en** |
| `Nitachukua 2, black` | sw | **en** |
| `Asante, delivery Thika` | sw | **en** |
| `Nyeupe size 46` | None | en |
| `Nataka size 44 black` | None | en |
| `Kesho, size 42` | None | en |

These are the most common shapes a Kenyan customer types after the first
exchange. Fix: a Swahili content word (`_SW_WORDS`/`_SW_EXTRA`/verb shape)
should win over English *product* words (`size|black|white|delivery|…`);
only English *function* words (`the|is|please|can|…`) should flip the guess.
`language_mismatch` on the same input returns None (reproduced), so the gate
will not catch the English reply that follows.

### 4.6 Empty-reply-as-silence [C]/[H] S2

- [C] `_overlap_noted` is set when `_answered_after` finds **any** outbound
  recorded after the inbound (`runtime.py:1681–1684`) — a human reply, a
  payment reminder, an opt-out ack, a hold line, a cross-channel bridge. The
  OVERLAP_NOTE then tells the model "if your previous reply already answers
  this, reply with NOTHING". When that outbound was unrelated, the note is
  false, and an empty reply now ends the turn with `_mark_silenced` (the
  sweeper leaves it; `runtime.py:2690–2696`) — no stall line, no flag, no
  retry. Before the change the customer at least got "One moment".
  [H] whether the model does this often is a real-model question (§5).
- [C] **Cost regression on closers.** With the prompt now asking for an empty
  reply on a bare closer, `_run_and_send` returns at `:2690–2696` **before**
  `mark_closer_answered` (`:2726`). The `closer:` key is never armed, so every
  later "ok"/"thanks"/"asante" in the thread runs a full model turn (≈24 K
  prompt tokens) instead of being gated without a call. Arm the key in the
  empty-reply branch when `is_closer(text)`.

## 5. Correct in unit tests, at risk with the real model — what `agent_eval --cases` must check

| # | Risk | What the run must show |
|---|---|---|
| 5.1 | `_PAID_ACK_RE` covers "thank you for your payment / payment received / received your M-Pesa" but not the model's other registers ("I can see your payment", "payment noted", "we've got your M-Pesa, asante"). Those pass the gate; the legitimate conditional forms are held (4.2). | On every `confirm_paid_check` turn (58): the reply neither thanks for nor conditions on a payment in *any* wording, and `review` is not `held`. Read the transcripts, not the verdicts. |
| 5.2 | **The runner's regexes differ from the gate's.** `eval_run._THANKS_PAID_RE` (`eval_run.py:146`) ≠ `review._PAID_ACK_RE`; `eval_run._PRESSURE_RE` (`:149`) ≠ `review._PRESSURE_RE` (no `last few/unit`, no `leo tu`, bare `offer ends`). A turn can fail in the runner on a phrase the gate passes, and pass in the runner on one the gate holds. | Import the gate's regexes in `check_turn` instead of re-declaring them; otherwise the "first-draft" and "pass" metrics measure two different rules. [C] S3 |
| 5.3 | W7-4 (overlap silence) cannot occur in the runner: turns are sequential, so `_answered_after` is never true. The closer branch is measured (153 `silence` turns), the overlap branch is not. | Add an explicit overlap case: insert an outbound row between the inbound insert and `run_turn`, with (a) a reply that answers it and (b) an unrelated one; expect silence only in (a). |
| 5.4 | The runner inherits the floor's false holds: `after_hold` is set from `floor()` (`eval_run.py:447–449`), so after "Hold on, I'm sending the photo" the next turn fails "re-asked for a date" if Neema asks a legitimate "when would you like it?". | Set `after_hold` from the gold `expect.said`, not the floor. |
| 5.5 | The run uses WhatsApp contacts only: the Meta door (W1-2), TikTok/web doors, the Meta 502 (W1-13), the takeover re-check (W1-5) and the promised-offer path (W1-7) are never exercised. | Say so in BENCHMARK_RESULTS; add a fault-injection scenario to `agent_eval` (monkeypatch `review.rule_findings` to raise; `promotions.granted_promise` to raise) and assert the held outcome and the order note. |
| 5.6 | Language: `language_ok("sw", reply)` is `looks_swahili(reply)`, a short word list; a correct Swahili reply with none of the listed words scores False. | Report `language_continuity` with the misses attached for a human to read before quoting the number. |
| 5.7 | `escalate` passes on `intercept_mode == "human"`; the runner never resets the mode within a case, so once a case escalates every later `escalate` turn passes for free. | Reset or record the mode per turn. [C] S3 |

## 6. The measurement itself

| # | Finding | Tag / Sev |
|---|---|---|
| 6.1 | **The held-out half was read during tuning.** `tests/test_intelligence_floors.py` says "every phrasing here came from the independent case set's misses on the development half". Reproduced: 34 of its literals occur **only** in held-out texts, e.g. "Paid by card" (ctx-064, ctx-086, ctx-092, sales-082 — all HELD), "Done, paid" (ctx-098, safe-006, sales-076 — HELD), "Ok go for it" (ctx-086), "Thanks for the invoice" (ctx-064), "I told you on Facebook to stop messaging me…" (safe-057), "The lady at your shop was very rude to my wife" (ctx-025), "cheers" (ctx-080, sales-090), "Wrong number… Stop." (safe-061). BENCHMARK_RESULTS lists "Paid by card", "Done, paid", "cheers" under "What the misses are (dev half, inspected)" — they exist only in held-out. The split was fixed before tuning (commit order ecddee6 → 4365d3f confirms), but the regexes were written against held-out phrasings. The 0.787 is therefore a *training-set* number for those states, and the "intervals do not overlap" claim is not evidence of generalisation. | [C] S1 — report the held-out number as contaminated; re-split (new seed) and re-run with the current regexes, or commission a fresh independent batch as the only held-out set |
| 6.2 | **The developer negatives and audit cases are inside the halves.** `eval_cases.load()` loads every `*.jsonl`, and `split` hashes all 430 ids: held-out = 203 independent + **16 developer** + 8 audit (reproduced). Developer cases are written to pass; the floors scorer also reports them in the headline. | [C] S2 — score the headline on `independent_*.jsonl` only; keep developer and audit as separate rows |
| 6.3 | **Per-state accuracy is not reported.** Held-out after (reproduced): closing 59/67, None 34/36, paid_claim 25/29, stop 13/14, ready 24/33, needs_time 24/35, comparing 5/6, **consulting 8/17, complaint 8/17**. 103 of the 200 hits are closers and nulls. Macro-average over states ≈ 0.70, not 0.79. | [C] S2 — report per-state (macro) in BENCHMARK_RESULTS |
| 6.4 | **Wilson** (`eval_floors.wilson`) is the standard centre ± half-width form; 137/254 → [0.478, 0.600] matches the report; 0/5 → [0, 0.434]; 28/29 → [0.828, 0.994]. No library was available to cross-check, but the formula is correct. | [C] ok |
| 6.5 | **A run can score a pass without the behaviour.** `check_turn` has no positive assertion for `answer`, `hold_ack`, `care_first`, `ask_one` or `confirm_paid_check`; `require` is skipped when the reply is empty (`eval_run.py:200`: `if r.strip() and not re.search(...)`). Reproduced on the case set: **875 of 1,220 turns pass on an empty reply**; 101 `answer` turns carry no assertion at all. A `run_turn` exception (`reply = ""`, `facts["error"]`, `:424–426`), a held draft (the hold line) and a wrongful silence are all passes; `summarise` never excludes `error` turns. With the model down the run would report ≈0.72. | [C] S1 — fail any non-`silence` turn whose reply is empty or whose `review == "held"` or which carries `error`; require at least one of `require`/`forbid`/`tool`/`figures` on `answer` turns at load time |
| 6.6 | `quote` passes on **any** money figure (`j["figures"]` non-empty), e.g. "delivery is KES 350" with no product price. | [C] S3 — require a figure that matches a hub row in this turn |
| 6.7 | Label vocabulary: `NEXT_ACTIONS` matches what `check_turn` branches on; `STATES` matches the floor; `LENGTH_KINDS` is the raters' vocabulary and the code's disagree (0.55) as the report says. `_LANG_MAP` drops sheng/mixed from the language metric — the hardest third of the language slice is not scored. | [C] S3 — say so beside the 0.913 |
| 6.8 | The "independent" cases were authored by sibling model instances in the same session, briefed on the label vocabulary. The dev→held-out gap (0.953→0.787) measures regex fit to one author's phrasing, not generalisation to customers. The register and BENCHMARK say "realistic by construction, not by sampling"; the headline should carry that caveat in the same sentence as the number. | [H] S2 |

## 7. Scope creep and architecture

| # | Finding | Tag / Sev |
|---|---|---|
| 7.1 | The performance view (`services/performance.py` 332 lines, seven raw SQL windows; `PerformanceView.tsx` 381 lines; a new admin route) ships in the same branch as the consent and payment safeguards and needs Postgres to test. It is §7 of the directive, so in scope — but it should be its own PR so the safety changes can be reviewed and reverted alone. | [C] S3 |
| 7.2 | Three new regex layers (`_READY_STRONG_RE`, `_COMPLAINT_STRONG_RE`, `_PAID_NEG_RE`) plus a precedence rule were added to fix bare "Paid"/"Sent"/"Done, paid" and the imperative time requests. The measured misses needed anchored whole-message forms and a time-hinted imperative; the wildcard forms (`sent (via|by) \w+`, `here is … screenshot`, `let me check … {0,40}`, bare `hurry`) are what produce §4. Smaller change, same measured gain. | [C] S2 |
| 7.3 | `guess_language` grew six word lists (~230 words) and a six-way decision tree; the measured gap (2.5) was "short English imperatives → None". The ASCII-default alone would have closed most of it without the mixed-message regression in 4.5. | [C] S3 |
| 7.4 | `eval_run.TOOL_ALIASES`, `_Sandbox`, the rater packet and `append_history` are reasonable; `_cap_standing_orders`, `_served`, `_merge_next_action`, the photo row and `customer_told` are each the smallest change. No objection. | — |

## Recommended order of repair

1. §6.5 (the runner passes empty replies) and §6.1/6.2 (contaminated held-out) — before any number is quoted again.
2. §4.2 (hold on "once payment is confirmed", "no hurry", "last few") and §4.3 (opt-out on "stop messaging me about the cups") — before deployment; make `paid_ack`/`pressure` soft for the first days.
3. §4.1 (7-day holds on "No rush, go ahead", "Hold on", "Ngoja") and §4.5 (Swahili → English flip).
4. §1.1, §1.2, §1.7, §4.6 (closer-key arming).
5. Register: downgrade the five VERIFIED COMPLETE rows that rest on `inspect.getsource` (§2) and add the "inbound replies only" / "DM mode only" / "one rewrite, never a hold" qualifications (§1.3, §1.2, §3.1).
