# TikTok DMs → Neema, relayed by ManyChat

TikTok exposes no inbound-DM API we can integrate directly; ManyChat (an
official TikTok partner) owns that transport. So TikTok is Neema's first
**synchronous relay channel**: ManyChat POSTs each customer DM to
`POST /api/manychat/webhook` (see `apps/api/app/routers/manychat.py`) and
delivers whatever `reply` comes back — there is **no push API**. Everything
that follows is shaped by three TikTok facts:

1. **~10s** — ManyChat's External Request timeout. Neema answers within
   `MANYCHAT_REPLY_BUDGET_S` (default 9s) or returns a short resend line.
2. **~10 automated replies / 48h window** — every reply must count. An empty
   `reply` from Neema is *deliberate silence* (closer gate, intercept hold) —
   the flow must simply not send in that case, never substitute a canned line.
3. **No push** — re-engage / cart-recovery jobs skip the channel, the inbox
   composer is closed with a pointer to ManyChat Live Chat, and a human
   takeover is served by ManyChat's Live Chat screen, not Neema's dashboard.

Comments are **out of scope**: TikTok's comment-to-DM automation is only open
in VN/TH/ID today ("coming soon" elsewhere, per ManyChat). Rescope when that
lands in our markets.

## Server side (already live)

- Endpoint: `POST https://neema.bethanyhouse.co.ke/api/manychat/webhook`
- Auth: `X-ManyChat-Key` header, checked against `MANYCHAT_WEBHOOK_KEY` in
  `/home/neema/neema-ai/.env` on the VPS (endpoint 503s until set).
- Request body (we define it — ManyChat sends what the flow's External
  Request is configured to send):

```json
{
  "subscriber_id": "<ManyChat User ID — the identity key>",
  "name": "<Full Name>",
  "message": "<Last Text Input>",
  "channel": "tiktok"
}
```

- Response: `{"reply": "<text or empty>", "handled_by": "ai" | "human"}` —
  the flow maps `$.reply` to a custom field and sends it if non-empty.
- Identity: `(tiktok, subscriber_id)` on the Person/Identity spine — merges
  with the customer's WhatsApp self once a phone is captured (same machinery
  as Messenger/IG).

## ManyChat side (one-time setup)

Prereqs: TikTok **Business** account connected to ManyChat; ManyChat **Pro**
(External Request is a paid feature).

Build one automation, triggered by **User sends a message** (and set the
account's **Default Reply** to it as well, so every DM lands here):

1. **Set Custom Field** `ai_reply` → *clear/empty*. (A stale value from the
   previous turn must never be re-sent if this turn's request fails.)
2. **External Request** (Action → Make External Request):
   - `POST https://neema.bethanyhouse.co.ke/api/manychat/webhook`
   - Headers: `Content-Type: application/json`,
     `X-ManyChat-Key: <value of MANYCHAT_WEBHOOK_KEY>`
   - Body: the JSON above, inserting the **User ID**, **Full Name**, and
     **Last Text Input** system variables with the `{}` picker.
   - Response mapping: JSON path `$.reply` → custom field `ai_reply`.
3. **Condition**: `ai_reply` *has any value*
   - **Yes** → **Send message**: `{{ai_reply}}`
   - **No** → *(nothing — end the flow; the empty branch is Neema choosing
     silence, or a rare relay failure the customer shouldn't feel twice)*

Optional: a **Welcome Message** automation with a short static greeting
("Karibu Bethany House! Ask me about cassocks, communion ware, gowns — or
anything you saw in our videos 🙏") — static on purpose: a brand-new contact
has no `Last Text Input` yet.

## Verifying

```bash
curl -s -X POST https://neema.bethanyhouse.co.ke/api/manychat/webhook \
  -H 'Content-Type: application/json' -H "X-ManyChat-Key: $KEY" \
  -d '{"subscriber_id":"smoke_test","message":"Do you have cassocks?","name":"Smoke Test","channel":"tiktok"}'
```

Expect a warm catalogue answer in `reply` within ~9s. Wrong key → 401; key
unset on the box → 503; non-tiktok `channel` → 400.
