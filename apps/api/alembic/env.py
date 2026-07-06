import os
from logging.config import fileConfig
from sqlalchemy import engine_from_config, pool
from alembic import context
from dotenv import load_dotenv

# Load .env for local CLI use (Docker sets env vars directly)
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '../../.env.local'),
            override=False)
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '../../.env'),
            override=False)

# Import ALL models so Alembic can see them for autogenerate
from app.models import Base
from app.models.agent import Agent            # noqa: F401
from app.models.conversation import Conversation  # noqa: F401
from app.models.message import Message        # noqa: F401
from app.models.intercept import Intercept    # noqa: F401
from app.models.user import User              # noqa: F401
from app.models.order_event import OrderEvent # noqa: F401
from app.models.catalog import Catalog        # noqa: F401
from app.models.session import Session              # noqa: F401
from app.models.customer_history import CustomerHistory  # noqa: F401
from app.models.ai_usage import AiUsage                    # noqa: F401

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def get_url() -> str:
    """Read the SYNC database URL (psycopg2) — Alembic needs sync connections."""
    url = os.environ.get("DATABASE_URL_SYNC")
    if not url:
        raise RuntimeError("DATABASE_URL_SYNC not set")
    return url


def run_migrations_offline() -> None:
    url = get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = get_url()
    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,   # detect column type changes
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()