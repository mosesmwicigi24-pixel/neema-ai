# Neema calling vs the platform today (2026-09-27)

Source of truth for the platform: `docs/research/META_CALLING_2026-09.md` (official
Meta docs, cited). This file maps each finding onto Neema's code and decides
what to do. Categories: Already Implemented · Needs Improvement · Newly
Available · Beta/Limited · Deprecated · Not Supported.

| # | Capability | Category | Neema today | Decision |
|---|---|---|---|---|
| 1 | User-initiated calls (connect → accept → terminate, first answer wins) | Already Implemented | `admin.py` answer/terminate, `call_log.py`, both clients | Keep |
| 2 | Business-initiated calls (connect with SDP offer) | Already Implemented | `/calls/connect` | Keep; add `biz_opaque_callback_data` (#9) |
| 3 | Free-form `call_permission_request` (inside 24 h window) | Already Implemented | `wa_calling.request_call_permission` | Keep for in-window |
| 4 | **Permission request as a TEMPLATE, outside the 24 h window** | Newly Available (to us) | Not used: outside the window our request fails, so "Send call request" silently can't work for anyone who hasn't messaged in 24 h | **Add**: pick free-form vs template by window; template create/status endpoint |
| 5 | **`GET /<PNID>/call_permissions`** (status, expiry, can request / can call, limit counters) | Newly Available (to us) | We guess from our own redis store (`unknown` until we see a reply) — a self-made restriction: agents are told to "send a call request" to customers who already allowed calls from their business profile or by calling us | **Use Meta's answer as the truth**, cache briefly, fall back to our store |
| 6 | Request limits 1/24 h, 2/7 d (reset by any connected call); 138009 | Needs Improvement | Agent can tap "Send call request" into a guaranteed failure | Show "you can ask again {time}" from the limit counters |
| 7 | Permanent permission (2025-11-03), profile grants, auto-revoke after 4 unanswered | Needs Improvement | Stored `permanent` flag but the UI never says it; no unanswered-streak awareness | Say "Allowed permanently / until {date}"; warn after 2 unanswered / rejected calls |
| 8 | Callback permission (`callback_permission_status`): a customer who calls us grants 7-day permission | Newly Available (to us) | Not configurable from Neema | **Add** calling-settings endpoint + card (status, callback permission, call hours, voicemail) — owner decides to switch on |
| 9 | Business-initiated call status webhooks RINGING / ACCEPTED / REJECTED + `biz_opaque_callback_data` | Needs Improvement | Ignored: we say "Ringing…" as soon as Meta accepts the request (the phone may not ring yet) and learn of a rejection only at terminate | Handle statuses: "Calling…" → "Ringing…" on RINGING; REJECTED → "{First} declined" at once; opaque data correlates the row |
| 10 | Full calling error table (138000–138023, 613, 131026, 131009, 190 token) | Needs Improvement | 7 codes mapped | Map all with the next action (retry / request / wait / admin) |
| 11 | Graph API v21.0 expires 2027-01-21; v20 already expired | Deprecated (soon) | `waba_api_version = v21.0` for everything | Calling endpoints on a supported current version (`waba_calling_api_version`, v23.0 = runway to 2027-10); selfcheck warns 90 days before any configured version expires. Messaging version bump left to a deliberate, tested change |
| 12 | Meta recording + transcription per call (2026-06-30, free, Swahili, speaker-separated) | Newly Available | Browser/phone records a mixed file; self-hosted Whisper is **off by default**, so production likely has no transcripts and no insights | **Add** opt-in (setting, default off — Meta speaks a recording announcement to the customer, the owner must choose it); handle `call_transcription_available` / `call_recording_available` into the existing insights pipeline |
| 13 | Voicemail GA (2026-06-25): arrives as an audio message whose id is the WACID | Newly Available | Voicemail audio would land in chat unlinked to the call | Link voicemail to its call (Calls view "Voicemail", thread pill) + settings toggle |
| 14 | 24 h window refreshed by an inbound call (answered or not) | Standard | Window checks look at messages only | Count inbound calls when choosing free-form vs template |
| 15 | Must `terminate` even after RTCP BYE (billing) | Already Implemented | Clients terminate on every local end path | Keep |
| 16 | Messenger Calling API GA (2026-02-11): inbound + outbound WebRTC, permissions, `calling_optin` template, Kenya listed | Newly Available | Our copy says "Messenger doesn't let businesses take calls" — **now false** | **Correct the copy now**; Messenger calling itself = a new channel adapter (see §Messenger below) |
| 17 | Instagram business calling | Not Supported | "Call on WhatsApp instead" sheet | Keep |
| 18 | WhatsApp video / screen share / hold / transfer | Not Supported (planned) | Not offered | Keep not offering |
| 19 | SIP signaling + SIP webhooks, SDES, G.711 | Newly Available (SIP webhooks) | WebRTC via Graph | Not adopted: WebRTC to agents' devices is working; SIP only pays off with a PBX / AI SIP bridge |
| 20 | Conversation Routing, new account model | Newly Available | Single partner (us) | Not needed |
| 21 | Direct Send voice-call button | Beta/Limited | — | Not adopted (beta) |
| 22 | `voice_call` button / `wa.me/call` deep link with payload | Standard | Not used | Add "Call us" deep link generation for follow-ups? — low value; skipped |
| 23 | Meta-hosted AI voice agent | Not Supported | — | Bring-your-own is allowed; OpenAI Realtime SIP is the viable route — a separate project (cost, consent, SIP), not a surgical change |
| 24 | Call quality metrics webhook | Not Supported (WhatsApp) | — | — |
| 25 | `paid_messaging_account_id` → `messaging_account_id` by 2026-12-31 | Deprecated | Not used by Neema | Nothing to do |

## Messenger calling

Messenger now has a business Calling API (inbound + outbound, WebRTC, permission
requests via a `calling_optin` template, `calls` and `call_permission_reply`
page webhooks). Neema already runs Messenger messaging with `pages_messaging`, and
its softphone is plain WebRTC offer/answer — so Messenger calls fit the existing
engine as a second channel adapter, not a redesign.

## Known limits

Found by the adversarial storms in `apps/api/tests/test_calls_adversarial_db.py`
(2026-09-27). Each is a platform limitation, or the price of degrading instead
of failing; nothing here is fixable on our side alone.

- **No exactly-once, no ordering (Meta).** We dedupe per (call, event) in
  redis for an hour and make every handler idempotent on the row. With redis
  down there is no dedup at all: correctness still holds (conditional moves),
  but a redelivered `connect` whose row was lost to a database blip may ring
  the team a second time.
- **Terminate before connect with redis down.** A terminate that beats its
  `connect` is parked in redis. With redis unavailable it can't be parked, so
  the late `connect` rings a call that is already over until the 2-minute
  stale sweep closes it (missed).
- **Answer lock without redis is per-row.** When redis is down the answer
  lock is a conditional update on the ringing row (still one `accept` across
  workers). If the database is ALSO down (no row to claim) it falls back to a
  per-process claim — two API workers could then both reach Meta; Meta
  accepts only the first (the second gets an error the agent sees as 502).
- **Decline vs. Meta's terminate without redis.** The "this was a decline"
  intent lives in the redis lock; with redis down, a Meta terminate that beats
  our own bookkeeping logs the call `missed` instead of `declined`.
- **A caller hanging up exactly as an agent answers.** Meta can accept our
  answer and end the call in the same instant. We log what Meta reports
  (`completed` when its terminate carries a duration, the agent kept on the
  row) and the phone gets 410 — the agent may have heard nothing.
- **Accept timeout is Meta's (30–60 s WhatsApp, 60 s Messenger).** A slow
  network between the agent's phone and us can lose the call; the phone gets
  a 502 / 410 with the reason. Nothing we can extend.
- **Permission request limits.** WhatsApp: 1 a day / 2 a week per customer;
  after a request we send, Neema blocks a second one for 24 h without asking
  Meta. Requests made outside Neema (another tool on the same number) are only
  known from Meta's `call_permissions` counters (cached ~60 s). Messenger
  gives usage but no reset time, so `request_available_at` stays null there.
- **Missed-call message cooldown without redis** is per process: two API
  workers could each send one (at most one per worker per cooldown).
- **A transcription stuck `processing`** (the worker died mid-analysis) is not
  re-claimed by a later Meta event; an agent's Transcribe (own recording) or a
  manual fix is needed. Meta sends the transcription event once per call.

