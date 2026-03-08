import asyncio
import bcrypt
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text
from sqlalchemy.exc import ProgrammingError
from app.models.agent import Agent
from app.core.database import AsyncSessionLocal
from app.core.security import hash_password


SEEDS = [
    {
        "email": "nyorojnr@gmail.com",
        "password": "MN7KNC10",
        "name": "Admin",
        "role": "admin",
        "is_available": True,
        "is_superuser": True,
    },
    {
        "email": "agent@bethanyhouse.com",
        "password": "agent123",
        "name": "Agent One",
        "role": "agent",
        "is_available": True,
        "is_superuser": False,
    },
]


async def seed_agents(db: AsyncSession) -> None:
    try:
        await db.execute(text("SELECT 1 FROM agents LIMIT 1"))
    except ProgrammingError:
        print("[seed] agents table not ready yet — skipping seeds")
        return

    for data in SEEDS:
        result = await db.execute(
            select(Agent).where(Agent.email == data["email"])
        )
        exists = result.scalar_one_or_none()
        if exists:
            print(f"[seed] Already exists: {data['email']}")
            continue
        hashed = hash_password(data["password"])
        agent = Agent(
            email=data["email"],
            password_hash=hashed,
            name=data["name"],
            role=data["role"],
            is_available=data["is_available"],
            is_superuser=data["is_superuser"],
        )
        db.add(agent)
        print(f"[seed] Created: {data['email']}")
    await db.commit()

async def run_seeds() -> None:
    async with AsyncSessionLocal() as db:
        await seed_agents(db)


if __name__ == "__main__":
    asyncio.run(run_seeds())