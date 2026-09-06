"""Encryption of stored session state."""

from pathlib import Path

import pytest

from lifeline.config import Settings
from lifeline.services.crypto import (
    Cipher,
    DecryptionError,
    derive_fernet_key,
    load_or_create_secret,
)


def test_round_trips_a_document(settings: Settings) -> None:
    cipher = Cipher.from_settings(settings)
    payload = {"cookies": [{"name": "session", "value": "abc"}], "origins": []}

    assert cipher.decrypt_json(cipher.encrypt_json(payload)) == payload


def test_ciphertext_does_not_contain_the_plaintext(settings: Settings) -> None:
    token = Cipher.from_settings(settings).encrypt_json({"value": "s3cr3t-cookie"})

    assert b"s3cr3t-cookie" not in token


def test_a_different_key_cannot_decrypt(settings: Settings) -> None:
    token = Cipher("one secret").encrypt_json({"a": 1})

    with pytest.raises(DecryptionError):
        Cipher("another secret").decrypt_json(token)


def test_corrupt_state_raises_rather_than_reading_as_empty(settings: Settings) -> None:
    # An empty state would look exactly like "logged out" and would notify about a
    # session that is in fact still there.
    with pytest.raises(DecryptionError):
        Cipher.from_settings(settings).decrypt_json(b"not-a-fernet-token")


def test_key_derivation_is_stable_and_key_shaped() -> None:
    assert derive_fernet_key("abc") == derive_fernet_key("abc")
    assert derive_fernet_key("abc") != derive_fernet_key("abd")
    assert len(derive_fernet_key("abc")) == 44


def test_configured_secret_is_used_verbatim(settings: Settings) -> None:
    assert load_or_create_secret(settings) == "test-secret-key"
    assert not settings.secret_key_path.exists()


def test_generates_and_persists_a_key_when_none_is_configured(data_dir: Path) -> None:
    unconfigured = Settings(data_dir=data_dir)

    first = load_or_create_secret(unconfigured)

    assert first
    # Stability across restarts is what makes stored sessions survive one, so a second
    # call must return the same secret rather than a new one.
    assert load_or_create_secret(unconfigured) == first
    assert unconfigured.secret_key_path.read_text() == first


def test_generated_key_is_not_world_readable(data_dir: Path) -> None:
    unconfigured = Settings(data_dir=data_dir)

    load_or_create_secret(unconfigured)

    assert unconfigured.secret_key_path.stat().st_mode & 0o077 == 0


def test_secret_can_be_read_from_a_file(data_dir: Path) -> None:
    # Trailing newline included on purpose: a mounted secret almost always has one, and
    # keeping it would derive a different key than the same value passed in the
    # environment.
    path = data_dir / "mounted-secret"
    path.write_text("from-a-file\n")

    assert Settings(data_dir=data_dir, secret_key_file=path).secret_key == "from-a-file"


def test_an_explicit_value_wins_over_a_file(data_dir: Path) -> None:
    path = data_dir / "mounted-secret"
    path.write_text("from-a-file")

    settings = Settings(data_dir=data_dir, secret_key="from-the-environment", secret_key_file=path)

    assert settings.secret_key == "from-the-environment"


def test_a_missing_secret_file_is_an_error(data_dir: Path) -> None:
    # Silently falling back would generate a fresh key and orphan every stored session.
    with pytest.raises(FileNotFoundError):
        Settings(data_dir=data_dir, secret_key_file=data_dir / "absent")
