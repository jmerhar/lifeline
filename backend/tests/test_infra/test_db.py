"""The engine's behaviour, and the transaction helper."""

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import StatementError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from lifeline.config import Settings
from lifeline.db import session_scope, wants_sqlite_pragmas
from lifeline.models import Site
from tests.conftest import make_site


class TestSqlitePragmas:
    async def test_enforces_foreign_keys(self, engine: AsyncEngine) -> None:
        # SQLite ignores every ON DELETE CASCADE in the schema unless this is on, which would
        # silently leave orphaned checks and sessions behind.
        async with engine.connect() as connection:
            result = await connection.execute(text("PRAGMA foreign_keys"))

            assert result.scalar_one() == 1

    async def test_uses_write_ahead_logging(self, engine: AsyncEngine) -> None:
        # So the scheduler can record a check while the UI reads the site list.
        async with engine.connect() as connection:
            result = await connection.execute(text("PRAGMA journal_mode"))

            assert result.scalar_one() == "wal"

    def test_are_wanted_for_a_sqlite_url(self, data_dir) -> None:
        assert wants_sqlite_pragmas(Settings(data_dir=data_dir).resolved_database_url) is True

    def test_are_not_wanted_for_another_backend(self) -> None:
        # Attaching them to another backend's engine would fail on its first connection.
        assert wants_sqlite_pragmas("postgresql+asyncpg://user@localhost/db") is False


class TestSessionScope:
    async def test_commits_on_success(
        self, sessionmaker: async_sessionmaker[AsyncSession], db: AsyncSession
    ) -> None:
        async with session_scope(sessionmaker) as session:
            session.add(make_site(id=None, name="committed"))

        assert (await db.execute(select(Site.name))).scalar_one() == "committed"

    async def test_rolls_back_when_the_body_raises(
        self, sessionmaker: async_sessionmaker[AsyncSession], db: AsyncSession
    ) -> None:
        with pytest.raises(RuntimeError):
            async with session_scope(sessionmaker) as session:
                session.add(make_site(id=None, name="doomed"))
                raise RuntimeError("something went wrong")

        assert (await db.execute(select(Site))).scalars().all() == []

    async def test_rolls_back_on_cancellation(
        self, sessionmaker: async_sessionmaker[AsyncSession], db: AsyncSession
    ) -> None:
        # Cancellation is not an Exception, so catching only Exception here would commit a
        # half-finished unit of work when a request was abandoned.
        import asyncio

        with pytest.raises(asyncio.CancelledError):
            async with session_scope(sessionmaker) as session:
                session.add(make_site(id=None, name="abandoned"))
                raise asyncio.CancelledError

        assert (await db.execute(select(Site))).scalars().all() == []


class TestUtcDateTime:
    async def test_reads_back_a_timezone_aware_value(self, db: AsyncSession) -> None:
        from datetime import UTC, datetime

        from lifeline.models import Check, CheckOutcome

        written = datetime(2026, 6, 1, 12, 30, tzinfo=UTC)
        site = make_site(id=None)
        db.add(site)
        await db.flush()
        db.add(Check(site_id=site.id, started_at=written, outcome=CheckOutcome.OK))
        await db.commit()
        db.expunge_all()

        stored = (await db.execute(select(Check))).scalar_one()

        # Naive here would make every comparison against datetime.now(UTC) raise TypeError.
        assert stored.started_at.tzinfo is not None
        assert stored.started_at == written

    async def test_refuses_a_naive_value(self, db: AsyncSession) -> None:
        # Assuming UTC would be wrong exactly when a caller has a local time in hand.
        from datetime import datetime

        from lifeline.models import Check, CheckOutcome

        site = make_site(id=None)
        db.add(site)
        await db.flush()
        db.add(Check(site_id=site.id, started_at=datetime(2026, 6, 1), outcome=CheckOutcome.OK))

        # SQLAlchemy wraps the type's own error in a StatementError on the way out.
        with pytest.raises(StatementError, match="timezone-aware"):
            await db.commit()

    async def test_converts_another_zone_to_utc(self, db: AsyncSession) -> None:
        from datetime import UTC, datetime, timedelta, timezone

        from lifeline.models import Check, CheckOutcome

        amsterdam = timezone(timedelta(hours=2))
        site = make_site(id=None)
        db.add(site)
        await db.flush()
        db.add(
            Check(
                site_id=site.id,
                started_at=datetime(2026, 6, 1, 14, 0, tzinfo=amsterdam),
                outcome=CheckOutcome.OK,
            )
        )
        await db.commit()
        db.expunge_all()

        stored = (await db.execute(select(Check))).scalar_one()

        assert stored.started_at == datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
