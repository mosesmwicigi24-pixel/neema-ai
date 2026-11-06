# Verified Capability Baseline: what Neema genuinely does today

Written 2026-11-06 for the owner of the Neema AI sales agent. This document consolidates
seven read-only inventories taken the same day (areas A–G below). Nothing in it was
produced by running the agent; where an inventory ran anything it was an offline import of
`app.agent.prompt`/`app.agent.runtime` to measure the assembled prompt (area A) and an
`except`-block sweep over `app/agent` + `app/services` (area E). No test was run, no server
contacted except `GET /api/health` on the production box, and the repository was not changed.

**Tags.** `[C]` = confirmed by reading the cited code at file:line. `[H]` = hypothesis or
inference, not verified. An `[H]` from an inventory is never upgraded here.
**Status words.** OPERATIONAL = code path complete, tested, no flag that defaults off.
PARTIAL = code complete but gated off by default, record-only, or with a known gap.
UNVERIFIED = cannot be judged from code alone (depends on production values, the hub, or a run).
**Paths.** Relative to `apps/api/app/` unless they start with `apps/`, `docs/`, `tests/`
(`apps/api/tests/`) or `web/` (`apps/web/src/`).

Sources: `A-runtime-prompt.md`, `B-tools.md`, `C-commerce.md`, `D-channels-identity.md`,
`E-verification-grounding.md`, `F-memory-state.md`, `G-dashboard-eval-apps.md` (session
scratchpad, `inventory/`), plus the 5 Nov agent audit, the 5 Nov outreach audits and the three
6 Nov execution-verification passes for section 4.

---

## 1. How a message becomes a reply

### 1.1 The common spine — `run_turn` (`agent/runtime.py:1463–2331`) [C]

Every channel ends in the same function. In order (A §2):

1. **Budget breaker** (1497–1508): `ai_budget.guard_turn` raises `DailyBudgetExceeded` at the stop (`ai_daily_stop_usd`=60) and swaps the main model for the light one past `ai_daily_budget_usd`=40. The breaker fails open to "ok" when redis is broken (A 0.7).
2. **Market and identity** (1513–1572): Meta/TikTok → `_meta_market` (USD until evidence; Swahili → KES remembered 30 d under `market:swahili:*`); WhatsApp/web → phone prefix or `User.country_iso`.
3. **Prompt inputs** (1573–1586): DB-stored directives + learned rules + house voice + the running offer → `build_system_prompt` (1587–1593, `agent/prompt.py:98–1711`) with the channel addendum appended to the same string (1594–1599).
4. **Per-customer tail** `customer_context(name, country, promise, clock=True)` (1612; `prompt.py:1714–1747`), later extended with recent phone calls (1650–1655), cross-channel lines (1789–1794) and deal guidance (1813–1820).
5. **History** (1630–1633): the last 40 messages for a DM, 14 for a comment thread, windowed to 40–59 rows by `_window_keep` (901–914, 949–1023); an OVERLAP note if a reply already went out after the rows being answered (1638–1644).
6. **Church-goods guard** (1679–1719): silence, decline (team flagged) or a note. Fails open (1700–1703).
7. **Pacing** (1726–1760): silence, defer, cool close (flag) or economy (light model + note).
8. **Turn notes**: FX line (1765–1774), shared-link preview (1799–1805), customer-state live note (1807–1811), product-interest block (1826–1832).
9. **Images**: image block (1837–1840), photo check shadow/live (1845–1868), current message appended (1869–1894).
10. **Post/ad context** as a *leading* user message, with the post image on first contact (1899–2076).
11. **Memory, LENGTH, ALREADY-TOLD, comment reading** → notes on the last user message (2031–2066).
12. **Tools**: `ToolContext` and the per-channel tool list (2078–2139); `sys_blocks=[system, tail]` (2141); notes attached to the last user message (2143).
13. **Tool loop** (2155–2207): up to `tier2_max_iterations`=8 model calls (4 for comments); every tool call in a response runs sequentially; no text → one `tool_choice: none` nudge, then the stock line `"One moment — let me check on that for you."` (2162–2171); iteration cap → last text, else `_reply_in_words`, else `"Let me get a colleague to help you with this."` (2201–2206).
14. **After the draft**: the gate (2214–2231), photo-refer override (2232–2240), cassock ladder (2244–2262), length record (2265–2270), said-once record (2272–2281), conversation budget (2284–2292), product-interest remember (2304–2310), usage row (2313–2322), lead signals (2327–2330).

Callers of `run_turn`: `_run_and_send` (WhatsApp, 2595–2674), `_run_and_send_meta` (2908–3008), `_run_comment_engage` (5832), the ManyChat and web-chat routers, copilot, the reply sweeper (`bridge`), `actions` (`follow-up`), `hub_events` (`announce`), unclaimed, cart recovery and the eval jobs (A §2) [C].

Models (A §1) [C]: `build_llm` (2333–2350) → `AnthropicLLM(model or tier2_model, max_tokens=4096, cache=tier2_prompt_cache)`. `_model_params` (`agent/llm.py:160–171`): `claude-sonnet-5-5` → `effort="high"`, `claude-haiku-5-5` → `effort="low"`. `route_model` (717–735) sends bare greetings/acks to the light model, everything else and any media to the main one; `route_comment_model` (762–784) defaults comments to the light model. Fallbacks (`llm.py:174–184, 234–247`): sonnet-5-5→sonnet-5, haiku-5-5→haiku-4-5, only on `BadRequestError` or a `refusal` stop reason.

### 1.2 WhatsApp (Cloud API) — OPERATIONAL [C] (D §1)

`POST /api/wa/webhook` (`routers/whatsapp_webhook.py:30–63`). Verify token `WHATSAPP_VERIFY_TOKEN` else `META_VERIFY_TOKEN` (:26–27, 403 when unset :35–37). `X-Hub-Signature-256` HMAC with `WHATSAPP_APP_SECRET` else `META_APP_SECRET` — **returns True (skips) when neither is set, "dev only"** (:44–49). Taps for calls (:221–347), wamid stash (:196–218), call-permission replies (:111–125), voicemail (:128–147), account updates (:162–193) are each best-effort.

`services/wa_native.handle_webhook` (:670–696) → `record_delivery_statuses` first (:678–684) → `parse_events` (:125–187) → `_ingest_one` (:485–520): idempotency keys `wa:native:seen:<wamid>` 24 h (set only after persistence) and `wa:native:inflight:<wamid>` 120 s; a failing ingest releases the guard and the door answers **502** so Meta redelivers (`whatsapp_webhook.py:104–107`). `_ingest_guarded` (:523–666): media download/rehost (:198–236), voice notes queued for transcription (:566–573, :627–628), quote resolution (:580–598), `messaging.upsert_message` (`messaging.py:511–…`; video/document → flag only, thread stays AI :614–640), CTWA ad referral → `users.state.lead_source/ad_ref` (:142–195). Wake rules: `inbound_kinds.describe` — reactions, stickers, system, call_permission, deleted/edited never wake the agent (`services/inbound_kinds.py:38`, `wa_native.py:636–638`).

**Debounce** `wa:native:buf:<wa_id>` + token (:300–345); `_reply_after_debounce` sleeps `WHATSAPP_DEBOUNCE_SECONDS`=30 (`core/config.py:253`) and drains only if its token is still current (:407–420); **no redis → immediate reply, no debounce** (:300–304). **Pre-reply gates** (:421–479): voice-note token; document request → human escalation with `Intercept(intercept)` (:434–437, :369–405); `intercept_mode != ai` → silent + copilot draft (:441–454); `reconcile_waref` (:457–462); blue tick + typing (:266–290, :466–473); then `runtime.schedule_reply` with dedup `native:<wa_id>:<token|text[:32]>` (:475–479).

`schedule_reply` (`runtime.py:2720–2758`): `_is_paused` → `is_opt_out` (the **only** inbound door that recognises an opt-out, 2729–2731 → `_handle_opt_out` 2676–2718) → `closer_gate` (621–714) → dedup `agent:seen:<id>` 600 s (fail-open when redis is down, 2740) → cooling slow lane → `_run_and_send` (2595–2674) under the in-flight lock `agent:inflight:<channel>:<key>` (2529–2575; TTL 240 s, waits ≤120 s then proceeds). After `run_turn`: silence/echo guards (`_is_echo` 2491–2517) → **`_still_ai` just before the send** (2625–2627; re-reads `intercept_mode`, fails open on DB error 2590–2591) → `messaging._send_waba` (:223–240). A thrown turn → `record_turn_failure` + one hold line per 2 h (2660–2669, `_send_hold_line` 2425–2488). An unknown delivery outcome (`SendOutcomeUnknown`, `messaging.py:196–209`) is recorded as `raw_meta.delivery={"status":"unknown"}` and never resent (2628–2640).

### 1.3 Messenger and Instagram DMs — PARTIAL (auto-reply behind `META_AGENT_REPLY`, default False) [C] (D §2)

`POST /api/meta/webhook` (`routers/meta_webhook.py:35–122`); handshake needs `META_VERIFY_TOKEN` (:43–49); `object=instagram` → channel `instagram`, else `messenger` (:101). `_valid_signature` **returns True when `META_APP_SECRET` is unset** (:53–57). `_capture_events` (:225–470) walks `entry[].messaging` or `entry[].standby` (:240), skips `is_echo` (:243) — so a colleague answering from Meta's own Page Inbox is invisible and the thread stays `ai` — captures ad attribution on message-less events then `continue` (:250–263), dedups on `(channel, mid)` (:268–274), enriches the profile (:300–325), resolves the person (:335–340), creates the conversation (:370) and the Message row with `wa_id=None`, `external_id=sender` (:378–389). **One commit per delivery; capture exceptions are swallowed and the webhook still acks 200** (:113–117, :435).

Routing (:412–430): `intercept_mode == ai` with text or image/audio → queued; `human` with text → `copilot.schedule_human_held`; `paused` → nothing. Replies fire **only `if settings.meta_agent_reply`** (:464–470) via `runtime.schedule_meta_reply(dedup_id=mid)` (3010–3064): `_is_paused` → `closer_gate` → dedup `agent:seen:meta:<mid>` 600 s → cooling → burst buffer `agent:burst:buf/tok:<channel>:<ext>` for `META_DEBOUNCE_SECONDS`=12 with "typing…" meanwhile (3047–3055, 3073–3140). **No `is_opt_out` check on this door** [C]. `_run_and_send_meta` (2908–3008) → `run_turn` → `_still_ai` (2951–2953) → `meta_send.send_to_channel` (:613–651; strips markdown; `POST /me/messages` with the Page token in the `Authorization` header, `_graph_post` :35–60; page token per page from `META_PAGE_TOKENS` else `META_PAGE_TOKEN` :25–32). Hitting the 24 h window wall (`is_outside_window` 2767–2773) turns the composed reply into a held draft and sends the thread to a human with a one-tap card (2988–2999, `escalate_to_human` 2796–2843). Meta delivery/read receipts are discarded (:250–263); `raw_meta.delivery` exists only for WhatsApp [C].

### 1.4 Facebook / Instagram public comments — PARTIAL (`META_COMMENT_REPLY` default False) [C] (D §3, A)

Same webhook; `_capture_comment_events` (`meta_webhook.py:719–825`) is inert unless `settings.meta_comment_reply` (:724). Channel `facebook` for Page comments, `instagram` for IG (:733–736); own Page ids skipped (:746–747); dedup `meta:comment:<id>` 7 d (:748–753); post context cached `meta:postctx:v2:<channel>:<post>` 14 d (:618–648); Message row with `waba_msg_id=comment_id` and `comment_context` (:797–808); commit, then `runtime.schedule_comment_engage` (:817–825) — one task per comment, no debounce. `_run_comment_engage` (`runtime.py:5627–6110`) reads intent (`read_comment`, light model, 3934), plans public/DM/human, calls `run_turn(public_comment=True)` (5832) on `route_comment_model` with 12 tools and a 4-iteration cap, posts the public reply through `reply_to_comment` (`meta_send.py:220–241`), which strips every URL/e-mail and country-hedge question (`sanitize_public_comment` :192–217), likes on FB (`like_comment` :244–264, `META_COMMENT_LIKE` default True), and sends the DM opener via `send_private_reply` (:267–281) only if not opted out (5912–5921 — with a synthetic conversation whose `person_id=None`, so only the redis key is consulted). Complaints are flagged, never intercepted (`_route_comment_to_human` 4042–4075).

### 1.5 Web chat (storefront) — OPERATIONAL for the visitor; dashboard reply path not operational [C] (D §4)

`POST /api/web/chat` (`routers/web_chat.py:142–253`), `X-Storefront-Key` vs `STOREFRONT_KEY` (503 unset, 401 bad, :34–41). Identity `wa_id = "web_" + sha1(session_id)[:20]` (:135–139); `User` row (:157–166); **Conversation created with `wa_id=web_…` and no `channel`, so the server default `whatsapp` applies** (:183–191, `models/conversation.py:37`); no `Identity` row unless `?ref=` (:61–95). Takeover checked **once, before the turn** (:198, :212–214) → canned "one of our team will reply"; no `_still_ai`, no copilot draft. `run_turn` (:218; web detected by prefix `runtime.py:1491–1492`); empty reply → "🙏" (:222–223); failure → `_hold_line("web")` + flag per 2 h (:224–244); outbound saved as channel `whatsapp` (:248–249). A dashboard reply on such a conversation goes to `_send_waba("web_…")` and fails (`conversation.py:481–524`; the only `web_` guard is the sweeper skip `reply_sweeper.py:387`).

### 1.6 TikTok — ManyChat relay OPERATIONAL; native PARTIAL [C] (D §5–6)

Relay: `POST /api/manychat/webhook` (`routers/manychat.py:74–198`), `X-ManyChat-Key` (:52–60); steps aside once `tiktok_native.native_live(db)` (:93–95). Identity `(tiktok, subscriber_id)` (:107–113); no dedup. Takeover before the turn → `_HUMAN_LINE` once per 12 h then empty replies (:134–145); `closer_gate` → `run_turn(channel="tiktok")` under `asyncio.wait_for(MANYCHAT_REPLY_BUDGET_S=9.0)` (:151–159); timeout → `_BUDGET_LINE` (:160–170); failure → hold line + flag per 2 h (:171–194). The reply travels only in the HTTP response; `send_to_channel("tiktok")` raises unless native is configured (`meta_send.py:630–641`).
Native: `POST /api/tiktok/webhook/events` (`routers/tiktok_webhook.py:78–98`) **503 when `TIKTOK_APP_SECRET` is unset (fails closed)** (:80–81); `im_receive_msg` → `_receive` (:101–166) → `schedule_meta_reply("tiktok", …)` → the same 12 s burst and `_run_and_send_meta`. The owner typing in the TikTok app is persisted as `sender=human_agent` but `intercept_mode` stays `ai` (:185–193).

### 1.7 SMS — receive-only [C] (D §7)

`POST /api/sms/inbound` (`routers/sms.py:34–87`): 404 until `SMS_INBOUND_TOKEN` set, bearer compared with `!=` (:41–45); identity `(sms, digits)` adopts the WhatsApp person with the same digits (:59, `identity.py:97–101`); conversation **forced to `human`** every time (:63–64). Outbound refused (`conversation.py:629–632`, :900–903). No agent reply ever.

### 1.8 The gate — what every model-composed live reply passes (E §1) [C]

A turn is gated when `reply and not read_only and not scribe_only and _gate_applies(user_text)` (`runtime.py:2215`); `_gate_applies` (1146–1156) is False for empty text and for text starting with `(` or `[` whose first 160 chars match `internal|not a customer message|context —|\bsystem\b`. **The whole gate call is wrapped in `except Exception` → "reply gate failed open" and the ungated draft continues to the send path** (2216–2231).

`review_reply` (`agent/review.py:1387–1425`) merges two layers: **the rules** (`rule_findings` 1047–1150, deterministic — figure, currency, item, where, link, status, variants, colour, internal, promise, payment_line, domain, gift, context, photos; hardness is the `hard` key on each finding, 1401–1402) and **the reviewer** (`reviewer_verdict` 1275–1370; `review_model_main`=`claude-sonnet-5` on money turns per `_MONEY_TURN_RE`, else `review_model_light`=`claude-haiku-4-5`, 1266–1272; window 16 turns × 400 chars, 1253–1254; told "Never fail for tone, warmth, length or emoji", 1347). **The reviewer's findings are always soft** (1398–1401, 1412–1414); only rules can hold. Decision (`_gate_turn_reply` 1323–1460): `pass` (1382–1384); one rewrite with `rewrite_block` (`review.py:1452–1515`, `tool_choice: none`) → `rewritten` (1423–1427); `soft` = the draft with no hard finding and the fewest soft ones, **"the rewrite wins a tie"** (1431–1441); `held` when both drafts carry a hard finding (1442–1460) → `_flag_held_reply` moves the conversation to HUMAN, writes an Intercept flag with the unsent draft, alerts the team once (1202–1237); `held_recently` (6 h NX key, `review.py:1566–1577`) → silence, else `_REVIEW_HOLD_DM(_PRICE)` (1140–1143, 1259–1262); held under a public comment → `""` (1445–1446). Verdicts tallied per UTC day, 3-day TTL (`review.py:1521–1543`).

### 1.9 What reaches the customer without the gate (E §2) [C]

| Path | Composed by | Why it is ungated | Source |
|---|---|---|---|
| Canned comment lines (`_comment_public_reply`, `_OVER_CAP_SELL_POOL`, `_campaign_canned`, low-intent thank-you) | code, priced from the trusted post identity (cheapest variant) | guarded by `identity_trusted`, `is_bare_price_ask`/`_names_product`, `review.item_issues`; no review gate | runtime.py:5944–6031, 5721–5764 |
| **Cassock ladder second message** | code from two hub rows | composed after the gate, never reviewed | runtime.py:2246–2261, 2642–2647, 2967–2971; services/cassock_ladder.py:67–110 |
| Church-goods guard decline/silence | code | returns before the gate | runtime.py:1680–1716; domain.py:479–524 |
| Cooling `cool` line, `silence`/`defer` | code | returns before the gate | runtime.py:1724–1760 |
| **Tool-sent messages mid-turn**: `send_product_cards` (WA cards/album, Meta carousel/photos), `send_measurement_guide` | code, prices via `_to_display` | sent while the loop runs, before the gate reads the draft; cannot be recalled if the reply is later held | tools.py:2663–2890, 3111–3133 |
| Order-confirmation relay `_relay_order_confirmation` (`hub_relay_receipt`) | code | legacy bridge path | services/messaging.py:1005–1016, 924 |
| Hold line `_send_hold_line` | config text, names no product/price | n/a | runtime.py:2385–2488 |
| Opt-out acknowledgement `_handle_opt_out` | code | — | runtime.py:2676–2717 |
| Private complaint message `_private_complaint_message` | code constant | — | runtime.py:3515–3528 |
| **Scheduled follow-ups** `actions._compose_follow_up` → `run_turn(read_only=True)` → `actions._send` | model | `read_only` skips the gate; `_gate_applies` also False (text starts "[SCHEDULED FOLLOW-UP — not a customer message") | services/actions.py:436–458, 509–551, 944–960 |
| Code-composed follow-ups (quote follow-up, payment reminder) | code | figures frozen at planning | actions.py:939–944; quote_followup.py:170–192 |
| Template follow-ups outside the window | approved WhatsApp template | template body | actions.py:390–425, 876–909; templates.py:35,128 |
| **After-sale announcements** `hub_events._compose_announcement` → `run_turn(read_only=True)` → raw send | model | read_only | services/hub_events.py:173–184, 280–298 |
| **Team-answer delivery** `admin.py:1778` → `run_turn(read_only=True)` → raw send | model | read_only, human-triggered | routers/admin.py:1770–1805 |
| Reply-sweeper cross-channel bridge `run_turn(read_only=True)` | model | read_only (send path not read [H]) | services/reply_sweeper.py:120–139 |
| Unclaimed-chat canned `FOLLOW` line (the answer itself is gated) | code | — | services/unclaimed.py:132–145, 184–196 |
| Copilot draft / briefing, admin draft | model | a human sends it | services/copilot.py:58–66, 191–196; routers/admin.py:1643–1651 |
| Human replies and human-approved held drafts | human | by design | services/conversation.py:514/522/825 |
| Missed-call message, recording notice, seasonal outreach | config/code text | — | services/missed_call.py:96–104; recording_notice.py:165–175; jobs/seasonal_outreach.py:262–293 |
| Cart-recovery job `run_turn(read_only=True)` → `actions.plan` | model | the dispatcher sends (row "Scheduled follow-ups") | jobs/cart_recovery.py:170–186, 226–244 |

Gated: WhatsApp live reply (runtime.py:2595–2650), Meta/TikTok DM incl. burst drain (2908–2975), web chat (`web_chat.py:218`), ManyChat (`manychat.py:156`), public comment answer (5833–5856, 6035–6041, 6049–6065; the DM's storefront link is added after the gate, 5905–5932), the `_reply_in_words` fallback (2205–2208), the unclaimed-chat answer (`unclaimed.py:132–145`). Post-gate transforms: `plain_public_voice` on public comment and DM text (`agent/voice.py:92–115`, runtime.py:5695, 5905); `strip_repeated_greeting` on follow-ups (`actions.py:458`).

---
