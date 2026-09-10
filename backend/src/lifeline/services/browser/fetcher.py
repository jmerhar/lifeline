"""Pinging a site through a real browser."""

from ...models import Site
from ..checker import MAX_BODY_CHARS, FetchResult
from ..cookies import StorageState, differs
from .manager import BrowserManager


class BrowserFetcher:
    """Replays a stored session in a headless browser.

    For sites that decide what to serve after running JavaScript, where a plain request
    gets a shell of a page and no evidence either way about the session. Costs a browser
    launch per check, so it is opt-in per site rather than the default.
    """

    def __init__(self, manager: BrowserManager) -> None:
        self._manager = manager

    async def fetch(
        self, site: Site, state: StorageState, *, accept_language: str
    ) -> FetchResult:
        result = await self._manager.fetch(
            site.ping_url, state, site.user_agent, accept_language=accept_language
        )
        # A browser folds whatever the page was handed into its own storage as it navigates, so
        # the state it gives back already carries any reissued session; whether one arrived is
        # decided by comparing it against what went in. Everything counts, not only the cookies:
        # a site that keeps its token in local storage sets none at all, and comparing those alone
        # said nothing had changed every single time.
        rotated = differs(state, result.state)
        return FetchResult(
            status_code=result.status_code,
            final_url=result.final_url,
            body=result.body[:MAX_BODY_CHARS],
            state=result.state,
            rotated=rotated,
        )
