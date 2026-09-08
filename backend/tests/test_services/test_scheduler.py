"""The background loop: running due checks, refreshing warnings, pruning history."""

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lifeline.config import Settings
from lifeline.models import Check, CheckOutcome, Site, SiteStatus
from lifeline.services.notifier import Notifier
from lifeline.services.runner import CheckRunner
from lifeline.services.scheduler import Scheduler
from lifeline.services.store import load_settings_row
from tests.conftest import RecordingSender, make_site

NOW = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)


@pytest.fixture
def build_scheduler(
    sessionmaker: async_sessionmaker[AsyncSession],
    settings: Settings,
    notifier: Notifier,
    make_runner: Callable[..., CheckRunner],
) -> Callable[..., Scheduler]:
    """Build a scheduler over the test runner."""

    def build(**overrides: object) -> Scheduler:
        return Scheduler(
            sessionmaker,
            settings.model_copy(update=overrides) if overrides else settings,
            make_runner(),
            notifier,
        )

    return build


class TestTick:
    async def test_checks_the_sites_that_are_due(
        self, db: AsyncSession, site: Site, build_scheduler: Callable[..., Scheduler]
    ) -> None:
        await build_scheduler().tick(now=NOW)

        assert len((await db.execute(select(Check))).scalars().all()) == 1

    async def test_prunes_history_past_the_retention_window(
        self, db: AsyncSession, site: Site, build_scheduler: Callable[..., Scheduler]
    ) -> None:
        db.add(
            Check(
                site_id=site.id,
                started_at=NOW - timedelta(days=400),
                outcome=CheckOutcome.OK,
            )
        )
        await db.commit()

        await build_scheduler().tick(now=NOW)

        db.expunge_all()
        remaining = (await db.execute(select(Check))).scalars().all()
        assert all(check.started_at > NOW - timedelta(days=90) for check in remaining)


class TestRiskRefresh:
    async def test_flags_a_deadline_that_arrives_without_any_check(
        self,
        db: AsyncSession,
        site: Site,
        build_scheduler: Callable[..., Scheduler],
        sender: RecordingSender,
    ) -> None:
        # Both clocks run down on their own: nothing has to fail for an account to lapse.
        site.status = SiteStatus.ALIVE
        site.inactivity_limit_days = 90
        site.last_ok_at = NOW - timedelta(days=86)
        # After the deadline, so no check will reset it in time — which is the only case worth a
        # warning.
        site.next_check_at = NOW + timedelta(days=30)
        row = await load_settings_row(db)
        row.apprise_urls = "tgram://token/chat"
        await db.commit()

        await build_scheduler().tick(now=NOW)

        db.expunge_all()
        assert (await db.get(Site, site.id)).status is SiteStatus.AT_RISK
        assert "running out of time" in sender.titles[0]

    async def test_clears_the_flag_once_the_deadline_moves_out(
        self, db: AsyncSession, site: Site, build_scheduler: Callable[..., Scheduler]
    ) -> None:
        site.status = SiteStatus.AT_RISK
        site.inactivity_limit_days = 90
        site.last_ok_at = NOW - timedelta(days=1)
        site.next_check_at = NOW + timedelta(days=3)
        await db.commit()

        await build_scheduler().tick(now=NOW)

        db.expunge_all()
        assert (await db.get(Site, site.id)).status is SiteStatus.ALIVE

    async def test_leaves_a_lapsed_site_alone(
        self, db: AsyncSession, site: Site, build_scheduler: Callable[..., Scheduler]
    ) -> None:
        # It has already been reported as needing a login.
        site.status = SiteStatus.LAPSED
        site.inactivity_limit_days = 1
        site.last_ok_at = NOW - timedelta(days=1)
        site.next_check_at = NOW + timedelta(days=3)
        await db.commit()

        await build_scheduler().tick(now=NOW)

        db.expunge_all()
        assert (await db.get(Site, site.id)).status is SiteStatus.LAPSED


class TestLifecycle:
    async def test_does_not_start_when_disabled(
        self, build_scheduler: Callable[..., Scheduler]
    ) -> None:
        scheduler = build_scheduler(scheduler_enabled=False)

        scheduler.start()

        assert scheduler._task is None

    async def test_stopping_an_unstarted_scheduler_is_harmless(
        self, build_scheduler: Callable[..., Scheduler]
    ) -> None:
        await build_scheduler().stop()

    async def test_starts_once_and_stops_cleanly(
        self, build_scheduler: Callable[..., Scheduler]
    ) -> None:
        scheduler = build_scheduler(scheduler_enabled=True, scheduler_tick_seconds=60)
        try:
            scheduler.start()
            first = scheduler._task
            scheduler.start()

            assert scheduler._task is first
        finally:
            await scheduler.stop()

        assert scheduler._task is None

    async def test_the_loop_outlives_a_failing_tick(
        self, build_scheduler: Callable[..., Scheduler], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # A scheduler that dies on one bad tick silently stops every future check.
        scheduler = build_scheduler(scheduler_enabled=True, scheduler_tick_seconds=0)
        ticked_twice = asyncio.Event()
        calls: list[int] = []

        async def failing_tick(**_: object) -> None:
            calls.append(1)
            if len(calls) == 1:
                raise RuntimeError("boom")
            ticked_twice.set()

        monkeypatch.setattr(scheduler, "tick", failing_tick)

        try:
            scheduler.start()
            await asyncio.wait_for(ticked_twice.wait(), timeout=5)
        finally:
            await scheduler.stop()

        assert len(calls) >= 2
