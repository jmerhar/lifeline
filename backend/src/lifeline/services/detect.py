"""Working out how to tell a live session from a dead one, by looking at both.

The hardest question when adding a site is what text or URL distinguishes a signed-in page
from a signed-out one, and it is a question nobody can answer without having seen both pages.
Fetching the same URL twice — once with the stored session and once with no cookies at all —
produces exactly that pair, and the difference between them is the answer.

Deliberately not clever about it. Rather than diffing the two documents and inventing a regex
from whatever fell out, this looks for a short list of phrases that reliably mean "signed in"
or "signed out" on a page written in English, and reports the ones that appear on one side and
not the other. A person can read the result, understand why it was chosen, and change it. A
generated regex is none of those things, and the cost of getting this wrong is a site that
reports itself healthy while its session is dead.
"""

import logging
from dataclasses import dataclass, field
from urllib.parse import urlsplit

import httpx

from ..config import Settings
from ..models import PingMethod, Site
from ..models.enums import CheckOutcome
from .browser.manager import BrowserManager, BrowserUnavailable
from .checker import MAX_BODY_CHARS, FetchResult, decide
from .cookies import StorageState, empty_state, state_to_jar

# A session with nothing in it, for the signed-out half of the comparison.
EMPTY_STATE: StorageState = empty_state()

logger = logging.getLogger(__name__)

# Phrases that appear on a page you are looking at while signed in, and not otherwise. Ordered
# by how specific they are: "log out" is an action only offered to somebody who is signed in,
# whereas "my account" is a label a marketing page might also carry.
SIGNED_IN_MARKERS = (
    "Log out",
    "Logout",
    "Sign out",
    "Signout",
    "My account",
    "My profile",
)

# The mirror image: text a login page shows and a signed-in page does not. "Remember me" is the
# strongest of these, since it belongs to a login form and nothing else.
SIGNED_OUT_MARKERS = (
    "Remember me",
    "Forgot your password",
    "Forgot password",
    "Enter your password",
    "Log in",
    "Sign in",
)


@dataclass(frozen=True)
class Probe:
    """What one URL returned, under one set of cookies."""

    status_code: int
    final_url: str
    body: str


@dataclass
class Detected:
    """The rules a pair of probes suggests, and what could not be worked out."""

    # Where a request with no session ends up, which is the site's login page by definition.
    login_url: str | None = None
    login_url_pattern: str | None = None
    success_pattern: str | None = None
    failure_pattern: str | None = None
    # Plain sentences for the interface: what was found, and what was not.
    notes: list[str] = field(default_factory=list)

    @property
    def found_anything(self) -> bool:
        """Whether the pair produced a rule at all.

        The login URL is not counted: it says where to open a browser, not how to judge a page.
        """
        return any((self.login_url_pattern, self.success_pattern, self.failure_pattern))


class Detector:
    """Fetches a site's ping URL signed in and signed out, and compares the two."""

    def __init__(self, settings: Settings, browser: BrowserManager | None = None) -> None:
        self._settings = settings
        self._browser = browser

    async def probe(self, site: Site, state: StorageState | None) -> Probe:
        """Fetch the ping URL once, with the given cookies or with none.

        Fetched the way the site will actually be checked. A site that builds its page in the
        browser serves the same markup signed in or out — the difference appears only once the
        JavaScript has run — so comparing plain responses for one of those reports, correctly and
        uselessly, that the two are identical.
        """
        if site.ping_method is PingMethod.BROWSER:
            return await self._probe_rendered(site, state)
        headers = {"User-Agent": site.user_agent or self._settings.default_user_agent}
        async with httpx.AsyncClient(
            cookies=state_to_jar(state) if state is not None else None,
            headers=headers,
            # Always followed, whatever the site's own setting says: the point here is to find
            # out where a signed-out request *lands*, which a stopped redirect never reveals.
            follow_redirects=True,
            timeout=self._settings.request_timeout_seconds,
        ) as client:
            response = await client.get(site.ping_url)
        return Probe(
            status_code=response.status_code,
            final_url=str(response.url),
            body=response.text[:MAX_BODY_CHARS],
        )

    async def _probe_rendered(self, site: Site, state: StorageState | None) -> Probe:
        """Load the page in a browser and report the document its JavaScript produced."""
        if self._browser is None:
            raise BrowserUnavailable("this deployment cannot render pages in a browser")
        result = await self._browser.fetch(
            site.ping_url, state or EMPTY_STATE, site.user_agent
        )
        return Probe(
            status_code=result.status_code,
            final_url=result.final_url,
            body=result.body[:MAX_BODY_CHARS],
        )

    async def detect(self, site: Site, state: StorageState) -> Detected:
        """Work out the site's rules from a signed-in and a signed-out fetch."""
        signed_in = await self.probe(site, state)
        signed_out = await self.probe(site, None)
        return compare(signed_in, signed_out)


def compare(signed_in: Probe, signed_out: Probe) -> Detected:
    """Derive what rules the difference between two probes supports."""
    found = Detected()

    if signed_out.final_url != signed_in.final_url:
        found.login_url = _without_query(signed_out.final_url)
        found.login_url_pattern = _distinctive_part(signed_out.final_url, signed_in.final_url)
        found.notes.append(
            f"Signed out, the request ends at {signed_out.final_url} instead of "
            f"{signed_in.final_url}. That is the most reliable signal there is."
        )

    found.success_pattern = _only_in(SIGNED_IN_MARKERS, signed_in.body, signed_out.body)
    if found.success_pattern:
        found.notes.append(
            f"{found.success_pattern!r} is on the page when signed in and not when signed out."
        )

    found.failure_pattern = _only_in(SIGNED_OUT_MARKERS, signed_out.body, signed_in.body)
    if found.failure_pattern:
        found.notes.append(
            f"{found.failure_pattern!r} appears only once the session is gone."
        )

    if signed_out.status_code != signed_in.status_code:
        found.notes.append(
            f"Signed out, the site answers HTTP {signed_out.status_code} rather than "
            f"{signed_in.status_code}, so the expected status alone would catch it."
        )

    if not found.found_anything:
        found.notes.append(
            "The page looks the same signed in and signed out, so nothing here can tell them "
            "apart. Open the site logged out, find some text only that page shows, and put it "
            "in 'Page must not contain'."
        )
    return found


def _only_in(candidates: tuple[str, ...], present: str, absent: str) -> str | None:
    """The first candidate that is in ``present`` and not in ``absent``.

    Matched without regard to case, because a page's own capitalisation is not something the
    person configuring it should have to reproduce, but returned as written: it is stored as a
    pattern the site owner reads, and the matcher is case-insensitive too.
    """
    lowered_present = present.lower()
    lowered_absent = absent.lower()
    for candidate in candidates:
        needle = candidate.lower()
        if needle in lowered_present and needle not in lowered_absent:
            return candidate
    return None


def _without_query(url: str) -> str:
    """A URL with its query and fragment dropped.

    The redirect to a login page usually carries where to return to afterwards
    (``?return=%2Fhome``). Kept, that would be stored as the place to open a browser for every
    future login, sending it back to one particular page for reasons nobody would remember.
    """
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}{parts.path}"


def _distinctive_part(landed: str, expected: str) -> str:
    """The shortest part of ``landed`` that will not also match ``expected``.

    A whole URL works as a pattern but reads as noise and breaks the moment the site appends a
    query parameter, so the last path segment is preferred — "login.php" rather than
    "https://example.org/login.php?return=%2Fhome". The full path is the fallback for a URL
    whose last segment is something unhelpfully common, and the whole URL for one with no path
    to speak of.
    """
    path = urlsplit(landed).path
    segment = path.rstrip("/").rsplit("/", maxsplit=1)[-1]
    if segment and segment not in expected:
        return segment
    if path and path not in expected:
        return path
    return landed


@dataclass(frozen=True)
class Trial:
    """What a set of rules would conclude about a page, live and dead."""

    live_outcome: CheckOutcome
    live_detail: str | None
    dead_outcome: CheckOutcome
    dead_detail: str | None

    @property
    def works(self) -> bool:
        """Whether these rules would call a working session working and a dead one dead.

        Both halves matter and neither is enough alone. Rules that pass the live page but also
        pass the dead one describe a site that never reports a problem; rules that catch the dead
        page but fail the live one report a problem constantly. The second is at least loud.
        """
        return self.live_outcome.is_success and not self.dead_outcome.is_success


def verify(site: Site, signed_in: Probe, signed_out: Probe) -> Trial:
    """Judge both pages by ``site``'s rules, using the code that judges a real check.

    Not a search for each string in each page, which would answer a narrower question than the
    one being asked. The rules interact — a login-page pattern is consulted before the status
    code, and a missing success pattern is only reached if the status matched — so the only
    honest test is the verdict itself, twice.
    """
    return Trial(
        live_outcome=(live := decide(site, _as_result(signed_in))).outcome,
        live_detail=live.detail,
        dead_outcome=(dead := decide(site, _as_result(signed_out))).outcome,
        dead_detail=dead.detail,
    )


def _as_result(probe: Probe) -> FetchResult:
    """A probe in the shape a verdict is passed.

    The session fields are what a check would have merged back into storage, and no verdict reads
    them, so an empty one stands in rather than inventing a jar this never touched.
    """
    return FetchResult(
        status_code=probe.status_code,
        final_url=probe.final_url,
        body=probe.body,
        state=EMPTY_STATE,
        rotated=False,
    )
