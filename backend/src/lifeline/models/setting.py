"""Instance-wide settings, held in a single row."""

from sqlalchemy import Boolean, CheckConstraint, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin

# The only primary key this table ever holds.
SETTINGS_ID = 1


class Setting(Base, TimestampMixin):
    """Everything configurable at runtime rather than through the environment.

    A single row rather than a key/value table: these are a fixed, typed set of knobs,
    and a typed row means a bad value is rejected on write instead of surfacing as a
    string that fails to parse weeks later inside the scheduler.
    """

    __tablename__ = "settings"
    __table_args__ = (CheckConstraint(f"id = {SETTINGS_ID}", name="singleton"),)

    id: Mapped[int] = mapped_column(primary_key=True, default=SETTINGS_ID)

    # Apprise target URLs, one per line (mailto://, tgram://, ntfy:// and the rest).
    apprise_urls: Mapped[str] = mapped_column(Text, default="")

    notify_on_lapsed: Mapped[bool] = mapped_column(Boolean, default=True)
    notify_on_recovered: Mapped[bool] = mapped_column(Boolean, default=True)
    notify_on_errors: Mapped[bool] = mapped_column(Boolean, default=True)
    notify_on_cookie_expiry: Mapped[bool] = mapped_column(Boolean, default=True)
    notify_on_deadline: Mapped[bool] = mapped_column(Boolean, default=True)

    # How long a site stays quiet after notifying about it, so one dead session cannot
    # turn into a message per tick.
    notify_cooldown_hours: Mapped[int] = mapped_column(Integer, default=24)
    # How far ahead of a cookie expiry or an inactivity deadline to warn. Long enough to
    # leave time to sit down and log in.
    warning_lead_days: Mapped[int] = mapped_column(Integer, default=7)
    # Consecutive failed checks before the failures are reported as a site problem rather
    # than treated as a transient network blip.
    error_threshold: Mapped[int] = mapped_column(Integer, default=3)

    # How much detail the log carries. A setting rather than only an environment variable,
    # because the moment DEBUG is wanted is the moment something is failing, and restarting the
    # container to get it discards whatever was interesting.
    log_level: Mapped[str] = mapped_column(String(10), default="INFO")

    # Sent with every check, and with the comparison that works a site's rules out. A site with
    # more than one language decides from this which to answer in, and without it answers in
    # whichever it prefers — which is how a page a person reads in English arrives in Hungarian,
    # taking every pattern they typed with it.
    accept_language: Mapped[str] = mapped_column(String(120), default="en-US,en;q=0.9")

    default_interval_days: Mapped[int] = mapped_column(Integer, default=7)
    retention_days: Mapped[int] = mapped_column(Integer, default=90)
    # A login session left open holds a browser and an X server; this closes it.
    browser_idle_timeout_minutes: Mapped[int] = mapped_column(Integer, default=15)

    @property
    def apprise_url_list(self) -> list[str]:
        """The configured targets, blank lines and comments dropped."""
        return [
            line.strip()
            for line in self.apprise_urls.splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
