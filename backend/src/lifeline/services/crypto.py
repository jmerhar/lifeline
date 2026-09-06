"""Encryption of stored session state.

A captured session is equivalent to being logged in — anything able to read it can use
the account without knowing the password. It is therefore encrypted in the database, so
that a stray copy of the file (a backup, a snapshot, a support tarball) is not a set of
live credentials.
"""

import base64
import hashlib
import json
import logging
import os
import secrets
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

from ..config import Settings

logger = logging.getLogger(__name__)


class DecryptionError(RuntimeError):
    """Stored state could not be decrypted with the current key."""


def derive_fernet_key(secret: str) -> bytes:
    """Turn any secret string into a Fernet key.

    Derived rather than used verbatim so that ``SECRET_KEY`` can be whatever a deployment
    finds convenient — hex, a passphrase, a mounted file with a trailing newline — instead
    of demanding exactly 32 url-safe base64 bytes. The derivation is unsalted and single
    pass: it makes an arbitrary string usable, and does not pretend to stretch a weak one,
    so the key should be random rather than memorable.
    """
    return base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest())


def load_or_create_secret(settings: Settings) -> str:
    """Return the configured secret, generating and persisting one if there is none.

    Generating on first boot is what lets the tool start with no configuration at all.
    The file is written with owner-only permissions and never rewritten: losing it means
    every stored session has to be captured again, so it must survive a restart.
    """
    if settings.secret_key:
        return settings.secret_key

    path = settings.secret_key_path
    if path.exists():
        return path.read_text().strip()

    path.parent.mkdir(parents=True, exist_ok=True)
    secret = secrets.token_urlsafe(48)
    # Written 0600 through the open flags rather than chmod'ed afterwards, which would
    # leave the contents world-readable for the moment in between.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as handle:
        handle.write(secret)
    logger.info("generated a new encryption key at %s", path)
    return secret


class Cipher:
    """Encrypts and decrypts the JSON documents kept in the database."""

    def __init__(self, secret: str) -> None:
        self._fernet = Fernet(derive_fernet_key(secret))

    @classmethod
    def from_settings(cls, settings: Settings) -> "Cipher":
        """Build a cipher from the configured or self-generated secret."""
        return cls(load_or_create_secret(settings))

    def encrypt_json(self, payload: Any) -> bytes:
        """Serialise and encrypt a JSON-compatible object."""
        return self._fernet.encrypt(json.dumps(payload, separators=(",", ":")).encode())

    def decrypt_json(self, token: bytes) -> Any:
        """Decrypt and deserialise a document written by :meth:`encrypt_json`.

        A wrong key and a corrupted value are the same failure here, and both mean the
        stored session is unusable — so this raises rather than returning an empty state,
        which would look like "logged out" and trigger a misleading notification.
        """
        try:
            return json.loads(self._fernet.decrypt(token))
        except (InvalidToken, ValueError) as exc:
            raise DecryptionError(
                "stored session state could not be decrypted; the encryption key has "
                "changed or the value is corrupt"
            ) from exc
