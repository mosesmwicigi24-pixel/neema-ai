# Meta Business Calling: research brief (as of 2026-09-27)

Scope: the current WhatsApp Business Calling API (Cloud API) and related Meta capabilities, with a focus on what changed from June to September 2026. This brief is meant to be compared against an existing implementation.

Method: I fetched the official Meta developer pages on 2026-09-27. The legacy `/docs/whatsapp/cloud-api/calling` URL now redirects to `/documentation/business-messaging/whatsapp/calling`. For each page I read the rendered HTML, which shows a `lastUpdated` date. Some pages also have a `.md` export. **Warning:** at least two `.md` exports (the FAQ and Direct Send) are older than the HTML, so where the two differed I used the HTML. Every claim below cites a URL; short quotes are in double quotes. Anything I could not verify is marked **unconfirmed**.

Tags: **[Newly Available]** · **[Beta/Limited]** · **[Deprecated]** · **[Not Supported]** · **[Standard]** (unchanged).

Base URL used below: `WA = https://developers.facebook.com/documentation/business-messaging/whatsapp`

Page freshness (HTML `lastUpdated`): overview 2026-06-26 · user-call-permissions 2026-06-26 · business-initiated-calls 2026-06-26 · user-initiated-calls 2026-06-24 · call-settings 2026-07-06 · sip 2026-09-22 · call-recording 2026-08-31 · call-transcription 2026-08-31 · pricing 2026-09-11 · faq 2026-09-16 · integration-patterns 2026-09-16 · troubleshooting 2026-06-24 · reference 2026-06-26 · conversation-routing/calling-webhooks 2026-09-22 · changelog 2026-09-25.

---

## 0. Executive summary: what changed recently

| Date | Change | Tag | Source |
|---|---|---|---|
| 2026-09-23 | Conversation Routing launched. A new "Incoming Call" entry point routes call webhooks and call-permission replies to a configured primary partner. Standby partners receive only `terminate` for business-initiated calls. | Newly Available | [changelog][CHG], [conv-routing calling webhooks][CRW] |
| 2026-09-22 | SIP mTLS clarified. Meta presents a client cert (`client.sip.fbclientcerts.com`) only when it acts as the TLS client. | Newly Available (doc) | [changelog][CHG], [SIP][SIP] |
| 2026-09-22 | New WhatsApp account model (Phase 1 GA). Rollout runs from 2026-09-23 to mid-October 2026. Calling docs now recommend it for splitting messaging and calling partners on one number. | Newly Available | [changelog][CHG], [integration patterns][IP] |
| 2026-09-11 | Calling rate cards effective 2026-10-01 published. 9 markets become standalone; rates are unchanged. | Standard | [pricing][PRC] |
| 2026-08-31 | Known issue: recording and transcripts can be cut short when the user changes networks. | Beta/Limited | [recording][REC] |
| 2026-07-30 | "Call on WhatsApp" voice-call button added to Direct Send, which is itself a beta. | Beta/Limited | [changelog][CHG], [Direct Send][DS] |
| 2026-06-30 | **Call recording and call transcription** launched: per call, opt-in, free for now, with a mandatory spoken announcement. | Newly Available | [changelog][CHG], [REC], [TRN] |
| 2026-06-26 | **SIP call webhooks** added (`webhook_delivery`, `call_created`, `terminate`). | Newly Available | [changelog][CHG], [SIP] |
| 2026-06-25 | **Voicemail GA**. It was alpha on 2026-05-29. | Newly Available | [changelog][CHG], [call settings][CS] |
| 2026-06-16 | `messaging_account_id` added. `paid_messaging_account_id` is deprecated: migrate by 2026-12-31. | Deprecated | [changelog][CHG] |
| 2026-05-28 | BSUID and username fields added to calling webhooks (`to_user_id`, `from_user_id`, `recipient_user_id`, `contacts[].username` and others). | Newly Available | [changelog][CHG] |
| 2026-03-23 | G.711 (PCMA/PCMU) via `audio.additional_codecs`. | Standard (since March) | [overview changelog][OV] |
| 2026-01-27 | Calling restrictions based on user feedback took effect. | Standard | [OV] |
| 2025-12-19 | Business-initiated connected-call limit raised to 100 per 24h per user (from 10). | Standard | [OV] |
| 2025-12-10 | `call_icons.restrict_to_user_countries`. | Standard | [OV] |
| 2025-11-03 | Permanent call permissions. | Standard | [UCP] |

**Graph API:** v20.0 expired on 2026-09-24, three days before this brief. v26.0 is the latest (released 2026-07-29). See §10.

---

## 1. Call permission requests (business-initiated prerequisite)

### 1.1 API shapes today: both free-form and template **[Standard]**
- "You can proactively request a calling permission ... either as a: Free form interactive message [or a] Template message" ([UCP]).
- **Free-form (inside the customer service window):** `POST /<PHONE_NUMBER_ID>/messages` with `"type":"interactive"` and `"interactive":{"type":"call_permission_request","action":{"name":"call_permission_request"},"body":{"text":"..."}}`. The body is optional, and the free-form version does "not support header and footer" ([UCP]).
- **Template (outside the window):** create with `POST /<WABA_ID>/message_templates`, using `"category": "[MARKETING|UTILITY]"` and a component `{"type": "call_permission_request"}` alongside HEADER, BODY and FOOTER. Then send as a normal `"type":"template"`. The docs say "your business can send the template message to the user as a call permission request outside of a customer service window", and "Context (that is, a text body) is required when sending a template message" ([UCP]).
  - **So yes:** a permission request can go out as a MARKETING or UTILITY template outside the 24-hour window.
- **Inside an ordinary marketing or utility template?** The only documented form is a dedicated template whose `components` include `{"type":"call_permission_request"}`, and its category is MARKETING or UTILITY ([UCP]).
  - **Unconfirmed:** whether that component can be combined with other buttons (URL or quick-reply) in the same template. No example or rule was found. Note that a call permission request component is not the same thing as a `voice_call` button.
- "The call permission request interactive object cannot be edited by the business. Only the message body can be customized" ([UCP]).
- Users can be addressed by BSUID with the `recipient` field. If both `to` and `recipient` are sent, `to` wins ([UCP]).
- Charges: "Call permission request messages are subject to messaging charges" ([UCP], [PRC]).
- Errors: sending to an old client version gives "error webhook with error code 131026" ([UCP]). Error `138017` means "a permanent permission already exists" ([TS]).

### 1.2 Limits (per business number and user pair) **[Standard]**
- Permission requests: "Maximum of 1 permission request in 24 hours" and "Maximum 2 permission requests within 7 days". These limits "reset when any connected call (business-initiated/user-initiated) is made" and apply to both free-form and template requests ([UCP]). Exceeding them gives error `138009` ([TS]).
- Connected business-initiated calls: "maximum of 100 connected calls every 24 hours" ([UCP]). Exceeding this gives `138012`, where "Currently 100 connected business initiated calls are allowed within 24 hours" and `error_data` includes when the next call is allowed ([TS]). The limit was raised on 2025-12-19 from 10/day, which itself was raised from 5 on 2025-10-13 ([OV]).
- Separate per-number rate limit: "rate limit of 10000 per 24 hours for initiating new calls per business phone number" ([BIC]).
- Sandbox and public test numbers: 25 requests/day and 100/week; nudge after 5 unanswered calls and revoke after 10 ([OV], [SBX]).
- **Doc conflicts to note:**
  - The `GET call_permissions` sample response shows `start_call` with `max_allowed: 5`, and the field description says "a business can only send 2 permission requests in a 24-hour period". Both contradict the 1/24h request limit and the 100/24h call limit stated elsewhere ([UCP]).
  - The SIP 403 error row still says "Currently 5 connected business initiated calls are allowed within 24 hours" ([TS]).
  - Treat 1/day and 2/week (requests) and 100/day (connected calls) as current, because they appear in the prose, the error table and the calling changelog.

### 1.3 Expiry and permanence **[Standard; permanent since 2025-11-03]**
- Temporary permissions are "granted for 7 calendar days (168 hours)" from approval. "Permanent permissions do not expire, but they have the same connected calls limit" ([UCP]).
- How a user grants permanent permission: by choosing it when replying to a request ("The user can choose between temporary or permanent"), or at any time via the business profile ("Users can review and change calling permission for a business at any time in the business profile") ([UCP]).
- A *request* expires on whichever comes first:
  - the user interacts with a newer request
  - 7 days after the user accepts or declines
  - 7 days after delivery with no response ([UCP])
- "No webhook is sent when a temporary permission expires" ([UCP]).
- Reaching the 24h call limit does not revoke the permission: "permission remains open until the full 7 days ... or permanently" ([FAQ]).

### 1.4 Unanswered and rejected business-initiated calls **[Standard]**
- "2 consecutive unanswered calls result in a system message to reconsider an approved permission" and "4 consecutive unanswered calls result in an approved permission being automatically revoked" ([UCP]).
- The heading reads "When business-initiated calls go unanswered or are rejected", and SIP 486 is described as "Rejected calls impact call permissions". So rejected calls count toward the streak ([UCP], [TS]).

### 1.5 Revocation delivery **[Standard]**
- Auto-revocation after 4 unanswered calls arrives as a `call_permission_reply` with `"response":"reject","response_source":"automatic"` ([UCP]).
- **Unconfirmed:** whether a manual revoke from the business profile produces a webhook. The docs say the webhook fires "whenever a user selects or updates their calling permissions", and show a sample for *granting* permanent permission from the profile, but no sample for revoking from the profile ([UCP]).

### 1.6 Query API: yes, it exists **[Standard]**
- `GET /<PHONE_NUMBER_ID>/call_permissions?user_wa_id=<PHONE>` or `?recipient=<BSUID>` ([UCP]).
- Response:
  - `permission.status`: `no_permission` | `temporary` | `permanent`, plus an expiry that is absent when permanent.
  - `actions[]`: `send_call_permission_request` and `start_call`, each with `can_perform_action`.
  - `limits[]`: `time_period` (ISO 8601, e.g. `PT24H`, `P7D`), `max_allowed`, `current_usage`, `limit_expiration_time`.
- **Field-name conflict:** the sample uses `"expiration_time"` but the parameter table says `expiration`. Code should accept both ([UCP]).
- Rate limit: 100 requests per 1-second window ([UCP]). Error `613` means the fetch-permission API limit was hit ([TS]).
- An uncallable number returns `no_permission` ([UCP]).

### 1.7 Callback (auto) permission when the user calls **[Standard]**
- This requires `callback_permission_status: "ENABLED"` in settings ([CS], [UCP]). "The WhatsApp user automatically provides temporary call permissions by placing a call to the business" ([UCP]).
- The setting "Configure[s] whether a WhatsApp user is prompted with a call permission request after calling your business. Note: The call permission request is triggered by either a missed or connected call" ([CS]).
- Duration: temporary, so 7 days. The sample webhook shows `is_permanent:false` with an `expiration_timestamp` ([UCP]).
- "not supported on companion devices yet" ([UIC]).
- Resulting `context.id` = "Call ID of the missed call ... Shows when callback permission is enabled in settings and the user calls the business" ([UCP]).
  - **Doc ambiguity:** the wording says "missed call placed by the business", but the sample shows a `wacid` for a user-initiated call.
- **Doc ambiguity:** the text suggests the user is "prompted", i.e. shown the permission UI, yet the webhook says `response_source: "automatic"`. Treat the permission as automatic but still user-visible. Exact UX is unconfirmed.

---

## 2. Permission reply webhook **[Standard]**
- It is delivered on the **`messages`** field, not `calls`, as `messages[].interactive.type = "call_permission_reply"` ([UCP], [CRW]).
- If you use Conversation Routing, "subscribe to both calls and messages. A subscription to calls alone does not deliver the permission responses" ([CRW]).
- Fields in `interactive.call_permission_reply`:
  - `response`: `accept` | `reject`
  - `is_permanent`: bool; "For temporary permission this will always be false"
  - `expiration_timestamp`: string, seconds; only when accepted and temporary
  - `response_source`: `user_action` | `automatic` ([UCP])
- Envelope fields: `from`, `from_user_id` (BSUID), `from_parent_user_id` (optional), `id`, `timestamp`, `context.{from,id}`. `context` is absent for profile-initiated grants and for automatic revokes ([UCP]).
- Documented scenarios ([UCP]):
  - temporary accept
  - permanent accept from a request
  - permanent accept from the profile (no `context`)
  - reject
  - automatic callback accept (`context.id` = `wacid…`)
  - automatic revoke (reject/automatic, no `context`)
- No separate "call_permission status" webhook field was found for WhatsApp. **Unconfirmed that none exists.** Messenger does have a dedicated `call_permission_reply` field (see §7).

---

## 3. Business-initiated calls (Graph API signaling)

### 3.1 Connect **[Standard]**
```
POST /<PHONE_NUMBER_ID>/calls
{ "messaging_product":"whatsapp", "to":"<phone>", "recipient":"<BSUID>", "action":"connect",
  "session":{"sdp_type":"offer","sdp":"<RFC 8866 SDP>"}, "biz_opaque_callback_data":"<≤512 chars>",
  "recording":{...optional}, "transcription":{...optional} }
```
- The response is `{"calls":[{"id":"wacid..."}]}` ([BIC]).
- `action` values: "connect | pre_accept | accept | reject | terminate". No other actions are documented, so there is **no hold, transfer, mute or media_update on WhatsApp** ([BIC], [REF]).
- `biz_opaque_callback_data` is at most 512 characters and is echoed in the status and terminate webhooks ([BIC]).
- A reply with `138006` means there is no approved permission ([BIC]).

### 3.2 Webhooks (field `calls`) **[Standard, BSUID fields added 2026-05-28]**
- **Connect:** carries the SDP answer: `event:"connect"`, `direction:"BUSINESS_INITIATED"`, `session.sdp_type:"answer"`. "apply the SDP Answer ... to your WebRTC stack" ([BIC]).
- **Status:** `statuses[].type:"call"`, `status: RINGING | ACCEPTED | REJECTED`, plus `biz_opaque_callback_data`. "The ACCEPTED call status webhook arrives after the call is established ... for call event auditing." On rejection, "You also receive the call terminate webhook" ([BIC]).
- **Terminate:**
  - `status: COMPLETED | FAILED`
  - `start_time`, `end_time` and `duration`, "Only present when the call was picked up"
  - "Even unanswered calls are considered completed"
  - `errors[]` with a calling error code on failure ([BIC])
- Ordering and delivery: "Ordering is not guaranteed" (terminate can arrive before connect) and there is no exactly-once delivery ([FAQ]).
- You must call `terminate` even if you saw an RTCP BYE: "Ending the call this way also ensures pricing is more accurate" ([BIC]).

### 3.3 Ringing timeout (business-initiated)
- **Unconfirmed.** No documented number of seconds before an unanswered business-initiated call ends. SIP returns "480 Temporarily Unavailable — WhatsApp user is not reachable or did not answer" ([TS]).

### 3.4 Calling error codes (WhatsApp) **[Standard]** ([TS])

| Code | Meaning |
|---|---|
| 100 | Invalid parameter, including SDP validation |
| 613 | Fetch call permission API limit (429) |
| 131009 | `voice_call` interactive not supported (sender country) |
| 131030 | Recipient not in allowed list (public test numbers only) |
| 131044 | No valid payment method (user-initiated call error webhook) |
| 131055 | Graph API not allowed for SIP-enabled numbers |
| 138000 | Calling not enabled (401) |
| 138001 | Receiver uncallable (not on WhatsApp, new Terms of Service not accepted, unsupported client) |
| 138002 | Concurrent calls limit (1000) |
| 138003 | Duplicate call |
| 138004 | Connection error (500) |
| 138005 | Call rate limit exceeded (per number) |
| 138006 | No approved call permission |
| 138007 | Connect timeout: SDP not applied in time |
| 138009 | Permission request limit hit |
| 138012 | Business-initiated connected-calls limit (100/24h) |
| 138013 | Business-initiated calling not available (country) |
| 138014 | Calling temporarily disabled (low quality) |
| 138015 | Calling cannot be enabled (needs messaging limit ≥2000) |
| 138017 | Permanent permission already exists |
| 138018 | Technical prerequisites not met (no `calls` subscription and no SIP) |
| 138019 | Call setup failed (terminate webhook) |
| 138020 | Relay connection failed |
| 138021 | Media receive timeout |
| 138022 | Media transmit timeout |
| 138023 | Accepted but no media signals |

- Codes 138008, 138010, 138011 and 138016 are not in the table.
- 138011 is mentioned in the FAQ ("How to avoid 138011 ...") without a definition. Its meaning is **unconfirmed** ([FAQ]).

---

## 4. User-initiated calls, settings, hours, callbacks

### 4.1 Flow **[Standard]**
1. A connect webhook arrives with an SDP **offer** (`direction:"USER_INITIATED"`), optionally with `deeplink_payload` or `cta_payload` ([UIC]).
2. `pre_accept` (recommended) with an SDP answer.
3. `accept` with the same SDP answer, optionally with `biz_opaque_callback_data`, `recording` and `transcription`.
4. Or `reject`, or `terminate` ([UIC], [REC]).

Details:
- "flow the call media only after you receive a 200 OK" from accept ([UIC]).
- The accept SDP must match the pre-accept SDP ([UIC]).
- If media flows early the caller's timer starts, so pre-accept requires control over when media starts ([FAQ]).
- **Timeout:** "about 30 to 60 seconds after the Call Connect webhook is sent for the business to accept ... the call is terminated on the WhatsApp user side with a 'Not Answered' notification and a Terminate Webhook" ([UIC]).
- Supported consumer devices: primary and companion iPhone/Android phones only. WhatsApp Web does not support calls and Desktop is consumer-to-consumer only ([UIC], [FAQ]).
- DTMF follows RFC 4733, "Only 8000 clock rate", and has "no webhook for conveying DTMF digits" ([UIC]).
- Maximum call duration: "There is no call duration limit" ([FAQ]).

### 4.2 Settings endpoint **[Standard + Newly Available: voicemail, audio]** ([CS])
`POST /<PHONE_NUMBER_ID>/settings` and `GET /<PHONE_NUMBER_ID>/settings[?include_sip_credentials=true]`, with a `calling` object:
- `status`: `ENABLED` | `DISABLED`. Calling is off by default and requires a messaging limit ≥2000.
- `call_icon_visibility`: `DEFAULT` | `DISABLE_ALL`. The FAQ also mentions `HIDE_IN_CHAT` ([FAQ]). Hiding icons "does not disable a WhatsApp user's ability to make unsolicited calls" (for example from contacts, call logs, CTAs, or the call bubble) ([CS], [FAQ]).
- `call_icons.restrict_to_user_countries`: ISO country list. It keys on the user's **registered phone-number country**, not their location. `[]` means no restriction. Added 2025-12-10 ([CS], [OV]).
- `call_hours`:
  - `status` and `timezone_id`
  - `weekly_operating_hours[]` (`day_of_week`, `open_time`, `close_time` as "HHMM"; at most 2 per day; no overlaps)
  - `holiday_schedule[]` (up to 20; `date` YYYY-MM-DD, `start_time`, `end_time`). The table says `open_time`/`close_time`, but the samples use `start_time`/`end_time`, which is a doc inconsistency.
  - Omitting `holiday_schedule` deletes the existing one.
  - Outside hours the client offers chat, or a callback request if callback is enabled, and shows the next available slot.
- `callback_permission_status`: `ENABLED` | `DISABLED` (see §1.7).
- `sip`: `status`, `webhook_delivery`, `servers[]` (`hostname`, `port` default 5061, `request_uri_user_params`) (see §5).
- `srtp_key_exchange_protocol`: `DTLS` (default) | `SDES` ([SIP]).
- `audio.additional_codecs`: `["PCMA","PCMU"]`; "Opus is always enabled by default and cannot be removed".
- `voicemail` **[Newly Available, GA 2026-06-25]**:
  - `status`; `triggers` from `REJECT` and `TIMEOUT`
  - `audio.default.announcement_media_id`: audio/ogg Opus, under 60 s, uploaded with `use_case=call_voicemail_announcement`
  - `timeout_seconds`: 0–30
  - "When voicemail is enabled, turn off call hours"
  - The voicemail arrives on the **`messages`** field as an inbound audio message whose `messages[].id` is the **WACID**. It is "best-effort".
- Clients may take "up to 7 days" to reflect config changes ([CS]).
- The `account_settings_update` webhook (since 2025-07-21) tracks changes to `status`, `call_icon_visibility`, `callback_permission_status`, `sip.status` and `srtp_key_exchange_protocol` ([CS]).
- Restrictions:
  - The GET response carries `calling.restrictions.restrictions_list[]` (`RESTRICTED_BUSINESS_INITIATED_CALLING` | `RESTRICTED_USER_INITIATED_CALLING`, with an expiration).
  - `account_update` webhooks send `ACCOUNT_VIOLATION` (`LOW_BUSINESS_INITIATED_CALLING_QUALITY`, `LOW_USER_INITIATED_CALLING_QUALITY`, `USER_INITIATED_CALLS_LOW_PICKUP_RATE`) and `ACCOUNT_RESTRICTION` (`RESTRICTED_USER_INITIATED_CALLING_CALL_BUTTON_HIDDEN`).
  - Pauses last 7 days ([CS]).

### 4.3 Callback requests **[Standard]**
- There is no separate "callback request" API. The callback prompt is driven by `callback_permission_status` together with call hours ([CS]).
- **Unconfirmed:** whether a distinct webhook exists for "user requested a callback", as opposed to the `call_permission_reply` with `response_source:"automatic"`.

### 4.4 Call buttons and deep links **[Standard]** ([CB])
- **Interactive button:** `"type":"voice_call"` with `action.parameters.{display_text (≤20 chars, default "Call Now"), ttl_minutes (1–43200, default 10080), payload (≤512)}`.
- **Template button:** `{"type":"voice_call","text","ttl_minutes"}`. At creation, `ttl_minutes` must be 1440–43200. At send time it can be overridden, and a payload added, via `sub_type:"voice_call"`.
- **Deep link:** `wa.me/call/<NUMBER>?biz_payload=...`, which arrives as `deeplink_payload`. Not supported on desktop.
- Payloads require client version ≥2.25.27.
- **Direct Send** (beta) supports a single voice-call button in a `"category":"utility"` free-form message; it was documented on 2026-07-30 ([DS]).

---

## 5. Media: WebRTC, SIP, codecs, security

- **Three configurations** ([OV]):
  1. Graph API + webhooks with WebRTC (ICE, DTLS, SRTP)
  2. SIP (TLS) with WebRTC media
  3. SIP with SDES SRTP
- SDES can also be used with Graph signaling: "You can use SDES instead of ICE+DTLS with Graph API + Webhook signaling" ([OV]).
- **Codecs:** "Additional audio codecs supported: PCMA, PCMU" alongside OPUS ([OV]). G.711 "requires transcoding" and "can add latency" ([CS]). Mandatory media settings ([IP]):
  - Opus at 48 kHz with 20 ms ptime
  - a single SSRC
  - DTMF at 8 kHz
- **ICE:** Meta is ICE-lite and always CONTROLLED. Your side should be ICE-full and CONTROLLING, and should use regular nomination ([IP], [FAQ]).
- **TURN:** "Does Meta provide any STUN/TURN servers ...? No", and TURN is "not mandatory" because Meta's SDP has one IPv4 and one IPv6 host candidate. Media UDP ports are "40012, 3482, 3484, 3478, 3480 ... subject to change" ([FAQ]).
- **DTLS:** use ECDSA/ECDH certificates, and act as the DTLS client ([IP], [FAQ]).
- **Stream shape:** one stream and one audio track. No SDP re-negotiation or re-INVITE ("Re-INVITES are not supported") ([FAQ]).
- **Timeouts:** the call disconnects at 20 s with no business media at the start, and at 30 s with no media mid-call. Keep sending RTCP ([TS]).
- **Audio clipping:** mitigations include SDES, pre-accept and buffering ([TS]).
- **SIP** ([SIP]):
  - TLS is mandatory. Domain `wa.meta.vc`. Digest auth (username = business number, Meta-generated password via `include_sip_credentials=true`).
  - Headers: `x-wa-meta-wacid`, `-phone-number-id`, `-user-id`, `-parent-user-id`, `-username`, `-cta-payload`, `-deeplink-payload`, `-call-duration`.
  - One SIP server per number.
  - "Our terms disallow use of PSTN on any leg of the WhatsApp call" ([IP]).
  - **SIP webhooks [Newly Available 2026-06-26]:** set `sip.webhook_delivery:"ENABLED"` to receive `call_created` and `terminate` on `calls`. These carry no SDP.
- **Recording and consent [Newly Available 2026-06-30]** ([REC], [TRN]):
  - Per call, add `recording` and/or `transcription` objects on `connect` or `accept`: `{status, purpose (≤250 chars, required), announcement_language}`.
  - Meta mixes in an announcement: "The audio of this call will be recorded for the following purpose: …".
  - Results arrive on `calls` as `event: call_recording_available` (ogg/opus media ID) and `call_transcription_available` (JSON document with speaker channels 0=Business and 1=Customer, word timings, and a detected language that **includes Swahili**).
  - The download URL is valid for 5 minutes. Retention is 7 days.
  - "Call recording is currently free ... Separate pricing ... planned", with no date.
  - The known issue above applies.
  - **Doc conflict:** the FAQ still answers "Does Meta offer services such as voice recording, transcript, voice-mail? No." ([FAQ]). That answer is stale.
- **Quality metrics:**
  - WhatsApp has no call-quality metrics webhook. Health Status exposes only `can_receive_call_sip`, and "Other calling-related fields are planned" ([HS]). `call_analytics` offers aggregate counts and cost ([AN], [PRC]). The call-logs tab is in WhatsApp Manager ([TS]).
  - **[Not Supported]** on WhatsApp as a per-call metrics API. Messenger does have a Call metrics API (§7).
- **Video and screen share on WhatsApp:** "Video *, screen share *" with the note "* Feature planned or in development" **[Not Supported / planned]** ([OV]).
- **Transfer:** "Meta doesn't have any native support"; transfers happen only on the partner side ([FAQ]). **Hold:** not documented. **[Not Supported]**
- **Concurrency conflict:** the HTML FAQ says "Max concurrent calls is 5000" but elsewhere says "the 1000 concurrent calls limit". Error 138002 says 1000 ([FAQ], [TS]). Assume 1000 is the enforced limit unless you test otherwise.

---

## 6. New in July–September 2026 (consolidated)
- **Newly Available:**
  - Call recording and transcription (2026-06-30, refined in July and August)
  - SIP call webhooks (2026-06-26)
  - Voicemail GA (2026-06-25)
  - Conversation Routing with an Incoming Call entry point (2026-09-23)
  - New account model, Phase 1 GA (2026-09-23)
  - SIP mTLS client cert (2026-09-22)
  - October 2026 rate cards (2026-09-11)
- **Beta/Limited:** Direct Send voice-call button (Direct Send is beta); recording and transcription known network-change issue.
- **Deprecated:** `paid_messaging_account_id`, to be migrated to `messaging_account_id` by 2026-12-31 (a calling endpoint parameter too) ([CHG]). Graph API v20.0 expired on 2026-09-24 ([GV]).
- **Not found / planned:** WhatsApp video calling, screen share, hold, native transfer, per-call quality metrics, voice agents run by Meta on the Calling API ([OV], [FAQ]).
- No new call `action` values and no limit changes were found for July–September 2026 in the changelog ([CHG]).

---

## 7. Messenger and Instagram calling
- **Messenger: GA [Newly Available since 2026-02-11].**
  - "The Messenger Calling API is now generally available. Any app with the pages_messaging permission can enable voice calling ... via third-party integration. The API supports inbound and outbound calls using WebRTC" ([MCHG]).
  - Programmatic receive and place are **both supported**:
    - `/{page-id}/calls` with `accept`, `reject`, `terminate` and `media_update`
    - `GET /{page-id}/messenger_call_permissions?psid=`
    - the `calling_optin` template
    - `calls` and `call_permission_reply` webhook fields
    - video (VP8, VP9, H264, H265, AV1)
    - `messenger_call_settings`
    - a metrics API ([MC], [MB2C], [MVID], [MCS], [MWH])
  - Consumer-to-business: "have 60 seconds to accept". Permission expires after 7 days, with at most "2 call permission requests per thread per day" ([MC2B], [MB2C]).
  - Doc inconsistency: `has_permission` is described as "permanent" but also given a 7-day expiry ([MB2C]).
  - Available-country list **includes Kenya** ([MC]).
  - Page eligibility check: `POST /{page-id}/business_messaging_feature_status` with `messenger_api_calling` ([MC]).
- **Instagram: no business calling API found [Not Supported / unconfirmed].**
  - The Instagram Messaging landing page mentions "APIs for messaging and calling", but its calling card links to WhatsApp and Messenger calling ([IGM]).
  - No `instagram-messaging/*call*` pages exist in its navigation, and the IG changelog has no calling entries.

---

## 7a. Messenger calling — exact shapes (read 2026-09-27)
Read from the official pages (their `.md` sources) on 2026-09-27. Every field below appears in the docs; nothing is invented. Where the docs disagree with themselves, that is flagged and our code parses both ways. This is what `apps/api/app/services/messenger_calling.py` and the page-webhook tap in `routers/meta_webhook.py` implement.

**Big difference from WhatsApp: the SDP direction is reversed for inbound calls.**
- The Messenger `connect` webhook carries **no SDP**.
- The business sends the **offer** in `accept`, and Meta returns the **answer** in the HTTP response ([MACC], [MC2BF]).
- So for a Messenger call the softphone builds an offer, not an answer.

### Access and eligibility
- GA on 2026-02-11. "Any app with the `pages_messaging` permission can enable voice calling" ([MCHG]). No other permission is named. All calls use the **Page access token**.
- Eligibility check ([MC]):

  ```
  POST /{page-id}/business_messaging_feature_status
  {"features":[{"feature":"messenger_api_calling"}]}
  → {"data":[{"feature":"messenger_api_calling","status":"enabled"}]}
  ```

  The prose says "A status of `ENABLED`" but the sample says `"enabled"`, so compare case-insensitively.
- Kenya is on the available-countries list ([MC]).
- **Unconfirmed:** the minimum Graph version. No page names one, so we use `settings.meta_graph_version`.

### Webhook fields
- Subscribe to `calls`. For business-initiated calls, also subscribe to `call_permission_reply` ([MWH]).
- Call events arrive as **`entry[].calls[]`**, not under `changes[]` or `messaging[]`:

  ```
  {"object":"page","entry":[{"id":"{page-id}","time":…,"calls":[ … ]}]}
  ```

- **`connect`** (consumer- and business-initiated):

  ```
  {id:"c_…", to:"{page-id}", from:"{psid}", event:"connect", timestamp, call_direction:"business_initiated"|"user_initiated"}
  ```

  - There is no `session` or SDP, and no caller name.
  - **Unclear:** `to` and `from` are documented as "Callee (Page ID)" and "Caller (PSID)" even for business-initiated calls. We take the PSID to be whichever side is not the page `entry.id`.
- **`call_status`** (business-initiated only):

  ```
  {id, event:"call_status", timestamp, recipient_id:"{psid}", call_status:"ringing"|"accepted"}
  ```

  There is no rejected status. A declined call ends with `terminate`.
- **`media_update`** (business-initiated calls, and whenever the consumer mutes or turns video on):

  ```
  {id, event:"media_update", timestamp, session:{version:int, sdp_renegotiation:{sdp_type:"offer", sdp}}}
  ```

  "apply the one with the highest version number".
- **`terminate`**:

  ```
  {id, event:"terminate", timestamp, status:"Completed"|"Failed", start_time, end_time, duration}
  ```

  - `Completed` "includes calls rejected by the consumer or business".
  - `duration` is empty if the business never connected.
- **`call_permission_reply`** ([MB2C], [MB2CF]):

  ```
  {"object":"page","entry":[{"sender":{"id":"{psid}"},"recipient":{"id":"{page-id}"},"timestamp":…,
    "call_permission_reply":{"response":"approve"|"reject","expiration_timestamp":"{ts}"}}]}
  ```

  - The sample puts it straight on `entry[]`, yet the prose calls it "a postback webhook". We also accept it inside `entry[].messaging[]`.
  - `expiration_timestamp` is present only on `approve`.
- **`call_settings_update`** (entry `call_settings`: `audio_enabled`, `icon_enabled`, `call_routing`, `call_hours`) ([MCS]). We log it only.

### `/{page-id}/calls` actions
All are `POST /{page-id}/calls`. `platform:"messenger"` is optional; the docs spell it both "Messenger" and "messenger", and we send lowercase.

- **accept** ([MACC]):

  ```
  {platform, call_id, action:"accept", session:{sdp_type:"offer", sdp}}
  → {success:true, session:{sdp_response, sdp_renegotiation}}
  ```

  - You have **60 s**. "If you don't respond, the call terminates on the consumer side with 'Not Answered'", followed by a terminate webhook ([MC2B], [MACC]).
  - Apply the answer first, then the renegotiation offer, then create a local answer.
  - **Inconsistent:** the accept sample shows `sdp_response` and `sdp_renegotiation` as plain strings. The JS sample and the media_update response show `{sdp_type, sdp}` objects. We accept both.
- **reject**: `{platform, call_id, action:"reject"}` → `{success:true}` (incoming calls only) ([MREJ]).
- **terminate**: `{platform, call_id, action:"terminate"}` → `{success:true}` ([MREJ], [MINIT]).
- **connect** (business-initiated) ([MINIT]):

  ```
  {platform, to:"{psid}", action:"connect", session:{sdp_type:"offer", sdp}}
  → {success:true, id:"c_…", session:{sdp_response:{sdp_type:"answer", sdp}}}
  ```

  - The answer comes back **synchronously**.
  - After the consumer picks up, a `media_update` renegotiation offer follows.
  - **Unclear:** the docs only say "Generate an SDP answer and apply it to your peer connection". No endpoint for posting that answer back is documented. We relay the offer to the browser as a `media_update` event.
- **media_update** (video/tracks) ([MVID]):

  ```
  {platform, call_id, action:"media_update", from_version, to_version, tracks:[{msid,label,status}], session:{sdp_type:"offer", sdp}}
  ```

  **Not used.** Neema is voice only and never offers video.
- Error codes ([MERR]):

  | Code | Meaning |
  |---|---|
  | 2018389 | Page not allowlisted |
  | 2018390 | Invalid call id |
  | 2018391 | Invalid connection parameter |
  | 2018392 | Invalid SDP |
  | 2018393 | Page not in call |
  | 2018394 | Insufficient permission to join |
  | 2018395 | Cannot join failed call |
  | 2018396 | Cannot join ended call |
  | TBD | Call rate limit exceeded |

  - The consumer-has-no-permission error on `connect` has **no documented code**. We check permission before connecting and match its text defensively.

### Permission
- **Read** ([MB2C]):

  ```
  GET /{page-id}/messenger_call_permissions?psid={psid}
  → {permission:{status:"no_permission"|"has_permission", expiration_time}, actions:[{action_name:"send_call_permission_request"|"start_call", can_perform:bool, limits:[{time_period:"PT24H", max_allowed:2, current_usage}]}]}
  ```

  - The field is `can_perform`. WhatsApp's is `can_perform_action`.
  - `has_permission` is described as "permanent" but "expires in 7 days by default", so we honour `expiration_time`.
- **Request** ([MB2C]):

  ```
  POST /{page-id}/messages
  {recipient:{id:psid}, message:{attachment:{type:"template", payload:{template_type:"calling_optin"}}}}
  → {recipient:{id}, message_id}
  ```

  - The consumer sees **Accept** and **Decline** buttons.
  - Limits: "at most **2 call permission requests per thread per day**". Each permission lasts **7 days**.
  - Send API rules apply, including the 24-hour window.
- **Implicit (callback) permission** after "a fully connected call" or after the consumer calls and "the business does not pick up" ([MB2C]).

### Settings
All under `POST /{page-id}/messenger_call_settings` ([MCS]):
- `icon_enabled`
- `call_hours{timezone_id, weekly_operating_hours[{day_of_week, open_time "hhmm", close_time}]}`
- `call_routing{ring_target: "META"|"PARTNERS"}`. **Incoming calls reach our webhook only with `PARTNERS`**, and the app must be subscribed to `calls` before `PARTNERS` can be set.

The `call_prompt` template (`ttl_days`, default 7) and the `audio_call` button CTA exist, but we don't use them. Messenger uses DTMF over RTP with no DTMF webhook ([MC]).

### Instagram
Unchanged from §7: no business calling API.

---

## 8. Pricing
- "All user-initiated calls are free" ([PRC]).
- Business-initiated calls are billed per **6-second pulse** (partial pulses round up), by the callee's country code, with monthly volume tiers. A call that crosses a tier is priced entirely at the higher-volume (lower) rate. A payment method or credit line is required ([PRC], [FAQ]).
- Permission-request messages are billed as messages ([PRC]).
- An inbound call opens or refreshes the 24-hour customer service window "regardless of if you accept the call or not", and so does the user accepting your call ([PRC]).
- **Kenya:** not listed as a standalone market. The pricing page's country-code table lists Kenya under **"Rest of Africa"** ([PRI]).
  - USD rate card effective 2026-07-01, "Rest of Africa" per minute, from the official CSV linked from [PRC]:

    | Monthly minutes | USD/min |
    |---|---|
    | 0–50,000 | 0.0103 |
    | 50,001–250,000 | 0.0084 |
    | 250,001–1M | 0.0074 |
    | 1M–2.5M | 0.0062 |
    | 2.5M–5M | 0.0047 |
    | 5M+ | 0.0042 |

  - The 2026-10-01 card is identical for Rest of Africa.
  - Caveat: the page says current cards are "effective April 1, 2026", but the "current" USD link resolves to a CSV titled "effective August 1, 2025". Kenya's Rest of Africa list rate is 0.0103 in both files.
- The tier webhook is `account_update` with `VOLUME_BASED_PRICING_TIER_UPDATE` and `pricing_category:"CALLING"` ([PRC]).
- Recording and transcription are currently free ([PRC]).
- Business-initiated calling is not available for business numbers from US, CA, EG, VN or NG. User-initiated calling works wherever Cloud API does ([OV]). Kenya is therefore eligible for business-initiated calls.

---

## 9. Meta AI and voice agents
- There is no Meta-hosted voice agent on the Calling API. The FAQ says AI voicebots are allowed and bring-your-own: "Meta only provides the raw media stream ... Many businesses use automated voicebots including AI bots", subject to the Business Solution Terms ([FAQ]).
- **Meta Business Agent** (announced 2026-06-03) is a *messaging* agent on WhatsApp and Messenger. Its developer overview and the announcement mention no voice or calling capability ([MBA], [MBAN]). **[Not Supported for calls / unconfirmed]**
- Meta's July 2025 announcement said calling "paves the way for AI-enabled voice support in the future" ([N25]). No launch was found.
- Policy: since 2026-01-15, general-purpose "AI Providers" are restricted on the Business Platform. This targets general-purpose assistants, not business-specific support bots ([AIP]).

## 10. Graph API versions ([GV])
- **v26.0:** released 2026-07-29, expiry TBD. This is the latest.
- **v25.0:** released 2026-02-18, expires 2028-07-29.
- **v24.0:** expires 2028-02-18.
- **v23.0:** expires 2027-10-08.
- **v22.0:** expires 2027-05-20.
- **v21.0:** expires 2027-01-21.
- **v20.0:** expired 2026-09-24.
- The Calling FAQ still lists "minimum Graph API version is v17.0", but v17 expired on 2025-09-12 ([FAQ], [GV]).
- The v26.0 changelog has no WhatsApp calling items ([GV26]).

## 11. Realtime speech options for bridging (brief)
- **OpenAI Realtime API:**
  - GA; connects over WebRTC or WebSocket.
  - Native SIP ingress at `sip:$PROJECT_ID@sip.api.openai.com;transport=tls`, with a `realtime.call.incoming` webhook and accept, reject, refer and hangup endpoints.
  - The docs example uses the model `gpt-realtime-2.1` ([OAI-SIP], [OAI-RT]).
  - Meta forbids PSTN on any leg, and a SIP trunk alone is allowed ([IP]). So SIP-to-SIP VoIP bridging to OpenAI appears compatible. **Unconfirmed:** whether the codec and SRTP choices interoperate without transcoding.
- **Google Gemini Live API:** WebSocket; input is "16-bit PCM audio, 16kHz", output "24kHz" ([GEM]).
- **Deepgram Voice Agent API:** WebSocket, full STT → LLM → TTS pipeline, configurable LLM providers ([DG]).
- **Anthropic Claude API:** no realtime speech-to-speech or audio-input endpoint appears in the Claude API reference I checked. Claude would sit as the text LLM in a cascaded STT → LLM → TTS pipeline. **Unconfirmed:** whether an audio feature launched after that reference.

---

## Could not confirm
1. The ringing timeout for business-initiated calls.
2. The meaning of error 138011.
3. Whether a manual revoke from the business profile emits a webhook.
4. Whether a `call_permission_request` template component can be combined with other buttons.
5. A distinct "callback requested" webhook.
6. Concurrency: 1000 vs 5000.
7. The exact `GET call_permissions` expiry field name: `expiration_time` vs `expiration`.
8. Instagram calling API (none found).
9. Meta-hosted voice agents (none found).
10. Anthropic realtime audio.
11. Whether "current" USD calling rates follow the April 2026 or August 2025 file. Kenya's rates are the same in both.

---

## Citations
- [OV] WA/calling — https://developers.facebook.com/documentation/business-messaging/whatsapp/calling
- [UCP] https://developers.facebook.com/documentation/business-messaging/whatsapp/calling/user-call-permissions
- [BIC] https://developers.facebook.com/documentation/business-messaging/whatsapp/calling/business-initiated-calls
- [UIC] https://developers.facebook.com/documentation/business-messaging/whatsapp/calling/user-initiated-calls
- [CS] https://developers.facebook.com/documentation/business-messaging/whatsapp/calling/call-settings
- [SIP] https://developers.facebook.com/documentation/business-messaging/whatsapp/calling/sip
- [REC] https://developers.facebook.com/documentation/business-messaging/whatsapp/calling/call-recording/
- [TRN] https://developers.facebook.com/documentation/business-messaging/whatsapp/calling/call-transcription/
- [CB] https://developers.facebook.com/documentation/business-messaging/whatsapp/calling/call-button-messages-deep-links
- [TS] https://developers.facebook.com/documentation/business-messaging/whatsapp/calling/troubleshooting
- [FAQ] https://developers.facebook.com/documentation/business-messaging/whatsapp/calling/faq
- [IP] https://developers.facebook.com/documentation/business-messaging/whatsapp/calling/integration-patterns
- [REF] https://developers.facebook.com/documentation/business-messaging/whatsapp/calling/reference
- [SBX] https://developers.facebook.com/documentation/business-messaging/whatsapp/calling/sandbox
- [PRC] https://developers.facebook.com/documentation/business-messaging/whatsapp/calling/pricing
- [PRI] https://developers.facebook.com/documentation/business-messaging/whatsapp/pricing
- [CRW] https://developers.facebook.com/documentation/business-messaging/whatsapp/conversation-routing/calling-webhooks
- [CHG] https://developers.facebook.com/documentation/business-messaging/whatsapp/changelog
- [DS] https://developers.facebook.com/documentation/business-messaging/whatsapp/direct-send/supported-message-types/
- [HS] https://developers.facebook.com/documentation/business-messaging/whatsapp/support/health-status
- [AN] https://developers.facebook.com/documentation/business-messaging/whatsapp/analytics
- [AIP] https://developers.facebook.com/documentation/business-messaging/whatsapp/pricing/ai-providers
- [GV] https://developers.facebook.com/docs/graph-api/changelog/versions
- [GV26] https://developers.facebook.com/docs/graph-api/changelog/version26.0
- [MC] https://developers.facebook.com/documentation/business-messaging/messenger-platform/calling
- [MC2B] https://developers.facebook.com/documentation/business-messaging/messenger-platform/calling/consumer2biz
- [MB2C] https://developers.facebook.com/documentation/business-messaging/messenger-platform/calling/biz2consumer/check-permissions
- [MWH] https://developers.facebook.com/documentation/business-messaging/messenger-platform/calling/webhooks
- [MVID] https://developers.facebook.com/documentation/business-messaging/messenger-platform/calling/videocalling
- [MCS] https://developers.facebook.com/documentation/business-messaging/messenger-platform/calling/callsettings
- [MCHG] https://developers.facebook.com/documentation/business-messaging/messenger-platform/changelog
- [MACC] https://developers.facebook.com/documentation/business-messaging/messenger-platform/calling/consumer2biz/accept-c2b-call
- [MREJ] https://developers.facebook.com/documentation/business-messaging/messenger-platform/calling/consumer2biz/reject-end-call
- [MC2BF] https://developers.facebook.com/documentation/business-messaging/messenger-platform/calling/consumer2biz/call-flow
- [MB2CF] https://developers.facebook.com/documentation/business-messaging/messenger-platform/calling/biz2consumer/call-flow
- [MINIT] https://developers.facebook.com/documentation/business-messaging/messenger-platform/calling/biz2consumer/initiate-call
- [MERR] https://developers.facebook.com/documentation/business-messaging/messenger-platform/error-codes
- [IGM] https://developers.facebook.com/documentation/business-messaging/instagram-messaging
- [MBA] https://developers.facebook.com/documentation/meta-business-agent/overview
- [MBAN] https://about.fb.com/news/2026/06/meta-business-agent/
- [N25] https://about.fb.com/news/2025/07/centralized-campaigns-ai-support-businesses-whatsapp/
- [OAI-SIP] https://developers.openai.com/api/docs/guides/realtime-sip
- [OAI-RT] https://developers.openai.com/api/docs/guides/realtime
- [GEM] https://ai.google.dev/gemini-api/docs/live
- [DG] https://developers.deepgram.com/docs/voice-agent

[OV]: https://developers.facebook.com/documentation/business-messaging/whatsapp/calling
[UCP]: https://developers.facebook.com/documentation/business-messaging/whatsapp/calling/user-call-permissions
[BIC]: https://developers.facebook.com/documentation/business-messaging/whatsapp/calling/business-initiated-calls
[UIC]: https://developers.facebook.com/documentation/business-messaging/whatsapp/calling/user-initiated-calls
[CS]: https://developers.facebook.com/documentation/business-messaging/whatsapp/calling/call-settings
[SIP]: https://developers.facebook.com/documentation/business-messaging/whatsapp/calling/sip
[REC]: https://developers.facebook.com/documentation/business-messaging/whatsapp/calling/call-recording/
[TRN]: https://developers.facebook.com/documentation/business-messaging/whatsapp/calling/call-transcription/
[CB]: https://developers.facebook.com/documentation/business-messaging/whatsapp/calling/call-button-messages-deep-links
[TS]: https://developers.facebook.com/documentation/business-messaging/whatsapp/calling/troubleshooting
[FAQ]: https://developers.facebook.com/documentation/business-messaging/whatsapp/calling/faq
[IP]: https://developers.facebook.com/documentation/business-messaging/whatsapp/calling/integration-patterns
[REF]: https://developers.facebook.com/documentation/business-messaging/whatsapp/calling/reference
[SBX]: https://developers.facebook.com/documentation/business-messaging/whatsapp/calling/sandbox
[PRC]: https://developers.facebook.com/documentation/business-messaging/whatsapp/calling/pricing
[PRI]: https://developers.facebook.com/documentation/business-messaging/whatsapp/pricing
[CRW]: https://developers.facebook.com/documentation/business-messaging/whatsapp/conversation-routing/calling-webhooks
[CHG]: https://developers.facebook.com/documentation/business-messaging/whatsapp/changelog
[DS]: https://developers.facebook.com/documentation/business-messaging/whatsapp/direct-send/supported-message-types/
[HS]: https://developers.facebook.com/documentation/business-messaging/whatsapp/support/health-status
[AN]: https://developers.facebook.com/documentation/business-messaging/whatsapp/analytics
[AIP]: https://developers.facebook.com/documentation/business-messaging/whatsapp/pricing/ai-providers
[GV]: https://developers.facebook.com/docs/graph-api/changelog/versions
[GV26]: https://developers.facebook.com/docs/graph-api/changelog/version26.0
[MC]: https://developers.facebook.com/documentation/business-messaging/messenger-platform/calling
[MC2B]: https://developers.facebook.com/documentation/business-messaging/messenger-platform/calling/consumer2biz
[MB2C]: https://developers.facebook.com/documentation/business-messaging/messenger-platform/calling/biz2consumer/check-permissions
[MWH]: https://developers.facebook.com/documentation/business-messaging/messenger-platform/calling/webhooks
[MVID]: https://developers.facebook.com/documentation/business-messaging/messenger-platform/calling/videocalling
[MCS]: https://developers.facebook.com/documentation/business-messaging/messenger-platform/calling/callsettings
[MCHG]: https://developers.facebook.com/documentation/business-messaging/messenger-platform/changelog
[MACC]: https://developers.facebook.com/documentation/business-messaging/messenger-platform/calling/consumer2biz/accept-c2b-call
[MREJ]: https://developers.facebook.com/documentation/business-messaging/messenger-platform/calling/consumer2biz/reject-end-call
[MC2BF]: https://developers.facebook.com/documentation/business-messaging/messenger-platform/calling/consumer2biz/call-flow
[MB2CF]: https://developers.facebook.com/documentation/business-messaging/messenger-platform/calling/biz2consumer/call-flow
[MINIT]: https://developers.facebook.com/documentation/business-messaging/messenger-platform/calling/biz2consumer/initiate-call
[MERR]: https://developers.facebook.com/documentation/business-messaging/messenger-platform/error-codes
[IGM]: https://developers.facebook.com/documentation/business-messaging/instagram-messaging
[MBA]: https://developers.facebook.com/documentation/meta-business-agent/overview
[MBAN]: https://about.fb.com/news/2026/06/meta-business-agent/
[N25]: https://about.fb.com/news/2025/07/centralized-campaigns-ai-support-businesses-whatsapp/
[OAI-SIP]: https://developers.openai.com/api/docs/guides/realtime-sip
[OAI-RT]: https://developers.openai.com/api/docs/guides/realtime
[GEM]: https://ai.google.dev/gemini-api/docs/live
[DG]: https://developers.deepgram.com/docs/voice-agent
