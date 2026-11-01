"""Database engine and session handling, through jigkit."""

from jigkit.db import create_engine as _create_engine
from jigkit.db import create_sessionmaker, session_scope
from sqlalchemy.ext.asyncio import AsyncEngine

from .config import Settings

__all__ = ["create_engine", "create_sessionmaker", "session_scope"]


def create_engine(settings: Settings) -> AsyncEngine:
    """Build the engine for ``settings``' database, with SQLite's pragmas wired in."""
    return _create_engine(settings.resolved_database_url)
