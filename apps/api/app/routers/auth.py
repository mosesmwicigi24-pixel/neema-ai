from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import get_db
from app.models.agent import Agent
from app.core.security import verify_password, create_access_token, create_refresh_token, decode_token
from app.schemas.auth import LoginRequest, TokenResponse

router = APIRouter()


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
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Agent not found")

    return {
        "access_token": create_access_token(agent_id),
        "refresh_token": create_refresh_token(agent_id),
        "token_type": "bearer",
    }