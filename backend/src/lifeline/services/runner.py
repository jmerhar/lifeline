"""Running checks against the database: persisting results and reacting to them."""

import logging
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..config import Settings
from ..models import (
    CaptureMethod,
    Check,
    CheckOutcome,
    PingMethod,
    Setting,
    Site,
    SiteSession,
    SiteStatus,
)
from .checker import (
    CheckReport,
    Fetcher,
    HttpFetcher,
    Verdict,
    is_at_risk,
    next_check_time,
    perform_check,
)
from .cookies import StorageState, cookie_names, earliest_expiry
from .crypto import Cipher, DecryptionError
from .notifier import Event, Notifier
from .store import due_sites, get_site, load_settings_row

logger = logging.getLogger(__name__)

# The statuses that mean the stored session itself is the problem.
_LOGGED_OUT_STATUSES = (SiteStatus.LAPSED,)


class CheckRunner:
    """Performs checks and applies what they mean to a site.

    Fetchers are injected per ping method so that a test drives the whole path — verdict,
    persistence, status transition and notification — without a network or a browser.
    """

    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        settings: Settings,
        cipher: Cipher,
        notifier: Notifier,
        fetchers: dict[PingMethod, Fetcher] | None = None,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._settings = settings
        self._cipher = cipher
        self._notifier = notifier
        self._fetchers: dict[PingMethod, Fetcher] = fetchers or {
            PingMethod.HTTP: HttpFetcher(settings)
        }

    def _fetcher_for(self, site: Site) -> Fetcher:
        fetcher = self._fetchers.get(site.ping_method)
        if fetcher is None:
            raise RuntimeError(
                f"{site.ping_method} checks are not available in this deployment"
            )
        return fetcher

    def _load_state(self, site: Site) -> tuple[StorageState | None, str | None]:
        """Decrypt a site's stored session, or say why it cannot be used."""
        if site.session is None:
            return None, None
        try:
            return self._cipher.decrypt_json(site.session.state), None
        except DecryptionError as exc:
            # Reported as a lapsed session because the remedy is the same — log in again —
            # and because pretending the site is unreachable would hide a real problem.
            return None, str(exc)

    async def run(self, site_id: int, *, now: datetime | None = None) -> Check | None:
        """Check one site, record the result and act on it."""
        now = now or datetime.now(UTC)
        async with self._sessionmaker() as session:
            site = await get_site(session, site_id)
            if site is None:
                return None
            settings_row = await load_settings_row(session)

            state, state_error = self._load_state(site)
            if state_error is not None:
                report = CheckReport(
                    verdict=Verdict(CheckOutcome.LOGIN_EXPIRED, state_error),
                    status_code=None,
                    final_url=None,
                    duration_ms=0,
                    state=None,
                    rotated=False,
                )
            else:
                report = await perform_check(site, state, self._fetcher_for(site))

            check = self._record(session, site, report, now)
            events = self._apply(site, report, settings_row, now)
            await session.commit()

        for event, detail in events:
            await self._notifier.notify(settings_row, event, site, detail, now=now)
        return check

    def _record(
        self, session: AsyncSession, site: Site, report: CheckReport, now: datetime
    ) -> Check:
        """Write the check row and fold a rotated session back into storage."""
        check = Check(
            site_id=site.id,
            started_at=now,
            outcome=report.verdict.outcome,
            status_code=report.status_code,
            final_url=report.final_url,
            duration_ms=report.duration_ms,
            detail=report.verdict.detail,
        )
        session.add(check)

        if report.rotated and report.state is not None and site.session is not None:
            self._save_state(site.session, report.state, now)
        return check

    def _save_state(self, stored: SiteSession, state: StorageState, now: datetime) -> None:
        stored.state = self._cipher.encrypt_json(state)
        stored.rotated_at = now
        stored.earliest_expiry = earliest_expiry(state)
        stored.cookie_names = ",".join(cookie_names(state))

    def _apply(
        self, site: Site, report: CheckReport, settings_row: Setting, now: datetime
    ) -> list[tuple[Event, str | None]]:
        """Update the site from a check and collect the notifications it warrants."""
        previous = site.status
        outcome = report.verdict.outcome
        site.last_check_at = now

        if outcome.is_success:
            site.last_ok_at = now
            site.consecutive_failures = 0
            site.status = SiteStatus.ALIVE
        else:
            site.consecutive_failures += 1
            site.status = SiteStatus.LAPSED if outcome.means_logged_out else SiteStatus.ERROR

        # After the failure count is updated, so a failing site's backoff grows.
        site.next_check_at = next_check_time(site, outcome, now=now)

        events: list[tuple[Event, str | None]] = []
        if site.status in _LOGGED_OUT_STATUSES and previous not in _LOGGED_OUT_STATUSES:
            events.append((Event.LAPSED, report.verdict.detail))
        elif site.status is SiteStatus.ALIVE and previous in (SiteStatus.LAPSED, SiteStatus.ERROR):
            events.append((Event.RECOVERED, None))
        elif (
            site.status is SiteStatus.ERROR
            and site.consecutive_failures >= settings_row.error_threshold
        ):
            events.append((Event.ERRORS, report.verdict.detail))

        # Risk is evaluated on a live session only: a lapsed one has already been reported,
        # and saying it also expires soon adds nothing to act on.
        if site.status is SiteStatus.ALIVE:
            reason = is_at_risk(site, settings_row, now=now)
            if reason is not None:
                site.status = SiteStatus.AT_RISK
                events.append((Event.AT_RISK, reason))
        return events

    async def run_due(self, *, now: datetime | None = None) -> list[int]:
        """Check every site that is due, one after another.

        Sequential on purpose. Checks are cheap but not free, and running them in parallel
        would put a burst of requests on several sites at once and a burst of CPU on the
        host, to save time that nothing is waiting for.
        """
        now = now or datetime.now(UTC)
        async with self._sessionmaker() as session:
            due = await due_sites(session, now)
            site_ids = [site.id for site in due]

        for site_id in site_ids:
            try:
                await self.run(site_id, now=now)
            except Exception:
                # One site's failure must not stop the rest of the sweep; the traceback is
                # logged rather than swallowed so it is still diagnosable.
                logger.exception("check failed for site %s", site_id)
        return site_ids

    async def store_session(
        self,
        site_id: int,
        state: StorageState,
        captured_via: CaptureMethod,
        *,
        user_agent: str | None = None,
        now: datetime | None = None,
    ) -> None:
        """Save a freshly captured session for a site."""
        now = now or datetime.now(UTC)
        async with self._sessionmaker() as session:
            site = await get_site(session, site_id)
            if site is None:
                raise LookupError(f"no site with id {site_id}")
            stored = site.session or SiteSession(site_id=site_id, captured_at=now, state=b"")
            stored.captured_via = captured_via
            stored.captured_at = now
            stored.rotated_at = None
            self._save_state(stored, state, now)
            if user_agent:
                site.user_agent = user_agent
            site.session = stored
            # A new session is a new situation: it is due for a check now, and the status
            # is not yet known rather than still whatever the dead session scored.
            site.status = SiteStatus.UNKNOWN
            site.consecutive_failures = 0
            site.next_check_at = None
            await session.commit()
        # Cooldowns from the previous session would silence the message that says whether
        # this login actually worked.
        self._notifier.forget(site_id)
