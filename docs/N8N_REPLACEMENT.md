# WhatsApp goes native — retiring n8n

The API now contains a complete in-process replacement for the n8n WhatsApp
pipeline (`app/services/wa_native.py`), gated by one flag. Messenger, Instagram,
Facebook, the web chat, calls and every sweep already ran natively; WhatsApp was
the last channel flowing through n8n.

## What maps to what

| n8n workflow | Native replacement |
|---|---|
| webhook receive + parse | `wa_native.parse_events` — on the raw payload the front door already receives first |
| message persistence (`POST /api/n8n/message`) | the **same** `n8n_bridge.upsert_message` — conversation upsert, profile name + country, previews, broadcasts, video/document escalation are identical by construction |
| message-debounce-buffer | redis token buffer — rapid messages combined for `WHATSAPP_DEBOUNCE_SECONDS` (default 15, the value n8n actually ran) and answered once |
| customer-profile-session-setup → `should_run_ai` → reply | `reconcile_waref` + `runtime.schedule_reply` directly (pause, dedup and human-intercept guards preserved) |
| voice-note-transcription (OpenAI) | `call_transcribe` provider dispatch: faster-whisper when installed (free, private), OpenAI whisper-1 fallback when a key exists — cutover never loses transcription |
| product-image-recognition (GPT-4o) | nothing needed — Claude vision reads the image natively in `run_turn`; the captioner was redundant spend |
| reply-dispatch / conversation-intelligence (Tier 1 brain) | already dormant — `should_run_ai=false` for tier-2 traffic; the Tier 2 agent composes and sends every reply |
| TTS audio replies to voice notes | **deferred deliberately** — voice notes get a text reply; revisit if customers miss it |

## Cutover (one flag)

1. On the box, add to the API `.env`:
   ```
   WHATSAPP_NATIVE=1
   ```
2. Restart the API (or wait for the next deploy pull):
   ```bash
   docker compose -f docker-compose.yml -f docker-compose.vps.yml up -d api
   ```
3. In the n8n editor, **pause** the WhatsApp workflows (main, debounce, profile,
   voice, image recognition). Do not delete them.
4. Send a test message to the business number; confirm the reply arrives and the
   message shows in the inbox. Watch:
   ```bash
   docker compose -f docker-compose.yml -f docker-compose.vps.yml logs -f api | grep -i "wa_native\|neema.agent"
   ```

### Rollback (instant)
Remove `WHATSAPP_NATIVE=1` (or set `0`), restart the API, unpause the n8n
workflows. The forward path is untouched code — behaviour returns to exactly
today's.

### Decommission (after ~a week of clean native running)
- Stop the n8n container (frees its RAM/CPU on the VPS).
- Remove `WHATSAPP_FORWARD_URL` from the API `.env`.
- The `n8n/*.json` exports stay in the repo as the historical record; the
  `Sync n8n workflows` GitHub Action can be disabled.
- Later (once nothing calls them): retire the `/api/n8n/*` endpoints and the
  `N8N_API_SECRET`.

## Why the native path is safe by construction
- **Flag off = byte-identical behaviour** (the forward code path is unchanged).
- **Same persistence function** n8n called — not a re-implementation.
- **Idempotent**: every wamid is processed once (redis `nx` guard), so Meta
  retries never double-reply.
- **Human-intercept, agent-pause and reply-dedup guards** all sit in the shared
  code the native path calls — the same ones the n8n path used.
- Voice transcription **falls back to the same OpenAI engine n8n used**, so the
  worst case at cutover equals today, not worse.

## Decisions from the Phase-0 inventory (node-by-node audit of the live workflows)

Ported exactly:
- **Debounce = 15s** — the value the n8n node actually executed (its names said
  12/30/35; 15 was the parameter that ran). Configurable via
  `WHATSAPP_DEBOUNCE_SECONDS`.
- **Document/file-request escalation** — "send me the price list PDF / brochure /
  katalogi" flips the chat to a human with the same dashboard notification.
  PHOTO requests are NOT escalated: Neema sends product-photo cards herself now.
- **Voice notes**: transcript becomes the Message row's `text` (the dashboard's
  transcription toggle contract) and the agent's turn — same as n8n's ordering.

Fixed rather than replicated (n8n bugs the inventory caught):
- The "new conversation" notification fired on EVERY inbound text (its condition
  referenced a field the API never returns). Native fires it only on genuine
  first contact.
- The n8n notify payloads carried a literal `=` prefix and double-quoted flag
  URLs (expression bugs) — not replicated.

Deliberately dropped (with reasons):
- **TTS audio replies** to voice notes — voice in, text out. Revisit on demand.
- **GPT-4o image captions** — Claude vision reads the photo natively in the
  agent turn; the caption was a Tier-1 crutch (the "Image analysis" toggle in
  the inbox simply shows nothing new for native messages).
- **Per-turn "conversation intelligence" JSON** (mood/closeReadiness/…) — was
  never persisted; shaped only the retired Tier-1 prompt.
- **Per-message session rows** (`/api/n8n/session` wrote turns=1 with a
  per-second session id — effectively meaningless) and the degraded
  customer_history writer (production writes an empty snapshot today).
- **Tier-1's hardcoded payment prompt** (Paybill 542542 etc.) — payments already
  flow through hub checkout links for all tier-2 traffic, which is all traffic.
  If the Paybill should be quotable, add it to BUSINESS_INFO.
- Dead n8n branches (order_update notification, hold-path logging) that never
  executed.

## Notes
- Statuses (delivered/read receipts) are parsed and dropped — parity with n8n.
- Stickers ride the image path (Claude vision can see them).
- The GPT-4o image-captioning spend disappears in native mode.
- Voice transcription needs either `WHISPER_ENABLED=1` (self-hosted) or the
  existing `OPENAI_API_KEY` (whisper-1 fallback — the engine n8n used). The key
  is already on the box, so voice works at cutover with no new config.
