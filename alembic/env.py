"""Alembic environment configuration for async PostgreSQL migrations."""

import asyncio
import os
import sys
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy.ext.asyncio import create_async_engine

from alembic import context
from src.db.models import Base

# Alembic Config object
config = context.config

# Interpret the config file for Python logging
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# MetaData for autogenerate support
target_metadata = Base.metadata

# Detect available env files (for diagnostics + fallback)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_ENV_PROD = _PROJECT_ROOT / ".env.prod"
_ENV_LOCAL = _PROJECT_ROOT / ".env"


def _load_env_file() -> dict[str, str]:
    """Load key=value pairs from .env.prod or .env if present.

    Returns a dict of variables found in the file (does not set os.environ).
    """
    env_path = _ENV_PROD if _ENV_PROD.exists() else _ENV_LOCAL
    if not env_path.exists():
        return {}
    result: dict[str, str] = {}
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, _, value = line.partition("=")
            result[key.strip()] = value.strip()
    return result


_FILE_ENV = _load_env_file()

# Print diagnostics (names only, no values)
print("[alembic] env file detection:")
print(f"  .env.prod exists: {_ENV_PROD.exists()}")
print(f"  .env exists:      {_ENV_LOCAL.exists()}")
print(f"  loaded {len(_FILE_ENV)} vars from file")
print(f"  DATABASE_URL in process env: {bool(os.getenv('DATABASE_URL'))}")
print(f"  DATABASE_URL in file:        {'DATABASE_URL' in _FILE_ENV}")


def _get_database_url() -> str:
    """Return DATABASE_URL from environment or .env file.

    Priority:
        1. Process env: DATABASE_URL
        2. Process env: DATABASE_PUBLIC_URL (Railway)
        3. Process env: POSTGRES_URL
        4. .env.prod / .env file: DATABASE_URL

    Auto-converts ``postgresql://`` to ``postgresql+asyncpg://``.
    """
    url = os.getenv("DATABASE_URL", "").strip()
    if not url:
        url = os.getenv("DATABASE_PUBLIC_URL", "").strip()
    if not url:
        url = os.getenv("POSTGRES_URL", "").strip()
    if not url:
        url = _FILE_ENV.get("DATABASE_URL", "").strip()

    if not url:
        env_keys = sorted(os.environ.keys())
        print(
            "[alembic] DATABASE_URL is not set in process env or env file.",
            file=sys.stderr,
        )
        print(f"  Available process env keys: {', '.join(env_keys)}", file=sys.stderr)
        print(f"  Env file vars loaded: {list(_FILE_ENV.keys()) or 'none'}", file=sys.stderr)
        raise RuntimeError(
            "DATABASE_URL environment variable is not set. "
            "Set it via Railway Variables, environment, or .env.prod file. "
            f"Process env keys: {', '.join(env_keys)}"
        )

    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return url


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL and not an Engine.
    """
    url = _get_database_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection) -> None:
    """Execute migrations inside a connection context."""
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """Run migrations in 'online' mode using an async engine.

    Creates an async engine, connects, and runs the migrations.
    """
    url = _get_database_url()
    connectable = create_async_engine(
        url,
        echo=False,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())