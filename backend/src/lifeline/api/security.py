"""Passwords, the login throttle and logins, on jigkit.auth.

jigkit hashes passwords (Argon2id, at least ten characters), throttles failed logins per
address, and keeps logins as hashed tokens in ``login_sessions`` with a sliding expiry, so
logging out really ends one.
"""

from datetime import timedelta

from jigkit.auth import (
    LoginThrottle,
    PasswordTooShort,
    burn_password_check,
    hash_password,
    verify_password,
)
from jigkit.auth.sessions import SessionStore

from ..config import Settings
from ..models import LoginSession

__all__ = [
    "LoginThrottle",
    "PasswordTooShort",
    "burn_password_check",
    "hash_password",
    "login_sessions",
    "verify_password",
]


def login_sessions(settings: Settings) -> SessionStore:
    """The store of browsers' logins, lasting ``SESSION_LIFETIME_HOURS`` from their last use."""
    return SessionStore(
        LoginSession,
        owner="user_id",
        lifetime=timedelta(hours=settings.session_lifetime_hours),
    )
