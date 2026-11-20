# D. Enforcement coverage

## Rules by domain and status

| Domain | Rules | Hard | Soft | Partial | Observed | Instruction only | Conflicting | Not implemented | Not verified |
|---|---|---|---|---|---|---|---|---|---|
| sales | 147 | 3 | 12 | 16 | 1 | 103 | 10 | 1 | 1 |
| financial | 140 | 23 | 7 | 63 | 0 | 35 | 9 | 1 | 2 |
| naturalness | 105 | 2 | 5 | 22 | 18 | 55 | 3 | 0 | 0 |
| product | 88 | 8 | 5 | 35 | 0 | 33 | 7 | 0 | 0 |
| action_integrity | 82 | 16 | 6 | 34 | 0 | 21 | 3 | 2 | 0 |
| tone | 66 | 1 | 2 | 12 | 2 | 42 | 7 | 0 | 0 |
| boundaries | 66 | 5 | 4 | 25 | 0 | 31 | 1 | 0 | 0 |
| memory | 35 | 0 | 4 | 3 | 0 | 26 | 1 | 0 | 1 |
| channel | 33 | 2 | 0 | 16 | 0 | 14 | 0 | 0 | 1 |
| continuity | 28 | 0 | 5 | 9 | 0 | 10 | 3 | 0 | 1 |
| fulfilment | 26 | 2 | 2 | 3 | 0 | 17 | 1 | 1 | 0 |
| temporal | 14 | 0 | 4 | 3 | 0 | 6 | 0 | 0 | 1 |

# Outbound routes and their safeguards


Scope: `/home/user/neema-ai/apps/api/app`. Established by reading the code paths; nothing was executed
(the environment has no Python dependencies installed, so pure predicates such as `is_closer` /
`initiated_issues` were read, not run). Paths are relative to `apps/api/app/`.

## 0. Low-level senders (what everything below ends in)

| Sender | File:line | Notes |
|---|---|---|
| `_send_waba` (WA free-form text) | services/messaging.py:273 | via `_post_graph` (262) → raises `SendOutcomeUnknown` on read/write timeout. No gate, no opt-out, no window check, no dedupe of its own. |
| `send_wa_template` | services/messaging.py:350 | via `_post_graph`. No parameter validation of its own (that lives in `services/templates.py:94 validate_params`, used only by `templates.send`). |
| `_send_waba_product_card` | services/messaging.py:293 | own `httpx` client, NOT `_post_graph` → no `SendOutcomeUnknown`; falls back to image+caption / plain text. |
| `_send_waba_image` / `_send_waba_audio` | services/messaging.py:194 / 221 | own `httpx` client. `_send_waba_audio` has NO caller (TTS replies are not implemented; wa_native.py:19 says "DEFERRED"). |
| `_send_waba_media` (staff media) | services/conversation.py:965 | own `httpx` client. |
| `send_meta_message` / `send_meta_media` / `send_meta_carousel` | services/meta_send.py:63 / 98 / 129 | via `_graph_post` (35) → `SendOutcomeUnknown`. `human_agent=True` only from staff paths. |
| `reply_to_comment` | services/meta_send.py:220 | the only sender with a built-in content guard: `sanitize_public_comment` (192) strips URLs, e-mails and the "are you in Kenya?" hedge. HARD, at the send boundary. |
| `send_private_reply` (comment → DM) | services/meta_send.py:267 | no guard of its own. |
| `send_to_channel` | services/meta_send.py:613 | dispatcher: strips markdown off-WhatsApp, routes TikTok native / Meta / WA. No gate, opt-out or window logic. |
| `tiktok_native.send_text` / `send_to_user` | services/tiktok_native.py:187 / 220 | own `httpx` client → no `SendOutcomeUnknown`. Reached only through `send_to_channel`. |
| `templates.send` | services/templates.py:128 | purpose→template registry + `validate_params` (HARD: empty / placeholder residue / fake order number refused). |
| `save_outbound_message` / `save_outbound_channel_message` | services/messaging.py:1048 / 1084 | persistence only. Always `sender=ai`. Called AFTER the send by every path; no check of any kind. |
| HTTP-response replies | routers/web_chat.py:283, routers/manychat.py:228 | reply travels in the HTTP response; no Graph call. |
| `mailer.send` | services/mailer.py:63 | only caller is `services/password_reset.py:107` (staff). Never mails a customer. |
| SMS | routers/sms.py | receive-only; `send_agent_reply` refuses the channel (services/conversation.py:629). |
| `routers/public.py` | — | no outbound message; `/order/measure` stores an inbound and sets human mode (229). |

## 1. Where the safeguards live

- **Reply gate** — `runtime._gate_turn_reply` (agent/runtime.py:1490) → `review.review_reply` (rules + model reviewer). Called at agent/runtime.py:2701-2714, only when `reply and not read_only and not scribe_only and _gate_applies(user_text)`. Fail-closed on error (`_gate_failed_closed`, 2716-2726).
  - Consequence 1: **every `read_only=True` turn is ungated** (all Neema-initiated composition and every staff draft).
  - Consequence 2: `_gate_applies` (1218) also switches the gate off for any text starting `(`/`[` containing "internal / not a customer message / system".
- **Initiated-message rules** — `review.initiated_issues` (agent/review.py:974-995): hard = `paid_ack`, `status`; soft (logged, still sent) = `pressure`, `internal`. **No figure, item, link, colour, domain or language rule.** Called in exactly two places: `actions._send` (services/actions.py:525-528) and `hub_events._celebrate` (services/hub_events.py:286-293).
- **Opt-out** — `intent.is_opt_out` (inbound door) and `intent.opted_out(..., fail_closed=True)` / `opt_out_state` (services/intent.py:230, 273).
- **Unknown send outcome** — `SendOutcomeUnknown` (services/messaging.py:246) raised only by `_post_graph` and `meta_send._graph_post`.
- **Human mode** — `runtime._still_ai` (3113, re-read right before the send, fail-closed) plus the webhook pre-checks.
- **Outreach control** — `OUTREACH_MODE` default `shadow` (core/config.py:214); read only by `actions.process_due` (services/actions.py:924).

## 2. Paths × safeguards

Legend: Y = enforced in code, N = absent, n/a = does not apply, "ro" = `run_turn(read_only=True)`.

### A. Replies to something the customer just said

| # | Path / entry / trigger | Text | Reply gate | Opt-out | Dedupe / unknown outcome | Rate limit / cap | 24h window | Human mode | Language | OUTREACH_MODE | Gap vs. the live turn |
|---|---|---|---|---|---|---|---|---|---|---|---|
| A1 | **Live WhatsApp turn** — services/wa_native.py:420 `_reply_after_debounce` → runtime.py:3314 `schedule_reply` → 3138 `_run_and_send` → 3182 `_send_waba` | model | Y (2701) | inbound door Y (3323) | `agent:seen` nx (3332); in-flight lock (3144); `_is_echo` (3170); `SendOutcomeUnknown` recorded, never resent (3183-3194) | pause key (2893), closer gate (3329), pacing slow lane (3341) | n/a (reply) | Y: wa_native.py:458 + `_still_ai` (3175) | Y, gate rule `language` hard, DM mode only (review.py:1473) | n/a | **baseline** |
| A2 | **Live Messenger / Instagram / TikTok-native turn** — routers/meta_webhook.py:497, routers/tiktok_webhook.py:167 → runtime.py:3614 `schedule_meta_reply` → 3505 `_run_and_send_meta` → 3560 `send_to_channel` | model | Y | Y (3626) | `agent:seen:meta` (3634); burst buffer; in-flight; echo; unknown recorded (3561-3572) | as A1 | Y: window error → held draft + human (3591-3602) | Y: meta_webhook.py:451, tiktok_webhook.py:165, `_still_ai` (3553) | Y | n/a | none |
| A3 | **Cassock-ladder second message** — runtime.py:2772-2786 builds it AFTER the gate; sent at 3195-3200 / 3573-3577 | canned, prices from hub catalogue rows (`cassock_ladder.message`) | **N** (appended after the gate) | n/a | once a month per contact (services/cassock_ladder.py:122); **no `SendOutcomeUnknown` handling** | monthly | n/a | covered by the first send's check | sw/en only | n/a | an exception on this second send falls to the turn's `except` (3211 / 3590) → `record_turn_failure` and **the welcome hold line is sent after a successful reply** |
| A4 | **Photo-refer safe line** — runtime.py:2762-2771 swaps the gated reply for `photo_check.SAFE_LINE` | canned | N (post-gate swap; no figures) | n/a | as A1 | — | — | sets human mode | sw/en only | n/a | none material |
| A5 | **Gate hold line** — `_hold_dm_for` (runtime.py:1642) / `_REVIEW_HOLD_DM` (1213) returned by the gate | canned | is the gate's own output | n/a | `held_recently` → one per few hours (1628) | Y | — | thread moved to human (`_flag_held_reply`) | en/sw/fr/pt/hi | n/a | none |
| A6 | **No-model hold line** — runtime.py:2960 `_send_hold_line`, from the `except` of A1/A2 (3223, 3609) | canned (`_hold_line`, 2914: phone numbers from config, no price) | N (canned) | **N** | `agent:holdline` nx 2h (2981); marked `hold_line` so the sweeper retries; **no `SendOutcomeUnknown` handling** (swallowed by blanket `except`, 3025) | 1 per 2h | N (a Meta window error is routed elsewhere first) | **N — no `_still_ai` re-check** | **English only** | n/a | language; human-mode re-check |
| A7 | **Opt-out acknowledgement** — runtime.py:3228 `_handle_opt_out` | canned (intent.py:288) | N | this IS the door | acknowledged once (`already`, 3259); unknown outcome recorded (3266) | once | n/a | N | en/sw/fr/hi | n/a | **a second "stop" returns at 3259-3260 with no outbound row and no `_mark_silenced` → see A12** |
| A8 | **Person door acknowledgement** — runtime.py:3277 `_handle_person_request` → services/person_door.py:79 `route` | canned; `{when}` = next staffed start (commitments) | N | **N — not checked** (it is a reply) | none: every repeat re-acknowledges by design (person_door.py:16); unknown outcome recorded | N | n/a | sets human | en/sw/fr/pt | n/a | no per-message dedupe |
| A9 | **Web chat** — routers/web_chat.py:246 | model | Y (run_turn not read-only) | Y (224) | **no inbound dedupe, no in-flight lock, no echo guard** | none | n/a | Y at 207; re-check `_still_ai(...) is False` (250) → **`None` (unreadable) falls through and replies: fail-open**, live turn is fail-closed | gate | n/a | **no person door** (`wants_a_person` never called); no closer gate; fail-open takeover check |
| A10 | **ManyChat / TikTok relay** — routers/manychat.py:174 | model | Y | Y (153) | closer gate (169); no echo guard, no in-flight lock; reply budget timeout → `_BUDGET_LINE` | — | n/a | Y at 121; `_still_ai is False` (178) fail-open on `None` | gate | n/a | **no person door**; markdown not stripped (reply bypasses `send_to_channel`) |
| A11 | **Product cards / photos / album / measurement guide** — agent/tools.py:3009 `_send_product_cards` (3094, 3119, 3170, 3189, 3218), 3457 `_send_measurement_guide` | code-built: hub name + `_fmt_price(_to_display(p.price …))` + storefront URL | **N — sent inside the tool loop, BEFORE the gate** | n/a | none; no `SendOutcomeUnknown` (own httpx) | 6 cards, 5 album photos | n/a | **N — no `_still_ai` at tool time** | n/a | n/a | cards stay delivered when the gate then HOLDS the reply, when a colleague takes the chat mid-turn, when the echo guard suppresses the text, and when the turn later crashes (customer gets cards + the welcome hold line). Read-only turns cannot call it (runtime.py:2582-2592). |
| A12 | **Missed-reply sweeper** — main.py:400 → services/reply_sweeper.py:319 `sweep_missed_replies` → 483/485 `_run_and_send*` | model | Y (same turn) | **N — goes straight to `_run_and_send`, bypassing `schedule_reply`'s `is_opt_out` and `wants_a_person` doors** | lock 300s (417), in-flight (424), silenced (436), fresh re-check (449), 3 strikes then human (465) | 3 tries / message | 23h max age (333) | Y (387) + `_still_ai` | gate | n/a | **a repeat opt-out (A7) or an opt-out whose handler raised (3274) is left as "latest inbound, AI mode" → ~90 s later the sweeper runs a full model turn on "stop messaging me" and sends the reply.** `is_closer`/`silence_decision` (67-71) do not match opt-out wording (regex at runtime.py:630). By reading; not executed. |
| A13 | **Unclaimed human chat answer** — main.py:443 → services/unclaimed.py:149 `sweep_unclaimed` → 127 `answer_fact` → 106 `_send` ×2 | model sentence + canned `FOLLOW` | Y (run_turn NOT read-only, 135) | N (reply) | `unclaimed:{msg.id}` nx (166); **no echo guard, no in-flight lock, no `SendOutcomeUnknown` handling, rows unstamped** | once per message | 23h (70) | deliberately sends INTO a human-mode thread; **no re-check that a colleague was assigned or replied while it composed** | `FOLLOW` sw/en only | n/a | full tool kit is live in this turn (not read-only): only the `NOTE` prompt (39-47) stops `update_cart` / `create_order` on a thread a human holds — INSTRUCTION only. A gate "held" outcome returns the hold DM, which is then sent followed by `FOLLOW` (two promise lines). |
| A14 | **Money-hold holding line** — services/auto_release.py:316 `_maybe_holding_line` → 254 `_send_holding_line` | canned (`HOLDING_LINE`, 129) | N | N (reply to a waiting customer) | once per hold (DB count of `person_hold_line`, 334-339, plus the team-note guard 291) | once | Y, 23h (331) | deliberately in human mode | sw/en only | n/a | none material |
| A15 | **Public comment — model answer** — routers/meta_webhook.py:878 / tools/catchup.py:145 → runtime.py:6451 `_run_comment_engage` → 6687 `run_turn(public_comment=True)` → `_post_public` 6549 `reply_to_comment` | model, wrapped by `_comment_public_reply` (5224) | Y, mode "comment" (held → `_VERIFY_HOLD_POOL` + colleague, 6913-6920) | n/a (public) | comment id dedupe in the webhook (meta_webhook.py:801-806); one conversation per person per post (`_thread_prior`, 6475) | `_post_over_cap`, `_person_over_cap` (6677-6678) cap MODEL calls, not replies | n/a | **N — no `intercept_mode` / `_still_ai` check anywhere in `_run_comment_engage`** | gate's language rule is DM-only (review.py:1473) → **not checked on comments**; canned lines sw/en | n/a | a comment thread held by a colleague is still answered publicly; `_post_public` swallows every exception (6552) and **the row is saved whether or not the reply posted** (6947-6951, 6603-6607) — the inbox shows a reply the customer never got; an unknown outcome is not distinguished. Link/country-hedge strip is HARD (`sanitize_public_comment`). |
| A16 | **Public comment — canned lines** (thanks / welcome / which-item / empathy / campaign / free-path price) — runtime.py:6588-6612, 6893-6925 | canned; **price from the post's recorded hub identity** (`_public_price_text`, 6973) | N (no model text). Guarded in code instead: price only on a trusted identity and a bare price ask (6832-6853); `item_issues` (6838) | n/a | as A15 | — | n/a | N | sw/en | n/a | as A15 |
| A17 | **Comment → DM (private reply)** — runtime.py:6779 `send_private_reply` | gated model answer + code link (`_dm_text`, 5209) | Y for the answer (same turn); link is code-minted (`_storefront_product_link`) | Y, fail-closed (`_comment_dm_allowed`, 1428; 6777) | Meta allows one private reply per comment; **no `SendOutcomeUnknown` handling and the DM is never saved to the thread** | — | Meta-enforced | **N** | — | n/a | DM text is not persisted (only the public line is) → the inbox cannot show what the customer received privately |
| A18 | **Complaint private message** — runtime.py:4128 `_private_complaint_message` | canned | N | Y (6596) | one per comment | — | Meta | N | sw/en | n/a | not persisted either |

### B. Messages Neema initiates (nobody just wrote)

| # | Path / entry / trigger | Text | Reply gate | Opt-out | Dedupe / unknown outcome | Rate limit / cap | 24h window | Human mode | Language | OUTREACH_MODE | Gap vs. the live turn |
|---|---|---|---|---|---|---|---|---|---|---|---|
| B1 | **Dispatcher, model-composed** — services/actions.py:1086 `actions_loop` (60 s) → 666 `process_due` → 436 `_compose_follow_up` (ro) → 515 `_send`. Kinds `follow_up`, `customer_promise` (services/deals.py:264/272), `check_in` / `replenishment` (agent/tools.py:3388), `buying_follow_up` (jobs/cart_recovery.py:236), `fit_check` (services/hub_events.py:444) | **model** | **N — ro turn; only `initiated_issues` (actions.py:525): hard = paid_ack / status** | Y: `opt_out_state` (731); unknown → deferred, parked after 3 (732-767) | `claim` (593) conditional UPDATE; `_repeats_earlier` (1016); 3 tries then park (819-836); `SendOutcomeUnknown` → `needs_approval` (1046) — recorded in the thread on WhatsApp only (542-549), **not on Meta/TikTok (555 has no try)** | one message per customer per tick (712); `MAX_AUTO_NUDGES = 2` per deal (262); **daily cap of one routine message is shadow-only by default** | Y (`_within_window`, 838) | Y (`needs_approval`, 244) + 7-day flag rule (250-258) | park when the person's stored language is not en/sw/fr (908-917); the composed text's language is not verified | **Y — the only path it governs** (924) | a follow-up may state any price, item, discount, delivery date or link and no rule looks at it. The cart nudge's reason carries "total N" (cart_recovery.py:240) for the model to restate. |
| B2 | **Dispatcher, code-composed quote follow-up** — services/quote_followup.py:268 `on_turn` (planned by the scribe) → `process_due` | canned (`compose`, 152); **figures = prices found in that turn's own `search_catalog` results AND in the reply, captured at quote time** (`extract_quote`, 101) | N (canned) + `initiated_issues` | Y | exact-repeat check (1016); one pending per deal (`dedupe_key=buying:{deal}`); `stale_reason` (329) | as B1 | Y (planned inside it, withdrawn when shut) | Y (301, 338) | sw+en or en only; no check for fr/pt/hi customers beyond the stored-language park | Y | price is not re-read from the hub at send (≈4 h later, or next morning after quiet hours) — a hub price edit in between is restated at the old figure |
| B3 | **Dispatcher, code-composed payment reminder** — jobs/payment_followup.py:254 `_handle` → `process_due` | canned (`compose` 181 / `compose_many` 204); **amount = `OrderEvent.hub_total` else local `subtotal`** (`_amount`, 197); link = `customer_link(order)` | N + `initiated_issues` | Y at plan (281) and at send (731) | per-order redis guard (262); live hub re-check `live_verdict` (329; "unknown" defers) | daily 10:00 job | Y | Y at plan (173) and send | **English only**; parked only if stored language ∉ {en, sw, fr} — a Swahili or French customer gets the English text | Y (transactional → `decide` returns "go", actions.py:335) | the AMOUNT is not re-read at send time (only paid/unpaid is); falls back to the local subtotal when the hub total is missing |
| B4 | **Dispatcher, template outside 24h** — services/actions.py:390 `_send_followup_template` → `templates.send` | Meta template; params: first name, order number scraped from `action.reason` by regex (405) then validated (`order_number_param`), canned phrase | N; `validate_params` HARD | Y | `claim` (951); `TemplateRefused` → park; `SendOutcomeUnknown` → park (971) | as B1 | n/a (the template is the way in) | **N — bypassed.** `needs_approval` returns "outside the 24h messaging window" BEFORE it looks at human mode (238-245), and the template branch fires on exactly that string (948) | stored-language park applies (908-917: any non-routine row outside the window) | Y for routine-class rows | a thread held by a colleague, flagged in the last 7 days ("never sell into displeasure"), over the KES 50,000 sensitivity line or already nudged twice still gets the automatic template once the window has shut — every check after line 242 is skipped |
| B5 | **Hub event announcement, in window** — routers/hub_events.py:37 → services/hub_events.py:499 `handle_event` → 206 `_celebrate` → 172 `_compose_announcement` (ro) → 297/307 | **model**; brief carries order number, amount (`brief_for`, 93), tracking, receipt link | **N — ro; `initiated_issues(paid_known, status_known=True)` (287) → for a paid event NO hard rule remains** | Y, fail-closed (265) — but the `try/except: pass` around it (263-271) means an exception inside sends anyway | event id nx 7d (533); paid: one per order 24h (240); WhatsApp unknown outcome recorded (298-302); **Meta: not handled** | quiet hours → deferred to 08:00 (235) | Y (258) | **N — never read** (transactional by design; a human-held thread still gets the model's message) | **N** (prompt only) | **N** | the model restates the amount, order number and receipt link and nothing compares them with the event |
| B6 | **Hub event, WhatsApp template outside 24h** — services/hub_events.py:315-336 | template; params: first name, order number, canned status word + receipt link | N; `validate_params` | Y | as B5; **`SendOutcomeUnknown` not caught** (propagates to `handle_event`'s blanket except, 548) | — | n/a | N | template language | N | the "Receipt: <link>" is concatenated into a template body parameter (328) |
| B7 | **Fit check / escalate draft** — hub_events.py:432 `_plan_fit_check` → B1/B4; `_escalate` (449) writes an internal note only | — | — | — | — | — | — | — | — | — | `_escalate` sends nothing to the customer |
| B8 | **Cross-channel bridge** — main.py:404 → reply_sweeper.py:282 `escalate_window_closed` → 143 `_try_continue_elsewhere` → 122 `_compose_bridge` (ro) → `actions._send` (188) | **model** (told to "answer it or move it one step forward") | **N — ro; `initiated_issues` only** | Y, fail-closed (180) | note on the source thread de-queues it (193-201); `SendOutcomeUnknown` escapes to the caller's `except` (311) → escalated to a human, never resent | — | Y (`messaging_window` open on the destination, 175) | Y (sibling must be AI mode, 156) | **N** | **N** (calls `_send` directly, `action=None`) | answers a customer's QUESTION (often a price) with model text that met no figure/item rule; not counted by the daily cap (stamped routine but outside `decide`) |
| B9 | **Seasonal outreach** — jobs/seasonal_outreach.py:306 `run`, manual CLI (`--send`) only | canned free-form (`compose`, 220) or marketing template (`send_wa_template` direct, 281) | N (canned) | Y, fail-closed (329) | `seasonal:{season}:{year}:{to}` nx (258) — **claimed BEFORE the send, so a failed send burns the year's slot**; no `SendOutcomeUnknown` branch | one per season per year; one per parish (181) | WhatsApp Y (template when closed). **Meta: none** — the docstring says "Meta channels have no such window" (24), which is false; an out-of-window Messenger send is refused and burns the guard | Y (AI-mode, open conversations, 140) | **English only, no language check** | **N — bypasses the dispatcher entirely** | rows carry NO outreach stamp → the dispatcher's daily cap cannot see them; no "asked for time" hold (`customer_state.hold_for`), no open-team-check hold, no 7-day-flag rule; template sent without `templates.validate_params`; stored as "[template …] " + the free-form text, which is not what the customer read |
| B10 | **Missed-call text** — services/call_log.py:445/536/539, routers/whatsapp_webhook.py:468 → services/missed_call.py:47 | canned config text (`settings.missed_call_message`) | N | Y, fail-closed (78) — skipped when no conversation row exists | cooldown per customer (86-97) | 1 per `missed_call_message_cooldown_h` | relies on the call having opened it | **N** | **N** (one configured language) | N | default OFF |
| B11 | **Recording notice** — services/call_log.py:310 → services/recording_notice.py:78 | canned config text | N | Y (120) | once per customer ever (PK claim, 128) — **claim is deleted on ANY send exception, including `SendOutcomeUnknown` (140-145) → may be sent twice** | once | Y (103-116) | N | N | N | default OFF |
| B12 | **Order confirmation + payment link** — routers/hub_bridge.py:52 → services/messaging.py:868 `upsert_order_event` → 1034 `_relay_order_confirmation` (1113) | canned; **total and currency from the hub's push response (`pushed.total_amount`), pay URL from `hub_client.fetch_payment_link`** | N | **N** | **none**; unknown outcome → swallowed by `except` (1041) | none | **N** | **N** | **English only** | N | NOT VERIFIED whether this legacy bridge endpoint is still called in production (`hub_relay_receipt` defaults True, core/config.py:449; the agent's own `create_order` does not call it). |
| B13 | Owner alert — services/auto_release.py:238 `forward_to_owner` | canned | — | — | — | — | — | — | — | — | goes to the owner's own numbers, not a customer |

### C. Staff-triggered sends

| # | Path / entry / trigger | Text | Reply gate | Opt-out | Dedupe / unknown outcome | Rate limit / cap | 24h window | Human mode | Language | OUTREACH_MODE | Gap |
|---|---|---|---|---|---|---|---|---|---|---|---|
| C1 | **Staff reply** — routers/admin.py:1977 `/reply` → services/conversation.py:612 `send_agent_reply` → 480 `_deliver_agent_reply` | staff-typed; may be an unedited AI draft (C6) or a machine translation (C7) | N | N | `client_msg_id` idempotency (648); ownership lock (642); **`SendOutcomeUnknown` is treated as a plain failure (656) → the claim is released and the person is told to retry → duplicate** | — | Meta: `human_agent` tag when 24h–7d (523). **WhatsApp: no check, a free-form text is sent outside 24h** | takes the chat | — | N | public comment replies still pass `sanitize_public_comment` |
| C2 | **Staff media / voice note** — routers/admin.py:2229, 2311 → conversation.py:875 `send_agent_media` | staff file + caption | N | N | **no idempotency key** | — | as C1 | lock + takeover | — | N | — |
| C3 | **One-tap approve of a held draft** — routers/admin.py:2027 → conversation.py:780 `approve_draft` | **model draft that the gate HELD (it carries a hard finding by definition, runtime.py:1626), or a window-closed draft** — unedited unless the person edits | N (the draft already failed it) | N | **no idempotency, no ownership lock (`_refuse_if_held_by_other` is not called), no `SendOutcomeUnknown` handling** | — | `human_agent` when applicable | — | — | N | saved as `sender=ai`; a double tap sends twice. The only control is the person reading it. |
| C4 | **Team answer through Neema** — routers/admin.py:1838 `/answer` | **model**, re-wording the facts a colleague typed, told to "invite the next step of the order in the same breath" | **N — ro turn AND no `initiated_issues` call** | **N** | **none: no claim, no idempotency key, no `SendOutcomeUnknown` handling** | none | Y (1869, 409 when shut) | **N — not read; no ownership lock** | prompt only | N | the weakest model path in the system: nothing compares the figures in the sent text with the facts typed; a double click sends two different model messages |
| C5 | **Approve a planned action** — routers/crm.py:1046 `approve_action` → `actions._send` (1085) | stored draft (model or code) or a fresh `_compose_follow_up` | N; `initiated_issues` (a hard finding surfaces as a 500) | **N — not re-checked at approval** | `claim` (1075); on `SendOutcomeUnknown` the row returns to its old status (1093) for another tap | — | **N — a row parked BECAUSE the window closed is sent free-form** | N | N | N | stamped as routine with no action id (`_send(db, redis, conv, text)` passes no action) |
| C6 | **Drafts shown to staff** — routers/admin.py:1628 `generate_draft` (ro), services/copilot.py:58 `_human_held` (ro), copilot.py:191 briefing | model | **N — ro, ungated**, even though they are the customer's own words | — | — | — | — | — | — | — | reach the customer only through C1; a send that matches the draft word for word is recorded as `unchanged` (conversation.py:595) |
| C7 | **Reply-box translation** — routers/admin.py:1994 → services/translate.py:429 `translate_reply` | **model translation** of the staff text; the customer receives the translation | N. "Keep … numbers, prices … EXACTLY" is prompt text (458); **no code compares the figures in the output with the input** | — | — | — | — | — | — | — | a mistranslated price goes out under a colleague's name |
| C8 | **WhatsApp invite / follow-up template** — routers/admin.py:3030 `/whatsapp-invite` → `send_wa_template` (3110) | Meta template, `{{1}}` = raw first word of the typed name | N; **bypasses `templates.send` / `validate_params`** | **N** (a person who opted out on Messenger can be templated on WhatsApp) | **none — no cooldown, no idempotency** | none | refuses when the WhatsApp window is open (3066) | — | template language | N | — |
| C9 | **Call-permission request** — routers/admin.py:3920-3942 (`wa_calling.request_call_permission[_template]`), 3992 (Messenger `calling_optin`) | canned / template | N | N | Messenger: request limit (3989) | Meta-enforced | Y (route chosen by window) | — | — | N | — |

## 3. The three lists

### (a) Senders reachable with MODEL-WRITTEN text and NO reply gate

1. **Team answer through Neema** — routers/admin.py:1874-1899. Read-only turn, no `initiated_issues`, straight to `_send_waba` / `send_to_channel`. No deterministic check of any kind.
2. **Dispatcher follow-ups** (`follow_up`, `customer_promise`, `check_in`, `replenishment`, `buying_follow_up`, `fit_check`) — services/actions.py:436-453 → 515-528. Only `paid_ack` and `status` are hard.
3. **Hub event announcements** — services/hub_events.py:172-186 → 282-309. With `status_known=True` and (for paid events) `paid_known=True`, no hard rule is left.
4. **Cross-channel bridge** — services/reply_sweeper.py:122-141 → 188. Same two rules only.
5. **Approve planned action** when no draft is stored — routers/crm.py:1081-1085 (person in the loop; `initiated_issues` only).
6. **One-tap approve of a held draft** — services/conversation.py:780-826 (person in the loop; the text is the one the gate refused).
7. **Staff sending an unedited AI draft** — routers/admin.py:1669-1681 / services/copilot.py:58-68 → services/conversation.py:612 (person in the loop; the draft was never gated).
8. **Reply-box translation** — services/translate.py:454-479 → conversation.py:612 (person in the loop who usually cannot read the target language).

Gated model text, for contrast: A1, A2, A9, A10, A12, A13, A15, A17 (all `run_turn` without `read_only`).
Not model text but figure-bearing and ungated: A3, A11, A16, B2, B3, B12 — see (c).

### (b) Senders with NO opt-out check

Neema-initiated (the ones that matter):
- **Order confirmation relay** — services/messaging.py:1113-1126 (B12).
- **No-model hold line** — agent/runtime.py:2960-3003 (A6; a reply, but sent with no check).
- **Missed-call text and recording notice when no conversation row exists** — services/missed_call.py:78, services/recording_notice.py:120 both test `conv is not None and …`; with no row the send proceeds (an opt-out recorded on the person via another channel is not consulted).
- **Hub event announcement** if the opt-out read raises — the surrounding `try/except: pass` (services/hub_events.py:263-271) lets the send continue. `opted_out(fail_closed=True)` catches its own DB errors, so this needs an import/attribute error; low likelihood, but it is fail-open.

Replies that bypass the inbound opt-out door:
- **Missed-reply sweeper** — services/reply_sweeper.py:478-487 calls `_run_and_send*` directly; `is_opt_out` / `wants_a_person` live only in `schedule_reply` / `schedule_meta_reply` (agent/runtime.py:3323-3328, 3626-3631). Combined with `_handle_opt_out` returning silently on a repeat (3259-3260) this produces a model reply to a customer who has said "stop" twice.
- **Unclaimed answer** (unclaimed.py:127), **person door ack** (runtime.py:3277), **money-hold line** (auto_release.py:316), **web chat / ManyChat person door** — replies; no check.

Staff-triggered, none checked: `/answer` (admin.py:1838), `approve_action` (crm.py:1046), `approve_draft`, `/reply`, `/reply-media`, `/whatsapp-invite` (admin.py:3030), call-permission requests.

Public comment replies are never checked (public by nature); the DM they open is (runtime.py:6777, 6596).

### (c) Figures inserted into canned / code-built text, and where each comes from

| Where | Figure | Source | Freshness / risk |
|---|---|---|---|
| services/quote_followup.py:152-171 `compose` | item price(s) | `extract_quote` (101-150): a `search_catalog` row price that the reply also stated as money and whose item the reply named | captured at quote time; **not re-read** when sent hours later |
| jobs/payment_followup.py:181-217 `compose` / `compose_many` | order amount | `_amount` (197): `OrderEvent.hub_total`, else **local `subtotal`**; currency `hub_currency` → `currency` → "KES" | local mirror at plan time; send-time check covers paid status only (329) |
| services/messaging.py:1113-1124 `_relay_order_confirmation` | order total | hub push response `total_amount`, `currency_code` (1035-1037) | hub's own figure |
| services/hub_events.py:93-104 `brief_for` | payment amount | hub event `amount` / `currency` — placed in the BRIEF; **the model writes the customer-facing figure**, unverified | model restatement |
| services/hub_events.py:320-328 | none (status words) + receipt link | `_receipt_link_for` (399) | link inside a template parameter |
| agent/runtime.py:6973-6990 `_public_price_text`, used at 6893 | public comment price ("from KES …") | post identity row `price_kes` / `price` / `price_usd`, cheapest variant (`_variant_floor`, 6961); **converted at `settings.usd_kes_rate` (default 100 when unset) when one currency is missing** | redis-recorded post identity, not a fresh hub read at reply time — NOT VERIFIED how long that record can outlive a hub price edit (`_remember_post_product`, 5489, was not traced to its TTL) |
| agent/runtime.py:6885-6889 `_bundle_items_text` / `_components_text` | per-item set prices | `matched["bundle_rows"]` / `components` from the same identity row | as above |
| services/cassock_ladder.py:110 `follow_up` → `message` | cassock + two set prices | `svc.catalog_items(db, redis)` at turn time (runtime.py:2779) | live catalogue cache; sent after the gate, never read by it |
| agent/tools.py:3031-3036 product cards | card price text | `_fmt_price(_to_display(p["price"], ctx, p["price_usd"], prices=p["prices"]), ctx.currency)` from `catalog_items` | live catalogue cache; sent before the gate |
| jobs/cart_recovery.py:239-242 | cart total | `cartmod.cart_total(cart)` written into the action's `reason`; **the model restates it** | unverified model restatement |
| jobs/seasonal_outreach.py:220-231 | "about N week(s)" | `liturgical` season date arithmetic; item name from the customer's last same-season `OrderEvent.items[0]` | no price |
| services/person_door.py:86 | "back at HH:MM" | `commitments.next_staffed_start` | a time, not money |
| agent/runtime.py:2914-2957 `_hold_line` | phone numbers | `settings.whatsapp_handoff_number` / `_alt` | config |

## 4. Not verified

- Whether `routers/hub_bridge.py:52` (`/order-event` → B12) is still called by anything in production.
- TTL / refresh of the recorded post identity that prices canned comment replies.
- `_handle_opt_out`-then-sweeper behaviour (A12) was established by reading; the predicates were not executed (no dependencies installed).
- `settings.outreach_mode` in the deployed environment — the default is `shadow` (core/config.py:214) and a dashboard row can override it (services/app_settings.py:263); the live value was not readable from here.
- Whether Meta refuses or silently drops a free-form WhatsApp text sent outside 24h by C1 / C5 (external behaviour, not in this code).
