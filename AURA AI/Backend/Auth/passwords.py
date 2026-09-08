"""Password hashing with Argon2id when available and a safe stdlib fallback."""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
from typing import Optional

try:  # Optional production dependency.
    from argon2 import PasswordHasher as _Argon2PasswordHasher
    from argon2 import exceptions as _argon2_exceptions
except Exception:  # pragma: no cover - depends on deployment extras
    _Argon2PasswordHasher = None
    _argon2_exceptions = None


class PasswordHasher:
    """Hash and verify passwords without ever exposing the password in storage."""

    algorithm = "argon2id" if _Argon2PasswordHasher else "pbkdf2-sha256"

    def __init__(self, argon: Optional[object] = None) -> None:
        self._argon = argon or (
            _Argon2PasswordHasher(time_cost=3, memory_cost=64 * 1024, parallelism=2, hash_len=32, salt_len=16)
            if _Argon2PasswordHasher
            else None
        )

    def hash(self, password: str) -> str:
        self._validate_password(password)
        if self._argon:
            return self._argon.hash(password)
        iterations = 600_000
        salt = secrets.token_bytes(16)
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations, dklen=32)
        return "pbkdf2-sha256${}${}${}".format(
            iterations,
            base64.urlsafe_b64encode(salt).decode("ascii").rstrip("="),
            base64.urlsafe_b64encode(digest).decode("ascii").rstrip("="),
        )

    def verify(self, encoded: str, password: str) -> bool:
        if not isinstance(encoded, str) or not isinstance(password, str):
            return False
        try:
            if encoded.startswith("$argon2") and self._argon:
                return bool(self._argon.verify(encoded, password))
            if encoded.startswith("pbkdf2-sha256$"):
                _, iterations_raw, salt_raw, expected_raw = encoded.split("$", 3)
                iterations = int(iterations_raw)
                salt = base64.urlsafe_b64decode(salt_raw + "=" * (-len(salt_raw) % 4))
                expected = base64.urlsafe_b64decode(expected_raw + "=" * (-len(expected_raw) % 4))
                actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations, dklen=len(expected))
                return hmac.compare_digest(actual, expected)
        except Exception:
            return False
        return False

    def needs_rehash(self, encoded: str) -> bool:
        if self._argon:
            try:
                return bool(self._argon.check_needs_rehash(encoded))
            except Exception:
                return not encoded.startswith("$argon2")
        return not encoded.startswith("pbkdf2-sha256$600000$")

    @staticmethod
    def _validate_password(password: str) -> None:
        if not isinstance(password, str) or len(password) < 12:
            raise ValueError("Password must be at least 12 characters")
        if len(password) > 512:
            raise ValueError("Password is too long")
