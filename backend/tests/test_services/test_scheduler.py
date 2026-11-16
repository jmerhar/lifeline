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
from tests.conftest import RecordingSender

NOW = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)


class FakeTime:
    """A monotonic clock that a sleep moves forward instead of waiting."""

    def __init__(self) -> None:
        self.now = 0.0

    def clock(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.now += seconds
        # Yields, so a test waiting on the loop gets to run between rounds.
        await asyncio.sleep(0)


@pytest.fixture
def build_scheduler(
    sessionmaker: async_sessionmaker[AsyncSession],
    settings: Settings,
    notifier: Notifier,
    make_runner: Callable[..., CheckRunner],
) -> Callable[..., Scheduler]:
    """Build a scheduler over the test runner."""

    def build(*, time: FakeTime | None = None, **overrides: object) -> Scheduler:
        return Scheduler(
            sessionmaker,
            settings.model_copy(update=overrides) if overrides else settings,
            make_runner(),
            notifier,
            **({"clock": time.clock, "sleep": time.sleep} if time else {}),
        )

    return build


class TestChecks:
    async def test_checks_the_sites_that_are_due(
        self, db: AsyncSession, site: Site, build_scheduler: Callable[..., Scheduler]
    ) -> None:
        await build_scheduler().check_due(now=NOW)

        assert len((await db.execute(select(Check))).scalars().all()) == 1

    async def test_sleeps_until_the_soonest_check(
        self, db: AsyncSession, site: Site, build_scheduler: Callable[..., Scheduler]
    ) -> None:
        site.next_check_at = NOW + timedelta(minutes=10)
        await db.commit()
        time = FakeTime()
        scheduler = build_scheduler(time=time, scheduler_tick_seconds=3600)

        await scheduler.check_due(now=NOW)

        assert scheduler._schedule._due["checks"] == 600

    async def test_never_sleeps_longer_than_the_tick(
        self, db: AsyncSession, site: Site, build_scheduler: Callable[..., Scheduler]
    ) -> None:
        site.next_check_at = NOW + timedelta(days=3)
        await db.commit()
        scheduler = build_scheduler(time=FakeTime(), scheduler_tick_seconds=300)

        await scheduler.check_due(now=NOW)

        assert scheduler._schedule._due["checks"] == 300

    async def test_never_looks_again_sooner_than_a_minute(
        self, db: AsyncSession, site: Site, build_scheduler: Callable[..., Scheduler]
    ) -> None:
        # However soon the next check is, the loop must not spin waiting for it.
        site.next_check_at = NOW + timedelta(seconds=5)
        await db.commit()
        scheduler = build_scheduler(time=FakeTime(), scheduler_tick_seconds=300)

        await scheduler.check_due(now=NOW)

        assert scheduler._schedule._due["checks"] == 60

    async def test_waits_the_full_tick_with_no_site_enabled(
        self, build_scheduler: Callable[..., Scheduler]
    ) -> None:
        scheduler = build_scheduler(time=FakeTime(), scheduler_tick_seconds=300)

        await scheduler.check_due(now=NOW)

        assert scheduler._schedule._due["checks"] == 300


class TestPrune:
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

        await build_scheduler().prune(now=NOW)

        db.expunge_all()
        assert (await db.execute(select(Check))).scalars().all() == []


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

        await build_scheduler().refresh_risk(now=NOW)

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

        await build_scheduler().refresh_risk(now=NOW)

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

        await build_scheduler().refresh_risk(now=NOW)

        db.expunge_all()
        assert (await db.get(Site, site.id)).status is SiteStatus.LAPSED


class TestLifecycle:
    async def test_does_not_start_when_disabled(
        self, build_scheduler: Callable[..., Scheduler]
    ) -> None:
        scheduler = build_scheduler(scheduler_enabled=False)

        scheduler.start()

        assert not scheduler.running

    async def test_stopping_an_unstarted_scheduler_is_harmless(
        self, build_scheduler: Callable[..., Scheduler]
    ) -> None:
        await build_scheduler().stop()

    async def test_starts_once_and_stops_cleanly(
        self, build_scheduler: Callable[..., Scheduler]
    ) -> None:
        scheduler = build_scheduler(scheduler_enabled=True)
        try:
            scheduler.start()
            first = scheduler._task
            scheduler.start()

            assert scheduler._task is first
        finally:
            await scheduler.stop()

        assert not scheduler.running

    async def test_runs_each_job_on_its_own_interval(
        self, build_scheduler: Callable[..., Scheduler]
    ) -> None:
        scheduler = build_scheduler(scheduler_tick_seconds=300)

        assert {job.name: job.every for job in scheduler.jobs} == {
            "checks": 300,
            "risk": 60 * 60,
            "prune": 24 * 60 * 60,
        }

    async def test_the_loop_outlives_a_failing_job(
        self,
        build_scheduler: Callable[..., Scheduler],
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        # A scheduler that dies on one bad round silently stops every future check.
        scheduler = build_scheduler(time=FakeTime(), scheduler_enabled=True)
        ran_twice = asyncio.Event()
        calls: list[int] = []

        async def failing_check(**_: object) -> None:
            calls.append(1)
            if len(calls) == 1:
                raise RuntimeError("boom")
            ran_twice.set()

        monkeypatch.setattr(scheduler, "check_due", failing_check)

        try:
            scheduler.start()
            await asyncio.wait_for(ran_twice.wait(), timeout=5)
        finally:
            await scheduler.stop()

        assert len(calls) >= 2
        # With the traceback, which the schedule on its own would not log.
        assert "the checks job failed" in caplog.text
        assert "RuntimeError: boom" in caplog.text

    async def test_waking_checks_at_once(
        self, build_scheduler: Callable[..., Scheduler], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The real sleep: without the wake-up, the second look would be five minutes away.
        scheduler = build_scheduler(scheduler_enabled=True, scheduler_tick_seconds=300)
        looked = asyncio.Queue[int]()

        async def recording_check(**_: object) -> None:
            looked.put_nowait(1)

        monkeypatch.setattr(scheduler, "check_due", recording_check)

        try:
            scheduler.start()
            await asyncio.wait_for(looked.get(), timeout=5)
            scheduler.wake()
            await asyncio.wait_for(looked.get(), timeout=5)
        finally:
            await scheduler.stop()
