"""The shared queries, and the settings row's defaults."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lifeline.models import SETTINGS_ID, Check, CheckOutcome, Setting, Site
from lifeline.services.store import (
    due_sites,
    get_site,
    list_sites,
    load_settings_row,
    prune_checks,
    recent_checks,
)
from tests.conftest import make_settings, make_site

NOW = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)


class TestSettingsRow:
    async def test_creates_the_row_on_first_read(self, db: AsyncSession) -> None:
        row = await load_settings_row(db)

        assert row.id == SETTINGS_ID

    async def test_reuses_the_existing_row(self, db: AsyncSession) -> None:
        first = await load_settings_row(db)
        first.retention_days = 5
        await db.commit()

        second = await load_settings_row(db)

        assert second.retention_days == 5
        rows = (await db.execute(select(Setting))).scalars().all()
        assert len(rows) == 1

    async def test_defaults_match_the_model(self, db: AsyncSession) -> None:
        # Keeps tests/conftest.make_settings from drifting away from the column defaults;
        # a test built on stale defaults asserts against behaviour nothing has.
        stored = await load_settings_row(db)
        await db.commit()
        helper = make_settings()

        for column in Setting.__table__.columns:
            if column.name in ("id", "created_at", "updated_at"):
                continue
            assert getattr(helper, column.name) == getattr(stored, column.name), column.name


class TestAppriseUrlList:
    def test_splits_lines_and_drops_blanks_and_comments(self) -> None:
        row = make_settings(
            apprise_urls="tgram://token/chat\n\n# the family mailbox\nmailto://user:pw@host\n  "
        )

        assert row.apprise_url_list == ["tgram://token/chat", "mailto://user:pw@host"]

    def test_is_empty_when_nothing_is_configured(self) -> None:
        assert make_settings().apprise_url_list == []


class TestSiteQueries:
    async def test_lists_sites_by_name(self, db: AsyncSession) -> None:
        db.add_all([make_site(id=None, name="zulu"), make_site(id=None, name="alpha")])
        await db.commit()

        assert [site.name for site in await list_sites(db)] == ["alpha", "zulu"]

    async def test_finds_one_site(self, db: AsyncSession, site: Site) -> None:
        assert (await get_site(db, site.id)).name == site.name

    async def test_reports_a_missing_site_as_none(self, db: AsyncSession) -> None:
        assert await get_site(db, 999) is None


class TestDueSites:
    async def test_a_new_site_is_due_immediately(self, db: AsyncSession) -> None:
        # Otherwise adding a site tells you nothing until an interval has passed.
        db.add(make_site(id=None, next_check_at=None))
        await db.commit()

        assert len(await due_sites(db, NOW)) == 1

    async def test_a_site_scheduled_in_the_future_is_not_due(self, db: AsyncSession) -> None:
        db.add(make_site(id=None, next_check_at=NOW + timedelta(hours=1)))
        await db.commit()

        assert await due_sites(db, NOW) == []

    async def test_a_site_scheduled_in_the_past_is_due(self, db: AsyncSession) -> None:
        db.add(make_site(id=None, next_check_at=NOW - timedelta(seconds=1)))
        await db.commit()

        assert len(await due_sites(db, NOW)) == 1

    async def test_a_disabled_site_is_never_due(self, db: AsyncSession) -> None:
        db.add(make_site(id=None, enabled=False, next_check_at=None))
        await db.commit()

        assert await due_sites(db, NOW) == []

    async def test_never_checked_sites_come_first(self, db: AsyncSession) -> None:
        db.add_all(
            [
                make_site(id=None, name="scheduled", next_check_at=NOW - timedelta(days=1)),
                make_site(id=None, name="new", next_check_at=None),
            ]
        )
        await db.commit()

        assert [site.name for site in await due_sites(db, NOW)] == ["new", "scheduled"]


class TestCheckHistory:
    async def test_returns_the_newest_checks_first(self, db: AsyncSession, site: Site) -> None:
        for offset in range(5):
            db.add(
                Check(
                    site_id=site.id,
                    started_at=NOW - timedelta(hours=offset),
                    outcome=CheckOutcome.OK,
                )
            )
        await db.commit()

        checks = await recent_checks(db, site.id, limit=3)

        assert [check.started_at for check in checks] == [
            NOW,
            NOW - timedelta(hours=1),
            NOW - timedelta(hours=2),
        ]

    async def test_prunes_checks_past_the_window(self, db: AsyncSession, site: Site) -> None:
        db.add(Check(site_id=site.id, started_at=NOW - timedelta(days=91), outcome=CheckOutcome.OK))
        db.add(Check(site_id=site.id, started_at=NOW - timedelta(days=1), outcome=CheckOutcome.OK))
        await db.commit()

        removed = await prune_checks(db, retention_days=90, now=NOW)
        await db.commit()

        assert removed == 1
        assert len(await recent_checks(db, site.id, limit=10)) == 1

    async def test_retention_of_zero_keeps_everything(self, db: AsyncSession, site: Site) -> None:
        # Zero reads as "no retention limit", not as "delete the entire history".
        db.add(Check(site_id=site.id, started_at=NOW - timedelta(days=900), outcome=CheckOutcome.OK))
        await db.commit()

        assert await prune_checks(db, retention_days=0, now=NOW) == 0
        assert len(await recent_checks(db, site.id, limit=10)) == 1

    async def test_deleting_a_site_takes_its_checks(self, db: AsyncSession, site: Site) -> None:
        # Enforced by SQLite only when the foreign-key pragma is on, which db.py sets.
        db.add(Check(site_id=site.id, started_at=NOW, outcome=CheckOutcome.OK))
        await db.commit()

        await db.delete(site)
        await db.commit()

        assert (await db.execute(select(Check))).scalars().all() == []
