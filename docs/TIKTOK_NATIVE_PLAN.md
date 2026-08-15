# TikTok native — everything on Neema, ManyChat retired

ManyChat taught us the transport (docs/TIKTOK_MANYCHAT_SETUP.md); this is the
plan that removes it. TikTok's **Business Messaging API**
(business-api.tiktok.com) gives an approved developer app the exact access
ManyChat has: OAuth on the owner's Business Account, real-time DM webhooks,
and a send API. Kenya is eligible (only EEA/Switzerland/UK are excluded).
Approval is an application, not a partnership — "typically a few days".
Chatwoot ships this integration open-source, which is the working reference
these shapes were mirrored from.

## What's already built (inert until configured)

| Piece | Where |
|---|---|
| OAuth connect/callback + token store (24h access auto-refresh, 30d refresh) | `services/tiktok_native.py`, tokens in `app_settings.tiktok_oauth` |
| DM webhook: signature check, `im_receive_msg` → async agent, echo/owner-reply handling | `routers/tiktok_webhook.py` (`POST /api/tiktok/webhook/events`) |
| Sending: `send_to_channel("tiktok", …)` goes native once the app is configured | `services/meta_send.py` — dashboard humans + hold line included |
| Async agent path (no more 10s squeeze) | reuses `runtime.schedule_meta_reply` — channel-generic |
| 48h messaging window in the inbox once native is live | `services/conversation.py::messaging_window` |
| ManyChat cutover guard: relay answers empty once native is live | `routers/manychat.py` |

Env (VPS `.env`): `TIKTOK_APP_ID`, `TIKTOK_APP_SECRET`, `TIKTOK_CONNECT_KEY`
(owner door for the connect flow), `TIKTOK_REDIRECT_URI`
(default `https://neema.bethanyhouse.co.ke/api/tiktok/oauth/callback`).

## The owner's part (nobody else can do this — it's your TikTok login)

1. **developers.tiktok.com** → create a developer account (verify email).
2. **business-api.tiktok.com/portal/apps** → create an app: name *Neema AI*,
   description "AI customer service and sales assistant for Bethany House's
   own TikTok Business account", icon, privacy/terms URLs
   (`https://neema.bethanyhouse.co.ke/terms`), redirect URI **exactly**
   `https://neema.bethanyhouse.co.ke/api/tiktok/oauth/callback`.
3. In the app, **apply for Business Messaging API** access. Use case:
   first-party customer support/sales on our own Business Account. Enable the
   "TikTok Accounts" permission when it appears after approval.
4. Put App ID + App Secret in the VPS `.env` (`TIKTOK_APP_ID`,
   `TIKTOK_APP_SECRET`) — or hand them over in chat to be installed.

## Cutover (after approval — config flip, ~10 minutes)

1. Set the two env values; container restart picks them up.
2. Open `https://neema.bethanyhouse.co.ke/api/tiktok/oauth/connect?key=<TIKTOK_CONNECT_KEY>`
   in a browser where the **business TikTok account** is logged in → Authorize.
   The callback stores tokens, self-registers the webhook, and shows
   "✅ TikTok connected as @…". (If self-registration fails, set the callback
   URL `https://neema.bethanyhouse.co.ke/api/tiktok/webhook/events` in the app
   portal manually.)
3. Send the account a test DM from another TikTok — Neema answers async.
4. In ManyChat: pause/delete the TikTok automation (the relay already answers
   empty by itself once native is live). Downgrade/cancel ManyChat when
   comfortable.
5. If the 30-day refresh token ever lapses (long outage), the send path raises
   "reconnect needed" and step 2 is repeated.

## Phase next: comments — the thing ManyChat can't do here

The same Business API family has organic comment endpoints
(`/business/comment/list/`, reply, hide) used for comment management. Once the
app is approved and connected, we evaluate the granted scopes and, if comment
access is included (or obtainable by an additional permission request), add a
comment poller: new comment → same agent, short public reply + "DM us"
invitation → the DM continues natively. That leapfrogs ManyChat, whose
comment-to-DM is VN/TH/ID-only.

## Identity note

ManyChat-era TikTok contacts are keyed on ManyChat subscriber ids; native
contacts on TikTok open_ids. They don't collide, but a customer who talked
during both eras appears as two identities until the phone number (captured
early by design) merges them into one person — the same merge that already
unifies WhatsApp and social selves.
