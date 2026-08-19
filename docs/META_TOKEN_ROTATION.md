# Meta page token — rotation and durability

On 2026-08-19 every Messenger/Instagram send began failing with:

> `Meta send message failed (401): {"error":{"message":"Error validating
> access token: The session has been invalidated because the user changed
> their password …"}}`

That is the defining weakness of a **user-session-derived** page token: it
dies the moment the Facebook account that minted it changes its password,
logs out everywhere, or has a security checkpoint. Inbound webhooks keep
working (they verify with the App Secret), so the inbox looks alive while
nothing can be answered on Meta — the same silhouette as an out-of-credit
outage, on a different credential.

## The durable fix: a System User token

Mint the token from a **System User**, not from a person. System-user tokens
do not depend on anyone's login session and survive password changes.

1. business.facebook.com → **Settings** → **Users → System users** →
   `Add` (Admin system user, e.g. `neema-bot`).
2. **Add assets**: assign the Facebook Page(s) (and the Instagram account's
   linked page) with **Manage** permission.
3. **Generate token**: select the Neema Meta app; scopes:
   `pages_messaging`, `pages_manage_engagement`, `pages_read_engagement`,
   `pages_manage_metadata`, `instagram_basic`, `instagram_manage_messages`,
   `instagram_manage_comments`. Choose **never expire**.
4. On the VPS, update the env file the api container reads:
   - `META_PAGE_TOKEN=<the new token>` (single-page setup), and/or
   - `META_PAGE_TOKENS={"<page_id>":"<token>", …}` (multi-page map).
5. Restart: `docker compose up -d api` (or wait for the next deploy tick —
   the container re-reads the env file on recreate).
6. Verify in one minute: send any Messenger thread a reply from the
   dashboard — a red toast means it still fails (the toast carries Graph's
   own reason); silence plus the bubble appearing means it works.

## How the system tells you now (built after this outage)

- **`/api/health`** classifies the failure honestly: `"kind": "meta"` with
  a remedy line naming the page token — never again "check
  ANTHROPIC_API_KEY" for a Facebook problem.
- **The hourly self-check probes every configured token** against Graph
  (`GET /me`) and raises a once-notified finding the hour a token dies —
  before a customer send has to fail first. It also lands on the 08:00
  standup's system-health line.
- **A failed human send shows a red toast** with Graph's reason and keeps
  your typed text; failed AI sends count into `/api/health` with the same
  honest kind.
- After the token is fixed, the missed-reply sweeper automatically rescues
  Meta DMs still inside their 24-hour window; older ones were escalated to
  the team with the reason.
