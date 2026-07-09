# CLAUDE.md — Neema AI

Guidance for AI assistants (and humans) working in this repository. Read this before making changes.

## What this is

**Neema AI** is a multi-channel **AI sales agent for e-commerce**, built for **Bethany House** (a Christian clergy/communion/vestments store — cassocks, communion cups, anointing oil, etc.). It runs customer sales conversations end-to-end (browse catalogue → build cart → confirm order → payment link) autonomously, backed by a real-time **admin dashboard** where human agents monitor, intercept, and take over conversations ("human-in-the-loop").

Channels:
- **WhatsApp** — primary, the only checkout-capable channel.
- **Facebook Messenger, Instagram DMs, and FB/IG post comments** — read-only for sales (no cart/order/payment). The agent answers from the same catalogue and drives buyers to WhatsApp via one-tap `wa.me` deep links to check out.

The **Bethany House hub** (`https://hub.bethanyhouse.co.ke`) is the **single source of truth** for catalogue, pricing, stock, and orders. Neema pushes confirmed orders to it and fetches M-Pesa / payment links back (`apps/api/app/core/hub_client.py`).

**Currency gate:** Kenya (`+254`) customers are quoted **KES**; everyone else — and all Messenger/Instagram, which have no phone number — is quoted **USD** (= round(KES / `usd_kes_rate`, default 100), preferring the hub's own `price_usd`).

> ⚠️ **README vs. code:** `README.MD` describes the AI as running in **n8n with OpenAI GPT-5** ("Tier 1"). The code has since grown a **"Tier 2" agent that runs inside FastAPI using Anthropic Claude** with tool-calling. Both tiers coexist behind per-`wa_id` flags. **Trust the code (`apps/api/app/agent/`) for the AI layer** — the README's AI section is partly stale. n8n is now largely a thin WhatsApp relay that forwards inbound messages to the API and stays silent when the sender is Tier 2.

## Repository layout

pnpm monorepo, but only `apps/web` is a pnpm workspace (`pnpm-workspace.yaml`). **There is no root `package.json`.** The Python API is not a pnpm package.

```
apps/
  api/            FastAPI backend, Python 3.12 — the core service
  web/            Next.js 16 admin dashboard, TypeScript (the only pnpm package, name: "web")
db/seed.sql       Product catalog seed data
deploy/           systemd unit + timer for the pull-based VPS deployer
docs/             Design/plan markdown (see below)
n8n/              Exported n8n workflow JSON (auto-synced from live editor by CI)
nginx/nginx.conf  Reverse proxy for standalone installs only (disabled in prod)
scripts/
  box-deploy.sh   The VPS pull-deployer
  hub/            Hub integration helpers (backfill_aliases.php, README.md)
docker-compose*.yml
.github/workflows/  deploy.yml, n8n-sync.yml
```

Design/plan docs worth reading before touching those areas: `docs/MULTICHANNEL_SCOPE.md`, `docs/MULTICHANNEL_IDENTITY_PLAN.md`, `docs/PAYMENT_RECONCILE_CONTRACT.md`, `docs/UI_REFRESH_PLAN.md`.

### `apps/api/app/`
- `main.py` — FastAPI app factory + lifespan (Redis connect, **startup DDL migrations** for `custom_roles`).
- `core/` — `config.py` (Pydantic `Settings`), `security.py` (JWT), `phone.py`, `countries.py`, `ai_pricing.py`, `hub_client.py` (order push / payment link / status), `database.py`.
- `models/` — SQLAlchemy ORM (async, `DeclarativeBase`): `conversations`, `catalog`, `users`, `ai_usage`, `customer_history`, `order_events`, `sessions`, `intercepts`, `messages`, `persons`, `identities`, `identifiers`, `person_merges`, `agents` (+ `custom_roles`, created at runtime in `main.py`).
- `schemas/` — Pydantic request/response DTOs (`auth`, `n8n`, `conversation`).
- `routers/` — `health`, `auth`, `admin`, `crm`, `roles`, `n8n_bridge`, `meta_webhook`, `agent` (Tier 2), `websocket`, `media`. Mounted under `/api/*`.
- `services/` — `n8n_bridge`, `meta_send`, `meta_media`, `channel`, `merge`, `lead_signals`, `identity`, `conversation`, `reconcile`, `redis`.
- `agent/` — **Tier 2 Claude agent**: `runtime.py` (turn loop), `llm.py` (`AnthropicLLM`), `tools.py` (11 tool defs), `cart.py`, `prompt.py` (system prompt), `memory.py` (cross-conversation memory), `media.py` (Claude vision image blocks).
- `jobs/reengage.py` — re-engagement sweep for customers waiting ≤24h.
- `alembic/` — migrations (`env.py` reads `DATABASE_URL`), `seeds.py`, `alembic.ini`.
- `tests/` — 19 pytest files.

### `apps/web/src/`
- `app/` — App Router: `(dashboard)/layout.tsx`, `login/page.tsx`, `dashboard/page.tsx`, `api/auth/[...nextauth]/route.ts`, `layout.tsx`, `globals.css`.
- `components/views/` — main screens: `ConversationsView`, `OrdersView`, `OverviewView`, `CatalogView`, `ReportsView`, `LeadsView`, `ProfileView`, `SettingsView`, `AgentsView`.
- `components/ui/` — shadcn/ui + custom components.
- `lib/` — `api.ts`, `auth.ts` (NextAuth), `websocket.tsx`, `roles.ts`, `permissions.ts`, `channels.tsx`, `waText.tsx`, `themes.ts`.
- `hooks/` — `useApi.ts`, `useIsMobile.ts`.

## Tech stack

**Backend** (`apps/api`, Python 3.12, `requirements.txt`): FastAPI 0.115, uvicorn[standard], SQLAlchemy 2.0 [asyncio] + asyncpg (async driver) / psycopg2-binary (Alembic sync), Alembic, redis 5, pyjwt, passlib[bcrypt], pydantic 2 + pydantic-settings, httpx (WABA/Meta/hub calls), phonenumbers (E.164 identity), and both the **`openai`** and **`anthropic`** SDKs (anthropic powers Tier 2). Dev: pytest + pytest-asyncio (`requirements-dev.txt`).

**Frontend** (`apps/web`, `packageManager: pnpm@10.30.1`): Next.js 16.1.6, React 19.2, next-auth 4, next-themes, @tanstack/react-query 5, axios, zustand 5, socket.io-client 4 (WebSocket), Tailwind CSS **v4** (`@tailwindcss/postcss`), radix-ui, shadcn, lucide-react, recharts, sonner, date-fns. TypeScript `strict`, path alias `@/* → ./src/*`.

**Infra:** PostgreSQL 16, Redis 7, pgAdmin, Nginx, Docker Compose, n8n (Tier 1 workflows). Node 20 LTS.

## Build / dev / test commands

**Whole stack (local, recommended):**
```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up
```
Dev override gives hot-reload for api (`uvicorn --reload`, runs `alembic upgrade head` + seeds on start) and web (`pnpm run dev`). Ports: web `:3000`, api `:8000`, Postgres `:5432`, Redis `:6379`, pgAdmin `:5051`, n8n `:5678`.

**Web** (`cd apps/web`):
```bash
pnpm run dev      # next dev --webpack
pnpm run build    # next build --webpack  (also the de-facto typecheck)
pnpm run start    # next start
pnpm run lint     # eslint
```
There is **no `test` or `typecheck` script** for web. Type errors surface via `next build`; run `pnpm exec tsc --noEmit` manually if you want a standalone check.

**API** (`cd apps/api`, no npm scripts):
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload   # dev server
pytest                                                     # tests (pytest-asyncio, run from apps/api)
```
Prod entry (Dockerfile CMD): `python -m alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 2`. There is no `pytest.ini`/`pyproject.toml`/`conftest.py` — always run `pytest` from `apps/api`.

**Migrations (Alembic, from `apps/api`):**
```bash
alembic revision --autogenerate -m "name"
alembic upgrade head
```
`alembic.ini` leaves `sqlalchemy.url` blank; `env.py` reads `DATABASE_URL` from `.env`. **Note:** `app/main.py` *also* runs idempotent DDL at startup (the `custom_roles` table + role seeds), independent of Alembic — the schema is managed by **both** mechanisms. Catalog seed: `docker compose exec postgres psql -U neema -d neema -f /tmp/seed.sql` (after copying `db/seed.sql` in).

## How a turn works (message flow)

**WhatsApp:** WhatsApp Business Cloud API → n8n webhook → n8n forwards to FastAPI `POST /api/agent/turn` (authed via `x-n8n-secret`, checked by `verify_n8n_secret`). If the sender `is_tier2()`, the **Claude loop** in `agent/runtime.py::run_turn` builds system prompt + memory + last 20 messages, calls Claude with tools, executes tool calls (max `tier2_max_iterations=8`), sends the reply via WABA (`services.n8n_bridge._send_waba`), persists it, refreshes lead signals, and returns `routed=true`. Otherwise it returns `routed=false` and n8n runs the Tier 1 GPT-5 flow.

**Meta channels** (`routers/meta_webhook.py`): GET verify handshake (`meta_verify_token`) + signed POSTs (`X-Hub-Signature-256` via `meta_app_secret`). Inbound DMs → `runtime.schedule_meta_reply` (background task, deduped in Redis by Meta message id). Comments → `runtime.schedule_comment_engage`: a light Claude call classifies intent (high/low/negative/spam), then plans a public reply + private DM opener. Inbound Meta media is **re-hosted** so image URLs don't expire (`services/meta_media.py`). Meta sends put the **Page token in the Authorization header, never the URL**.

**Agent tools** (`agent/tools.py`, Anthropic tool schema): `search_catalog`, `get_cart`, `update_cart`, `create_order`, `check_order_status`, `capture_customer`, `add_tags`, `set_lead_source`, `remember`, `handoff_to_human`, `whatsapp_checkout_link`. Meta channels get a **read-only subset**: `{search_catalog, remember, handoff_to_human, whatsapp_checkout_link}`. Pricing, stock, and order creation are **server-authoritative** via `core/hub_client.py` — the model never invents prices.

**Data stores:** PostgreSQL 16 (async via asyncpg; ~15 app tables, n8n's own schema lives in the same instance). Redis 7 for pub-sub (WebSocket events), session cache, agent dedup keys (`agent:seen:*`), and `waref:*` attribution links. WebSocket at `wss://…/ws/{agent_id}` emits `new_message`, `intercept_changed`, `order_updated`.

**Identity spine:** the same person is reconciled across phone / PSID / IGSID via `models/person.py` (`persons`, `identities`, `identifiers`, `person_merges`) and `services/identity.py` + `services/merge.py`. See `docs/MULTICHANNEL_IDENTITY_PLAN.md`.

## Conventions

**Commits** — Conventional Commits, scoped, lowercase, imperative, specific and product-oriented (often with an em-dash + rationale):
```
feat(meta): name social leads + answer logistics — profile enrichment + biz facts
fix(channel): capture inbound Meta media so images render
style(web): human/agent reply bubbles now green
```
Types seen: `feat`, `fix`, `style`. Scopes: `meta`, `channel`, `web`, `agent`, `jobs`, `agent+web`.

**Python style:** heavy explanatory block comments (the "why"), `from __future__ import annotations`, dataclasses for context objects, module-level loggers namespaced `neema.agent` / `neema.hub` / `neema.startup`, defensive `try/except` around Redis/hub/tool calls (**never crash the turn**), section banners `# ── … ──`.

**TS/React style:** `@/*` path alias, shadcn/ui conventions (`components.json`), screens under `components/views/`, feature-flagged UI.

**Config/env:** all runtime config flows through the Pydantic `Settings` in `core/config.py` reading `.env` (`extra="ignore"`). **Feature flags default OFF/safe** (`meta_agent_reply=False`, `meta_comment_reply=False`; the Meta webhook is inert until `meta_verify_token` is set). `.env.example` documents every var. **Never commit `.env`.** Tier 2 rollout is gated by `tier2_enabled_wa_ids` / `tier2_all`.

## Deployment — read before pushing

> 🚨 **`main` auto-deploys to production within ~2 minutes.** Keep work-in-progress off `main`. Your designated working branch is `claude/claude-md-docs-51n3sn`.

- **CI (`.github/workflows/deploy.yml`)**: on push/PR to `main`, builds two Docker images (`apps/api` and `apps/web`, target `runner`) with buildx + GHA cache, and on push pushes them to **GHCR**: `ghcr.io/mosesmwicigi24-pixel/neema-ai-api` and `…/neema-ai-web`, tagged `latest` + commit SHA. **CI does not deploy** — it only builds/pushes images. Web build args bake in `NEXT_PUBLIC_API_URL=https://neema.bethanyhouse.co.ke/api` and `NEXT_PUBLIC_WS_URL`. The two GHCR packages must be public.
- **Pull-based deploy** (`scripts/box-deploy.sh` + `deploy/neema-deploy.timer`/`.service`): a systemd timer on the VPS runs every 2 min. It `git fetch/reset --hard origin/main`, `docker compose … pull api web`, recreates api+web **only if** the git ref or an image digest changed, then health-checks `http://127.0.0.1:8000/api/health` (10×6s), guarded by `flock`. (Pull-based because the host firewall drops GitHub-runner IPs on port 22.) A merge lands in prod ~2 min later.
- **Compose files:** `docker-compose.yml` is the base (postgres, redis, pgadmin, api, web; `nginx` and `n8n` services are **commented out** — in prod a host-level nginx terminates TLS and n8n runs separately). `docker-compose.vps.yml` is the prod override (pulls GHCR `${IMAGE_TAG:-latest}`, publishes api/web on `127.0.0.1` only). `docker-compose.dev.yml` is the dev override.
- **Rollback:** `IMAGE_TAG=<old-sha> docker compose -f docker-compose.yml -f docker-compose.vps.yml up -d --no-deps api web`.
- **Prod host:** `neema.bethanyhouse.co.ke`. Host nginx (certbot TLS) routes `/api/auth/*` → Next.js `:3000`, `/api/*` + `/ws` → FastAPI `:8000`, `/` → Next.js `:3000`.
- **n8n sync (`.github/workflows/n8n-sync.yml`)**: every 6h (+ manual), SSHes to the VPS, exports active n8n workflows, redacts secrets, and opens a PR (label `n8n-sync`) when `n8n/*.json` changed — live workflow edits stay reviewable in git. **Don't hand-edit `n8n/*.json`**; edit in the n8n UI and let the sync PR capture it.

## Gotchas

1. **`main` = production** (~2 min lag). Never push WIP there.
2. **README's AI section is stale** (n8n/GPT-5 only). The live AI layer is the in-API Claude "Tier 2" agent — see `apps/api/app/agent/`.
3. **Schema is managed by both Alembic and startup DDL** in `main.py`. When adding tables/columns, prefer an Alembic migration; be aware the `custom_roles` bootstrap runs at startup regardless.
4. **Two GHCR namespaces appear in docs** — the authoritative one is `ghcr.io/mosesmwicigi24-pixel`.
5. **Pricing/stock/orders are hub-authoritative.** Never let the agent (or new code) fabricate prices, stock, or order state — always go through `core/hub_client.py`.
6. **Money never flows through Meta channels.** Cart/order/payment tools are WhatsApp-only; Meta gets the read-only tool subset.
