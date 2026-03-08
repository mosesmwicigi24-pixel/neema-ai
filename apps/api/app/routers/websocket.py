from fastapi import APIRouter, WebSocket, WebSocketDisconnect
import redis.asyncio as aioredis
import asyncio
import json

router = APIRouter()

# Map: conversation_id → set of connected WebSocket clients
active_connections: dict[str, set[WebSocket]] = {}


@router.websocket("/ws/{agent_id}")
async def websocket_endpoint(websocket: WebSocket, agent_id: str):
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