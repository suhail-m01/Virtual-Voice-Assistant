"""Append-only, tamper-evident audit ledger.

The ledger stores a cryptographic digest of metadata, not raw prompts, documents
or payment credentials.  It is a useful local integrity control, not a claim that
Aura runs on a blockchain.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import threading
import time
from typing import Any, Mapping, Optional

from .privacy import pseudonymous_user_ref, safe_metadata, redact_sensitive


def redact_resource_ref(value: str) -> str:
    safe = redact_sensitive(str(value)).text
    return safe[:256]


class AuditIntegrity(str, Enum):
    VERIFIED = "VERIFIED"
    BROKEN = "BROKEN"
    EMPTY = "EMPTY"


@dataclass(frozen=True)
class AuditEvent:
    event_id: str
    previous_hash: str
    timestamp: int
    user_ref: str
    action: str
    resource_ref: str
    outcome: str
    metadata_digest: str
    current_hash: str


class AuditLedger:
    def __init__(self, database_path: str, *, installation_salt: Optional[bytes] = None) -> None:
        self.database_path = database_path
        self._salt = installation_salt or secrets.token_bytes(32)
        self._lock = threading.RLock()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.database_path, timeout=10, check_same_thread=False)
        db.row_factory = sqlite3.Row
        return db

    def _init_db(self) -> None:
        with self._connect() as db:
            db.execute(
                """CREATE TABLE IF NOT EXISTS audit_events (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT NOT NULL UNIQUE,
                    previous_hash TEXT NOT NULL,
                    timestamp INTEGER NOT NULL,
                    user_ref TEXT NOT NULL,
                    action TEXT NOT NULL,
                    resource_ref TEXT NOT NULL,
                    outcome TEXT NOT NULL,
                    metadata_digest TEXT NOT NULL,
                    current_hash TEXT NOT NULL UNIQUE
                )"""
            )

    def append(self, *, user_id: str, action: str, resource_ref: str = "", outcome: str, metadata: Optional[Mapping[str, Any]] = None, timestamp: Optional[int] = None) -> AuditEvent:
        if not user_id or not action or not outcome:
            raise ValueError("user_id, action and outcome are required")
        safe = safe_metadata(dict(metadata or {}))
        metadata_digest = hashlib.sha256(json.dumps(safe, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")).hexdigest()
        now = int(time.time() if timestamp is None else timestamp)
        user_ref = pseudonymous_user_ref(user_id, self._salt)
        resource_ref = redact_resource_ref(resource_ref)
        event_id = secrets.token_hex(16)
        with self._lock, self._connect() as db:
            previous = db.execute("SELECT current_hash FROM audit_events ORDER BY sequence DESC LIMIT 1").fetchone()
            previous_hash = previous["current_hash"] if previous else "0" * 64
            current_hash = self._hash(event_id, previous_hash, now, user_ref, action, resource_ref, outcome, metadata_digest)
            db.execute(
                "INSERT INTO audit_events(event_id,previous_hash,timestamp,user_ref,action,resource_ref,outcome,metadata_digest,current_hash) VALUES(?,?,?,?,?,?,?,?,?)",
                (event_id, previous_hash, now, user_ref, action, resource_ref, outcome, metadata_digest, current_hash),
            )
        return AuditEvent(event_id, previous_hash, now, user_ref, action, resource_ref, outcome, metadata_digest, current_hash)

    def events(self, *, limit: int = 100) -> list[AuditEvent]:
        if limit < 1 or limit > 10_000:
            raise ValueError("limit out of range")
        with self._connect() as db:
            rows = db.execute("SELECT * FROM audit_events ORDER BY sequence DESC LIMIT ?", (limit,)).fetchall()
        return [self._from_row(row) for row in reversed(rows)]

    def verify_chain(self) -> AuditIntegrity:
        with self._lock, self._connect() as db:
            rows = db.execute("SELECT * FROM audit_events ORDER BY sequence ASC").fetchall()
        if not rows:
            return AuditIntegrity.EMPTY
        previous = "0" * 64
        for row in rows:
            if row["previous_hash"] != previous:
                return AuditIntegrity.BROKEN
            expected = self._hash(row["event_id"], row["previous_hash"], row["timestamp"], row["user_ref"], row["action"], row["resource_ref"], row["outcome"], row["metadata_digest"])
            if not hmac.compare_digest(expected, row["current_hash"]):
                return AuditIntegrity.BROKEN
            previous = row["current_hash"]
        return AuditIntegrity.VERIFIED

    @staticmethod
    def _hash(event_id: str, previous_hash: str, timestamp: int, user_ref: str, action: str, resource_ref: str, outcome: str, metadata_digest: str) -> str:
        canonical = "|".join((event_id, previous_hash, str(timestamp), user_ref, action, resource_ref, outcome, metadata_digest))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @staticmethod
    def _from_row(row: sqlite3.Row) -> AuditEvent:
        return AuditEvent(row["event_id"], row["previous_hash"], row["timestamp"], row["user_ref"], row["action"], row["resource_ref"], row["outcome"], row["metadata_digest"], row["current_hash"])


class AuditAnchorAdapter:
    """Future extension point for anchoring a root hash to a permissioned ledger."""

    def anchor(self, root_hash: str) -> None:
        raise NotImplementedError("No external audit anchor is configured")
