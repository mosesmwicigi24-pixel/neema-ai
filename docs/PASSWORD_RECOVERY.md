# Password recovery

Owner, 2026-10-12: "Develop the way to recover when forgotten, sent to
info@bethanyhouse.co.ke." Neema had only `/login` and `/refresh`; a forgotten
password meant an admin typing a new one in Settings → Team.

## How it works

1. **Login → "Forgot your password?"** (`/forgot-password`). The person enters
   their account email.
2. `POST /api/auth/forgot-password {email}` (services/password_reset.py): one
   single-use token (32 random bytes; only its SHA-256 is kept, in redis, for
   `PASSWORD_RESET_TTL_MINUTES`, default 60) and ONE mail to
   `PASSWORD_RESET_INBOX` (default `info@bethanyhouse.co.ke`) naming the
   account ("Neema password reset for Moses Mwicigi") with the link
   `<MEDIA_PUBLIC_URL>/reset-password?token=…`. The office hands the link to
   the person. `PASSWORD_RESET_COPY_AGENT=true` also mails the account's own
   address.
   - The answer is the same whether or not the email is an account (no
     enumeration): "If that email belongs to a Neema account, a reset link has
     been sent to the Bethany House recovery inbox (…)".
   - 3 requests an hour per email, 10 per caller address → 429.
   - Mail not set up → 503 "…An admin can reset your password in Settings →
     Team"; a mail failure → 502 with the mailer's reason, token withdrawn.
3. **`/reset-password?token=…`**: new password twice (8+ characters) →
   `POST /api/auth/reset-password {token, password}`. The token is consumed on
   first use; the hash is replaced; the person signs in with the new password.

The mobile prefix `/api/agent-auth` carries the same routes — and on the public
host it is the one the pages call: there `/api/auth/*` belongs to NextAuth (the
dashboard's sign-in handler), which answers a POST with "This action with HTTP
POST is not supported by NextAuth.js". NextAuth itself reaches the API's
`/api/auth/login` over the internal network (`API_INTERNAL_URL`).

## What the box needs (`.env`, then both compose files as usual)

```
SMTP_HOST=smtp.gmail.com          # or the Workspace / provider relay
SMTP_PORT=587                     # 465 = SMTPS, anything else = STARTTLS
SMTP_USER=info@bethanyhouse.co.ke # the login
SMTP_PASSWORD=…                   # an app password, never the mailbox password
SMTP_FROM=info@bethanyhouse.co.ke # optional, defaults to SMTP_USER
PASSWORD_RESET_INBOX=info@bethanyhouse.co.ke
```

`MEDIA_PUBLIC_URL` (https://neema.bethanyhouse.co.ke) is the base of the link;
without it the caller's Origin header is used. The mail password is never
logged or returned; a refused login surfaces as "the mail server refused our
login — check SMTP_USER / SMTP_PASSWORD".

## The other ways to reset (no mail needed)

- **An admin in Settings → Team**: open the person, set a new password, save
  (`PATCH /api/admin/agents/{id}` with `password`; needs `manage_agents`).
- **The person, signed in, under Profile → Change password.**
- **On the box, as a last resort** (inside the api container):

  ```sh
  docker compose exec api python -c "
  import asyncio, sys
  from sqlalchemy import select
  from app.database import AsyncSessionLocal
  from app.models.agent import Agent
  from app.core.security import hash_password
  async def go(email, pw):
      async with AsyncSessionLocal() as db:
          a = (await db.execute(select(Agent).where(Agent.email == email))).scalar_one()
          a.password_hash = hash_password(pw); await db.commit(); print('reset', a.email)
  asyncio.run(go(sys.argv[1], sys.argv[2]))" 'mwicigimoses@gmail.com' 'NEW-PASSWORD'
  ```

Tests: `tests/test_password_reset.py` (mailer, helpers),
`tests/test_password_reset_db.py` (the whole flow on a real database).
