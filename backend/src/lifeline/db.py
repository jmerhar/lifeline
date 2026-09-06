"""Database engine and session handling."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import event
from sqlalchemy.engine.interfaces import DBAPIConnection
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import ConnectionPoolEntry

from .config import Settings


def _apply_sqlite_pragmas(dbapi_connection: DBAPIConnection, _record: ConnectionPoolEntry) -> None:
    """Turn on the SQLite behaviour this schema assumes.

    ``foreign_keys`` is off by default in SQLite, which silently makes every
    ``ON DELETE CASCADE`` in the schema a no-op and leaves orphaned rows behind. WAL
    lets the scheduler write a check while the UI reads the site list instead of the two
    blocking each other.
    """
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=5000")
    finally:
        cursor.close()


def wants_sqlite_pragmas(url: str) -> bool:
    """Whether ``url`` names a SQLite database.

    The pragmas below are SQLite's alone; attaching them to another backend's engine would
    fail on its first connection. SQLite is the supported database, but the URL can be
    overridden, so the check is made rather than assumed.
    """
    return url.startswith("sqlite")


def create_engine(settings: Settings) -> AsyncEngine:
    """Build the engine for ``settings``, with SQLite's pragmas wired in."""
    url = settings.resolved_database_url
    engine = create_async_engine(url, future=True)
    if wants_sqlite_pragmas(url):
        event.listen(engine.sync_engine, "connect", _apply_sqlite_pragmas)
    return engine


def create_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """A session factory that leaves loaded objects usable after a commit."""
    # expire_on_commit=False so a handler can still read the object it just saved
    # without a second round trip -- which under async would be an implicit IO in a
    # place that looks like attribute access.
    return async_sessionmaker(engine, expire_on_commit=False, autoflush=False)


@asynccontextmanager
async def session_scope(
    factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    """A transaction that commits on success and rolls back on any exception."""
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except BaseException:
            await session.rollback()
            raise
