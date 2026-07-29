"""Alembic environment.

The database URL comes from application settings, never from alembic.ini. A connection
string in a committed .ini is how credentials reach a repository, and it also lets
migrations and the application drift onto different databases without anyone noticing.
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context
from app.core.config import settings
from app.db.base import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Migrations can target the test database via `alembic -x db=test`. Anything else uses
# the application database.
_target = context.get_x_argument(as_dictionary=True).get("db")
_url = settings.test_database_url if _target == "test" else settings.database_url

if not _url:
    raise RuntimeError("No database URL configured. Copy .env.example to api/.env and fill it in.")

config.set_main_option("sqlalchemy.url", _url)

target_metadata = Base.metadata


def _run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        # Alembic ignores column type changes by default. A silently skipped type change
        # leaves the schema differing from the models with nothing reporting it.
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_offline() -> None:
    context.configure(
        url=_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
