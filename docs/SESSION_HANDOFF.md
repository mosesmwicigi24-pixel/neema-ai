# Session handoff — neema multichannel + identity epic

Portable context for continuing work on another device (e.g. iPad via
claude.ai/code). The code is all in git; this file carries the "what we were
doing" that a fresh session otherwise wouldn't have.

Repo: `mosesmwicigi24-pixel/neema-ai`

## How to deploy (read this before pushing)

UI-refresh work happens on branch **`feat/ui-refresh`**. Deploy by pushing it to
`main`, but only after the gated check:

1. `git fetch origin`
2. If `origin/main` advanced, `git merge origin/main --no-edit` (a concurrent
   backend session pushes here too — never revert it).
3. Confirm it's a fast-forward, then `git push origin feat/ui-refresh:main`.

CI ("Build & Push", `.github/workflows/deploy.yml`) builds the GHCR images on
every push to `main`. **Nobody deploys by hand after that.** The VPS runs
`scripts/box-deploy.sh` itself on a systemd timer every 2 minutes
(`deploy/neema-deploy.timer`): it fetches `origin/main`, pulls the images, and
recreates the containers only when something changed. Merge to `main` and the
change is live within about five minutes — roughly three for the build, then
the next timer tick. (The old "SSH in and run box-deploy.sh" step is gone; the
timer replaced it because the Hostinger edge intermittently blocks inbound
SSH from GitHub runners, so the box pulls instead of being pushed to.)

**To confirm a deploy landed**, read the running commit from the public health
endpoint — it is the git sha baked into the image at build time:

```
curl -s https://neema.bethanyhouse.co.ke/api/health
# {"status":"ok","version":"<sha of origin/main>","agent":{"replies":"ok"}}
```

If `version` still shows the previous sha five minutes after the merge, check
the Build & Push run on `main` before anything else. The same endpoint reports
`agent.replies` — `"failing"` with a `kind` (`credit`, `auth`, `meta`, …) means
Neema cannot answer and says why; it clears itself the moment a turn succeeds.

**Hard rule:** the box brings services up with BOTH compose files
(`docker-compose.yml` + `docker-compose.vps.yml`) — never a plain
`docker compose up` (that caused a 502 outage once). `box-deploy.sh` already
does this correctly, which is one more reason not to run compose by hand.

## How to verify

- **Web:** `cd apps/web && node_modules/.bin/tsc --noEmit` (exit 0) +
  `node_modules/.bin/next build` (Compiled successfully). `next build` does NOT
  run eslint, so pre-existing lint errors don't block.
- **Backend:** CI gates every PR (`.github/workflows/ci.yml`): the full pytest
  suite (~1,200 tests), a **ruff ratchet** (the finding count must never grow —
  baseline in `.ci/ruff-baseline.txt`), an alembic single-head + fresh-DB
  replay, and an import smoke test that catches crash-loops. Run the same
  things locally before pushing, exactly as CI does:

  ```
  cd apps/api
  pip install -r requirements-dev.txt
  DATABASE_URL=postgresql+asyncpg://neema:neema@127.0.0.1:5432/neema \
  DATABASE_URL_SYNC=postgresql+psycopg2://neema:neema@127.0.0.1:5432/neema \
  SECRET_KEY=ci-not-a-real-secret python -m pytest -q -rs
  ruff check . --output-format=json | python -c "import json,sys;print(len(json.load(sys.stdin)))"
  ```

  `python -m pytest`, never bare `pytest` — there is no conftest, so only the
  `-m` form puts `apps/api` on `sys.path`. One test needs a live Postgres and
  skips locally; CI's migrations job covers it. (If your local machine is stuck
  on Python 3.9 the suite won't run there; a remote session has 3.11+.)

## Recently shipped (all on `main`; live within ~5 min of merge — see above)

- **Font switch** → Manrope / DM Serif Display / DM Mono across the admin UI.
- **Inbox polish** — channel-tab count badges no longer cropped; handoff/system
  events show in the Activity Log only (not inline in the thread).
- **Customer panel** recolored gold → dark navy; full country name instead of
  ISO code; human/agent reply bubbles are green (`#2ad113`); **Lead Pipeline**
  rendered as a horizontal gold stepper (goldenrod `#c89b3c` / `#a97c14`).
- **Facebook channel split** — FB page comments now use `channel="facebook"`
  (distinct from Messenger DMs = `messenger`); new **FB** inbox tab + MSG tab,
  wired through the `Channel` type, `META_CHANNELS`, and cross-channel chips.
- **Inbound Meta media** now captured (images were showing as `[fallback]`
  text) and **re-hosted** to `/var/neema/media` so Meta's expiring CDN links
  become permanent (`services/meta_media.py`, background off the webhook ack).

## Open / next

- Nothing to run — the timer deploys `main`. Confirm the `version` sha at
  `/api/health`, then hard-refresh (⌘+Shift+R) on `neema.bethanyhouse.co.ke`.
- Review on the live site: the FB tab, inbound image rendering, and the Lead
  Pipeline stepper (gold shade + label spacing in the narrow sidebar).
- Media re-host + FB-channel changes affect **new** activity only; conversations
  captured before deploy keep their old channel / expired-CDN media.

## Guardrails still in effect

- Never paste secrets/tokens/full `.env` into chat; secrets live on the box
  `.env` only.
- Never push WIP to `main` without the gated fast-forward check above.
- Concurrent sessions share git worktrees — work in a dedicated worktree per
  branch to avoid mixing uncommitted files.
