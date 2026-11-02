"""The background work that keeps checks happening, on jigkit's tick loop.

Each tick checks whatever is due, refreshes the risk warnings and prunes history; the due time
already lives on each site's row. A tick is a method call, so a test drives it directly.
"""

import logging
from datetime import UTC, datetime

from jigkit.scheduler import TickLoop
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..config import Settings
from ..models import SiteStatus
from .checker import is_at_risk
from .notifier import Event, Notifier
from .runner import CheckRunner
from .store import list_sites, load_settings_row, prune_checks

logger = logging.getLogger(__name__)


class Scheduler:
    """Runs due checks, refreshes risk warnings and prunes history."""

    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        settings: Settings,
        runner: CheckRunner,
        notifier: Notifier,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._settings = settings
        self._runner = runner
        self._notifier = notifier
        # Looked up on each tick rather than bound now, so a test can replace ``tick``.
        self._loop = TickLoop(
            lambda: self.tick(),
            settings.scheduler_tick_seconds,
            enabled=settings.scheduler_enabled,
            name="lifeline-scheduler",
        )

    async def tick(self, *, now: datetime | None = None) -> None:
        """Do one round of work."""
        now = now or datetime.now(UTC)
        await self._runner.run_due(now=now)
        await self._refresh_risk(now)
        await self._prune(now)

    async def _refresh_risk(self, now: datetime) -> None:
        """Re-evaluate the deadlines that pass without anything being checked.

        A site can run out of time while every check succeeds: the inactivity deadline and
        a cookie's expiry both approach on their own. Recomputing each tick is what makes
        the warning arrive on the day it is due rather than at the next check.
        """
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

    async def _prune(self, now: datetime) -> None:
        async with self._sessionmaker() as session:
            settings_row = await load_settings_row(session)
            removed = await prune_checks(session, settings_row.retention_days, now)
            await session.commit()
        if removed:
            logger.info("pruned %d check(s) past the retention window", removed)

    @property
    def running(self) -> bool:
        """Whether the loop is ticking."""
        return self._loop.running

    def start(self) -> None:
        """Begin ticking, if the deployment wants a scheduler at all."""
        self._loop.start()

    async def stop(self) -> None:
        """Stop ticking and wait for the loop to unwind."""
        await self._loop.stop()
