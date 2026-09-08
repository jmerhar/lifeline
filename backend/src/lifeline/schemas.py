"""The shapes the HTTP API accepts and returns.

Separate from the models on purpose: a request body must never be able to set
``status`` or ``last_ok_at``, and a response must never carry a stored session's bytes.
"""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .models import CaptureMethod, CheckOutcome, PingMethod, SiteStatus

# A site's own fields, as the API accepts them.
Name = Annotated[str, Field(min_length=1, max_length=120)]
Url = Annotated[str, Field(min_length=1, max_length=2048)]
Pattern = Annotated[str | None, Field(default=None, max_length=512)]


class SiteWrite(BaseModel):
    """What a client may set on a site."""

    name: Name
    ping_url: Url
    login_url: Annotated[str | None, Field(default=None, max_length=2048)] = None
    enabled: bool = True
    interval_days: Annotated[int, Field(default=7, ge=1, le=365)] = 7
    jitter_percent: Annotated[int, Field(default=10, ge=0, le=50)] = 10
    ping_method: PingMethod = PingMethod.HTTP
    user_agent: Annotated[str | None, Field(default=None, max_length=512)] = None
    expected_status: Annotated[int, Field(default=200, ge=100, le=599)] = 200
    follow_redirects: bool = True
    login_url_pattern: Pattern = None
    success_pattern: Pattern = None
    failure_pattern: Pattern = None
    inactivity_limit_days: Annotated[int | None, Field(default=None, ge=1, le=3650)] = None
    notes: str | None = None

    @field_validator("ping_url", "login_url")
    @classmethod
    def _require_http_url(cls, value: str | None) -> str | None:
        """Reject anything that is not an http(s) URL.

        Not cosmetic: the ping is made with the site's stored cookies, and a ``file://`` or
        ``data:`` target would be a way to make the server read something it should not.
        """
        if value is None or not value.strip():
            return None
        candidate = value.strip()
        if not candidate.lower().startswith(("http://", "https://")):
            raise ValueError("must be an http:// or https:// URL")
        return candidate


class SessionRead(BaseModel):
    """What is known about a stored session, without any of its secrets."""

    model_config = ConfigDict(from_attributes=True)

    captured_at: datetime
    captured_via: CaptureMethod
    rotated_at: datetime | None
    expires_at: datetime | None
    cookie_names: list[str]


class CheckRead(BaseModel):
    """One entry of a site's history."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    site_id: int
    started_at: datetime
    outcome: CheckOutcome
    status_code: int | None
    final_url: str | None
    duration_ms: int | None
    detail: str | None


class SiteRead(SiteWrite):
    """A site as the UI shows it."""

    id: int
    favicon: str | None = None
    status: SiteStatus
    consecutive_failures: int
    last_check_at: datetime | None
    last_ok_at: datetime | None
    next_check_at: datetime | None
    # When the account lapses if nothing succeeds first, derived from the last success.
    deadline_at: datetime | None
    # Why the site needs attention, when it does. A status on its own leaves someone looking at
    # "due soon" with no way to find out what is due.
    risk: str | None = None
    session: SessionRead | None = None
    # The outcomes of the most recent checks, oldest first, for the pulse strip.
    pulse: list[CheckOutcome] = Field(default_factory=list)


class CookieImport(BaseModel):
    """A session pasted in by hand."""

    # A cookie header, a JSON export from a cookie extension, or a cookies.txt file: the
    # format is detected rather than declared, because the person pasting has a clipboard.
    text: Annotated[str, Field(min_length=1)]
    user_agent: Annotated[str | None, Field(default=None, max_length=512)] = None


class SettingsWrite(BaseModel):
    """The instance settings a client may change."""

    apprise_urls: str = ""
    notify_on_lapsed: bool = True
    notify_on_recovered: bool = True
    notify_on_errors: bool = True
    notify_on_cookie_expiry: bool = True
    notify_on_deadline: bool = True
    notify_cooldown_hours: Annotated[int, Field(default=24, ge=0, le=8760)] = 24
    warning_lead_days: Annotated[int, Field(default=7, ge=0, le=365)] = 7
    error_threshold: Annotated[int, Field(default=3, ge=1, le=100)] = 3
    # Constrained to the names the logging module knows, so a typo is refused here rather than
    # silently leaving the level at whatever it was.
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    default_interval_days: Annotated[int, Field(default=7, ge=1, le=365)] = 7
    retention_days: Annotated[int, Field(default=90, ge=0, le=3650)] = 90
    browser_idle_timeout_minutes: Annotated[int, Field(default=15, ge=1, le=240)] = 15


class SettingsRead(SettingsWrite):
    """The instance settings, as returned."""

    model_config = ConfigDict(from_attributes=True)


class SetupState(BaseModel):
    """Whether this instance still needs configuring."""

    setup_required: bool
    # Whether the wizard demands the token from the container log.
    token_required: bool


class SetupRequest(BaseModel):
    """The first-run wizard's submission."""

    username: Annotated[str, Field(min_length=1, max_length=120)]
    password: Annotated[str, Field(min_length=1)]
    # Printed to the log at startup. Required unless the deployment turned it off, so that
    # an instance exposed to the internet cannot be claimed by whoever finds it first.
    token: str | None = None


class LoginRequest(BaseModel):
    """A login attempt."""

    username: str
    password: str


class UserRead(BaseModel):
    """Who is logged in."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    last_login_at: datetime | None


class LoginSessionRead(BaseModel):
    """A live interactive-login session."""

    site_id: int
    # Where the browser's screen is streamed from, relative to the API root.
    ws_path: str
    width: int
    height: int
    expires_at: datetime


class Message(BaseModel):
    """A plain result for actions that have nothing else to say."""

    detail: str
