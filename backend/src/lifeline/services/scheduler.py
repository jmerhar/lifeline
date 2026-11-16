"""The background work that keeps checks happening, on jigkit's Schedule.

Three jobs, each on its own interval: checking whatever is due, refreshing the risk warnings, and
pruning history. The due time of each check lives on its site's row; the checks job sleeps until
the soonest of them, and :meth:`Scheduler.wake` runs it at once. Each job is a method call, so a
test drives it directly.
"""

import asyncio
import contextlib
import logging
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from jigkit.scheduler import Job, LoggingReporter, Schedule
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..config import Settings
from ..models import SiteStatus
from .checker import is_at_risk
from .notifier import Event, Notifier
from .runner import CheckRunner
from .store import list_sites, load_settings_row, prune_checks, soonest_check

logger = logging.getLogger(__name__)

NAME = "lifeline-scheduler"
#: How often the risk warnings are recomputed. The deadlines they track are counted in days.
RISK_EVERY_SECONDS = 60 * 60
#: How often history past the retention window is removed.
PRUNE_EVERY_SECONDS = 24 * 60 * 60
#: The shortest wait between two looks for due checks, so a site whose next check is somehow
#: still in the past after a sweep cannot turn the loop into a busy one.
MIN_CHECK_GAP_SECONDS = 60


class Scheduler:
    """Runs due checks, refreshes risk warnings and prunes history."""

    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        settings: Settings,
        runner: CheckRunner,
        notifier: Notifier,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._settings = settings
        self._runner = runner
        self._notifier = notifier
        self._wake = asyncio.Event()
        # The jobs look their methods up when they run rather than binding them now, so a test
        # can replace one.
        self.jobs = [
            Job(
                "checks",
                settings.scheduler_tick_seconds,
                lambda: self._logged("checks", self.check_due),
                on_wake=True,
            ),
            Job("risk", RISK_EVERY_SECONDS, lambda: self._logged("risk", self.refresh_risk)),
            Job("prune", PRUNE_EVERY_SECONDS, lambda: self._logged("prune", self.prune)),
        ]
        self._schedule = Schedule(
            LoggingReporter(NAME, clock=clock, sleep=sleep), self.jobs, wake=self._wake
        )
        self._task: asyncio.Task[None] | None = None

    def wake(self) -> None:
        """Look for due checks at once rather than at the next turn, such as for a new session."""
        self._wake.set()

    async def check_due(self, *, now: datetime | None = None) -> None:
        """Check every site that is due, then sleep until the next one is.

        The wait is bounded by ``SCHEDULER_TICK_SECONDS`` as well, so a check that an edit in the
        interface brought forward is still picked up within that time.
        """
        now = now or datetime.now(UTC)
        await self._runner.run_due(now=now)
        async with self._sessionmaker() as session:
            soonest = await soonest_check(session, now)
        longest = self._settings.scheduler_tick_seconds
        if soonest is None:
            wait = longest
        else:
            until = (soonest - now).total_seconds()
            wait = min(max(until, MIN_CHECK_GAP_SECONDS), longest)
        self._schedule.due_in("checks", wait)

    async def refresh_risk(self, *, now: datetime | None = None) -> None:
        """Re-evaluate the deadlines that pass without anything being checked.

        A site can run out of time while every check succeeds: the inactivity deadline and
        a cookie's expiry both approach on their own. Recomputing them on a timer is what makes
        the warning arrive on the day it is due rather than at the next check.
        """
        now = now or datetime.now(UTC)
        async with self._sessionmaker() as session:
            settings_row = await load_settings_row(session)
            pending: list[tuple[object, str]] = []
            for site in await list_sites(session):
                if site.status not in (SiteStatus.ALIVE, SiteStatus.AT_RISK):
                    continue
                reason = is_at_risk(site, settings_row, now=now)
                if reason is None:
                    # Re-logging in pushes the deadline out again.
                    site.status = SiteStatus.ALIVE
                    continue
                if site.status is not SiteStatus.AT_RISK:
                    logger.info("%s is running out of time: %s", site.name, reason)
                site.status = SiteStatus.AT_RISK
                pending.append((site, reason))
            await session.commit()

        for site, reason in pending:
            await self._notifier.notify(settings_row, Event.AT_RISK, site, reason, now=now)

    async def prune(self, *, now: datetime | None = None) -> None:
        """Remove checks older than the retention window."""
        now = now or datetime.now(UTC)
        async with self._sessionmaker() as session:
            settings_row = await load_settings_row(session)
            removed = await prune_checks(session, settings_row.retention_days, now)
            await session.commit()
        if removed:
            logger.info("pruned %d check(s) past the retention window", removed)

    async def _logged(self, name: str, job: Callable[[], Awaitable[None]]) -> bool:
        """Run a job, logging a failure with its traceback rather than raising it.

        The schedule would log only the message, and a failing job carries on being retried
        when next due either way.
        """
        try:
            await job()
        except Exception:
            logger.exception("%s: the %s job failed; it runs again when next due", NAME, name)
            return False
        return True

    @property
    def running(self) -> bool:
        """Whether the loop is running."""
        return self._task is not None

    def start(self) -> None:
        """Begin running the jobs, if the deployment wants a scheduler at all."""
        if not self._settings.scheduler_enabled:
            logger.info("%s disabled by configuration", NAME)
            return
        if self._task is not None:
            return
        self._task = asyncio.create_task(self._schedule.run(), name=NAME)
        logger.info(
            "%s started, looking for due checks at least every %ds",
            NAME,
            self._settings.scheduler_tick_seconds,
        )

    async def stop(self) -> None:
        """Stop the loop and wait for it to unwind."""
        if self._task is None:
            return
        self._task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._task
        self._task = None
