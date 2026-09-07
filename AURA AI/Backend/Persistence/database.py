"""SQLite foundation and authenticated encryption for sensitive payloads."""
from __future__ import annotations

from contextlib import contextmanager
import base64
import hashlib
import hmac
import os
import secrets
import sqlite3
import threading
from typing import Iterator, Optional

try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
except Exception:  # pragma: no cover - optional dependency
    AESGCM = None


class EncryptionUnavailable(RuntimeError):
    pass


class EncryptedPayloadCodec:
    """AES-256-GCM codec with an explicit development-only plaintext escape hatch."""

    def __init__(self, key: Optional[bytes], *, allow_plaintext_dev: bool = False) -> None:
        if key is not None and len(key) != 32:
            raise ValueError("AES-256-GCM key must be 32 bytes")
        self.key = key
        self.allow_plaintext_dev = allow_plaintext_dev
        if key is not None and AESGCM is None:
            raise EncryptionUnavailable("cryptography is required for encrypted local storage")

    @property
    def encrypted(self) -> bool:
        return self.key is not None

    def encrypt(self, plaintext: str, *, associated_data: str = "") -> str:
        if not isinstance(plaintext, str):
            raise TypeError("plaintext must be text")
        if self.key is None:
            if not self.allow_plaintext_dev:
                raise EncryptionUnavailable("Encrypted storage key is not configured")
            return "DEV-PLAINTEXT:" + plaintext
        nonce = secrets.token_bytes(12)
        ciphertext = AESGCM(self.key).encrypt(nonce, plaintext.encode("utf-8"), associated_data.encode("utf-8"))
        return "AES256GCM:" + base64.urlsafe_b64encode(nonce + ciphertext).decode("ascii")

    def decrypt(self, value: str, *, associated_data: str = "") -> str:
        if value.startswith("DEV-PLAINTEXT:"):
            if not self.allow_plaintext_dev:
                raise EncryptionUnavailable("Plaintext development payload is disabled")
            return value[len("DEV-PLAINTEXT:"):]
        if not value.startswith("AES256GCM:") or self.key is None or AESGCM is None:
            raise EncryptionUnavailable("Encrypted storage key is unavailable")
        raw = base64.urlsafe_b64decode(value[len("AES256GCM:"):])
        if len(raw) < 13:
            raise EncryptionUnavailable("Encrypted payload is malformed")
        nonce, ciphertext = raw[:12], raw[12:]
        try:
            return AESGCM(self.key).decrypt(nonce, ciphertext, associated_data.encode("utf-8")).decode("utf-8")
        except Exception as exc:
            raise EncryptionUnavailable("Encrypted payload authentication failed") from exc


class Database:
    """Thread-safe SQLite connection factory with versioned migrations."""

    def __init__(self, path: str) -> None:
        self.path = path
        self._lock = threading.RLock()
        directory = os.path.dirname(os.path.abspath(path))
        if directory:
            os.makedirs(directory, exist_ok=True)
        self.migrate()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10, check_same_thread=False)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def migrate(self) -> None:
        with self._lock, self.connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS schema_migrations(version INTEGER PRIMARY KEY, applied_at INTEGER NOT NULL)")
            applied = {row[0] for row in db.execute("SELECT version FROM schema_migrations")}
            migrations = {1: self._migration_one}
            for version, migration in sorted(migrations.items()):
                if version not in applied:
                    migration(db)
                    db.execute("INSERT INTO schema_migrations(version, applied_at) VALUES(?, strftime('%s','now'))", (version,))

    @staticmethod
    def _migration_one(db: sqlite3.Connection) -> None:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS conversations (
                conversation_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL,
                title TEXT
            );
            CREATE TABLE IF NOT EXISTS memory_items (
                memory_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                conversation_id TEXT,
                kind TEXT NOT NULL,
                content_ciphertext TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                approved INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY(conversation_id) REFERENCES conversations(conversation_id)
            );
            CREATE INDEX IF NOT EXISTS idx_memory_user ON memory_items(user_id, created_at);
            CREATE TABLE IF NOT EXISTS tool_executions (
                execution_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                tool_name TEXT NOT NULL,
                risk_level TEXT NOT NULL,
                status TEXT NOT NULL,
                started_at INTEGER NOT NULL,
                completed_at INTEGER,
                duration_ms INTEGER,
                error_code TEXT
            );
            CREATE TABLE IF NOT EXISTS transactions (
                transaction_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                razorpay_order_id TEXT,
                razorpay_payment_id TEXT,
                payment_link_id TEXT,
                amount_minor INTEGER NOT NULL,
                currency TEXT NOT NULL,
                description TEXT NOT NULL,
                status TEXT NOT NULL,
                approval_reference TEXT,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_transactions_user ON transactions(user_id, created_at);
            """
        )

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            db = self.connect()
            try:
                yield db
                db.commit()
            except Exception:
                db.rollback()
                raise
            finally:
                db.close()
