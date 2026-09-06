"""Fetching a site's icon."""

import base64

import httpx
import pytest
import respx

from lifeline.services import favicon

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


@pytest.fixture
async def client() -> httpx.AsyncClient:
    async with httpx.AsyncClient(follow_redirects=True) as instance:
        yield instance


class TestFetch:
    @respx.mock
    async def test_prefers_the_conventional_path(self, client: httpx.AsyncClient) -> None:
        respx.get("https://example.org/favicon.ico").respond(
            200, content=PNG, headers={"content-type": "image/png"}
        )

        icon = await favicon.fetch("https://example.org/home", client=client)

        assert icon.startswith("data:image/png;base64,")

    @respx.mock
    async def test_falls_back_to_the_declared_icon(self, client: httpx.AsyncClient) -> None:
        # Plenty of sites serve nothing at /favicon.ico and declare the icon in the page.
        # Registered before the origin route: respx matches in order, and a route given only
        # an origin also matches paths under it.
        respx.get("https://example.org/favicon.ico").respond(404)
        respx.get("https://example.org/img/logo.png").respond(
            200, content=PNG, headers={"content-type": "image/png"}
        )
        respx.get("https://example.org").respond(
            200, html='<html><head><link rel="shortcut icon" href="/img/logo.png"></head></html>'
        )

        icon = await favicon.fetch("https://example.org/home", client=client)

        assert icon.startswith("data:image/png;base64,")

    @respx.mock
    async def test_treats_an_octet_stream_as_an_icon(self, client: httpx.AsyncClient) -> None:
        # Which is what a good many servers send for a .ico file.
        respx.get("https://example.org/favicon.ico").respond(
            200, content=PNG, headers={"content-type": "application/octet-stream"}
        )

        assert (await favicon.fetch("https://example.org/", client=client)).startswith(
            "data:image/x-icon;base64,"
        )

    @respx.mock
    async def test_refuses_something_that_is_not_an_image(self, client: httpx.AsyncClient) -> None:
        respx.get("https://example.org/favicon.ico").respond(
            200, text="<html>not found</html>", headers={"content-type": "text/html"}
        )
        respx.get("https://example.org").respond(200, html="<html><head></head></html>")

        assert await favicon.fetch("https://example.org/", client=client) is None

    @respx.mock
    async def test_refuses_an_icon_that_is_too_large(self, client: httpx.AsyncClient) -> None:
        # Embedded in every site listing, so the size ceiling is the point.
        respx.get("https://example.org/favicon.ico").respond(
            200,
            content=b"x" * (favicon.MAX_ICON_BYTES + 1),
            headers={"content-type": "image/png"},
        )
        respx.get("https://example.org").respond(200, html="<html></html>")

        assert await favicon.fetch("https://example.org/", client=client) is None

    @respx.mock
    async def test_refuses_an_empty_response(self, client: httpx.AsyncClient) -> None:
        respx.get("https://example.org/favicon.ico").respond(
            200, content=b"", headers={"content-type": "image/png"}
        )
        respx.get("https://example.org").respond(200, html="<html></html>")

        assert await favicon.fetch("https://example.org/", client=client) is None

    @respx.mock
    async def test_gives_up_quietly_when_the_site_is_unreachable(
        self, client: httpx.AsyncClient
    ) -> None:
        # A missing icon is cosmetic; a slow or hostile site must not stop a site being saved.
        respx.get("https://example.org/favicon.ico").mock(
            side_effect=httpx.ConnectError("no route")
        )

        assert await favicon.fetch("https://example.org/", client=client) is None

    @respx.mock
    async def test_gives_up_when_the_home_page_is_not_available(
        self, client: httpx.AsyncClient
    ) -> None:
        respx.get("https://example.org/favicon.ico").respond(404)
        respx.get("https://example.org").respond(500)

        assert await favicon.fetch("https://example.org/", client=client) is None

    @respx.mock
    async def test_skips_a_declared_icon_that_cannot_be_fetched(
        self, client: httpx.AsyncClient
    ) -> None:
        respx.get("https://example.org/favicon.ico").respond(404)
        respx.get("https://example.org/gone.png").respond(404)
        respx.get("https://example.org/ok.png").respond(
            200, content=PNG, headers={"content-type": "image/png"}
        )
        respx.get("https://example.org").respond(
            200, html='<link rel="icon" href="/gone.png"><link rel="icon" href="/ok.png">'
        )

        assert await favicon.fetch("https://example.org/", client=client) is not None

    @respx.mock
    async def test_ignores_a_link_tag_with_no_href(self, client: httpx.AsyncClient) -> None:
        respx.get("https://example.org/favicon.ico").respond(404)
        respx.get("https://example.org").respond(200, html='<link rel="icon" sizes="16x16">')

        assert await favicon.fetch("https://example.org/", client=client) is None

    async def test_refuses_a_url_that_is_not_http(self, client: httpx.AsyncClient) -> None:
        assert await favicon.fetch("file:///etc/passwd", client=client) is None
