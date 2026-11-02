"""Building the application: serving the built frontend, its guards, and its lifespan."""

from pathlib import Path

import httpx
import pytest

from lifeline.api.app import create_app
from lifeline.config import Settings


class TestFrontendServing:
    @pytest.fixture
    def built(self, data_dir: Path) -> Path:
        """A directory shaped like a built single-page app."""
        static = data_dir / "static"
        (static / "assets").mkdir(parents=True)
        (static / "index.html").write_text("<!doctype html><title>lifeline</title>")
        (static / "assets" / "app.js").write_text("console.log('hello')")
        (static / "favicon.svg").write_text("<svg/>")
        return static

    @pytest.fixture
    async def client(self, services, built: Path) -> httpx.AsyncClient:
        app = create_app(services.settings.model_copy(update={"static_dir": built}))
        # The lifespan is not run, so the services are attached by hand; see the app fixture.
        app.state.services = services
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://lifeline.test") as c:
            yield c

    async def test_serves_a_real_file(self, client: httpx.AsyncClient) -> None:
        response = await client.get("/favicon.svg")

        assert response.status_code == 200
        assert response.text == "<svg/>"

    async def test_serves_built_assets(self, client: httpx.AsyncClient) -> None:
        assert (await client.get("/assets/app.js")).status_code == 200

    async def test_serves_the_shell_for_a_client_side_route(
        self, client: httpx.AsyncClient
    ) -> None:
        # /settings is not a file; returning the shell is what lets the app read the URL and
        # render the right view.
        response = await client.get("/settings")

        assert response.status_code == 200
        assert "<title>lifeline</title>" in response.text

    async def test_serves_the_shell_at_the_root(self, client: httpx.AsyncClient) -> None:
        assert "lifeline" in (await client.get("/")).text

    async def test_refuses_to_escape_the_static_directory(
        self, client: httpx.AsyncClient
    ) -> None:
        # A crafted path must not be able to read arbitrary files from the container.
        response = await client.get("/../../../../etc/passwd")

        assert response.status_code == 200
        assert "root:" not in response.text

    async def test_the_api_still_wins_over_the_catch_all(
        self, client: httpx.AsyncClient
    ) -> None:
        assert (await client.get("/api/health")).status_code == 200

    async def test_serves_only_the_api_when_nothing_is_built(
        self, services, data_dir: Path
    ) -> None:
        # How the dev stack runs: Vite serves the app and proxies the API.
        app = create_app(services.settings.model_copy(update={"static_dir": data_dir / "absent"}))
        app.state.services = services
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://lifeline.test") as c:
            assert (await c.get("/api/health")).status_code == 200
            assert (await c.get("/settings")).status_code == 404


    async def test_assets_are_cached_for_good_and_the_shell_is_not(
        self, client: httpx.AsyncClient
    ) -> None:
        # Asset names carry a content hash; the shell must be re-checked to pick up a release.
        asset = await client.get("/assets/app.js")
        shell = await client.get("/settings")

        assert "immutable" in asset.headers["cache-control"]
        assert shell.headers["cache-control"] == "no-cache"

    async def test_an_unknown_api_path_is_a_404_not_the_shell(
        self, client: httpx.AsyncClient
    ) -> None:
        # A mistyped endpoint has to fail loudly rather than answer with the interface's HTML.
        assert (await client.get("/api/no-such-endpoint")).status_code == 404


class TestRequestGuards:
    async def test_a_write_without_the_interface_header_is_refused(
        self, client: httpx.AsyncClient
    ) -> None:
        # Another site's page cannot add the header without a CORS preflight, which is never
        # granted, so it cannot make a logged-in browser change anything.
        client.headers.pop("X-Requested-With")

        response = await client.post("/api/auth/login", json={"username": "a", "password": "b"})

        assert response.status_code == 403
        assert response.json() == {"detail": "missing_write_header"}

    async def test_a_write_from_another_origin_is_refused(self, client: httpx.AsyncClient) -> None:
        response = await client.post(
            "/api/auth/login",
            json={"username": "a", "password": "b"},
            headers={"Origin": "https://elsewhere.example"},
        )

        assert response.json() == {"detail": "foreign_origin"}

    async def test_every_response_carries_the_security_headers(
        self, client: httpx.AsyncClient
    ) -> None:
        response = await client.get("/api/health")

        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["x-frame-options"] == "DENY"


class TestLifespan:
    async def test_builds_the_services_and_disposes_of_them(self, settings: Settings) -> None:
        app = create_app(settings)

        async with app.router.lifespan_context(app):
            assert app.state.services is not None
            services = app.state.services

        # The engine is closed on the way out; using it afterwards is what would leak a
        # connection per restart in a reloading dev server.
        assert services.engine.pool.checkedout() == 0
