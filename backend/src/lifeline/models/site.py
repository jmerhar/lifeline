"""A site whose login session is being kept alive."""

from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin, UtcDateTime
from .enums import PingMethod, SiteStatus, enum_column

if TYPE_CHECKING:
    from .check import Check
    from .site_session import SiteSession


class Site(Base, TimestampMixin):
    """One account on one website.

    A site is really an *account*: the same website added twice, under two names, keeps
    two independent sessions and two browser profiles, which is how a second account on
    the same host is tracked.
    """

    __tablename__ = "sites"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)

    # The page a ping requests. It must require a login to render as itself, or a check
    # can pass while the session is dead.
    ping_url: Mapped[str] = mapped_column(String(2048))
    # Where the interactive login starts. Falls back to the ping URL's origin.
    login_url: Mapped[str | None] = mapped_column(String(2048), default=None)

    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    interval_days: Mapped[int] = mapped_column(Integer, default=7)
    # Spreads the schedule so a site is not requested at the same clock time forever.
    jitter_percent: Mapped[int] = mapped_column(Integer, default=10)
    ping_method: Mapped[PingMethod] = mapped_column(
        enum_column(PingMethod), default=PingMethod.HTTP
    )

    # Captured at login and replayed verbatim: a Cloudflare clearance cookie is bound to
    # the User-Agent that earned it, so pinging with a different one fails the challenge.
    user_agent: Mapped[str | None] = mapped_column(String(512), default=None)
    # The site's icon as a data URI, shown in the site list.
    favicon: Mapped[str | None] = mapped_column(Text, default=None)

    # How a ping's verdict is reached, in the order the checker applies them.
    expected_status: Mapped[int] = mapped_column(Integer, default=200)
    follow_redirects: Mapped[bool] = mapped_column(Boolean, default=True)
    # A substring or regex matched against the final URL. Landing here means the site
    # bounced the request to its login page, which is the clearest sign of a dead session.
    login_url_pattern: Mapped[str | None] = mapped_column(String(512), default=None)
    # Text that must appear in a logged-in response, and text that must not.
    success_pattern: Mapped[str | None] = mapped_column(String(512), default=None)
    failure_pattern: Mapped[str | None] = mapped_column(String(512), default=None)

    # How long this site tolerates an unused account. Drives the countdown in the UI and
    # the warning sent before the deadline; unset means the site imposes no limit.
    inactivity_limit_days: Mapped[int | None] = mapped_column(Integer, default=None)

    status: Mapped[SiteStatus] = mapped_column(enum_column(SiteStatus), default=SiteStatus.UNKNOWN)
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)
    last_check_at: Mapped[datetime | None] = mapped_column(UtcDateTime, default=None)
    last_ok_at: Mapped[datetime | None] = mapped_column(UtcDateTime, default=None)
    next_check_at: Mapped[datetime | None] = mapped_column(UtcDateTime, default=None)

    notes: Mapped[str | None] = mapped_column(Text, default=None)

    session: Mapped[SiteSession | None] = relationship(
        back_populates="site", cascade="all, delete-orphan", uselist=False, lazy="selectin"
    )
    checks: Mapped[list[Check]] = relationship(
        back_populates="site", cascade="all, delete-orphan", passive_deletes=True
    )

    @property
    def deadline_at(self) -> datetime | None:
        """When this account lapses if nothing succeeds before then.

        Measured from the last successful check rather than from the last attempt: a
        failing check does not reset a site's inactivity clock, and treating it as if it
        did would hide exactly the situation this tool exists to catch.
        """
        if self.inactivity_limit_days is None or self.last_ok_at is None:
            return None
        return self.last_ok_at + timedelta(days=self.inactivity_limit_days)

    @property
    def effective_login_url(self) -> str:
        """Where to open the browser for an interactive login."""
        return self.login_url or self.ping_url
