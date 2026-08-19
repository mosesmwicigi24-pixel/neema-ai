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

## Rotate it with one command

```bash
bash scripts/meta-token-install.sh
```

Paste **either** a page token or a user token; the script works out which it
is, extends a user token so the page token it yields never expires, lists the
pages that login administers (pick by **number** — typing a page id that isn't
in the list is how the wrong page gets chosen), verifies against Graph that
what it's about to install is a *Page* token for the page you meant, shows the
expiry, asks yes/no, backs up `.env`, updates `META_PAGE_TOKEN` **and** any
`META_PAGE_TOKENS` map entry, then force-recreates the api container.

Everything below is the same journey done by hand.

## Four traps this costs a morning to learn

1. **A user token is not a page token.** The user token is only the key that
   *fetches* the page token (`GET /me/accounts`). Installing it makes every
   send fail with `Object with ID 'me' does not exist`.
2. **The page dropdown in Graph Explorer gives a token that dies in hours.**
   Page tokens inherit the lifetime of the user token behind them. Extend the
   *user* token first (Access Token Debugger → **Extend Access Token**, or
   `grant_type=fb_exchange_token`), *then* call `/me/accounts`. Check the
   result with `/debug_token`: **`expires_at: 0` means never**.
3. **The App ID is not your Facebook user id**, and the App Secret must belong
   to the app that *issued* the token. `GET /debug_token?input_token=T&access_token=T`
   names both (`app_id`, `application`) — ask Graph instead of guessing. An
   empty `META_APP_SECRET` produces the misleading
   `Error validating client secret.`
4. **`docker compose restart` does not re-read `.env`.** Use
   `up -d --no-deps --force-recreate api`.

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
- **It reads the expiry too** (`/debug_token`) and warns up to **three days
  ahead** of a token that is going to die. The 2026-08-19 replacement token
  was installed at 10:20 UTC and would have expired at 12:00 the same day with
  every other check green; that silence is now impossible.
- **A missing `META_APP_SECRET` is reported as an open webhook.** Both webhook
  front doors skip `X-Hub-Signature-256` verification when no secret is set —
  a dev convenience that had gone unnoticed in production, leaving the
  callback URL able to accept forged customer messages (each one a paid AI
  turn, answered as if real).
- **A failed human send shows a red toast** with Graph's reason and keeps
  your typed text; failed AI sends count into `/api/health` with the same
  honest kind.
- After the token is fixed, the missed-reply sweeper automatically rescues
  Meta DMs still inside their 24-hour window; older ones were escalated to
  the team with the reason.
