"""Building the service graph, and the dependencies handlers rely on."""

from pathlib import Path

import pytest

from lifeline.api.deps import build_services, cipher_secret
from lifeline.services.crypto import load_or_create_secret
from lifeline.config import Settings
from lifeline.models import PingMethod


class TestBuildServices:
    async def test_wires_the_whole_graph(self, data_dir: Path) -> None:
        settings = Settings(data_dir=data_dir, scheduler_enabled=False)

        services = build_services(settings)

        try:
            assert services.runner is not None
            assert services.scheduler is not None
            assert services.browser is not None
            # Both ping methods must be available, or a site configured for the browser would
            # fail every check with an internal error instead of being checked.
            assert set(services.runner._fetchers) == {PingMethod.HTTP, PingMethod.BROWSER}
        finally:
            await services.engine.dispose()

    async def test_creates_the_data_directory(self, data_dir: Path) -> None:
        # Docker creates a missing bind-mount source as root, but a fresh local run has no
        # directory at all; the database cannot be opened inside one that does not exist.
        target = data_dir / "nested" / "state"
        services = build_services(Settings(data_dir=target, scheduler_enabled=False))

        try:
            assert target.is_dir()
        finally:
            await services.engine.dispose()

    async def test_generates_an_encryption_key_when_none_is_configured(
        self, data_dir: Path
    ) -> None:
        settings = Settings(data_dir=data_dir, scheduler_enabled=False)

        services = build_services(settings)

        try:
            assert settings.secret_key_path.exists()
        finally:
            await services.engine.dispose()


class TestCipherSecret:
    def test_signs_cookies_with_the_same_secret_as_the_session_store(
        self, settings: Settings
    ) -> None:
        # Rotating it invalidates browser logins and stored sessions together, which is the
        # honest behaviour: both were protected by it.
        assert cipher_secret(settings) == settings.secret_key


class TestGetSettings:
    def test_reads_the_environment_once(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from lifeline.config import get_settings

        get_settings.cache_clear()
        monkeypatch.setenv("LOG_LEVEL", "DEBUG")
        try:
            first = get_settings()

            # Cached, so a later environment change does not silently reconfigure a running
            # process halfway through its work.
            monkeypatch.setenv("LOG_LEVEL", "WARNING")
            assert get_settings() is first
            assert first.log_level == "DEBUG"
        finally:
            get_settings.cache_clear()

    def test_an_explicit_database_url_wins(self, data_dir: Path) -> None:
        settings = Settings(data_dir=data_dir, database_url="sqlite+aiosqlite:///:memory:")

        assert settings.resolved_database_url == "sqlite+aiosqlite:///:memory:"


class TestBlankSettings:
    def test_an_empty_static_dir_means_no_frontend(self, data_dir: Path) -> None:
        # Compose writes `VAR: ${VAR:-}` for an optional setting, so an unset variable arrives
        # as "". Path("") is Path("."), which is a real directory — the application would then
        # try to serve its own working directory as the built interface.
        assert Settings(data_dir=data_dir, static_dir="").static_dir is None

    def test_a_dot_static_dir_means_no_frontend(self, data_dir: Path) -> None:
        assert Settings(data_dir=data_dir, static_dir=".").static_dir is None

    def test_an_empty_secret_key_means_generate_one(self, data_dir: Path) -> None:
        settings = Settings(data_dir=data_dir, secret_key="")

        assert settings.secret_key is None
        assert load_or_create_secret(settings)

    def test_an_empty_setup_token_means_generate_one(self, data_dir: Path) -> None:
        from lifeline.api.app import resolve_setup_token

        settings = Settings(data_dir=data_dir, setup_token="")

        assert settings.setup_token is None
        assert resolve_setup_token(settings)

    def test_an_empty_database_url_falls_back_to_the_data_directory(self, data_dir: Path) -> None:
        settings = Settings(data_dir=data_dir, database_url="")

        assert settings.resolved_database_url.endswith("lifeline.db")

    def test_a_real_static_dir_is_kept(self, data_dir: Path) -> None:
        assert Settings(data_dir=data_dir, static_dir=data_dir).static_dir == data_dir
