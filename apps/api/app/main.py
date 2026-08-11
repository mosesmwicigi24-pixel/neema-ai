import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import redis.asyncio as aioredis

from app.core.config import settings
from app.routers import auth, admin, n8n_bridge, websocket, health, crm, roles, media, meta_webhook, public, short_link, whatsapp_webhook, web_chat, analytics, hub_events
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
    # Source-post context for Facebook/Instagram comment messages (see
    # models/message.py) — lets the inbox show WHAT a comment is replying to.
    "ALTER TABLE messages ADD COLUMN IF NOT EXISTS comment_context JSONB",
    # Made-to-order enquiries from the public measurement form (see
    # models/production_enquiry.py). Reviewed in the inbox, then pushed to the hub.
    """
    CREATE TABLE IF NOT EXISTS production_enquiries (
        id               UUID PRIMARY KEY,
        created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        product_slug     TEXT,
        product_name     TEXT,
        hub_product_id   BIGINT,
        customer_name    TEXT,
        phone            TEXT,
        country_iso      TEXT,
        measurements     JSONB NOT NULL DEFAULT '{}',
        notes            TEXT,
        location         TEXT,
        conversation_id  UUID REFERENCES conversations(id) ON DELETE SET NULL,
        person_id        UUID REFERENCES persons(id) ON DELETE SET NULL,
        status           TEXT NOT NULL DEFAULT 'new',
        hub_order_id     BIGINT,
        hub_order_number TEXT
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_prod_enq_conv ON production_enquiries (conversation_id)",
    "CREATE INDEX IF NOT EXISTS ix_prod_enq_status ON production_enquiries (status)",
    # Call recording + transcript + AI summary (see models/call.py). Idempotent so
    # the columns exist even if the alembic state on the box is behind.
    "ALTER TABLE calls ADD COLUMN IF NOT EXISTS recording_url VARCHAR(500)",
    "ALTER TABLE calls ADD COLUMN IF NOT EXISTS transcript TEXT",
    "ALTER TABLE calls ADD COLUMN IF NOT EXISTS transcript_lang VARCHAR(12)",
    "ALTER TABLE calls ADD COLUMN IF NOT EXISTS summary TEXT",
    "ALTER TABLE calls ADD COLUMN IF NOT EXISTS transcript_status VARCHAR(20) DEFAULT 'none'",
    # Parishes — the institution behind the individual (models/parish.py). Idempotent.
    """
    CREATE TABLE IF NOT EXISTS parishes (
        id         UUID PRIMARY KEY,
        name       VARCHAR(200) NOT NULL,
        norm       VARCHAR(200) NOT NULL UNIQUE,
        location   VARCHAR(200),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    "ALTER TABLE persons ADD COLUMN IF NOT EXISTS parish_id UUID REFERENCES parishes(id) ON DELETE SET NULL",
    "CREATE INDEX IF NOT EXISTS ix_persons_parish ON persons (parish_id)",
    # Unmet demand — what customers asked for that we couldn't sell (models/demand_signal.py).
    """
    CREATE TABLE IF NOT EXISTS demand_signals (
        id         UUID PRIMARY KEY,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        query      VARCHAR(200) NOT NULL,
        raw_query  TEXT,
        kind       VARCHAR(20) NOT NULL DEFAULT 'no_match',
        channel    VARCHAR(20),
        person_id  UUID REFERENCES persons(id) ON DELETE SET NULL,
        wa_id      VARCHAR(64),
        detail     TEXT
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_demand_created ON demand_signals (created_at)",
    "CREATE INDEX IF NOT EXISTS ix_demand_query ON demand_signals (query)",
    "CREATE INDEX IF NOT EXISTS ix_demand_kind ON demand_signals (kind)",
    "CREATE INDEX IF NOT EXISTS ix_demand_wa_id ON demand_signals (wa_id)",
    # Operator-editable settings KV — standing orders first (models/app_setting.py).
    """
    CREATE TABLE IF NOT EXISTS app_settings (
        id         VARCHAR(100) PRIMARY KEY,
        value      TEXT NOT NULL DEFAULT '',
        updated_by UUID,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    # Deals — Neema owns outcomes (models/deal.py). Idempotent.
    """
    CREATE TABLE IF NOT EXISTS deals (
        id              UUID PRIMARY KEY,
        person_id       UUID REFERENCES persons(id) ON DELETE SET NULL,
        conversation_id UUID REFERENCES conversations(id) ON DELETE SET NULL,
        title           VARCHAR(300),
        items_snapshot  JSONB NOT NULL DEFAULT '[]',
        stage           VARCHAR(30) NOT NULL DEFAULT 'new',
        blocking        TEXT,
        next_action     JSONB,
        guidance        TEXT,
        status          VARCHAR(20) NOT NULL DEFAULT 'open',
        created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_deals_person_id ON deals (person_id)",
    "CREATE INDEX IF NOT EXISTS ix_deals_conversation_id ON deals (conversation_id)",
    "CREATE INDEX IF NOT EXISTS ix_deals_stage ON deals (stage)",
    "CREATE INDEX IF NOT EXISTS ix_deals_status ON deals (status)",
    # Planned actions — Neema's initiative queue (models/agent_action.py). Idempotent.
    """
    CREATE TABLE IF NOT EXISTS agent_actions (
        id              UUID PRIMARY KEY,
        deal_id         UUID REFERENCES deals(id) ON DELETE CASCADE,
        conversation_id UUID REFERENCES conversations(id) ON DELETE SET NULL,
        due_at          TIMESTAMPTZ NOT NULL,
        kind            VARCHAR(30) NOT NULL DEFAULT 'follow_up',
        reason          TEXT,
        draft           TEXT,
        status          VARCHAR(20) NOT NULL DEFAULT 'planned',
        created_by      VARCHAR(10) NOT NULL DEFAULT 'ai',
        created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_agent_actions_deal_id ON agent_actions (deal_id)",
    "CREATE INDEX IF NOT EXISTS ix_agent_actions_conversation_id ON agent_actions (conversation_id)",
    "CREATE INDEX IF NOT EXISTS ix_agent_actions_due_at ON agent_actions (due_at)",
    "CREATE INDEX IF NOT EXISTS ix_agent_actions_status ON agent_actions (status)",
    # Learning loops (models/agent_feedback.py). Idempotent.
    """
    CREATE TABLE IF NOT EXISTS agent_feedback (
        id              UUID PRIMARY KEY,
        conversation_id UUID REFERENCES conversations(id) ON DELETE SET NULL,
        draft           TEXT NOT NULL,
        sent            TEXT NOT NULL,
        created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_agent_feedback_conversation_id ON agent_feedback (conversation_id)",
    "CREATE INDEX IF NOT EXISTS ix_agent_feedback_created_at ON agent_feedback (created_at)",
    """
    CREATE TABLE IF NOT EXISTS qa_findings (
        id              UUID PRIMARY KEY,
        conversation_id UUID REFERENCES conversations(id) ON DELETE SET NULL,
        kind            VARCHAR(40) NOT NULL,
        detail          TEXT,
        created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_qa_findings_conversation_id ON qa_findings (conversation_id)",
    "CREATE INDEX IF NOT EXISTS ix_qa_findings_kind ON qa_findings (kind)",
    "CREATE INDEX IF NOT EXISTS ix_qa_findings_created_at ON qa_findings (created_at)",
    # Reply-to (quote) on messages (see models/message.py). Idempotent.
    "ALTER TABLE messages ADD COLUMN IF NOT EXISTS reply_to_id UUID REFERENCES messages(id) ON DELETE SET NULL",
    "ALTER TABLE messages ADD COLUMN IF NOT EXISTS reply_to_text TEXT",
    "ALTER TABLE messages ADD COLUMN IF NOT EXISTS reply_to_sender VARCHAR(20)",
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
    for _name in ("neema.agent", "neema.hub", "neema.wa", "neema.wa_native",
                  "neema.meta", "neema.startup", "neema.hubevents",
                  "neema.deals", "neema.actions", "neema.copilot",
                  "neema.selfqa", "neema.settings", "neema.video",
                  "neema.selfcheck", "neema.identity"):
        _lg = logging.getLogger(_name)
        _lg.setLevel(logging.INFO)
        _lg.addHandler(_h)
        _lg.propagate = False

    # One unambiguous boot line for the WhatsApp pipeline — native is the only
    # mode since n8n's retirement (2026-07-30).
    logging.getLogger("neema.wa").info(
        "WhatsApp pipeline: native in-process (wa_native)")

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

    # ── Media storage ─────────────────────────────────────────────────────────
    # This is where the media dir gets CREATED — at startup, not at import. The
    # named volume at MEDIA_DIR must then be writable by this (non-root) process
    # or every upload/inbound-media save 500s.  Check once, loudly, at boot.
    try:
        from app.routers.media import MEDIA_DIR
        os.makedirs(MEDIA_DIR, exist_ok=True)
        probe = os.path.join(MEDIA_DIR, ".write_check")
        with open(probe, "w") as f:
            f.write("ok")
        os.remove(probe)
        logger.info("Media dir writable ✓ (%s)", MEDIA_DIR)
    except Exception as exc:
        logger.error(
            "Media dir NOT writable — uploads and inbound media WILL fail. "
            "Fix: docker compose exec -u root api chown -R appuser:appgroup "
            f"{MEDIA_DIR!r}. Error: {exc}"
        )

    # Run schema migrations before serving any traffic
    await run_migrations()

    # ── Auto-name "Unknown" Meta contacts, forever ────────────────────────────
    # The app names itself — no manual jobs. A background loop periodically (1) sweeps
    # the page-level Conversations API for participant names (works even when the
    # per-user Profile API is blocked) and (2) backfills profile pics/locale. Each
    # tick is redis-locked so only ONE worker across the fleet runs it; failures are
    # swallowed and never touch request handling. New Unknowns get named within a
    # tick of arriving — the operator never runs enrich_names by hand.
    import asyncio as _asyncio

    async def _meta_enrich_loop(interval: int = 900):
        # Small initial delay so startup (migrations, redis check) settles first.
        await _asyncio.sleep(20)
        while True:
            try:
                if redis is None or await redis.set("meta:enrich:tick", "1", nx=True, ex=interval - 30):
                    from app.services.meta_enrich import (
                        sweep_conversation_names, backfill_unknown_profiles,
                    )
                    async with AsyncSessionLocal() as db:
                        named = await sweep_conversation_names(db)
                    async with AsyncSessionLocal() as db:
                        # pages_messaging is approved, so the per-user Profile API now
                        # answers for everyone — retry_marked drains the contacts we
                        # gave up on while it was blocked (photos + any names the
                        # inbox sweep missed). Bounded per tick.
                        await backfill_unknown_profiles(db, limit=50, retry_marked=True)
                    if named:
                        logger.info("meta auto-enrich: named %s contact(s) this tick", named)
            except Exception as exc:
                logger.warning("meta auto-enrich tick failed: %s", exc)
            await _asyncio.sleep(interval)

    app.state._meta_enrich_task = _asyncio.create_task(_meta_enrich_loop())

    # ── Self-heal missed auto-replies ─────────────────────────────────────────
    # Auto-replies are fire-and-forget tasks — a deploy (every push) or a
    # transient LLM/Graph error loses the ones in flight, and the customer's DM
    # sits unanswered. This loop answers any Meta DM whose latest message is an
    # unattended inbound, so no sale is dropped just because a reply got orphaned.
    async def _missed_reply_loop(interval: int = 120):
        await _asyncio.sleep(45)                # let startup + the normal path settle
        while True:
            try:
                if redis is None or await redis.set("meta:missed:tick", "1", nx=True,
                                                    ex=interval - 20):
                    from app.services.reply_sweeper import (
                        sweep_missed_replies, escalate_window_closed,
                    )
                    await sweep_missed_replies(redis)
                    # Past Meta's 24h window Neema can't reply on THAT channel —
                    # continue on one the same person has open, else hand the
                    # thread to a human (who gets Meta's 7-day window).
                    await escalate_window_closed(redis)
            except Exception as exc:
                logger.warning("missed-reply sweep tick failed: %s", exc)
            await _asyncio.sleep(interval)

    app.state._missed_reply_task = _asyncio.create_task(_missed_reply_loop())

    # ── Hand quiet human-held threads back to the AI ──────────────────────────
    # Intercept was a one-way door: a colleague replying once switched the thread
    # to human mode, and only a manual Release could undo it — so Neema went
    # silent on that customer for good. This returns a thread to AI once the
    # human side has been quiet (see services/auto_release.py). Redis-locked so
    # only one worker sweeps per tick.
    async def _auto_release_loop(interval: int = 300):
        await _asyncio.sleep(90)
        while True:
            try:
                if redis is None or await redis.set("agent:autorelease:tick", "1",
                                                    nx=True, ex=interval - 30):
                    from app.services.auto_release import sweep_auto_release
                    await sweep_auto_release(redis)
            except Exception as exc:
                logger.warning("auto-release tick failed: %s", exc)
            await _asyncio.sleep(interval)

    app.state._auto_release_task = _asyncio.create_task(_auto_release_loop())

    # Hub event agency: quiet-hours-deferred celebrations drain each morning
    # (leader-locked; no-op while HUB_EVENTS_SECRET is unset).
    from app.services import hub_events as _hub_events
    app.state._hub_events_task = _asyncio.create_task(
        _hub_events.deferred_loop(app.state.redis))

    # Initiative engine: due planned actions execute each minute (leader-locked).
    from app.services import actions as _actions
    app.state._actions_task = _asyncio.create_task(
        _actions.actions_loop(app.state.redis))

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
app.include_router(analytics.router,  prefix="/api/admin", tags=["Analytics"])
app.include_router(hub_events.router, prefix="/api/hub", tags=["Hub Events"])
app.include_router(roles.router,      prefix="/api/admin", tags=["Roles"])
app.include_router(n8n_bridge.router, prefix="/api/n8n",   tags=["n8n Bridge"])
app.include_router(meta_webhook.router, prefix="/api/meta", tags=["Meta Webhook"])
app.include_router(whatsapp_webhook.router, prefix="/api/wa", tags=["WhatsApp Webhook"])
app.include_router(short_link.router, prefix="/api",       tags=["Short Link"])
app.include_router(websocket.router,  prefix="",           tags=["WebSocket"])
app.include_router(media.router,      prefix="/api",       tags=["Media"])
app.include_router(public.router,     prefix="/api/public", tags=["Public Catalog"])
app.include_router(web_chat.router,   prefix="/api/web",   tags=["Web Chat"])


@app.get("/api/health")
async def health_check(request):
    """Health check — validates DB + Redis connections."""
    try:
        await request.app.state.redis.ping()
        return {"status": "ok", "redis": "connected"}
    except Exception as e:
        return {"status": "degraded", "error": str(e)}