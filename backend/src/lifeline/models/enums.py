"""The closed sets of values the models store.

Persisted as their lowercase string values rather than their member names, so a row is
readable in a database client and a value read back by hand means something.
"""

from enum import StrEnum

from sqlalchemy import Enum as SaEnum


class SiteStatus(StrEnum):
    """How a site's session looked at its most recent check."""

    UNKNOWN = "unknown"
    ALIVE = "alive"
    AT_RISK = "at_risk"
    LAPSED = "lapsed"
    ERROR = "error"


class CheckOutcome(StrEnum):
    """What one ping established."""

    OK = "ok"
    LOGIN_EXPIRED = "login_expired"
    PATTERN_MISSING = "pattern_missing"
    HTTP_ERROR = "http_error"
    NETWORK_ERROR = "network_error"

    @property
    def is_success(self) -> bool:
        """Whether this outcome means the session is still usable."""
        return self is CheckOutcome.OK

    @property
    def means_logged_out(self) -> bool:
        """Whether this outcome points at the session rather than the network or the site."""
        return self in (CheckOutcome.LOGIN_EXPIRED, CheckOutcome.PATTERN_MISSING)


class PingMethod(StrEnum):
    """How a site is pinged."""

    HTTP = "http"
    BROWSER = "browser"


class CaptureMethod(StrEnum):
    """Where a stored session came from."""

    BROWSER = "browser"
    IMPORT = "import"


def enum_column(enum_type: type[StrEnum]) -> SaEnum:
    """A column type storing ``enum_type`` by value, as a plain VARCHAR with a check."""
    return SaEnum(
        enum_type,
        native_enum=False,
        validate_strings=True,
        values_callable=lambda members: [member.value for member in members],
    )
