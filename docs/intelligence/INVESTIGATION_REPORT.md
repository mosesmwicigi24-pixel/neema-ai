# Deep Investigation Report — material weaknesses, root causes, affected paths

Date: 2026-11-06. Sources: the seven read-only inventories (A runtime/prompt,
B tools, C commerce, D channels/identity, E verification/grounding, F
memory/state, G dashboard/eval/apps), the 5–6 November audits re-checked
against the current code (ff8c3b5), the live `/api/health`, and the
model-free measurements in BENCHMARK_RESULTS.md. Tags: **[C]** confirmed in
code at file:line · **[H]** hypothesis consistent with code, not reproduced ·
**[M]** measured in this programme. Severity: **S1** customer harm or
financial/consent error possible now · **S2** wrong or degraded behaviour
likely in ordinary traffic · **S3** quality, cost or maintainability.

Every finding names the workstream (W1–W10) that owns it in
ADVANCEMENTS_REGISTER.md. Nothing here is a fix; each row says what the
smallest effective change would be so the register can argue it.

## W1 — Reliability, truth, customer trust

| # | Finding | Sev | Evidence | Affected path | Smallest change |
|---|---|---|---|---|---|
| 1.1 | **The reply gate fails open.** Any exception inside the gate call sends the unverified draft. No test covers that branch. | S1 | [C] runtime.py:2214–2231 ("reply gate failed open"); E §1.5, §9 | every live reply on every channel | fail closed: on gate error hold the reply (silence on a closer, hold line otherwise) and flag; a test for the branch |
| 1.2 | **Opt-out is recognised only at the WhatsApp door.** "Stop messaging me" on Messenger, Instagram, TikTok and web chat is never recorded; the customer-state floor files a "stop" state only. | S1 | [C] runtime.py:2729 (only caller of `_handle_opt_out`); D §9 #1; F §2.5 | Meta/TikTok/web inbound; every later unprompted sender to that person | call the same door from `schedule_meta_reply`, the TikTok and web routers; record by person as well as handle |
| 1.3 | Opt-out is durable only when a person row exists; otherwise it lives in redis for a year and dies with a flush. The comment-DM check uses a synthetic conversation with no person. | S1 | [C] intent.py:431–433, 475–477; runtime.py:5915–5917 | comment DMs, early-funnel contacts | create the person on opt-out; look up by handle on every channel |
| 1.4 | The missed-reply sweeper's cross-channel continuation sends without an opt-out check. | S1 | [C] reply_sweeper.py:142–197 (no `opted_out` in file) | sweeper bridge messages | one `opted_out` call before the send |
| 1.5 | `_still_ai` (takeover re-check before send) fails open on a DB error; web chat and ManyChat never re-check at all. Human replies from Meta's Page Inbox are invisible (echo dropped), so Neema can talk over a colleague. | S1 | [C] runtime.py:2578–2593; web_chat.py:198–223; manychat.py:119–159; meta_webhook.py:243; D §9 #7–#9 | all channels | fail closed on error; re-check on sync channels; treat an `is_echo` from the page as a human turn |
| 1.6 | **Tools reach the customer and the hub before the gate.** `send_product_cards` and `send_measurement_guide` send mid-loop; `create_order` creates the hub order, clears the cart and records the event before the words are reviewed; none is reversible if the reply is then held. | S1 | [C] runtime.py:2176 vs 2213; tools.py (B §5) | any turn that calls them | hold the sends until the gate passes (cards and guide are deferrable); keep order creation but never let a held reply follow a created order silently |
| 1.7 | A promised discount silently drops off the order when the redis read fails (`granted_promise` → None). Quote time refuses, order time proceeds: inconsistent direction. | S1 | [C] tools.py:1457–1459; C §13 #15; E §9 | order creation under a promotion | fail closed: refuse to create the order and ask a colleague |
| 1.8 | `resolve_hub_line` falls back to the model-supplied unit price when the catalogue price is 0/None, and a test pins it as intended; the legacy bridge path has no unpriced-line refusal. | S1 | [C] hub_client.py:371–372; tests/test_hub_order_push.py:55; messaging.py:811–935 | order payload | refuse unpriced lines on both paths; retire the bridge order path |
| 1.9 | "Paid" is a prompt rule plus a soft reviewer rule; no code gate stops "thank you for your payment" after a claim. Staff can mark an order paid by hand with no hub check. | S1 | [C] prompt ("PAID IS A CLAIM…"), review.py:1332–1336 (soft, dm-only); admin.py:2516–2519 | payment claims; dashboard | a hard gate rule: a paid acknowledgement needs a hub paid state in this turn's tools |
| 1.10 | Unknown-delivery handling is right on WhatsApp and Meta sends, but Meta delivery receipts are discarded, so "delivered" is never known on Messenger/IG. | S2 | [C] meta_webhook.py:250–263 | Meta outbound | store the receipt on `raw_meta.delivery` as WhatsApp does |
| 1.11 | Identity: Meta sibling adoption keys on identical external ids across messenger/instagram/facebook; a collision would merge strangers. `capture_contact` (allowed on human-held threads) can merge persons and delete identifiers from a model-supplied phone. `/api/hub/payment` merges on the hub's word with a shared secret, no HMAC. | S2 | [C] identity.py:88–110 [H risk]; tools.py:1872–1897, 2032–2039; hub_bridge (C §13 #21) | identity merge | require two signals for a merge; no identifier deletion from a model call |
| 1.12 | Held replies: `escalate_to_human` and the reviewer hold move a thread to human but the dashboard human reply never sets human mode; an escalated, unclaimed thread can sit silent. | S2 | [C] conversation.py:612–700; auto_release.py:3–6 (doc contradicts code); 5 Nov audit C8 | human-held threads | (post-audit PR #308 added an unclaimed-chat answer; verify in production) |
| 1.13 | Meta webhook acks 200 even when capture raised (acked-and-lost); WhatsApp returns 502 so Meta redelivers. Signature checks are skipped when the secret is unset. | S2 | [C] meta_webhook.py:113–121 vs whatsapp_webhook.py:104–107; :53–57, :47–49 | Meta inbound | return 5xx on capture failure; fail closed without a secret |
| 1.14 | **Inbound reaches the inbox:** verified from outside the box on 6 Nov (routes answer 403 to unsigned posts; a Meta comment webhook was delivered, verified and answered 50 min after the ff8c3b5 deploy; the inbox query unchanged since 06:07 UTC with later rows visible). Not verified: a direct message end-to-end after 13:10 UTC, pending the owner's test. | — | [M] shadow log 14:12 UTC | — | owner test message; admin credential for a direct read |
| 1.15 | Financial grounding is strong where the gate runs (hard `figure` rule, hub rows only, USD via `usd_quote`), but `figures_in_results` accepts any numeric tool value (pack sizes, ids) and the prompt's "350" delivery figure is allowed in every currency. | S2 | [C] review.py:186–210, 1611–1612; E §9 | money replies | restrict facts to price-typed fields; fee figures per currency |

## W2 — Intent and contextual reasoning

| # | Finding | Sev | Evidence | Smallest change |
|---|---|---|---|---|
| 2.1 | The customer-state floor misses imperative time requests: "Please contact me on Thursday", "Call me tomorrow", "Let's talk next week" return no state, because the customer-promise regex requires "I'll/we'll/nita" + verb. The Judas form "I will decide on Thursday" is caught; the plainer form is not. | S2 | [M] eval_floors on the audit set: `said` 27/29; misses listed in BENCHMARK_RESULTS; [C] deals.py:41–54 | add the imperative forms to `_CUSTOMER_PROMISE_RE` with the same time-hint requirement; measure on the case set |
| 2.2 | "Thank you very much." is not a closer (the ack regex allows "thank you" but not "very much"/"so much"/"a lot"), so the politeness ping-pong the closer gate exists to stop still happens on the most common long form. | S2 | [M] is_closer → False; [C] runtime.py:696–703 | extend `_ACK_RE`; measure |
| 2.3 | A hold is cleared early only on model-note states; the floor never returns those, so with the note off a real customer message does not lift a hold until it expires. | S2 | [C] customer_state.py:299–305; F §4 | let a `ready`/buying-signal floor reading clear a hold |
| 2.4 | The scribe assigns `deal.next_action` wholesale on a promise and can erase an open team check or hold written earlier in the same turn; the availability-check note tells the model to say "I'll check and come back", which the promise regex matches. | S2 | [C] deals.py:233–247; tools.py:2263–2264 [H trigger] | merge instead of replace; test the same-turn case |
| 2.5 | The language guesser answers "unsure" for short English imperatives ("Please stop messaging me" → None, "Hello" → None), so `automated_ok` cannot vouch for them. | S3 | [M] guess_language; [C] customer_state.py:127–160 | treat ASCII-only text with no Swahili/French markers as English |
| 2.6 | The model-note layer (intent beyond the floor) runs only when the floor finds nothing and only with a key; its outputs feed `persons.state.customer_state`, which the model never reads. | S3 | [C] customer_state.py:204–215; F §2.4 | nothing until measured: the real-model eval will show whether the model layer is needed |

## W3 — Emotional and social intelligence

| # | Finding | Sev | Evidence | Smallest change |
|---|---|---|---|---|
| 3.1 | Complaint recognition is regex-only and the length target's "complaint" kind depends on `looks_negative`, which is a comment-intent detector; "My order is late, the service is on Sunday and nothing has arrived" is read as a default message. | S2 | [M] eval_floors length_kind misses; [C] runtime.py:3282 | feed the floor's `complaint` reading into the length target |
| 3.2 | The reviewer is told never to fail for tone; nothing measures social judgment. The research says scoring "empathy" is the wrong target: score acknowledge-then-fix and holding facts under pushback. | S3 | [C] review.py:1347; STANDARDS_RESEARCH §5 | human-rated hard cases (case set `judge: emotion`); objective sub-checks (no selling into distress, no over-apology loop) |
| 3.3 | Four independent pause mechanisms with different thresholds can each decide a customer "needs silence". | S3 | [C] A §0.5 | one decision point (W7) |

## W4 — Consultative sales judgment

| # | Finding | Sev | Evidence | Smallest change |
|---|---|---|---|---|
| 4.1 | No code rule stops manufactured urgency or scarcity; discounts are grounded (promotions) but "today only"/"last piece" are prompt-only. | S2 | [C] E §1.2 (no such rule kind) | a hard gate rule for urgency/scarcity phrases with no tool-sourced fact |
| 4.2 | Every catalogue row pushes 177–303 chars of `ask_next` prose at the model on every row, plus set notes; up to 8 rows ≈ 0.8–1.5 KB each. This is the mechanism behind the audit's "the set's contents on every turn". `said_once` now marks rows already told, which is the right counterweight. | S3 | [C] tools.py:1051–1084; B summary | measure before trimming: the case set's `detail` vs `short` turns |
| 4.3 | The prompt's SELL LIKE A CONSULTANT block is 45 K chars (47% of the base prompt) with worked examples longer than the brevity contract allows. | S3 | [C] A §0.2, §4 | no blind cut; a replay comparison first (W7) |

## W5 — Onboarding

| # | Finding | Sev | Evidence | Smallest change |
|---|---|---|---|---|
| 5.1 | No "already asked" memory for questions (size, colour, city): `said_once` covers what Neema told, not what the customer told. Re-asking is therefore only prevented by the 40-message history. | S2 | [C] F §2.2, §3 | the case set's `memory`/`onboarding` turns measure it; then a small "facts the customer gave" note (same mechanism as said_once) if the measurement shows re-asking |
| 5.2 | Images with no caption are dropped from history; a photo-only ask is only recoverable via product interest. | S2 | [C] runtime.py:1000–1002 | keep a placeholder row |
| 5.3 | Measurements and parish are recalled; sizes in free-text facts have no timestamp or expiry. | S3 | [C] memory.py | timestamps on facts |

## W6 — Closing

| # | Finding | Sev | Evidence | Smallest change |
|---|---|---|---|---|
| 6.1 | `create_order` success is reported as "the order was CREATED" and the result's `payment_url` key invites calling the order page "the payment link"; the legacy bridge path sends "✅ confirmed" on an unpaid order. | S2 | [C] review.py:885; tools.py:1579; messaging.py:1012 | rename the key; retire the bridge path |
| 6.2 | A Kenyan customer can hear three totals (chat sum with KES 350 delivery, quotation without, order link without). | S2 | [C] prompt.py:367; tools.py:3106, 1579 | one rule: delivery quoted separately everywhere, stated once |
| 6.3 | Verified paid-order conversion is derivable (`order_events.hub_payment_status`) but not shown; Overview revenue sums unpaid Neema-placed carts only. | S3 | [C] G §1.1 | dashboard (W10/§7) |

## W7 — Memory and context engineering

| # | Finding | Sev | Evidence | Smallest change |
|---|---|---|---|---|
| 7.1 | Base prompt ≈95–98 K chars (≈24 K tokens) + 1–20 K channel addendum + 8–18 K tools; llm.py says "~10k". History = last 40 raw messages, no summary. The research (Laban 2025, Chroma 2025) says multi-turn sharded requirements degrade models ~39% and focused context beats full history. | S2 | [C] A §0.2–0.3; STANDARDS_RESEARCH §8 | a measured experiment, not a cut: structured customer-state object near the prompt end; compare on the held-out set |
| 7.2 | Instruction hierarchy: directives cut at 600, learned rules keep newest at 1,200, but prompt.py:216 slices the pair at 1,800 (head), so the newest rules can still be cut; WHEN RULES COLLIDE never ranks directives, learned rules, house voice, deal guidance or turn notes. | S2 | [C] prompt.py:216; app_settings.py; A §0.13 | keep the newest at the combined cap; rank the dashboard inputs explicitly |
| 7.3 | Contradictions inside the prompt: "exactly ONE question" vs "not every message ends in a question"; three length numbers; pacing thresholds 3 vs 5; closers get one line vs emoji acks silenced; "hub" 46×. | S2 | [C] A §4.3 (quoted) | targeted edits only, after the baseline run |
| 7.4 | The "empty reply = silence" contract is broken by the loop's own fallback: empty text → a nudge call → "One moment — let me check on that for you.", the exact line the prompt bans. `stop_reason` is never inspected: a max_tokens-truncated reply is sent as final. | S2 | [C] runtime.py:916–922 vs 2162–2171; prompt.py:610–615 | honour empty on an overlap/closer; inspect stop_reason |
| 7.5 | Split memory homes: a Meta turn never reads the linked WhatsApp user's facts; said_once and product interest are keyed by channel+handle, not person; one phone call is stored three times and each eats a memory slot. | S2 | [C] memory.py:147–149; F §2.2, §2.6 | person-keyed reads |
| 7.6 | `persons.state` is rewritten without the write lock in `record_opt_out` and `customer_state.apply` (lost-update risk the state_lock contract exists for). | S2 | [C] intent.py:436–442; customer_state.py:264–278 | use `lock_for_write` |

## W8 — Multilingual and cultural

| # | Finding | Sev | Evidence | Smallest change |
|---|---|---|---|---|
| 8.1 | Language continuity is enforced by a soft, dm-only reviewer rule; automated messages are allowed only in en/sw/fr; language is overwritten per message. | S2 | [C] review.py:1332; customer_state.py:41, 266–269 | the case set's language slice; a hard continuity check for the scripts that can be detected |
| 8.2 | No native-speaker evaluation exists; no benchmark covers Swahili–English–Sheng conversation. | S3 | STANDARDS_RESEARCH §7 | a 30–40 item native-speaker packet (rater packet from the runner) |

## W9 — Autonomous commercial execution

| # | Finding | Sev | Evidence | Smallest change |
|---|---|---|---|---|
| 9.1 | Success is reported where only a human was notified: `_celebrate` returns handled/sent in four branches where the customer heard nothing; `handle_event` returns 200 before processing; the payment reminder marks `sent` when merely planned. | S2 | [C] hub_events.py:252–258, 318–334; routers/hub_events.py:287–290; payment_followup.py:318 | return the true outcome; the dashboard reads outcomes, not acks |
| 9.2 | `handoff_to_human` sets human mode but never alerts the team (three other hand-over paths do). `pause_conversation` is a no-op without redis. | S2 | [C] tools.py:2271–2300, 2921–2924 | ring once; fail closed |
| 9.3 | Order creation: 20 s hub call, no retry; idempotency only through redis and the redis read is except-pass. | S2 | [C] hub_client.py:724; tools.py:1424–1436 | a DB-side idempotency key |
| 9.4 | Two order-creation paths and two receipt shorteners; the paid thank-you wraps the durable link in the expiring one. | S2 | [C] C §13 #5–#6 | retire the legacy path; use the durable link |
| 9.5 | Tool-driven currency mutation mid-turn (`search_catalog`, `capture_contact` change `ctx.currency`), governing cart/quote/order figures in the same turn. | S2 | [C] tools.py:705, 1972 | lock currency per turn once a figure has been quoted |

## W10 — Evaluation and dashboard

| # | Finding | Sev | Evidence | Smallest change |
|---|---|---|---|---|
| 10.1 | `agent_eval.py` had 12 scripted conversations, deterministic checks, stdout only, no history, no held-out set, no pass^k. (Addressed in this programme: case set + runner + history; the real-model run is still BLOCKED on a key.) | S2 | [C] G §3; [M] this programme | — |
| 10.2 | Every "revenue" figure on the dashboard is the sum of Neema-placed cart subtotals (unpaid included); hub/POS/human-only orders are invisible; `paid_revenue` is computed but never rendered; Reports computes over an unpaged full list in the browser; two Settings panels save nothing. | S2 | [C] G §1.1–1.3 | §7 dashboard: paid vs unpaid, Neema vs assisted vs human, NOT YET MEASURED elsewhere |
| 10.3 | The usage row logs the configured model, not the one that answered after a fallback; totals exclude reviewer and rewrite calls. Weekly rule proposals cannot be approved (endpoint has no caller). | S3 | [C] runtime.py:2313 vs llm.py:246; G dead endpoints | log `last_model`; wire the proposals panel |
| 10.4 | Many tests are source-string assertions, not behaviour. | S3 | [C] A §0.17 | behaviour tests ride with each change |

## Cross-cutting: shadow-only protections and no-op flags

Recorded but never enforced by default: photo check (shadow), pacing budget
("live" identical to "shadow"), outreach rules (shadow), reply length
(record-only), said-once (advisory), the model reviewer (always soft). Off by
default with production value unknown from here: `meta_agent_reply`,
`meta_comment_reply`, `agent_initiative`, `quote_follow_up_enabled`,
`recovery_cart/payment_enabled`, `copilot_mode`, `hub_events_secret`,
`missed_call_message_enabled`. [C] E §5–§6. The inbox shows Messenger and
Instagram replies being sent, so at least `meta_agent_reply` is on in
production [M, inference from the screenshot and the spend ledger].

## What this investigation could not do

- Read the box's `.env`, logs or database (no SSH, no saved credential).
- Run the model (no key in the session): every behavioural claim above is
  about code paths, not transcripts, until the case set runs on the box or in
  the workflow.
- Observe the hub's side (whether it honours per-line discounts, posts
  payment events).
- Read `NEEMA_CAPABILITY_INTELLIGENCE_PROFILE_2026.md` (not provided).
