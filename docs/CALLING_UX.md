# Neema calling — the UX contract (web + Android)

Owner brief (2026-09-26): calling must feel instant, obvious, reliable, native and
effortless from the moment a call arrives until the call, the follow-up and the
customer interaction are completely finished. If an agent has to think about
what to press, wonder what state the call is in, or recover from an unclear
screen, it is not finished.

This file is the single contract both clients implement. The server side is
`apps/api/app/services/call_log.py` (statuses + events) and the `/admin/calls*`
routes in `apps/api/app/routers/admin.py`.

## 1. What the platforms actually support (never promise more)

| Channel   | Take a customer's call | Call a customer | Notes |
|-----------|------------------------|-----------------|-------|
| WhatsApp  | Yes (Cloud API calling) | Yes, once they allowed calls (`call_permission_request`) | Voice only. No video, no transfer, no hold, no conference in the API. |
| Messenger | Yes, via the Messenger Calling API **when enabled** (`messenger_calling_enabled`) | Yes, once they tapped Accept on our call request (`calling_optin`) | Voice only here: the API has video, but we never offer it. No transfer, hold or conference. |
| Instagram | **No** business calling API | **No** | Offer a WhatsApp call instead (their number if we have it, else ask for it). |

Which channels can call right now comes from the server (`channels` in
`GET /calls/ice-config`, or `GET /calls/channels`). Never offer a call it says
can't be placed. When Messenger calling is off, a Messenger conversation keeps
the old entry point: "Messenger calling isn't on — call {first name} on WhatsApp
instead". Instagram always gets that entry point, styled in Instagram's look.
Never show a video button, a transfer button, a hold button, or an
"end-to-end encrypted" claim. The incoming card's status line names the
platform: "WhatsApp voice call" or "Messenger voice call".

## 2. Server contract (what the clients read)

Call row (`GET /admin/calls`, `GET /admin/calls/{call_id}`, `call_update.call`):
```
id, call_id, wa_id, external_id, name, person_id, conversation_id,
channel ("whatsapp" | "messenger"),
direction (inbound|outbound), status, duration, agent_id, agent_name,
started_at, answered_at, ended_at, summary, insights, transcript_status
(none|recorded|pending|processing|done|failed), has_recording,
follow_up_open, follow_up_done_at
```
`status`: ringing · answered · completed · missed · declined · callback ·
no_answer · rejected · cancelled · failed. (`ended` never appears — the server
maps it. `rejected` and `has_voicemail`: see §2.1.)
`insights` (may be null): intent, products[], objections[], commitments[],
next_action, follow_up_message, sentiment.

Query: `GET /admin/calls?wa_id=…` (one WhatsApp customer), `?psid=…` (one
Messenger customer), `?channel=whatsapp|messenger`, `?view=follow_up` (open
missed / callback calls), `limit`.

Other routes: `GET /calls/ice-config` → `{ice_servers, record, transcribe,
auto_transcribe}` · `GET /calls/permission?wa_id=` → `{status: granted |
denied | requested | unknown, expires_at, permanent}` · `POST
/calls/request-permission {to}` → `{permission}` · `POST /calls/{id}/answer
{sdp}` (409 "call already answered by {name}", 410 "This call has already
ended.") · `POST /calls/{id}/terminate` → `{outcome}` (declined when it was
ringing inbound, cancelled when it was our ringing outbound call, completed when
live) · `POST /calls/{id}/callback` · `POST /calls/{id}/follow-up-done` ·
`POST /calls/connect {to, sdp, name}` (409 = no permission, 502 detail = a
reason the agent can act on) · recording upload / transcript / transcribe as
before (transcript now also carries `insights`).

Live events (`ws:channel:calls`, reach every signed-in agent):
- `incoming_call {call_id, from, name, at, channel}` — ring now
- `call_answered {call_id, agent_id, agent_name, direction}` — someone
  answered (for an outbound call: the customer answered)
- `outbound_answer {call_id, sdp}` — the customer's SDP answer to OUR call
- `call_ended {call_id, outcome, status (Meta raw), duration, direction,
  agent_id, agent_name}` — `outcome` is one of the statuses above
- `call_update {call}` — a row changed (logged, recording, transcript,
  insights, follow-up)
- `call_permission {wa_id, status, expires_at, permanent}`

Ordering (Meta doesn't promise it): a `terminate` that arrives before its
`connect` is parked and applied when the row is written — the call is logged
(missed) and never rings; a `connect` for a call already logged (a late
redelivery) never rings again; the customer's answer / Meta's terminate that
beat `/calls/connect`'s outbound row are applied the moment the row lands. A
call still `ringing` after 2 min is closed (missed / no_answer) whenever the
Calls list or a single row is read — only `ringing` rows, never a live call.

The thread (`GET /conversations/{id}/messages`, first page) now includes
`system_event` items with `event_kind: "call"`, `text` (the label), `agent_name`,
`event_reason` (the summary) and `call` (the full row).

### 2.0 Messenger calls (the second channel — all additive)

Shapes from Meta: `docs/research/META_CALLING_2026-09.md` §7a. A Messenger row
has `channel: "messenger"`, `wa_id: null`, `external_id` = the customer's PSID
(for WhatsApp rows `external_id` = `wa_id`). `conversation_id` is their
Messenger conversation. The call shows in that thread like any other. Statuses,
outcomes, follow-ups, multi-agent rules and the wrap-up table are the same as
WhatsApp. One exception: Messenger has no "declined" status for our call, so a
declined outbound call reads `no_answer`.

**The SDP is the other way round.** Meta sends no offer with a Messenger call.
- `GET /calls/{id}/offer` → `{sdp: null, channel: "messenger", offer_required:
  true, from}`. The phone creates the **offer** itself.
- `POST /calls/{id}/answer {sdp: <offer>}` → `{ok, call_id, channel, sdp:
  <Meta's answer>, sdp_type: "answer", renegotiation: <offer | null>}`. Apply
  `sdp` as the remote answer. Then, if `renegotiation` is set, apply it as a
  remote offer and create a local answer. The 409 (answered by {name}) and
  410 (already ended) rules are the same. Meta gives 60 s to accept.
- `terminate` / `callback` work as before. On a ringing inbound call the
  server sends Meta `reject`, otherwise `terminate`.

**Placing a Messenger call.**
- `POST /calls/connect {channel: "messenger", psid, sdp: <offer>, name?}` →
  `{ok, call_id, channel, sdp: <Meta's answer>, sdp_type: "answer",
  renegotiation}`. The answer arrives at once, not over the socket.
- 409 `code: "no_permission"`, `action: "request_permission"` when they
  haven't allowed calls. The server checks with Meta first and never rings them
  in that case.
- The call then moves on the same events as WhatsApp: `call_status {ringing}`,
  `call_answered` (the customer accepted), `call_ended`.
- Plus a new event, `media_update {call_id, channel, version, sdp_type:
  "offer", sdp}`: the customer picked up, or changed media. Apply the offer
  with the highest `version` and create a local answer.

**Permission (Messenger).**
- `GET /calls/permission?channel=messenger&psid=` has the same fields as
  WhatsApp, plus `channel` and `external_id`, with `wa_id: null`. It is
  Meta's `messenger_call_permissions` merged with our store.
- `POST /calls/request-permission {channel: "messenger", psid}` sends Meta's
  `calling_optin` request (Accept / Decline buttons) →
  `{permission, route: "calling_optin"}`.
- 409 `request_limit` (`wait`): Messenger allows 2 requests per thread per day.
- 409 `outside_window` (`none`): more than 24 h since their last message.
- The answer arrives as `call_permission {channel: "messenger", external_id,
  status: granted | denied, expires_at}`. A grant lasts 7 days, and a
  connected call or a missed inbound call also grants it.

**Events** carry `channel` for Messenger: `incoming_call {…, channel:
"messenger", from: <psid>, external_id, name: null}`. The name follows in the
next `call_update.call.name`, from the linked person. `call_ended` also
carries `channel`.

**The switch.** With `messenger_calling_enabled` off:
- Messenger call webhooks are only logged. Nobody is rung.
- Every Messenger action (`offer`, `answer`, `terminate`, `callback`,
  `connect`, `request-permission`, `permission`) returns 409
  `code: "messenger_calling_off"`, `action: "none"`.
- `channels.messenger` says `inbound: false, outbound: false`.

`GET /calls/channels` (also `channels` in `ice-config`) returns:
```
{whatsapp:  {inbound, outbound, video: false, sdp: "answer"},
 messenger: {inbound, outbound, video: false, sdp: "offer"},
 instagram: {inbound: false, outbound: false, video: false}}
```

Messenger error codes use the same `{detail, code, action}` shape:

| `code` | Meaning | `action` |
|---|---|---|
| `2018389` | Page not allowlisted | `admin` |
| `2018390` | Call no longer available | `none` |
| `2018391`, `2018392` | Bad offer | `retry` |
| `2018393`, `2018394` | Wrong Page | `admin` |
| `2018395`, `2018396` | Call already ended | `none` |
| `190` | Page token expired | `admin` |
| `4`, `613` | Rate limited | `wait` |

### 2.1 Additions (2026-09-27 platform refresh — all additive)

Source: `docs/research/META_CALLING_2026-09.md`, decisions in
`docs/research/NEEMA_CALLING_GAPS.md`. Nothing above changed meaning.

**New status `rejected`** (outbound): the customer declined our call (Meta's
REJECTED status). Terminal, not a follow-up. Wrap-up: "{First} declined" ·
**Message** · Call again later · Done. `no_answer` stays "didn't pick up".

**Call row** gains `has_voicemail` (bool) — WhatsApp voicemail for this call
arrived (the audio is also in the chat as a normal message). Calls view:
"Voicemail" badge; thread pill: "Missed call · voicemail".

**Refusals from calling routes** (connect, answer, terminate,
request-permission, settings, permission-template): body
`{detail, code, action, …}` + header `X-Neema-Reason: <code>`. `detail` is
still the sentence to show. `code` = Meta's error code as a string
(`"138006"`, `"190"`, …) or ours (`template_required`, `meta_unavailable`,
`rate_limited`, `not_configured`, `unknown`). `action` = what to offer:
`retry` (Try again) · `request_permission` (Send call request) · `wait` (show
when, if a time is given) · `admin` (tell them an admin must act; no retry
button) · `none` (Message instead). An expired token is `code "190"`,
`action "admin"`: "WhatsApp access token expired — an admin must renew it".
Connect and answer are never retried by the server (a duplicate would place
a second call) — the client's Try again is the only retry.

**`GET /calls/permission?wa_id=`** now returns (old fields unchanged):
```
wa_id, status (granted | denied | requested | unknown), expires_at, permanent,
meta_status (no_permission | temporary | permanent | null when Meta was unreachable),
can_call, can_request, request_available_at (ISO or null),
calls_left_today (int or null), revoked (bool), unanswered_streak (int),
source (meta | store)
```
Meta's answer is the truth (cached ~60 s). `requested` = we asked in the last
7 days and they haven't answered; `denied` = they declined (or `revoked:
true` — WhatsApp removed it after 4 unanswered calls). Show "Allowed
permanently" / "Allowed until {expires_at}". When `can_request` is false show
"You can ask again {request_available_at}" instead of the Send button. When
`unanswered_streak ≥ 2` warn before calling: "{First} hasn't answered your
last {n} calls — another unanswered call and WhatsApp may stop you calling
them" (WhatsApp revokes at 4).

**`POST /calls/request-permission {to, name?}`** → `{permission, route:
free_form | template, already_permitted?}`. Inside the 24 h window (their last
WhatsApp message or inbound call, answered or not) it is the free-form
request, outside it the approved template. 409 `code: template_required`,
`action: admin` when outside the window and no template exists ("{First}
hasn't messaged in 24 hours — WhatsApp only allows a call request by
template then. An admin can create it in Settings → WhatsApp calling.").
409 `code: "138009"`, `action: wait`, `request_available_at` when the
1-a-day / 2-a-week limit is hit. `already_permitted: true` (200, permission
granted permanent) = they already allowed calls permanently — show Call now.

**Admin (`manage_settings`)**:
- `GET /calls/permission-template` → `{configured, name, language, source
  (env | app), waba_configured, exists, status (approved | pending | rejected
  | … | null), category, error?}`; `POST /calls/permission-template {name?,
  language?, body_text?}` (body needs exactly one `{{1}}` = first name) →
  `{name, language, id, status: "pending"}`. Meta reviews it; requests use
  it as soon as it is approved.
- `GET /calls/settings` → `{status, call_icon_visibility,
  callback_permission_status, call_hours {status, timezone_id,
  weekly_operating_hours[], holiday_schedule[{date, start_time, end_time}]},
  voicemail {status, triggers[], timeout_seconds}, restrictions[] (read-only),
  last_settings_event, last_restriction_event}`.
  `POST /calls/settings` with only the fields to change → `{ok, sent,
  settings}`. `call_hours` / `voicemail` are merged over the current ones (the
  holiday schedule is always re-sent — WhatsApp deletes it when omitted); if
  the current settings can't be read nothing is written (503, `retry`).
  Changes can take up to 7 days to reach customers' phones.

**`GET /calls/ice-config`** adds `meta_transcription` (bool): WhatsApp
transcribes the call itself — after a call say "Summary in a minute" even
when nothing was recorded on this device. (When on, WhatsApp plays a short
recording announcement to the customer.)

**New live events** (`ws:channel:calls`):
- `call_status {call_id, status: "ringing"}` — our outbound call is ringing
  on the customer's phone: `placing` ("Calling…") → `ringing_out`
  ("Ringing…") on this event, not before.
- `call_ended` may carry `outcome: "rejected"` (and a `no_answer` may be
  corrected to `rejected` a moment later — take the latest).
- `call_permission` adds `revoked` (bool) and `reason: "automatic"` on an
  automatic revoke.
- `call_settings {value, at}` — Meta says calling settings changed.
- `calling_restricted {event, reasons[], value, at}` — Meta flagged or
  restricted calling (low quality / low pickup / call button hidden): show an
  admin banner; business-initiated calls may fail until it lifts (7 days).
- `call_update` also fires when a voicemail is linked and when WhatsApp's
  transcript / recording lands.

## 3. Client call phases

```
idle
incoming      ringing this device (inbound)
placing       outbound: building the offer / asking Meta ("Calling…")
ringing_out   outbound: Meta is ringing the customer ("Ringing…")
connecting    answered here, media not flowing yet ("Connecting…")
active        media flowing (timer runs from answered moment)
reconnecting  media path dropped; ICE has ≤ 10 s to recover ("Reconnecting…")
ending        hang-up sent ("Ending…") — never more than a moment
ended         wrap-up card with the outcome + next actions (below)
```
Rules:
- Exactly one phase at a time; the label on screen is always the phase's own
  words (table below). The timer shows only in `active` / `reconnecting`, and
  never counts while nothing is connected.
- A new `incoming_call` while in `ended` replaces the wrap-up at once. While a
  call is live, a second incoming call does not take over the screen: show a
  compact "Grace is also calling" banner with Decline / Call back later (the API
  has no hold, so answering it would mean hanging up — offer "End & answer").
- Every network call that can fail maps to a phase with a next action.

| Phase / outcome | Title (who) | Status line | Primary actions |
|---|---|---|---|
| incoming | Name (or +number) | "WhatsApp voice call" (or "Messenger voice call") + "Incoming…" | Decline · **Answer** · "Call back later" (text button) |
| placing | Name | "Calling…" | Mute · End |
| ringing_out | Name | "Ringing…" | Mute · End |
| connecting | Name | "Connecting…" | Mute · Audio · End |
| active | Name | mm:ss (+ "● Recording" when a recording is actually running) | Mute · Audio · Chat · Minimise · End |
| reconnecting | Name | "Reconnecting…" (amber, not colour-only: icon + text) | same as active |
| ended · completed | Name | "Call ended · 4:12" | **Open chat** · Call again · Done |
| ended · answered elsewhere | Name | "Answered by Ann" | Done (auto-closes after 4 s) |
| ended · declined (by me) | Name | "Call declined" | Message · Done |
| ended · missed (caller gave up while ringing) | Name | "Missed call" | **Call back** · Message · Done |
| ended · callback | Name | "Saved to call back — find it under Calls" | Done |
| ended · no_answer | Name | "No answer" | **Call again** · Message · Done |
| ended · cancelled | Name | "Call cancelled" | Done (auto-closes after 2 s) |
| ended · connection lost | Name | "Call dropped · 2:13 — the connection was lost" | **Call again** · Open chat · Done |
| ended · failed / unavailable | Name | the server's reason | Try again · Message · Done |
| ended · permission needed | Name | "{First} hasn't allowed WhatsApp calls yet" | **Send call request** · Message · Cancel |
| ended · permission requested | Name | "Call request sent — you'll be told when {first} taps Allow" | Message · Done |
| ended · mic blocked | Name | "Microphone blocked — allow it in settings" | Open settings (Android) / how-to (web) · Done |

"Message" / "Open chat" = go to the customer's WhatsApp conversation
(`conversation_id`), minimising a live call rather than ending it.
Wrap-up cards never auto-close when they carry an action the agent still owes
(missed, no answer, dropped, failed, permission) — only neutral ones do.

When `call_permission` arrives with `status: granted` for a customer an agent
asked, show a toast/banner "{First} allowed calls" with a **Call now** button.

## 4. Multi-agent + resilience rules

- Ringing stops on this device the moment any of these arrive: `call_answered`
  (someone else) → "Answered by {agent_name}"; `call_ended` → the outcome;
  a poll that finds the row not ringing; our own 409 / 410.
- Declining ends the call for the whole team (WhatsApp has no per-agent
  decline) — the Decline button's accessible label says "Decline call".
- After the live socket reconnects, or the app returns to the foreground, a
  device that shows any non-idle phase re-reads `GET /calls/{call_id}` and
  corrects itself (a call that ended while offline shows its real outcome).
- Media drop ("disconnected") → `reconnecting` for up to 10 s, then ended
  "connection lost" + terminate in the background. The UI must never look
  connected while no audio flows (no waveform, timer shows "Reconnecting…").
- Answer with no connection → stay on the incoming card, show "No connection —
  can't answer yet" inline, keep Answer enabled to retry while it still rings.
- Hang-up is instant on this device; the terminate request retries behind it.

## 5. Visual language

One Neema design system; WhatsApp calls look like WhatsApp calls:
- Call surface: WhatsApp dark (`#0B141A` → `#111B21` background, text
  `#E9EDEF`, secondary `#8696A0`), accent WhatsApp green `#25D366` / `#00A884`,
  end/decline red `#EA0038`. Avatar large and centred; name, then the status
  line; controls at the bottom in a rounded bar, round 56–64 px buttons with
  labels under them; Answer is the largest control and sits on the right
  (thumb side), Decline on the left — as in WhatsApp.
- Messenger entry points: Messenger blue `#0084FF` (gradient to `#A033FF`);
  Instagram: `#FEDA75 → #FA7E1E → #D62976 → #962FBF → #4F5BD5`. Used only
  on the "call on WhatsApp instead" sheet and the channel badge.
- Typography: the app's font; name 24–28 px semibold, status 14–15 px, timer
  tabular numerals.
- Touch targets ≥ 48 dp / 44 px everywhere; controls never overlap at 320 px
  width or at 200 % font size; nothing important below the fold on a short
  landscape phone.
- Motion: the ring pulse and connecting spinner only; ≤ 200 ms transitions;
  honour reduced motion (no pulse, no waveform animation). Never block an
  action behind an animation.
- Accessibility: every state is text + icon (never colour alone); status
  changes are announced (aria-live polite / Compose liveRegion); focus lands on
  Answer when a call rings (web); every control has a label; contrast ≥ 4.5:1.

## 6. The minimised call

While a call is placing / ringing_out / connecting / active / reconnecting the
agent can minimise it (and "Chat" does so automatically): a slim bar at the top
of the content area — green dot (amber when reconnecting), name, status/timer,
Mute, End, tap anywhere else to expand. The rest of Neema stays fully usable:
the conversation, the customer panel, orders. The bar never hides a toast or
the composer.

## 7. After the call

- Thread: a centred call pill where the call happened — icon (incoming /
  outgoing / missed), label ("Incoming call · 4:12", "Missed call"), who took
  it, time. If there is a summary: a card under it — summary, next action,
  and (when `insights.follow_up_message`) a "Use as reply" button that puts the
  message in the composer (never sends it).
- Customer panel: a "Calls" section — last calls, open follow-up badge, a
  WhatsApp-green Call button.
- Calls view: All · Follow-ups (count) filter; rows grouped Today / Yesterday /
  date; each row: avatar, name, direction icon + outcome word (coloured AND
  worded), duration, agent, time, one-tap call-back button; tapping a row opens
  its details: customer panel, call timeline (rang → answered by → ended),
  recording state, transcript/summary/insights, Call back · Open chat · Mark
  follow-up done. Loading skeleton, empty ("No calls yet — incoming WhatsApp
  calls ring here"), error ("Couldn't load calls" + Retry), offline states.
- Recording: during the call show "● Recording" only while a recording is
  really running. After: "Recording saved — summary in a minute" (auto),
  "Recording saved — Transcribe from Calls" (manual), or nothing when off.
  Transcript failed → Retry.
