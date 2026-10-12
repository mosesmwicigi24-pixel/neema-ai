from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.config import settings
from app.database import get_db
from app.models.agent import Agent
from app.core.security import verify_password, create_access_token, create_refresh_token, decode_token
from app.schemas.auth import ForgotPasswordRequest, LoginRequest, ResetPasswordRequest, TokenResponse

router = APIRouter()


def _caller_ip(request: Request) -> str:
    fwd = str(request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
    return fwd or (request.client.host if request.client else "")


def _site_url(request: Request) -> str:
    """Where the reset page lives: the public Neema host, else the caller's origin."""
    return (settings.media_public_url or str(request.headers.get("origin") or "")).rstrip("/")


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Agent).where(Agent.email == body.email))
    agent = result.scalar_one_or_none()
    if not agent or not verify_password(body.password, agent.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Invalid credentials")
    return {
        "access_token": create_access_token(str(agent.id)),
        "refresh_token": create_refresh_token(str(agent.id)),
        "token_type": "bearer",
        "agent_id": str(agent.id),
        "role": agent.role,
        "is_superuser": agent.is_superuser,
    }


@router.post("/refresh", response_model=TokenResponse)
async def refresh(body: dict, db: AsyncSession = Depends(get_db)):
    try:
        payload = decode_token(body["refresh_token"])
        if payload.get("type") != "refresh":
            raise ValueError("Wrong token type")
    except Exception:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Invalid refresh token")

    agent_id = payload["sub"]
    result = await db.execute(select(Agent).where(Agent.id == agent_id))
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    return {
        "access_token": create_access_token(agent_id),
        "refresh_token": create_refresh_token(agent_id),
        "token_type": "bearer",
        "agent_id": agent_id,          
        "role": agent.role,            
        "is_superuser": agent.is_superuser, 
    }


@router.post("/forgot-password")
async def forgot_password(body: ForgotPasswordRequest, request: Request,
                          db: AsyncSession = Depends(get_db)):
    """Self-serve recovery: a single-use reset link mailed to the business
    recovery inbox (services/password_reset). Same answer whether or not the
    email is an account; 429 when asked too often; 503 when mail is not set up."""
    from app.services import password_reset
    redis = getattr(request.app.state, "redis", None)
    out = await password_reset.request_reset(db, redis, body.email, _caller_ip(request), _site_url(request))
    return {"ok": True, "message": out["message"], "inbox": settings.password_reset_inbox}


@router.post("/reset-password")
async def reset_password(body: ResetPasswordRequest, request: Request,
                         db: AsyncSession = Depends(get_db)):
    """The link's token (one use) + the new password (8+ characters)."""
    from app.services import password_reset
    redis = getattr(request.app.state, "redis", None)
    out = await password_reset.complete_reset(db, redis, body.token, body.password)
    return {"ok": True, "email": out["email"]}
