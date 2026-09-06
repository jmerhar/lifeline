"""Pinging a site through a real browser."""

from ...models import Site
from ..checker import MAX_BODY_CHARS, FetchResult
from ..cookies import StorageState, cookie_names
from .manager import BrowserManager


class BrowserFetcher:
    """Replays a stored session in a headless browser.

    For sites that decide what to serve after running JavaScript, where a plain request
    gets a shell of a page and no evidence either way about the session. Costs a browser
    launch per check, so it is opt-in per site rather than the default.
    """

    def __init__(self, manager: BrowserManager) -> None:
        self._manager = manager

    async def fetch(self, site: Site, state: StorageState) -> FetchResult:
        result = await self._manager.fetch(site.ping_url, state, site.user_agent)
        # A browser merges Set-Cookie into its own jar as it navigates, so the state it
        # hands back already carries any rotation; "rotated" is decided by comparing what
        # is in it against what went in.
        rotated = cookie_names(result.state) != cookie_names(state) or any(
            before.get("value") != after.get("value")
            for before, after in zip(
                sorted(state["cookies"], key=lambda cookie: cookie["name"]),
                sorted(result.state["cookies"], key=lambda cookie: cookie["name"]),
                strict=False,
            )
        )
        return FetchResult(
            status_code=result.status_code,
            final_url=result.final_url,
            body=result.body[:MAX_BODY_CHARS],
            state=result.state,
            rotated=rotated,
        )
