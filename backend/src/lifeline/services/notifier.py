"""Sending notifications through Apprise.

One URL list covers email, Telegram, ntfy, Discord and the rest, so the tool needs no
per-transport configuration of its own and gains new destinations by upgrading a library
rather than by growing code.
"""

import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Protocol

from ..models import Setting, Site

logger = logging.getLogger(__name__)


class Event(StrEnum):
    """The things worth telling someone about."""

    LAPSED = "lapsed"
    RECOVERED = "recovered"
    ERRORS = "errors"
    AT_RISK = "at_risk"
    TEST = "test"


# Which settings toggle governs which event. TEST is absent on purpose: a test message is
# an explicit request, so honouring a toggle would make the button look broken.
_TOGGLES = {
    Event.LAPSED: "notify_on_lapsed",
    Event.RECOVERED: "notify_on_recovered",
    Event.ERRORS: "notify_on_errors",
    Event.AT_RISK: "notify_on_deadline",
}


@dataclass(frozen=True)
class Notification:
    """One message, ready to send."""

    event: Event
    title: str
    body: str


class Sender(Protocol):
    """Delivers a notification to every configured destination."""

    async def send(self, urls: list[str], title: str, body: str) -> bool:
        """Return whether at least one destination accepted the message."""
        ...


class AppriseSender:
    """Sends through Apprise.

    Apprise is synchronous and does network IO, so it runs in a worker thread: called
    directly it would block the event loop, stalling every other check and the web UI for
    as long as the slowest destination takes to answer.
    """

    async def send(self, urls: list[str], title: str, body: str) -> bool:
        return await asyncio.to_thread(self._send, urls, title, body)

    @staticmethod
    def _send(urls: list[str], title: str, body: str) -> bool:
        import apprise

        client = apprise.Apprise()
        for url in urls:
            if not client.add(url):
                logger.warning("apprise rejected a destination: %s", _redact(url))
        if not len(client):
            return False
        return bool(client.notify(title=title, body=body))


def _redact(url: str) -> str:
    """A notification URL with its credentials removed, for logging.

    An Apprise URL is mostly credential — a bot token, an SMTP password — so logging one
    verbatim writes a working secret into the container's log.
    """
    scheme, separator, rest = url.partition("://")
    if not separator:
        return "<malformed url>"
    return f"{scheme}://…" if not rest else f"{scheme}://…{rest[-4:]}"


def _describe(site: Site) -> str:
    """A site's name and where it was asked."""
    return f"{site.name} ({site.ping_url})"


def build(event: Event, site: Site | None = None, detail: str | None = None) -> Notification:
    """Compose the message for ``event``.

    Written as something to act on rather than a status dump: the point of the message is
    that someone has to go and log in.
    """
    match event:
        case Event.LAPSED:
            return Notification(
                event,
                f"lifeline: {site.name} needs a new login" if site else "lifeline",
                f"The session for {_describe(site)} is no longer valid.\n\n"
                f"{detail or 'The site did not accept the stored session.'}\n\n"
                "Open lifeline and log in again to keep the account active.",
            )
        case Event.RECOVERED:
            return Notification(
                event,
                f"lifeline: {site.name} is alive again",
                f"The session for {_describe(site)} is working again. Nothing to do.",
            )
        case Event.ERRORS:
            return Notification(
                event,
                f"lifeline: {site.name} cannot be reached",
                f"Checks against {_describe(site)} keep failing.\n\n"
                f"{detail or 'No further detail.'}\n\n"
                "The stored session has not been touched; this looks like the site or the "
                "network rather than the login.",
            )
        case Event.AT_RISK:
            return Notification(
                event,
                f"lifeline: {site.name} is running out of time",
                f"{_describe(site)}: {detail}\n\nLog in again before then.",
            )
        case Event.TEST:
            return Notification(
                event,
                "lifeline: test notification",
                "If you are reading this, notifications are configured correctly.",
            )


class Notifier:
    """Decides whether an event should be sent, and sends it.

    Both halves live here because "should this be sent" is the interesting part: a site
    whose session has died will fail every check from then on, and a message per check
    would train someone to ignore the one that matters.
    """

    def __init__(self, sender: Sender) -> None:
        self._sender = sender
        # Last time each (site, event) pair was actually sent. Held in memory rather than
        # in the database because its only job is to suppress repeats within a cooldown,
        # and a restart is a reasonable moment to be told again about a still-dead session.
        self._last_sent: dict[tuple[int | None, Event], datetime] = {}

    def _suppressed_until(self, key: tuple[int | None, Event], cooldown: timedelta) -> datetime | None:
        sent_at = self._last_sent.get(key)
        return None if sent_at is None else sent_at + cooldown

    async def notify(
        self,
        settings_row: Setting,
        event: Event,
        site: Site | None = None,
        detail: str | None = None,
        *,
        now: datetime | None = None,
    ) -> bool:
        """Send the message for ``event`` unless it is switched off or still cooling down."""
        now = now or datetime.now(UTC)
        toggle = _TOGGLES.get(event)
        if toggle is not None and not getattr(settings_row, toggle):
            return False

        urls = settings_row.apprise_url_list
        if not urls:
            return False

        key = (site.id if site else None, event)
        if event is not Event.TEST:
            until = self._suppressed_until(key, timedelta(hours=settings_row.notify_cooldown_hours))
            if until is not None and until > now:
                logger.debug("suppressing %s for site %s until %s", event, key[0], until)
                return False

        message = build(event, site, detail)
        delivered = await self._sender.send(urls, message.title, message.body)
        if delivered:
            self._last_sent[key] = now
            logger.info(
                "notified about %s%s via %s",
                event,
                f" for {site.name}" if site else "",
                ", ".join(_redact(url) for url in urls),
            )
        else:
            logger.warning("no destination accepted the %s notification", event)
        return delivered

    def forget(self, site_id: int) -> None:
        """Drop a site's cooldowns, so the next event about it is sent immediately.

        Called when a session is recaptured: the situation has materially changed, and
        holding the old cooldown would silence the message that says whether the new login
        actually worked.
        """
        for key in [key for key in self._last_sent if key[0] == site_id]:
            del self._last_sent[key]
