"""Performing one ping and deciding what it proved.

The fetch and the verdict are deliberately separate. Fetching is either an HTTP request
or a browser navigation; the verdict is the same reasoning either way, and keeping it a
pure function of a site's rules and a fetched response is what makes every branch of it
testable without a network or a browser.
"""

import logging
import random
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol

import httpx

from ..config import Settings
from ..models import CheckOutcome, Setting, Site
from .cookies import StorageState, merge_jar_into_state, state_to_jar

logger = logging.getLogger(__name__)

# How long the body is kept for pattern matching. Enough for any page's markers, and a
# bound on what a hostile or broken response can make this process hold in memory.
MAX_BODY_CHARS = 2_000_000

# Where the retry backoff for a failing site starts, and how it grows. The exponent is
# capped because a site that has been failing for months would otherwise multiply the base
# past timedelta's maximum and raise OverflowError from inside a scheduled check; anything
# above the cap is clamped to the site's interval anyway.
RETRY_BASE = timedelta(minutes=15)
RETRY_FACTOR = 4
MAX_RETRY_EXPONENT = 16


@dataclass(frozen=True)
class FetchResult:
    """What one fetch of a site's ping URL returned."""

    status_code: int
    final_url: str
    body: str
    # The session as it stands after the fetch, with anything the response set folded in.
    state: StorageState
    rotated: bool


@dataclass(frozen=True)
class Verdict:
    """What a fetch proved about the session, and why."""

    outcome: CheckOutcome
    detail: str | None = None


class Fetcher(Protocol):
    """Retrieves a site's ping URL using a stored session."""

    async def fetch(self, site: Site, state: StorageState) -> FetchResult:
        """Request ``site.ping_url`` with ``state`` and return what came back."""
        ...


def matches(pattern: str, text: str) -> bool:
    """Whether ``pattern`` occurs in ``text``, as a regex or failing that as plain text.

    Patterns are written by hand, and a URL or a snippet of page copy pasted into the
    field is frequently not valid regex — an unbalanced bracket in a query string, say.
    Falling back to a substring search means such a pattern still does the obvious thing
    instead of raising from inside a scheduled check.
    """
    try:
        return re.search(pattern, text, re.IGNORECASE) is not None
    except re.error:
        return pattern.lower() in text.lower()


def decide(site: Site, result: FetchResult) -> Verdict:
    """Judge one fetch against a site's rules.

    Ordered most specific first. Landing on the login page is the clearest evidence a
    session has gone, and it usually arrives as a perfectly ordinary 200, so it is
    checked before the status code — otherwise a site whose login page renders with the
    expected status would be reported as healthy.
    """
    pattern = site.effective_login_url_pattern
    if pattern and matches(pattern, result.final_url):
        return Verdict(
            CheckOutcome.LOGIN_EXPIRED,
            f"request ended at {result.final_url}, which is the site's login page",
        )

    if result.status_code != site.expected_status:
        return Verdict(
            CheckOutcome.HTTP_ERROR,
            f"expected HTTP {site.expected_status}, got {result.status_code}",
        )

    if site.failure_pattern and matches(site.failure_pattern, result.body):
        return Verdict(
            CheckOutcome.LOGIN_EXPIRED,
            f"the page contains {site.failure_pattern!r}, which only appears when logged out",
        )

    if site.success_pattern and not matches(site.success_pattern, result.body):
        return Verdict(
            CheckOutcome.PATTERN_MISSING,
            f"the page does not contain {site.success_pattern!r}",
        )

    return Verdict(CheckOutcome.OK)


def next_check_time(
    site: Site,
    outcome: CheckOutcome,
    *,
    now: datetime,
    rng: random.Random | None = None,
) -> datetime:
    """When this site should be pinged again.

    A successful or lapsed check waits the site's full interval: a dead session is not
    revived by asking again sooner, and requesting more often than the account needs is
    exactly the behaviour a site is entitled to object to. A failing *request* backs off
    from minutes upwards instead, so a passing network problem is retried promptly
    without turning into a week-long gap in cover.
    """
    interval = timedelta(days=site.interval_days)
    if outcome in (CheckOutcome.HTTP_ERROR, CheckOutcome.NETWORK_ERROR):
        exponent = min(max(site.consecutive_failures - 1, 0), MAX_RETRY_EXPONENT)
        return now + min(RETRY_BASE * RETRY_FACTOR**exponent, interval)

    # Jitter keeps a site from being asked at the same clock time for years, and spreads
    # a batch of sites added on the same day.
    spread = site.jitter_percent / 100
    factor = 1 + (rng or random).uniform(-spread, spread) if spread else 1.0
    return now + interval * factor


class HttpFetcher:
    """Fetches a site's ping URL with a plain HTTP request.

    The default, because a keep-alive ping needs nothing more than one authenticated
    request, and one request costs the site and this host almost nothing.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def fetch(self, site: Site, state: StorageState) -> FetchResult:
        headers = {"User-Agent": site.user_agent or self._settings.default_user_agent}
        async with httpx.AsyncClient(
            cookies=state_to_jar(state),
            headers=headers,
            follow_redirects=site.follow_redirects,
            timeout=self._settings.request_timeout_seconds,
        ) as client:
            response = await client.get(site.ping_url)
            # From the client, not from the jar built above: httpx copies a Cookies
            # instance when it takes one, so the original object never sees Set-Cookie.
            merged, rotated = merge_jar_into_state(state, client.cookies)
        return FetchResult(
            status_code=response.status_code,
            final_url=str(response.url),
            body=response.text[:MAX_BODY_CHARS],
            state=merged,
            rotated=rotated,
        )


@dataclass(frozen=True)
class CheckReport:
    """Everything one completed check produced."""

    verdict: Verdict
    status_code: int | None
    final_url: str | None
    duration_ms: int
    state: StorageState | None
    rotated: bool


async def perform_check(site: Site, state: StorageState | None, fetcher: Fetcher) -> CheckReport:
    """Ping ``site`` and report what happened, without touching the database.

    A site with no stored session is reported as lapsed rather than as an error: there is
    nothing wrong with the site or the network, someone simply has to log in.
    """
    started = time.monotonic()

    if state is None:
        return CheckReport(
            verdict=Verdict(CheckOutcome.LOGIN_EXPIRED, "no session has been captured yet"),
            status_code=None,
            final_url=None,
            duration_ms=0,
            state=None,
            rotated=False,
        )

    try:
        result = await fetcher.fetch(site, state)
    except httpx.HTTPError as exc:
        # Every network-level failure lands here: DNS, TLS, connect, read timeout. The
        # session is untouched, so it is not reported as lapsed.
        return CheckReport(
            verdict=Verdict(CheckOutcome.NETWORK_ERROR, f"{type(exc).__name__}: {exc}"),
            status_code=None,
            final_url=None,
            duration_ms=int((time.monotonic() - started) * 1000),
            state=None,
            rotated=False,
        )

    return CheckReport(
        verdict=decide(site, result),
        status_code=result.status_code,
        final_url=result.final_url,
        duration_ms=int((time.monotonic() - started) * 1000),
        state=result.state,
        rotated=result.rotated,
    )


def is_at_risk(site: Site, settings_row: Setting, *, now: datetime) -> str | None:
    """Why this site needs attention before anything else touches it, or None if it does not.

    Two clocks can run out — the site's own inactivity deadline, and the expiry of everything held
    for it — and in both cases a check normally resets them: a successful ping is activity, and it
    brings back a reissued cookie. So the question is not "is a deadline near" but **"will it pass
    before the next check"**. If a check comes first, that check will either move the deadline or
    report the session as gone, and a warning now would be noise either way.

    That leaves the case worth raising: the clock runs out before anything looks at this site again,
    which usually means the interval is longer than the site tolerates — or that nothing is going
    to look at it at all, because it has been paused or the schedule has stopped running.
    """
    lead = timedelta(days=settings_row.warning_lead_days)
    next_check = site.next_check_at
    if next_check is None:
        # Due immediately, so a check is about to reset whichever clock is running out.
        return None

    deadline = site.deadline_at
    if _runs_out_first(deadline, next_check, lead=lead, now=now):
        days = max((deadline - now).days, 0)
        return (
            f"the account lapses in {days} day(s), before the next check "
            f"{_when(next_check)} — shorten the interval or log in"
        )

    session = site.session
    expiry = session.expires_at if session is not None else None
    if _runs_out_first(expiry, next_check, lead=lead, now=now):
        days = max((expiry - now).days, 0)
        return (
            f"everything stored for this site expires in {days} day(s), before the next check "
            f"{_when(next_check)}"
        )
    return None


def _runs_out_first(
    clock: datetime | None, next_check: datetime, *, lead: timedelta, now: datetime
) -> bool:
    """Whether ``clock`` runs out before the next check, and near enough to say so.

    Only a check still to come can reset a clock. A next-check time in the past is not a check that
    is going to happen: it is one nothing has run — a site that has been paused, or a schedule that
    stopped — and treating it as imminent would silence a site precisely while nothing is looking
    at it.
    """
    if clock is None:
        return False
    if now <= next_check <= clock:
        return False
    return clock - lead <= now


def _when(moment: datetime) -> str:
    """A next-check time, for a sentence a person reads.

    Never asked about a site with no next-check time: that means due immediately, and a clock a
    check is about to reset is not warned about at all.
    """
    return f"on {moment:%d %b %Y}".replace(" 0", " ")
