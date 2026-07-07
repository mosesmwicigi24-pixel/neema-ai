from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import redis.asyncio as aioredis

from app.core.config import settings
from app.routers import auth, admin, n8n_bridge, websocket, health, crm, roles, media, agent
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
    import logging
    logger = logging.getLogger("neema.startup")
    # Surface Tier 2 agent + hub activity (tool calls, order pushes) at INFO so
    # live turns are observable; the root logger otherwise sits at WARNING.
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("%(levelname)s [%(name)s] %(message)s"))
    for _name in ("neema.agent", "neema.hub"):
        _lg = logging.getLogger(_name)
        _lg.setLevel(logging.INFO)
        _lg.addHandler(_h)
        _lg.propagate = False

    # ── Redis ─────────────────────────────────────────────────────────────────
    # Connect and immediately verify the node is writable (i.e. a primary, not
    # a read replica).  A replica raises ReadOnlyError on any write command,
    # which would otherwise crash the first request that tries to cache/publish.
    redis = aioredis.from_url(
        settings.redis_url,
        decode_responses=True,
        socket_connect_timeout=5,
        socket_timeout=5,
    )
    try:
        await redis.ping()
        # Write a throw-away key to confirm this node accepts writes.
        await redis.set("__startup_write_check__", "1", ex=10)
        await redis.delete("__startup_write_check__")
        logger.info("Redis: connected to writable primary ✓")
    except Exception as exc:
        # Log clearly so the error is obvious in deployment logs, but don't
        # crash — the app can still serve requests; Redis failures are handled
        # defensively throughout the codebase.
        logger.error(
            "Redis startup check failed — is REDIS_URL pointing at a read "
            f"replica instead of the primary?  Error: {exc}"
        )
    app.state.redis = redis

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
app.include_router(agent.router,      prefix="/api/agent", tags=["Tier 2 Agent"])
app.include_router(websocket.router,  prefix="",           tags=["WebSocket"])
app.include_router(media.router,      prefix="/api",       tags=["Media"])


@app.get("/api/health")
async def health_check(request):
    """Health check — validates DB + Redis connections."""
    try:
        await request.app.state.redis.ping()
        return {"status": "ok", "redis": "connected"}
    except Exception as e:
        return {"status": "degraded", "error": str(e)}