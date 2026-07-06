# Neema AI 🤖

> **WhatsApp AI sales agent for e-commerce** — handles customer conversations and orders end-to-end, with a real-time dashboard for human-in-the-loop control.

---

## Overview

Neema AI is a full-stack platform that powers conversational sales over WhatsApp. Customers interact naturally via WhatsApp, while the AI handles the conversation autonomously. Human agents can monitor, intercept, and take over any conversation in real time through aN admin dashboard.

---

## Architecture

```
WhatsApp (WABA)
      │
      ▼
   n8n Workflow  ──────────────────────────────────────────────┐
      │  (AI Agent, analyseGPT, context compose)         │
      │                                                         │
      ▼                                                         │
  FastAPI (Python 3.12)   ◄──── Admin Dashboard (Next.js 15)  │
      │    REST + WebSocket                                      │
      ├── PostgreSQL 16  (conversations, orders, catalog)        │
      ├── Redis 7         (pub-sub, session cache)               │
      └── WhatsApp API    (outbound messages)                    │
                                                                 │
  n8n ◄────────────────────────────────────────────────────────┘
```

### Services

| Service | Stack | Purpose |
|---------|-------|---------|
| **n8n** | n8nio/n8n | WhatsApp trigger, AI agent orchestration, workflow automation |
| **AI Agent** | OpenAI GPT-5 | Conversational sales, cart management, order flow |
| **FastAPI** | Python 3.12, asyncpg | REST API, WebSocket, n8n bridge |
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

### 6. Update the n8n workflow

1. Open n8n and log in
2. Import `n8n/neema-assistant-main.json`
3. Update all HTTP Request node URLs to point to your FastAPI instance
4. Set `N8N_API_SECRET` in n8n environment variables
5. Activate the workflow

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
N8N_API_SECRET=your_n8n_bridge_secret

# WhatsApp Business API
WABA_TOKEN=your_meta_bearer_token
WABA_PHONE_NUMBER_ID=your_phone_number_id

# Next.js
NEXTAUTH_SECRET=your_nextauth_secret
NEXTAUTH_URL=https://your-domain.com
NEXT_PUBLIC_API_URL=https://your-domain.com/api
NEXT_PUBLIC_WS_URL=wss://your-domain.com

# n8n
N8N_BASIC_AUTH_USER=admin
N8N_BASIC_AUTH_PASSWORD=your_n8n_password
N8N_HOST=your-domain.com
WEBHOOK_URL=https://your-domain.com/n8n/
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
│   │   │   ├── routers/        # Route handlers (admin, auth, n8n bridge, websocket)
│   │   │   └── services/       # Business logic (intercept, WABA, Redis)
│   │   └── alembic/            # Database migrations
│   └── web/                    # Next.js 15 admin dashboard
│       └── src/
│           ├── app/            # App Router pages
│           └── components/     # UI components
├── db/
│   └── seed.sql                # Product catalog seed data
├── nginx/
│   └── nginx.conf              # Reverse proxy config
├── n8n/
│   └── Neema_Assistant.json    # n8n workflow export
├── .env.example
├── docker-compose.yml
└── docker-compose.dev.yml      # Dev overrides (hot reload, exposed ports)
```

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
| n8n Editor | http://localhost:5678 |
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

### n8n Bridge (internal)
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/n8n/context/{wa_id}` | Get customer context |
| POST | `/api/n8n/upsert-user` | Upsert user & state |
| POST | `/api/n8n/log-message` | Persist message |
| GET | `/api/n8n/check-intercept/{wa_id}` | Check if conversation is intercepted |

### WebSocket
```
wss://your-domain.com/ws/{agent_id}
```
Receives real-time events: `new_message`, `intercept_changed`, `order_updated`.

---

## n8n Workflow

The n8n workflow handles the complete inbound WhatsApp message lifecycle:

1. **WhatsApp Trigger** — receives inbound message
2. **Extract Sender** — normalises `wa_id`
3. **Get Context** — fetches customer state from FastAPI
4. **analyseGPT** — classifies intent, mood, cart signals
5. **Neema AI Agent** — GPT-5 generates reply with cart/order actions
6. **Check Intercept** — gates sending if a human has taken over
7. **Generate Response** — post-processes and formats the reply
8. **Send via WABA** — delivers the message to WhatsApp

To migrate from the Firestore version, replace all HTTP node URLs with FastAPI endpoints and switch auth from Firebase OAuth to the `x-n8n-secret` header.

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

- **AI** — OpenAI GPT-5 (agent), GPT-5-mini (analysis & history)
- **Automation** — n8n
- **Backend** — FastAPI, SQLAlchemy (async), Alembic, Redis pub-sub
- **Frontend** — Next.js 15, NextAuth, Tailwind CSS, Socket.IO
- **Database** — PostgreSQL 16
- **Messaging** — WhatsApp Business Cloud API (Meta)
- **Infrastructure** — Docker Compose, Nginx, Let's Encrypt

---

## License

MIT — see [LICENSE](LICENSE) for details.