"""The persisted model.

Every model is re-exported here so that importing this package registers the whole
schema on ``Base.metadata`` — which is what Alembic's autogenerate and the test
fixtures' ``create_all`` both read.
"""

from .base import Base, TimestampMixin, UtcDateTime, utcnow
from .check import Check
from .enums import CaptureMethod, CheckOutcome, PingMethod, SiteStatus
from .setting import SETTINGS_ID, Setting
from .site import Site
from .site_session import SiteSession
from .user import User

__all__ = [
    "SETTINGS_ID",
    "Base",
    "CaptureMethod",
    "Check",
    "CheckOutcome",
    "PingMethod",
    "Setting",
    "Site",
    "SiteSession",
    "SiteStatus",
    "TimestampMixin",
    "User",
    "UtcDateTime",
    "utcnow",
]
