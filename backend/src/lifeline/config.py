"""Runtime configuration, read from the environment.

Every secret-bearing setting also accepts a ``*_FILE`` variant holding a path to read
the value from, so a deployment can mount a secret as a file rather than put its value
in an environment variable — where it is readable by anything that can inspect the
container, and where it tends to end up committed to a compose file.
"""

from functools import lru_cache
from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Sentinel accepted by ``setup_token`` to run the first-run wizard without a token.
SETUP_TOKEN_DISABLED = "off"


class Settings(BaseSettings):
    """Everything the application reads from its environment."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Where all mutable state lives: the database, the encryption key, browser profiles.
    # A single directory means a deployment has exactly one thing to persist and back up.
    data_dir: Path = Path("data")
    database_url: str | None = None

    # Encrypts stored session state. Supplied here, read from ``SECRET_KEY_FILE``, or —
    # absent both — generated into the data directory on first boot (see services.crypto).
    secret_key: str | None = None
    secret_key_file: Path | None = None

    # Guards the first-run wizard. Unset generates one and logs it; SETUP_TOKEN_DISABLED
    # turns the guard off for an instance that is not reachable from the internet.
    setup_token: str | None = None
    setup_token_file: Path | None = None

    auth_disabled: bool = False
    session_cookie_name: str = "lifeline_session"
    session_lifetime_hours: int = 24 * 14
    # Forces the ``Secure`` flag on or off. Left unset it follows the request scheme, so
    # an instance behind a TLS-terminating proxy gets secure cookies while a plain-HTTP
    # instance on a private network can still log in.
    cookie_secure: bool | None = None
    login_rate_limit_per_minute: int = 10

    log_level: str = "INFO"

    # The scheduler runs inside the API process. Disabled in tests, which drive the
    # checker directly rather than waiting for a tick.
    scheduler_enabled: bool = True
    scheduler_tick_seconds: int = 60

    browser_enabled: bool = True
    # An unpacked browser extension to load into the interactive-login browser. The image ships
    # Bitwarden here, so a password manager can fill the form in the panel — the browser is on
    # another machine, so the one on yours cannot. Point it elsewhere to load a different
    # extension, or set it empty to load none.
    browser_extension_dir: Path | None = None
    # X display numbers are allocated from here upwards, one per live login session.
    display_base: int = 99

    # Sent when fetching a site's icon, and used as the fallback for a site with no
    # captured User-Agent of its own.
    default_user_agent: str = (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    )
    request_timeout_seconds: float = 30.0

    # Where the built single-page app is served from. Absent, the API runs on its own,
    # which is how the dev stack works (Vite serves the app and proxies /api).
    static_dir: Path | None = None

    @model_validator(mode="after")
    def _blank_means_unset(self) -> Settings:
        """Treat an empty value as absent.

        Compose writes ``VAR: ${VAR:-}`` for an optional setting, so an unset variable arrives
        as an empty string rather than not at all. Left alone, an empty ``static_dir`` becomes
        ``Path(".")`` — which is a real directory, so the application would try to serve its
        own working directory as the built interface and fail at startup.
        """
        for field in (
            "static_dir",
            "secret_key",
            "setup_token",
            "database_url",
            "browser_extension_dir",
        ):
            value = getattr(self, field)
            if value is not None and str(value).strip() in ("", "."):
                object.__setattr__(self, field, None)
        return self

    @model_validator(mode="after")
    def _read_secret_files(self) -> Settings:
        """Fill any unset setting whose ``*_FILE`` companion names a readable file.

        An explicit value wins over a file, so a deployment can override one field of a
        mounted secret set without rebuilding it. A named file that cannot be read is an
        error rather than a silent fallback: continuing would mean generating a fresh
        encryption key and orphaning every stored session.
        """
        for field in type(self).model_fields:
            if not field.endswith("_file"):
                continue
            target = field.removesuffix("_file")
            path = getattr(self, field)
            if path is None or getattr(self, target) is not None:
                continue
            object.__setattr__(self, target, path.read_text().strip())
        return self

    @property
    def setup_token_disabled(self) -> bool:
        """Whether the first-run wizard has deliberately been left unguarded."""
        return self.setup_token == SETUP_TOKEN_DISABLED

    @property
    def resolved_database_url(self) -> str:
        """The database URL, defaulting to a SQLite file inside the data directory."""
        if self.database_url:
            return self.database_url
        return f"sqlite+aiosqlite:///{self.data_dir / 'lifeline.db'}"

    @property
    def secret_key_path(self) -> Path:
        """Where a self-generated encryption key is kept."""
        return self.data_dir / "secret.key"

    @property
    def profiles_dir(self) -> Path:
        """Root of the per-site browser profiles."""
        return self.data_dir / "profiles"


@lru_cache
def get_settings() -> Settings:
    """The process-wide settings, read once."""
    return Settings()
