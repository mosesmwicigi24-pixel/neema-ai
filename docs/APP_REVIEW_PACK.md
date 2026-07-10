# Meta App Review — submission pack (Neema Assistant)

Everything to copy-paste into the App Review forms. One approval unlocks THREE
blocked capabilities at once: DM delivery to the public, comment private-replies,
and reading Messenger names/photos (the Profile API 400s today — confirmed 1/69).

App: **Neema Assistant** (id 1076892141296942) · Pages: Bethany House
(1556733441275467), Bethany House Executive (103756315006608).

## Before submitting (blockers)
1. ✅ **Business Verification** — DONE (verified Jun 10 2025, use case "App
   requires access to permissions on Meta for Developers").
2. **App settings → Basic** — fill in (pages are LIVE, just paste the URLs):
   - Privacy Policy URL: `https://neema.bethanyhouse.co.ke/privacy`
   - Terms of Service URL: `https://neema.bethanyhouse.co.ke/terms`
   - Data Deletion Instructions URL: `https://neema.bethanyhouse.co.ke/data-deletion`
   - App icon 1024×1024 + category (Business).
3. App Mode: **Live** (already Live).
4. Recommended: enable **2FA** on the Business portfolio (Security Center shows
   0/1) and add a second admin — reviewers and Meta security prompts favor it.

## Permissions to request (Advanced Access)
| Permission | Why (copy-paste use case) |
|---|---|
| `pages_messaging` | "Bethany House is a Kenyan maker of clergy apparel. Our assistant, Neema, answers customer questions and takes orders over Messenger: it replies to customer-initiated DMs with prices and availability from our product catalogue, and addresses the customer by name (User Profile API) so service feels personal. All messages are replies to customers who contacted us first, within the 24-hour messaging window." |
| `pages_manage_engagement` | "When a customer comments on our Page's posts (e.g. asking a product's price), Neema replies publicly under that comment with the answer, so the customer and other shoppers get accurate information quickly." |
| `pages_read_engagement` | "We read comments on our own Page's posts to know what a customer asked, and the post's content so the reply is about the right product." |
| `pages_manage_metadata` | "We subscribe our Page to webhooks (messages, feed) so customer messages and comments reach our system in real time." |
| `instagram_basic` + `instagram_manage_comments` + `instagram_manage_messages` | Same use cases for our Instagram professional account (comments + DMs). Request only if the IG account is linked to the Page by then. |

## Screencast script (~2 minutes, screen-record with narration or captions)
The reviewer must SEE each permission working end-to-end:
1. **Setup shot** — log into the Neema dashboard (neema.bethanyhouse.co.ke),
   show the inbox with Messenger/Facebook conversations alongside WhatsApp.
2. **`pages_messaging`** — from a test user's phone: send the Bethany House Page
   a DM: "How much is a cassock?" → show Neema's reply arriving in Messenger
   (price + made-to-order note), and the same thread visible in the dashboard.
3. **`pages_read_engagement` + `pages_manage_engagement`** — comment "How much?"
   on a Page post → show the public reply appearing under the comment with the
   real price and an order link.
4. **Profile name** — show the dashboard displaying the test user's name/photo
   on the conversation (what the User Profile API powers).
5. Close on the dashboard showing the conversation history — demonstrating this
   is genuine customer service, human-supervised (Intercept/Pickup buttons visible).

Record at 1080p; no dead air; every permission visibly exercised. Do NOT show
tokens or the .env.

## Reviewer instructions (paste into "Steps to reproduce")
1. Our Facebook Page: facebook.com/<bethany-house-page-handle>.
2. Send the Page a Messenger message such as "How much is a clerical shirt?".
3. Within seconds our assistant replies with the price from our catalogue and an
   invitation to order on WhatsApp.
4. Comment "price?" on any recent Page post — a public reply with the price
   appears under your comment.
5. All replies are customer-initiated conversations answered inside the 24-hour
   window; our staff supervise every conversation from our dashboard and can take
   over at any time (human handoff).

If the reviewer cannot trigger flows from their own account, add a **test user**:
App roles → Testers, and note its credentials in the instructions field.

## After approval
- Nothing to deploy — the code already attempts DMs/private replies/Profile API
  and degrades gracefully; on approval they simply start succeeding.
- Then run the backlog namer to retro-name old contacts:
  `docker compose -f docker-compose.yml -f docker-compose.vps.yml exec -T api python -m app.jobs.enrich_names`
  — add `--retry-marked` so contacts previously stamped no-profile are tried
  again now that the API answers.
- Comment replies will start saying "check your inbox" automatically when the DM
  actually delivers (the honest-reply logic keys on the real send result).
