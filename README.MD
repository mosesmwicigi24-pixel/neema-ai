# Neema AI 🤖

> **WhatsApp AI sales agent for e-commerce** — handles customer conversations and orders end-to-end, with a real-time dashboard for human-in-the-loop control.

---

## Overview

Neema AI is a full-stack platform that powers conversational sales over WhatsApp. Customers interact naturally via WhatsApp, while the AI handles the conversation autonomously. Human agents can monitor, intercept, and take over any conversation in real time through aN admin dashboard.

---

## Architecture

```
WhatsApp / Messenger / Instagram / Web chat
      │  (webhooks)
      ▼
  FastAPI (Python 3.12)   ◄──── Admin Dashboard (Next.js 15)
      │    the Neema agent (Claude, tool-calling) + REST + WebSocket
      ├── PostgreSQL 16  (conversations, orders, catalog)
      ├── Redis 7         (pub-sub, debounce, session cache)
      ├── WhatsApp API    (outbound messages, calls)
      └── Bethany House hub (catalogue, orders, payments)
```

> n8n orchestrated the WhatsApp pipeline until 2026-07-30; everything now runs
> natively in the API (`app/services/wa_native.py`, `app/agent/`). See
> `docs/N8N_REPLACEMENT.md` for the migration record.

### Services

| Service | Stack | Purpose |
|---------|-------|---------|
| **AI Agent** | Anthropic Claude (tool-calling) | Conversational sales, cart management, order flow |
| **FastAPI** | Python 3.12, asyncpg | Channel webhooks, agent runtime, REST API, WebSocket |
| **Next.js** | Next.js 15, Tailwind | Admin dashboard UI |
| **PostgreSQL** | v16 | Persistent data store |
| **Redis** | v7 | Real-time pub-sub, session caching |
| **Nginx** | v1.27 | Reverse proxy, TLS termination |

---

## Features

- 💬 **Conversational AI** — AI powered agent handles the full order journey over WhatsApp
- 👤 **Customer Memory** — persistent customer history, preferences, and past orders
- 🎯 **Mood & Intent Analysis** — AI classifies tone, detects cart signals, routes actions
- 🧑‍💼 **Human-in-the-Loop** — agents can intercept, reply, approve AI drafts, or transfer conversations
- ⚡ **Real-time Dashboard** — live WebSocket updates, conversation threads, intercept controls
- 📦 **Product Catalog** — searchable catalog with SKU aliases, pricing, and stock management
- 🔐 **Role-based Access** — Admin / Agent / Read-only roles with JWT auth
- 🐳 **Fully Dockerised** — single `docker compose up` for the entire platform

---

## Prerequisites

Install on your host machine before starting:

| Tool | Min Version | Purpose |
|------|------------|---------|
| Docker Desktop | 24.x | Container runtime |
| Docker Compose | v2.24+ | Multi-service orchestration |
| Python | 3.12 | Local Alembic CLI only |
| Node.js | 20 LTS | Next.js scaffolding only |
| pnpm | 9.x | Frontend package manager |
| Git | 2.x | Version control |

---

## Quick Start

### 1. Clone the repo

```bash
git clone https://github.com/ngigi-nyoro/neema-ai.git
cd neema-ai
```

### 2. Configure environment variables

```bash
cp .env.example .env
```

Edit `.env` and fill in all required values (see [Environment Variables](#environment-variables) below).

### 3. Generate TLS certificates (local dev)

```bash
mkdir -p nginx/certs
openssl req -x509 -newkey rsa:4096 \
  -keyout nginx/certs/privkey.pem \
  -out nginx/certs/fullchain.pem \
  -days 365 -nodes \
  -subj '/CN=localhost'
```

### 4. Start all services

```bash
docker compose up -d
```

This will start PostgreSQL, Redis, FastAPI (with auto-migrations), Next.js, and Nginx.

### 5. Seed the product catalog

```bash
docker compose cp db/seed.sql postgres:/tmp/seed.sql
docker compose exec postgres psql -U neema -d neema -f /tmp/seed.sql
```

### 6. Point the Meta webhooks at the API

WhatsApp callback: `https://your-domain.com/api/wa/webhook` — Messenger/Instagram:
`https://your-domain.com/api/meta/webhook` (verify tokens from your `.env`).

### 7. Access the dashboard

```
https://your-domain.com
```

---

## Environment Variables

All secrets live in `.env` at the project root. Never commit this file — only `.env.example` is committed.

```env
# PostgreSQL
POSTGRES_DB=neema
POSTGRES_USER=neema
POSTGRES_PASSWORD=your_strong_password

DATABASE_URL=postgresql+asyncpg://neema:password@postgres:5432/neema
DATABASE_URL_SYNC=postgresql+psycopg2://neema:password@postgres:5432/neema

# Redis
REDIS_URL=redis://redis:6379/0

# FastAPI
SECRET_KEY=your_jwt_secret
N8N_API_SECRET=your_hub_bridge_secret   # hub → /api/n8n/* pushes (legacy header name)
ANTHROPIC_API_KEY=your_anthropic_key

# WhatsApp Business API
WABA_TOKEN=your_meta_bearer_token
WABA_PHONE_NUMBER_ID=your_phone_number_id

# Next.js
NEXTAUTH_SECRET=your_nextauth_secret
NEXTAUTH_URL=https://your-domain.com
NEXT_PUBLIC_API_URL=https://your-domain.com/api
NEXT_PUBLIC_WS_URL=wss://your-domain.com
```

See `.env.example` for the full list with descriptions.

---

## Project Structure

```
neema-platform/
├── apps/
│   ├── api/                    # FastAPI backend
│   │   ├── app/
│   │   │   ├── main.py         # App factory
│   │   │   ├── database.py     # SQLAlchemy async engine
│   │   │   ├── core/           # Config, security, JWT
│   │   │   ├── models/         # SQLAlchemy ORM models
│   │   │   ├── schemas/        # Pydantic request/response schemas
│   │   │   ├── routers/        # Route handlers (admin, auth, webhooks, hub bridge, websocket)
│   │   │   ├── agent/          # The Neema agent (prompt, tools, runtime)
│   │   │   └── services/       # Business logic (wa_native, intercept, WABA, Redis)
│   │   └── alembic/            # Database migrations
│   └── web/                    # Next.js 15 admin dashboard
│       └── src/
│           ├── app/            # App Router pages
│           └── components/     # UI components
├── db/
│   └── seed.sql                # Product catalog seed data
├── nginx/
│   └── nginx.conf              # Reverse proxy config
├── .env.example
├── docker-compose.yml
└── docker-compose.dev.yml      # Dev overrides (hot reload, exposed ports)
```

---

## Contributing & Deployment Workflow

**GitHub is the single source of truth** — `https://github.com/mosesmwicigi24-pixel/neema-ai`.
The server never receives direct edits; every change lands via this flow:

1. Branch from `main`, make your change, commit.
2. Open a **pull request** — CI builds both Docker images as a check.
3. Merge to `main` — GitHub Actions builds `neema-ai-api` and `neema-ai-web`
   and pushes them to GHCR (tagged `latest` + commit SHA for rollback).
4. The **VPS deploys itself**: a systemd timer (`deploy/neema-deploy.timer`)
   runs `scripts/box-deploy.sh` every 2 minutes — it fast-forwards
   `/home/neema/neema-ai` to `origin/main`, pulls the new GHCR images, and
   recreates `api` + `web` only if the git ref or an image digest changed,
   then health-checks `/api/health`. Deploy lands within ~2 min of merge.

**Why pull-based, not SSH push?** This shared box sits behind a host firewall
that intermittently drops GitHub-runner IPs on port 22, so an Actions→box SSH
push was unreliable. Outbound pulls from the box are unaffected. This requires
the two GHCR packages to be **public** (so the box pulls anonymously — no
registry credentials stored on the shared box).

Rollback: `IMAGE_TAG=<old-sha> docker compose -f docker-compose.yml -f docker-compose.vps.yml up -d --no-deps api web` on the server.

---

## Development

Use the dev compose override for hot reload and exposed ports:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up
```

| Service | Dev URL |
|---------|---------|
| Next.js Dashboard | http://localhost:3000 |
| FastAPI | http://localhost:8000 |
| PostgreSQL | localhost:5432 |
| Redis | localhost:6379 |

### Running migrations locally

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install alembic sqlalchemy asyncpg psycopg2-binary

cd apps/api
alembic revision --autogenerate -m "your_migration_name"
alembic upgrade head
```

---

## API Overview

### Auth
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/auth/login` | Agent login → returns JWT |
| POST | `/api/auth/refresh` | Refresh access token |

### Conversations
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/admin/conversations` | List all conversations |
| GET | `/api/admin/conversations/{id}/messages` | Get message thread |
| POST | `/api/admin/conversations/{id}/intercept` | Take over from AI |
| POST | `/api/admin/conversations/{id}/reply` | Send agent reply |
| POST | `/api/admin/conversations/{id}/approve-draft` | Approve AI draft |
| POST | `/api/admin/conversations/{id}/release` | Hand back to AI |
| POST | `/api/admin/conversations/{id}/transfer` | Transfer to another agent |

### Hub bridge (internal — legacy `/api/n8n` prefix)
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/n8n/payment` | Hub relays a captured M-Pesa payment (identity reconcile) |
| POST | `/api/n8n/order-event` | Hub pushes an order event |
| POST | `/api/n8n/customer-history` | Hub pushes a customer-history snapshot |

### WebSocket
```
wss://your-domain.com/ws/{agent_id}
```
Receives real-time events: `new_message`, `intercept_changed`, `order_updated`.

---

## The message lifecycle (native)

Every inbound WhatsApp message flows through `app/services/wa_native.py`:

1. **Webhook** — `/api/wa/webhook` verifies the Meta signature
2. **Parse + persist** — events parsed, messages saved, wamids deduped
3. **Debounce** — rapid messages combined (default 15s) and answered once
4. **Guards** — human-intercept, pause, and document-request escalation
5. **Agent turn** — the Neema agent (Claude, tool-calling) composes the reply
6. **Send via WABA** — delivered to WhatsApp, broadcast to the dashboard

Messenger/Instagram ride `/api/meta/webhook`; the storefront chat rides
`/api/web/chat` — same agent, same guards.

---

## Production Deployment

> **Note (live deployment):** at neema.bethanyhouse.co.ke the bundled nginx
> service is disabled — the host-level nginx terminates TLS (certbot) and
> proxies `/api/auth/*` → Next.js :3000, `/api/*` + `/ws` → FastAPI :8000,
> and `/` → Next.js :3000. The compose nginx is only for standalone installs.

### TLS — Let's Encrypt

```bash
sudo certbot certonly --standalone -d your-domain.com
# Copy certs to nginx/certs/
sudo crontab -e
# Add: 0 0 * * * certbot renew --quiet && docker compose kill -s HUP nginx
```

### Start production stack

```bash
docker compose up -d --build
```

---

## Tech Stack

- **AI** — Anthropic Claude (tool-calling agent; light model for trivial turns)
- **Backend** — FastAPI, SQLAlchemy (async), Alembic, Redis pub-sub
- **Frontend** — Next.js 15, NextAuth, Tailwind CSS, Socket.IO
- **Database** — PostgreSQL 16
- **Messaging** — WhatsApp Business Cloud API (Meta)
- **Infrastructure** — Docker Compose, Nginx, Let's Encrypt

---

## License

MIT — see [LICENSE](LICENSE) for details.