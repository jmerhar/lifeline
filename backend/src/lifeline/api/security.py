"""Password hashing, session cookies and login throttling."""

import json
import logging
from datetime import UTC, datetime, timedelta

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from cryptography.fernet import Fernet, InvalidToken

from ..services.crypto import derive_fernet_key

logger = logging.getLogger(__name__)

# Argon2id at the library's defaults: memory-hard, and the parameters move with the
# library rather than with a number pinned here that nobody revisits.
_hasher = PasswordHasher()

MIN_PASSWORD_LENGTH = 10


class PasswordTooShort(ValueError):
    """The chosen password is below the minimum length."""


def hash_password(password: str) -> str:
    """Hash a password for storage.

    A length floor is the one rule enforced in code. Everything else about password choice
    is advice, and this instance may be reachable from the internet, where a short password
    is the whole attack.
    """
    if len(password) < MIN_PASSWORD_LENGTH:
        raise PasswordTooShort(
            f"the password must be at least {MIN_PASSWORD_LENGTH} characters"
        )
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    """Whether ``password`` matches ``password_hash``."""
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


class SessionCookies:
    """Issues and reads the signed cookie that stands for a logged-in browser.

    Encrypted and self-contained rather than a key into a server-side table: there is one
    user and one process, so a stateless cookie removes a table, a cleanup job and a
    restart's worth of forced logouts, and Fernet's timestamp gives expiry for free.
    """

    def __init__(self, secret: str, lifetime: timedelta) -> None:
        self._fernet = Fernet(derive_fernet_key(secret))
        self._lifetime = lifetime

    def issue(self, user_id: int, *, now: datetime | None = None) -> str:
        """Mint a cookie value for ``user_id``."""
        issued = now or datetime.now(UTC)
        payload = {"uid": user_id, "iat": issued.isoformat()}
        return self._fernet.encrypt(json.dumps(payload).encode()).decode()

    def read(self, value: str) -> int | None:
        """The user id in ``value``, or None if it is invalid, tampered with or expired."""
        try:
            payload = json.loads(
                self._fernet.decrypt(value.encode(), ttl=int(self._lifetime.total_seconds()))
            )
            return int(payload["uid"])
        except (InvalidToken, ValueError, KeyError, TypeError):
            return None


class LoginThrottle:
    """Limits how fast login attempts can be made from one address.

    In memory, per process: this is one instance with one account, so the only thing worth
    stopping is an online guessing run, and a counter that resets on restart does that.
    """

    def __init__(self, limit_per_minute: int) -> None:
        self._limit = limit_per_minute
        self._attempts: dict[str, list[datetime]] = {}

    def allow(self, client: str, *, now: datetime | None = None) -> bool:
        """Record an attempt from ``client`` and say whether it may proceed."""
        now = now or datetime.now(UTC)
        window_start = now - timedelta(minutes=1)
        recent = [at for at in self._attempts.get(client, []) if at > window_start]
        if len(recent) >= self._limit:
            self._attempts[client] = recent
            return False
        recent.append(now)
        self._attempts[client] = recent
        return True

    def reset(self, client: str) -> None:
        """Forget a client's attempts, called after a successful login."""
        self._attempts.pop(client, None)
