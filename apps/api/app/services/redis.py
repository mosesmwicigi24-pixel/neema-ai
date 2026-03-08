import json

async def broadcast(redis, channel: str, payload: dict) -> None:
    await redis.publish(f"ws:channel:{channel}", json.dumps(payload))