# WhatsApp Voice Calling in Neema — build plan

**Decision:** human agent answers in the Neema dashboard (WebRTC softphone),
built **direct on the WhatsApp Cloud API** (no BSP). Voice only (Meta lists
video/screen-share as "in development"). Messenger has **no** business calling
API — Messenger callers get offered a WhatsApp call-back instead.

## The good news from Meta's actual API
The media path is **browser ↔ Meta directly** (WebRTC: ICE + DTLS + SRTP). Our
server is only a **signaling relay** — it never carries audio. So we do NOT need
an SFU/media server. We need:
- our API as the signaling endpoint (relay SDP + ICE over our existing WebSocket),
- a **TURN server** (self-hosted `coturn`) for NAT traversal,
- a WebRTC softphone in the dashboard (the agent's browser is the media endpoint).

## Exact API contract (verified against Meta docs, 2026-07)
Inbound call → webhook `field: "calls"`, `event: "connect"`, carries the caller's
**SDP offer**:
```json
{ "object":"whatsapp_business_account",
  "entry":[{ "changes":[{ "field":"calls", "value":{
    "metadata":{"phone_number_id":"...","display_phone_number":"..."},
    "calls":[{ "id":"wacid...", "event":"connect", "from":"<user>", "to":"<biz>",
               "session":{"sdp_type":"offer","sdp":"<RFC8866 SDP>"} }] }}]}]}
```
Accept: `POST /<PHONE_NUMBER_ID>/calls` with our **SDP answer**:
```json
{ "messaging_product":"whatsapp", "call_id":"wacid...",
  "action":"pre_accept",          // then "accept" — pre_accept first avoids audio clipping
  "session":{"sdp_type":"answer","sdp":"<our answer>"} }
```
Hang up: same endpoint, `"action":"terminate"`. A `event:"terminate"` webhook
returns duration + status.

## Prerequisites — GATES (mostly Moses / infra, before any of this can run)
1. **Daily messaging limit ≥ 2,000 unique recipients** on +254 785 490 805. Meta
   requires this tier before calling can be enabled. Check WhatsApp Manager →
   Phone numbers → messaging limit. (Grows with volume + quality; may need time.)
2. **Enable Calling** on the number: WhatsApp Manager → the number → Calling →
   enable + accept calling terms.
3. **Subscribe the `calls` webhook field.**
4. **Webhook routing:** WhatsApp inbound currently flows WABA → **n8n** → our API.
   Call signaling is real-time and must NOT detour through n8n. Repoint the WABA
   webhook to our API directly (our API forwards `messages` to n8n if still
   needed, handles `calls` itself), OR have n8n forward `calls` with minimal
   latency. Direct-to-us is strongly preferred.
5. **TURN server**: stand up `coturn` (a VPS box + a domain/IP + TLS). Modest
   resources; needed for reliable media across mobile networks.

## Phased build
- **Phase 0 — signaling proof** (testable only after gates 1-4): `calls` webhook
  handler on our API — parse `connect`/`terminate`, create a Call record, WS-
  broadcast "incoming call" to the dashboard. No audio yet. Proves the pipe.
- **Phase 1 — the softphone (the product):** dashboard WebRTC client. Incoming
  call rings in the inbox; agent clicks Answer → browser builds the SDP answer →
  our API relays it to Meta (pre_accept → accept) → audio flows browser↔customer.
  Mute / hang up / call timer / call logged on the customer's timeline.
  Buildable/testable against a **local mock** (loopback offer/answer) BEFORE the
  Meta gates clear — so it's ready the moment calling turns on.
- **Phase 2 — Messenger bridge:** a Messenger caller can't be answered via API,
  so Neema offers a WhatsApp call-back (reuses the Invite-to-WhatsApp flow).
- **Phase 3 (optional, large):** AI voice — STT → agent brain → TTS as the answerer.

## Cost / effort reality
- Weeks, not days. Real-time voice + WebRTC + call-state is a different class of
  work than messaging.
- Ongoing cost: TURN bandwidth (self-hosted = VPS + egress). Meta may bill
  per-minute for calls — confirm current WhatsApp calling pricing in the WABA.
- The 2,000-daily-limit gate is the practical blocker to even begin live testing.

## What can start NOW (no Meta gate)
Phase 1's softphone UI + signaling can be built and tested against a local
loopback mock, so it's production-ready before calling is enabled. That's the
recommended first slice while the messaging limit grows toward 2,000.
