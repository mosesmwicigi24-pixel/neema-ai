# Neema agent — read-only audit and correction plan (5 Nov 2026)

Nothing was changed. Every claim below is tagged:
**[C]** confirmed in code (file:line quoted) · **[L]** confirmed from live data (/api/health today) ·
**[P]** probable cause, consistent with the code and the Mama Beth chat but not reproducible here ·
**[U]** unknown, needs production data.

---

## A. How Neema processes a message today (the actual path)

**WhatsApp:** `POST /api/wa/webhook` → `wa_native.handle_webhook` → per message: media download, `upsert_message`, voice-note transcription scheduled → **30-second trailing debounce** (`whatsapp_debounce_seconds=30`, config.py:238; buffer `wa:native:buf:{wa_id}`) → texts of the burst joined → **human/paused check** (wa_native.py:409–424: `intercept_mode != ai` → no reply, copilot draft only) → `runtime.schedule_reply` → `_run_and_send` → `run_turn` → `_send_waba`. [C]

**Messenger/Instagram:** `POST /api/meta/webhook` → `_capture_events` → mode checked **at capture only** (meta_webhook.py:422) → `schedule_meta_reply` → 12-second burst → `_run_and_send_meta` → `run_turn` → `send_to_channel` (strips markdown). [C]

**n8n is retired** (whatsapp_webhook.py:3–5, hub_bridge.py:13–16). `n8n_bridge.py` is only the persistence/send layer under its old name. Dead n8n-era functions remain (`outbound_gate`, `get_profile`/`should_run_ai`, `route_message`, …) with zero callers; stale docstrings still describe n8n and a non-existent `whatsapp_native` setting. They change nothing at runtime. [C]

**Inside `run_turn` (runtime.py:1412–2197), in order:**
1. Budget guard (economy → light model). Market/currency. DB-stored directives + learned rules + house voice + offer loaded → `build_system_prompt`.
2. Per-customer "tail" system block (name, country, clock, call summaries, cross-channel lines, deal guidance).
3. History: **40 messages** (DM), re-sent whole every turn, notes excluded (runtime.py:923, 1569).
4. Church-goods guard; pacing (`cooling.decide`); FX; shared link; product-interest; memory block; photo check.
5. Leading context turn for post-sourced threads (`_set_context`, `_post_row_context`).
6. Model loop, up to 8 tool iterations (`tier2_max_iterations=8`). Model: Sonnet 5.5 (effort high) / Haiku 5.5 (effort low) for greetings; `max_tokens=4096`.
7. **The gate** `_gate_turn_reply`: rules + model reviewer → pass / **one rewrite** → second review → pass/soft/held.
8. Photo-refer override (live mode only), cassock ladder (second message once/30 days), conversation budget (record-only), usage log.

**Model-call cost today [L]:** a WhatsApp turn ≈ 41–45k tokens of context per call (`spend.cache_gaps.conversation.whatsapp.new = 41,574`); the rewrite call ≈ 47k (9 calls, 422k tokens). System prompt alone ≈ 93,455 chars ≈ 23k tokens for KE/KES; tools ≈ 6k more.

**Reviewer outcome today [L]:** passed 3 · rewritten 5 · soft 4 · held 0 → **first-draft pass 25%**. Three of every four replies the customer receives are second drafts written under the rewrite instructions (see C3).

---

## B. Previous improvements — what is still active, inactive, duplicated or conflicting

| Earlier work | State | Evidence |
|---|---|---|
| Brevity contract ("1–2 sentences, ~20 words") | **Active in the prompt, enforced nowhere** | prompt.py:1395–1403; no length check in gate or senders; reviewer told "Never fail for … length" review.py:1280 |
| "How our team answers" block (2026-10-30), incl. "NOT EVERY MESSAGE ENDS IN A QUESTION" | Active | prompt.py:1426–1455 |
| House voice (team replies distilled, PR #294) | Active; re-learned automatically every Sunday 05:00 | actions.py:562–567, stylebook.refresh; content [U] |
| Learned rules (weekly distillation, owner-approved) | Active; **cap keeps the oldest 1,200 chars, so new approvals are silently cut once full** | crm.py:1240 `[:1200]` |
| Pacing / cooling-off (2026-09-26) | Active but **fires ~0×/day** (buying regex too broad) | health `cooling` all zeros today; cooling.py |
| Conversation budget + bot shield (#304) | Record-only, never touches the reply | runtime.py:2149–2160 |
| Reviewer gate / double verification (2026-09-25) | Active; **its rewrite instruction conflicts with the brevity contract** | review.py:1431 vs prompt.py:1437 |
| Cross-conversation memory (`remember`, past orders, sizes) | Active | memory.py:138–202 |
| Cassock ladder (#300) | Active, second message once per 30 days | cassock_ladder.py:56–64 |
| "One moment — let me check" fallback | Active (sent as the real reply when the model returns no text) | runtime.py:2058 |
| n8n gating (`should_run_ai`, `outbound_gate`) | **Dead code** | n8n_bridge.py:142, 740–757; 0 callers |

No duplicated live handlers were found for WhatsApp or Meta. One message is answered by one path. [C]

---

## C. Confirmed root causes of the behaviour in the Mama Beth chat

### C1. Length is a wish, not a rule [C]
- The only length control is prose in the system prompt. The prompt is ~1,286 lines; the brevity section starts at rendered line 978 of ~1,290, after ~900 lines of selling rules.
- "WHEN RULES COLLIDE" ranks brevity **#4**, below "Money & truth safety" (#1) (prompt.py:475–482). The worked examples inside the #1-ranked rules are **50–60 words long**: the set rule (760–778), the photo rule (808–822), the first-contact welcome (1464–1477). The model is shown 55-word exemplars and told "20 words".
- Roughly 25 distinct "keep it short" rules vs ~15 "also include / state the total and what it comes with / give both prices in the same reply / end with the order step" mandates. Each per-turn note and each tool row adds more of the latter (C2).
- Nothing measures or clips the reply: `_send_waba` sends raw text (n8n_bridge.py:341–363); the gate never counts words; the reviewer is told to ignore length (review.py:1280).

### C2. The set's contents are pushed at Neema on every turn [C]
- `search_catalog` returns, on **every** set row, `set.comes_with` plus a note; on every piece of a set `part_of_set` with "give the piece's own price AND the set's total in the same reply" (tools.py:893–926); and `ask_next` on **every** row ("state them … ask only how many, how soon and the delivery city") (tools.py:1021–1040). A full result is 8 rows ≈ 2–4k tokens.
- For post-sourced threads `_set_context` prepends "give that one price for the whole set; it comes with …" to the conversation (runtime.py:5100–5120).
- The prompt's set rule says "what it comes with, the main piece first" (760–778).
- **There is no "already told this customer" memory anywhere.** Each turn re-derives the contents from scratch, so "the Bishop's set: cassock, mitre, red cincture, round collar shirt, staff, pectoral cross and ring — KES 60,500" came out three times.

### C3. The rewrite path makes replies longer and forces a question [C + L]
- Every model-reviewer finding is **soft** (review.py:1351–1352); soft findings trigger the one rewrite (runtime.py:1334–1363).
- The rewrite block ends: **"keep the warmth and the closing question"** (review.py:1431) — contradicting "NOT EVERY MESSAGE ENDS IN A QUESTION … they end one in four" (prompt.py:1437–1440). It also says "answer every question they asked" and lists every hub row with 140 chars of description, with **no length limit**.
- When neither draft is clean, the tie goes to the rewrite (runtime.py:1384 "the rewrite wins a tie").
- Today 75% of replies went through this path [L]. The rewrite is a second ~47k-token call on the writer model.

### C4. "Promise-only" replies pass the checker [C]
- STYLE: "a check is never the whole reply … If any part of the answer is in your tools or this chat, give it in that same message" (prompt.py:1431–1436).
- Reviewer prompt: "(A colleague reaching out, a delivery being arranged, **a price to be confirmed** are ordinary promises, not inventions.)" (review.py:1275–1277).
- Mama Beth: "Let me confirm the Bible with our team and get back to you right away." passed and went out. Nothing flagged it, nobody followed up.

### C5. The invented "Pentecost wears violet" [P, strong]
- The system prompt carries, every turn: "THE CHURCH YEAR — you know this without being told … Advent begins in about 3 week(s) (2026-11-29) and needs **violet (purple)**" (prompt.py:156–163; `liturgical.brief()` output today).
- She asked "Plz assist for pentacost churches" (Pentecostal denomination). Neema answered "For Pentecost, the lady Reverend wears violet (purple)" — the one colour word the prompt was pushing that day, attached to the wrong "Pentecost". It also contradicted the grey/green/white she had already given.
- The reviewer has no rule against unsupported claims about what a church or season "wears".

### C6. Internal language leaks ("search the hub", "hold the set") [C]
- "hub" appears **46 times** in the system prompt; there is no instruction never to say it to a customer. → "shall I search for the price in our hub to confirm it for you?"
- Prompt examples: "shall I reserve it for you?" (712), "Shall I hold these while you confirm the colours?" (1624). → "Shall I hold the Bishop's set while you decide…" (nothing is actually held).

### C7. The re-asked colour in Swahili [P]
- The model reviewer sees only the **last 8 turns, each cut to 260 characters** (review.py:1199–1204, 1235). The grey/green/white colours were given 7 turns and several long replies earlier, so the CONTRADICTS/re-ask rule (review.py:1273) had nothing to compare against.

### C8. Her last message has been unanswered for 9+ hours [C structure]
- The chat is in **Human** with nobody assigned. In that state: the live path never replies (wa_native.py:409–424), the sweeper only retries AI-mode threads (reply_sweeper.py:356–380), and `auto_release` refuses to release while the customer is waiting, and skips entirely when `intercept_since` is NULL (auto_release.py:165–174). `escalate_to_human` and the reviewer hold **never set `intercept_since`** (runtime.py:2548, 1177).
- Result: an escalated-but-unclaimed thread is silent indefinitely unless a person acts.

### C9. Two risks of double replies (not seen in this chat, confirmed in code) [C]
- The missed-reply sweeper re-runs a full turn 90 s after an inbound if no outbound exists, with no knowledge of a turn still in flight (30 s debounce + up to 60 s voice wait + up to 45 s photo check + model loop can exceed 90 s).
- There is no per-conversation lock around `_run_and_send`; a burst arriving mid-turn starts a second concurrent turn.
- Meta checks human mode only at capture, never before send.

### C10. Accuracy and hub data in this chat
- Prices quoted were **correct against today's hub**: Classic Princes Cassock Set 19,000; Bishop's set adds to 60,500 from hub rows. [L]
- "Bishop's Ring – KES 1,500" is the hub's plain **"Ring"** (1,500); a **"Bishopric Ring"** exists at 4,000. Possible wrong row. [P]
- Hub still shows **Cassock Set 19,500** (owner wanted 21,000) and **"Bishops Collar with a stud" has no price**. [L]
- "Comes in any colour you choose" and "the Bishop will come to the shop for fitting" are unverified claims the reviewer does not test. [C gap]

### C11. Stale-price vectors (none triggered here, but open) [C]
- `remember` facts are free text, 20 kept, no expiry, no price filter (memory.py:63–72).
- Cart lines keep the `unit_price` from when added (cart.py); a hub change would not show.
- "A COLLEAGUE'S ANSWER OVERRIDES YOURS — including your tools" (prompt.py:1604) applies to any `[TEAM]` line inside the 40–59-message window, however old.

---

## D. Corrections — smallest safe change for each, in priority order

| # | Change | Files | Fixes | Risk |
|---|---|---|---|---|
| **1** | Rewrite block: replace "keep the warmth and the closing question" with "keep the warmth; end with a question only if it moves the order; **no longer than the held draft; each fact once**". Widen the reviewer's window to 16 turns × 400 chars. Add three FAIL kinds to the reviewer: INTERNAL TALK (hub / system / search / "let me check our…"), UNSUPPORTED CUSTOM (what a church or season "wears", "any colour you choose", "comes to the shop" unless they said so), PROMISE-ONLY (a check with no answer when a row answers it). | review.py | C3, C4, C5, C6, C7 | Low. Reviewer tokens +~2k/call, uncached, ~21 calls/day. Tests in test_reply_review.py. |
| **2** | **"Said once" memory**: a Redis set per conversation of facts already sent (set contents by slug, address, payment lines, the Bishop's-set total), filled from each outbound reply. The turn note then says "Already told this customer: Cassock Set contents, KES 60,500 total — refer by name, do not re-list." `search_catalog` adds `already_told: true` on such a set row. | new `app/agent/said_once.py`, runtime.py (turn note), tools.py (one flag) | C2 | Low. Note only, no reply change; cache-safe (rides on the last message). |
| **3** | **Reply-length target, code-computed**: from the customer's message (words, question marks, intent: price ask / yes-no / list request / complaint) derive a target (e.g. ≤25 words for a short ask, ≤60 for a quote, no cap for an order summary or when they asked for detail). Put it in the turn note ("TARGET: at most 25 words") and **record** reply-words vs target per turn (Reports → Pacing already has the table). Record-only for 5–7 days; then, if over-length persists, one cheap trim pass only when a reply is >2× target and contains no list/order summary, keeping every verified figure. | runtime.py, conversation_budget.py (new decision `long`) | C1 | Low in phase 1 (a note). Phase 2 adds a Haiku call on the long tail only. |
| **4** | **Prompt conflicts, targeted edits only (no rewrite)**: (a) move brevity to precedence **#2**; (b) cut the three 50–60-word worked examples (set, photo, first-contact) to ≤25 words so examples match the contract; (c) one line: "Never say hub, system, search, catalogue lookup or 'confirm with the team' to a customer — give the fact or ask the one thing you need"; (d) on THE CHURCH YEAR: "for our planning — never tell a customer what their church 'wears'; a denomination question is answered by asking their preference"; (e) the two "hold/reserve" examples → "Shall I start your order?". | prompt.py | C1, C5, C6 | Low–medium: block 0 changes invalidate the fleet cache once (~2× write on the next turn per conversation, one time). Must re-run the prompt tests. |
| **5** | **Unclaimed human threads**: (a) `escalate_to_human` and the reviewer hold set `intercept_since`; (b) a timer: human + unassigned + latest message inbound for **N minutes** → a second team bell to the super admin naming the chat; (c) *optional, owner's call*: in that state Neema answers only a price/stock question from the hub ("The incense burner is KES 15,000") and says a colleague will follow up on the rest. | runtime.py, auto_release.py or reply_sweeper.py | C8 | (a)(b) low. (c) medium: it speaks into a human-held chat; needs a clear rule and the team told. |
| **6** | **Double-reply guards**: `agent:inflight:{ch}:{key}` set for the life of `_run_and_send`; the sweeper skips a thread whose key is set; `_run_and_send(_meta)` re-reads `intercept_mode` just before sending. | runtime.py, reply_sweeper.py | C9 | Low. |
| **7** | **Hub data (owner)**: Cassock Set → 21,000; price the Bishops Collar; decide whether "Ring" should be renamed so "Bishop's ring" resolves to the 4,000 row. | hub admin | C10 | None in code. |
| **8** | Minor: `learned_rules` cap keeps the **newest** text; `remember` tool rejects facts that contain a money figure; cart total re-priced from the hub at `get_cart` time. Dead n8n code and stale docstrings removed in a separate, no-behaviour PR. | crm.py, tools.py, cart.py | B, C11 | Low. |

**Not proposed:** a new agent, a new service, a separate "length model", or a wholesale prompt rewrite now. The 93k-char prompt should shrink later (the cost case is real: ~23k tokens of rules on every call), but only after items 1–4 show their effect in the measurements, and with a replay comparison first.

---

## E. Compatibility

- No API, schema or webhook payload changes except: one optional field (`already_told`) on a `search_catalog` row; one new Redis key family; one optional `PacingEvent.decision` value (`long`). Existing clients ignore all three.
- The debounce, voice-note and image paths are untouched; the changes sit in the gate (after the draft) and in turn notes (after history), so the cached prefix is unchanged except for item 4.
- Item 4 is the only change to the shared cached system block; it invalidates the fleet cache once.
- Rollback for every item is a revert; nothing migrates data.

---

## F. Testing plan (Phase 6)

**Baseline first.** `app/jobs/agent_eval.py` already runs scripted conversations through the real pipeline against throwaway contacts and deletes them. I will:
1. Add Mama Beth's conversation as a scripted scenario (anonymised; stops before any order) plus 6 more: short price ask, yes/no follow-up, "what's in the set" asked twice, Swahili bargain, denomination colour question, off-topic chat, a correction ("I mean rod").
2. Run it **before** any change and record per turn: words, sentences, questions asked, facts repeated, prices vs hub, reviewer outcome, tokens, latency.
3. Apply items 1–4, re-run, compare. Acceptance: median reply ≤ 25 words on short asks; zero re-lists of set contents after the first; zero "hub/system" words; all prices equal hub rows; first-draft pass ≥ 60%; no scenario loses a close that the baseline had.
4. Unit tests for each item (reviewer kinds, said-once, length target, inflight lock, intercept_since).

**Constraint:** this session has **no model API key**, so the live replay must run on the box (`docker compose … exec -T api python -m app.jobs.agent_eval`) or with a key you provide for a staging run. Everything else (unit tests, the full suite, Android, web) runs here as usual.

---

## G. Performance expectations (to be measured, not promised)

- Items 1 and 3 should cut output tokens per customer reply by roughly half on short asks and reduce rewrites (each a second ~47k-token call). Item 1 widens the reviewer's input by ~2k tokens per call (uncached, Haiku 4.5 / Sonnet 5: cents per day).
- Item 4 costs one fleet-wide cache rewrite. Item 2 adds ≤ 40 tokens per turn.
- The real cost lever remains the 23k-token rules block re-read every call; that is the later, staged rewrite with a replay comparison.

---

## H. Deployment readiness, approvals and rollback

- **Approval needed before coding:** go/no-go on items 1–6 and 8; for item 5(c) whether Neema may answer factual asks in an unclaimed human chat, and the N minutes for 5(b).
- **Owner actions independent of code:** item 7 (hub), and decide whether the Sunday house-voice block should stay automatic (its content is unknown to me; it can be read in Settings).
- **Rollback:** each item is a separate commit on one PR; any can be reverted alone. Nothing changes stored data.
- **Deployment:** per standing rule, merge when green and deploy; the two APKs follow (the Android app is unaffected by items 1–6, 8).
