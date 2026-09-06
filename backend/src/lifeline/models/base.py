"""Declarative base, shared column types and mixins."""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import DateTime, MetaData, TypeDecorator
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Deterministic constraint names. SQLite cannot ALTER a constraint, so Alembic rewrites
# the whole table to change one — which it can only do when every constraint has a name
# it can reproduce. Without this, migrations that touch a constraint fail on SQLite.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class UtcDateTime(TypeDecorator):
    """A timestamp that is always a timezone-aware UTC ``datetime`` in Python.

    SQLite has no timestamp type: it stores a string and hands back a naive
    ``datetime``, so comparing a loaded value against ``datetime.now(UTC)`` raises
    TypeError. Normalising to UTC on the way in and re-attaching the zone on the way
    out keeps every datetime in the application aware, whatever the backend. Naive
    input is rejected rather than assumed to be UTC, because the assumption is wrong
    exactly when a caller has a local time in hand.
    """

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError(f"expected a timezone-aware datetime, got {value!r}")
        return value.astimezone(UTC).replace(tzinfo=None)

    def process_result_value(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is None:
            return None
        return value.replace(tzinfo=UTC)


def utcnow() -> datetime:
    """The current time, timezone-aware, for column defaults."""
    return datetime.now(UTC)


class Base(DeclarativeBase):
    """Declarative base for every model."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class TimestampMixin:
    """Creation and modification times, maintained by the ORM."""

    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow, onupdate=utcnow)
