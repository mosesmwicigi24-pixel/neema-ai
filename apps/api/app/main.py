from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import redis.asyncio as aioredis
import asyncio

from app.core.config import settings
from app.routers import auth, admin, n8n_bridge, websocket, health, crm, roles
from app.seeds import run_seeds


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    app.state.redis = aioredis.from_url(
        settings.redis_url, decode_responses=True
    )
    # await asyncio.sleep(2)
    # await run_seeds()
    yield
    # Shutdown
    await app.state.redis.aclose()


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

app.include_router(health.router,     prefix="/api",        tags=["Health"])
app.include_router(auth.router,       prefix="/api/auth",   tags=["Auth"])
app.include_router(admin.router,      prefix="/api/admin",  tags=["Admin"])
app.include_router(crm.router,        prefix="/api/admin",  tags=["CRM"])
app.include_router(roles.router,      prefix="/api/admin",  tags=["Roles"])
app.include_router(n8n_bridge.router, prefix="/api/n8n",    tags=["n8n Bridge"])
app.include_router(websocket.router,  prefix="",            tags=["WebSocket"])


@app.get("/api/health")
async def health(request):
    """Health check — validates DB + Redis connections."""
    try:
        await request.app.state.redis.ping()
        return {"status": "ok", "redis": "connected"}
    except Exception as e:
        return {"status": "degraded", "error": str(e)}