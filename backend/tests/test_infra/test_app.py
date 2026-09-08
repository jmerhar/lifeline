"""Building the application: the setup token, and serving the built frontend."""

from pathlib import Path

import httpx
import pytest

from sqlalchemy.exc import OperationalError

from lifeline.api.app import create_app, resolve_setup_token, setup_is_pending
from lifeline.models import User
from lifeline.config import SETUP_TOKEN_DISABLED, Settings


class TestSetupToken:
    def test_uses_a_configured_token(self, settings: Settings) -> None:
        assert resolve_setup_token(settings) == "test-setup-token"

    def test_generates_one_when_none_is_configured(self, data_dir: Path) -> None:
        # An instance can be reachable before anyone has set it up; without a token, whoever
        # found the URL first would own it.
        token = resolve_setup_token(Settings(data_dir=data_dir))

        assert token
        assert len(token) >= 8

    def test_generates_a_different_token_each_time(self, data_dir: Path) -> None:
        settings = Settings(data_dir=data_dir)

        assert resolve_setup_token(settings) != resolve_setup_token(settings)

    def test_can_be_switched_off(self, data_dir: Path) -> None:
        settings = Settings(data_dir=data_dir, setup_token=SETUP_TOKEN_DISABLED)

        assert resolve_setup_token(settings) is None


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
        app.state.setup_token = None
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
        app.state.setup_token = None
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://lifeline.test") as c:
            assert (await c.get("/api/health")).status_code == 200
            assert (await c.get("/settings")).status_code == 404


class TestLifespan:
    async def test_builds_the_services_and_disposes_of_them(self, settings: Settings) -> None:
        app = create_app(settings)

        async with app.router.lifespan_context(app):
            assert app.state.services is not None
            assert app.state.setup_token == "test-setup-token"
            services = app.state.services

        # The engine is closed on the way out; using it afterwards is what would leak a
        # connection per restart in a reloading dev server.
        assert services.engine.pool.checkedout() == 0

    async def test_announces_an_unguarded_wizard(
        self, settings: Settings, caplog: pytest.LogCaptureFixture
    ) -> None:
        import logging

        app = create_app(settings.model_copy(update={"setup_token": SETUP_TOKEN_DISABLED}))

        with caplog.at_level(logging.WARNING):
            async with app.router.lifespan_context(app):
                pass

        assert app.state.setup_token is None
        assert "unguarded" in caplog.text

    async def test_prints_the_setup_token(
        self, settings: Settings, caplog: pytest.LogCaptureFixture
    ) -> None:
        # The one secret a new deployment has to find, and it is only ever printed here.
        import logging

        app = create_app(settings)

        with caplog.at_level(logging.INFO):
            async with app.router.lifespan_context(app):
                pass

        assert "test-setup-token" in caplog.text

    async def test_says_nothing_once_an_administrator_exists(
        self, settings: Settings, admin: User, caplog: pytest.LogCaptureFixture
    ) -> None:
        # A configured instance restarting has no wizard to guard, and a token in its log is a
        # live-looking secret that means nothing.
        import logging

        app = create_app(settings)

        with caplog.at_level(logging.INFO):
            async with app.router.lifespan_context(app):
                assert app.state.setup_token is None

        assert "test-setup-token" not in caplog.text

    async def test_guards_the_wizard_when_the_database_cannot_be_read(self) -> None:
        # Guessing "already set up" from a failed read would leave the wizard open on an
        # instance that turns out to be empty.
        assert await setup_is_pending(_BrokenServices())


class _BrokenServices:
    """Services whose database refuses to answer."""

    def sessionmaker(self) -> object:
        raise OperationalError("select", {}, Exception("no such table"))
