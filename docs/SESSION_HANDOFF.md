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

CI ("Build & Push") builds GHCR images. The VPS then pulls them:

```
./scripts/box-deploy.sh          # on the box, over SSH
```

**Hard rule:** the box brings services up with BOTH compose files
(`docker-compose.yml` + `docker-compose.vps.yml`) — never a plain
`docker compose up` (that caused a 502 outage once). `box-deploy.sh` already
does this correctly.

## How to verify

- **Web:** `cd apps/web && node_modules/.bin/tsc --noEmit` (exit 0) +
  `node_modules/.bin/next build` (Compiled successfully). `next build` does NOT
  run eslint, so pre-existing lint errors don't block.
- **Backend:** there is **no test gate** — CI only builds images, and the local
  machine has Python 3.9 (codebase needs 3.11+), so pytest can't run locally.
  Verify by syntax-checking (`python3 -m py_compile`), tracing the code path,
  and running any pure/standalone logic in isolation.

## Recently shipped (all on `main`; live only after `box-deploy.sh`)

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

- Run `./scripts/box-deploy.sh` to make the above live, then hard-refresh
  (⌘+Shift+R) on `neema.bethanyhouse.co.ke`.
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
