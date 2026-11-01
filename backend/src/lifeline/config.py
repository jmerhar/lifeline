"""Runtime configuration, read from the environment.

Built on jigkit's ``AppSettings``, which supplies the data directory, the database URL, the
log level, the cookie and scheduler settings, and the rules every app shares: a blank variable
means unset, and every secret-bearing setting accepts a ``*_FILE`` variant naming a file to read
it from instead (setting both is an error).
"""

from functools import lru_cache
from pathlib import Path

from jigkit.settings import AppSettings

# Sentinel accepted by ``setup_token`` to run the first-run wizard without a token.
SETUP_TOKEN_DISABLED = "off"


class Settings(AppSettings):
    """Everything the application reads from its environment."""

    database_filename = "lifeline.db"

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
    login_rate_limit_per_minute: int = 10

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

    @property
    def setup_token_disabled(self) -> bool:
        """Whether the first-run wizard has deliberately been left unguarded."""
        return self.setup_token == SETUP_TOKEN_DISABLED

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
