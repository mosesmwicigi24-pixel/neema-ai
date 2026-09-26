from fastapi import APIRouter, WebSocket, WebSocketDisconnect
import redis.asyncio as aioredis
import asyncio
import json

router = APIRouter()

# Map: conversation_id → set of connected WebSocket clients
active_connections: dict[str, set[WebSocket]] = {}

# Close code for a refused handshake (4000–4999 are the application's own):
# the clients treat any close as "reconnect later"; this one also tells a
# person reading the logs why.
WS_UNAUTHORIZED = 4401


async def _authorised(token: str | None, agent_id: str) -> bool:
    """The live feed carries every conversation's traffic — customers' names,
    numbers and messages — so a socket opens only for a signed-in agent: a
    valid ACCESS token whose subject is the agent in the path, and who still
    exists (a removed agent's token stops working here as it does on the API).
    Browsers can't set headers on a WebSocket, hence the `token` query param."""
    if not token:
        return False
    from app.core.security import decode_token
    try:
        payload = decode_token(token)
    except Exception:
        return False
    if payload.get("type") != "access" or str(payload.get("sub")) != agent_id:
        return False
    import uuid
    try:
        uuid.UUID(agent_id)
    except ValueError:
        return False
    from sqlalchemy import select
    from app.database import AsyncSessionLocal
    from app.models.agent import Agent
    async with AsyncSessionLocal() as db:
        found = (await db.execute(select(Agent.id).where(Agent.id == agent_id))).first()
    return found is not None


@router.websocket("/ws/{agent_id}")
async def websocket_endpoint(websocket: WebSocket, agent_id: str):
    if not await _authorised(websocket.query_params.get("token"), agent_id):
        # Closing before accept() refuses the upgrade (HTTP 403).
        await websocket.close(code=WS_UNAUTHORIZED)
        return
    await websocket.accept()
    redis: aioredis.Redis = websocket.app.state.redis
    pubsub = redis.pubsub()
    await pubsub.psubscribe("ws:channel:*")

    async def listen_redis():
        async for msg in pubsub.listen():
            if msg["type"] == "pmessage":
                try:
                    await websocket.send_text(msg["data"])
                except Exception:
                    break

    redis_task = asyncio.create_task(listen_redis())

    try:
        while True:
            data = await websocket.receive_text()
            event = json.loads(data)
            if event.get("type") == "ping":
                await websocket.send_text(json.dumps({"type": "pong"}))
    except WebSocketDisconnect:
        pass
    finally:
        redis_task.cancel()
        await pubsub.punsubscribe("ws:channel:*")
        await pubsub.aclose()
