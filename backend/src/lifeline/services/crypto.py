"""Encryption of stored session state.

A captured session is equivalent to being logged in — anything able to read it can use
the account without knowing the password. It is therefore encrypted in the database, so
that a stray copy of the file (a backup, a snapshot, a support tarball) is not a set of
live credentials.
"""

import base64
import hashlib
import json
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from jigkit import secrets as jigkit_secrets

from ..config import Settings


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
    """Return the configured secret, or the one generated into the data directory.

    Generating on first boot is what lets the tool start with no configuration at all. The
    generated file is owner-only and never rewritten: losing it means every stored session has
    to be captured again.
    """
    if settings.secret_key:
        return settings.secret_key
    return jigkit_secrets.load_or_create_secret(settings.secret_key_path)


class Cipher:
    """Encrypts and decrypts the JSON documents kept in the database."""

    def __init__(self, secret: str) -> None:
        self._fernet = Fernet(derive_fernet_key(secret))

    @classmethod
    def from_settings(cls, settings: Settings) -> Cipher:
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
