"""Alembic environment.

Runs migrations through the application's own async engine and settings, so `alembic
upgrade head` and the running app can never disagree about which database is being
migrated.
"""

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import Connection

from lifeline.config import get_settings
from lifeline.db import create_engine
from lifeline.models import Base, UtcDateTime

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _render_item(obj_type: str, obj: object, autogen_context: object) -> str | bool:
    """Render UtcDateTime as the plain DateTime it is built on.

    A migration is a standalone artefact that has to keep running years later; one that
    imports an application class stops working the moment that class is moved or renamed.
    UtcDateTime's only job is to normalise the Python value, so at the DDL level it is
    exactly ``sa.DateTime()`` and rendering it as such loses nothing.

    Everything else returns False, which is Alembic's "use the default rendering" —
    returning None instead makes it render the item as an empty string, which produces a
    migration whose tables have no columns and which still imports and runs.
    """
    if obj_type == "type" and isinstance(obj, UtcDateTime):
        return "sa.DateTime()"
    return False


def _configure(connection: Connection) -> None:
    """Point Alembic at a live connection.

    ``render_as_batch`` is required for SQLite, which cannot ALTER a column or a
    constraint: batch mode copies the table instead. Setting it unconditionally keeps
    generated migrations portable.
    """
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        render_as_batch=True,
        compare_type=True,
        render_item=_render_item,
    )


def run_migrations_offline() -> None:
    """Emit SQL to stdout instead of running it, for review or manual application."""
    context.configure(
        url=get_settings().resolved_database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
        render_item=_render_item,
    )
    with context.begin_transaction():
        context.run_migrations()


def _run(connection: Connection) -> None:
    _configure(connection)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """Apply migrations against the configured database."""
    settings = get_settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    engine = create_engine(settings)
    try:
        async with engine.connect() as connection:
            await connection.run_sync(_run)
    finally:
        await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
