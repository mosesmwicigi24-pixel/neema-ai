from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import redis.asyncio as aioredis

from app.core.config import settings
from app.routers import auth, admin, n8n_bridge, websocket, health, crm, roles
from app.database import AsyncSessionLocal
from sqlalchemy import text


# ── Startup migration ─────────────────────────────────────────────────────────
# Run DDL once at startup — not inside a request handler — so it executes
# before any traffic arrives and regardless of how many workers are running.

MIGRATION_STATEMENTS = [
    # Custom roles table
    """
    CREATE TABLE IF NOT EXISTS custom_roles (
        id          TEXT PRIMARY KEY,
        name        TEXT NOT NULL,
        description TEXT NOT NULL DEFAULT '',
        color       TEXT NOT NULL DEFAULT '#589b31',
        permissions JSONB NOT NULL DEFAULT '[]',
        protected   BOOLEAN NOT NULL DEFAULT FALSE,
        created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    # New columns on agents (safe — ADD COLUMN IF NOT EXISTS)
    "ALTER TABLE agents ADD COLUMN IF NOT EXISTS custom_role_id TEXT",
    "ALTER TABLE agents ADD COLUMN IF NOT EXISTS custom_permissions JSONB",
    # Seed: Super Admin (protected, cannot be modified)
    """
    INSERT INTO custom_roles (id, name, description, color, permissions, protected)
    VALUES (
        'super_admin', 'Super Admin',
        'Full platform access — cannot be modified',
        '#7c3aed',
        '["view_conversations","reply_conversations","intercept_release",
          "close_conversations","transfer_conversations","add_notes",
          "view_orders","manage_orders","view_catalog","manage_catalog",
          "view_leads","manage_leads","view_crm","edit_crm","view_analytics",
          "view_reports","export_reports","manage_agents","manage_roles",
          "manage_settings"]'::jsonb,
        TRUE
    ) ON CONFLICT (id) DO NOTHING
    """,
    # Seed: Agent
    """
    INSERT INTO custom_roles (id, name, description, color, permissions, protected)
    VALUES (
        'agent', 'Agent',
        'Handle conversations and orders',
        '#589b31',
        '["view_conversations","reply_conversations","intercept_release",
          "close_conversations","transfer_conversations","add_notes",
          "view_orders","manage_orders","view_catalog","view_crm","view_leads"]'::jsonb,
        FALSE
    ) ON CONFLICT (id) DO NOTHING
    """,
    # Seed: Viewer
    """
    INSERT INTO custom_roles (id, name, description, color, permissions, protected)
    VALUES (
        'viewer', 'Viewer',
        'Read-only access',
        '#699a32',
        '["view_conversations","view_orders","view_catalog",
          "view_crm","view_leads","view_analytics"]'::jsonb,
        FALSE
    ) ON CONFLICT (id) DO NOTHING
    """,
]


async def run_migrations():
    """Execute each DDL/seed statement individually (asyncpg cannot prepare multi-statement SQL)."""
    async with AsyncSessionLocal() as db:
        for stmt in MIGRATION_STATEMENTS:
            await db.execute(text(stmt))
        await db.commit()


# ── Lifespan ──────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Redis
    app.state.redis = aioredis.from_url(settings.redis_url, decode_responses=True)

    # Run schema migrations before serving any traffic
    await run_migrations()

    yield

    # Shutdown
    await app.state.redis.aclose()


# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Neema API",
    version="1.0.0",
    docs_url="/api/docs" if settings.environment != "production" else None,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router,     prefix="/api",       tags=["Health"])
app.include_router(auth.router,       prefix="/api/auth",  tags=["Auth"])
app.include_router(admin.router,      prefix="/api/admin", tags=["Admin"])
app.include_router(crm.router,        prefix="/api/admin", tags=["CRM"])
app.include_router(roles.router,      prefix="/api/admin", tags=["Roles"])
app.include_router(n8n_bridge.router, prefix="/api/n8n",   tags=["n8n Bridge"])
app.include_router(websocket.router,  prefix="",           tags=["WebSocket"])


@app.get("/api/health")
async def health_check(request):
    """Health check — validates DB + Redis connections."""
    try:
        await request.app.state.redis.ping()
        return {"status": "ok", "redis": "connected"}
    except Exception as e:
        return {"status": "degraded", "error": str(e)}