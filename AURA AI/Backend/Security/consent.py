"""Exact-action, expiring consent records."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import json
import secrets
import sqlite3
import time
from typing import Any, Mapping, Optional

from .privacy import safe_metadata


class RiskLevel(str, Enum):
    LOW = "LOW"
    SENSITIVE = "SENSITIVE"
    FINANCIAL = "FINANCIAL"
    DESTRUCTIVE = "DESTRUCTIVE"


class ConsentStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    EXPIRED = "EXPIRED"
    CONSUMED = "CONSUMED"


def parameters_digest(parameters: Mapping[str, Any]) -> str:
    canonical = json.dumps(safe_metadata(dict(parameters)), sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ConsentRecord:
    consent_id: str
    user_id: str
    action: str
    parameters_digest: str
    risk_level: RiskLevel
    created_at: int
    expires_at: int
    status: ConsentStatus
    approved_at: Optional[int] = None

    def is_current(self, *, now: Optional[int] = None) -> bool:
        current = int(time.time() if now is None else now)
        return self.status == ConsentStatus.APPROVED and current < self.expires_at


_APPROVAL_PHRASES = {
    "yes", "approve", "approve it", "approve this", "yes approve", "yes, approve", "confirm", "confirm it",
    "yes confirm", "yes, confirm", "continue with this action", "proceed with this action", "go ahead with this action",
}
_DENIAL_PHRASES = {"no", "no thanks", "cancel", "deny", "stop", "do not proceed", "don't proceed"}


def is_explicit_approval(response: str, *, active_action: Optional[str] = None) -> bool:
    """Accept only a clear response to an active approval request.

    Generic acknowledgements intentionally return False.  ``active_action`` is
    required so a stale voice utterance cannot authorize a financial operation.
    """
    if not active_action or not isinstance(response, str):
        return False
    normalized = " ".join(response.lower().strip().split()).rstrip(".!?")
    if normalized in _DENIAL_PHRASES or normalized in {"okay", "ok", "fine", "continue", "maybe", "later"}:
        return False
    return normalized in _APPROVAL_PHRASES or normalized in {f"yes, proceed with {active_action.lower()}".rstrip(".!?"), f"yes proceed with {active_action.lower()}".rstrip(".!?")}


class ConsentManager:
    def __init__(self, database_path: str, *, default_timeout_seconds: int = 120) -> None:
        self.database_path = database_path
        self.default_timeout_seconds = default_timeout_seconds
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.database_path, timeout=10)
        db.row_factory = sqlite3.Row
        return db

    def _init_db(self) -> None:
        with self._connect() as db:
            db.execute(
                """CREATE TABLE IF NOT EXISTS consent_records (
                    consent_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    parameters_digest TEXT NOT NULL,
                    risk_level TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    expires_at INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    approved_at INTEGER
                )"""
            )
            db.execute("CREATE INDEX IF NOT EXISTS idx_consent_user_status ON consent_records(user_id, status)")

    def create(self, user_id: str, action: str, parameters: Mapping[str, Any], risk_level: RiskLevel, *, timeout_seconds: Optional[int] = None, now: Optional[int] = None) -> ConsentRecord:
        if not user_id or not action:
            raise ValueError("user_id and action are required")
        if risk_level not in {RiskLevel.FINANCIAL, RiskLevel.DESTRUCTIVE, RiskLevel.SENSITIVE}:
            raise ValueError("Consent is only created for protected actions")
        created = int(time.time() if now is None else now)
        timeout = timeout_seconds if timeout_seconds is not None else self.default_timeout_seconds
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        record = ConsentRecord(secrets.token_urlsafe(18), user_id, action, parameters_digest(parameters), risk_level, created, created + timeout, ConsentStatus.PENDING)
        with self._connect() as db:
            # Only one active proposal per user/action; material parameters still
            # bind through the digest.
            db.execute("UPDATE consent_records SET status=? WHERE user_id=? AND status=?", (ConsentStatus.EXPIRED.value, user_id, ConsentStatus.PENDING.value))
            db.execute(
                "INSERT INTO consent_records(consent_id,user_id,action,parameters_digest,risk_level,created_at,expires_at,status) VALUES(?,?,?,?,?,?,?,?)",
                (record.consent_id, record.user_id, record.action, record.parameters_digest, record.risk_level.value, record.created_at, record.expires_at, record.status.value),
            )
        return record

    def get(self, consent_id: str) -> Optional[ConsentRecord]:
        with self._connect() as db:
            row = db.execute("SELECT * FROM consent_records WHERE consent_id=?", (consent_id,)).fetchone()
        return self._from_row(row) if row else None

    def approve(self, consent_id: str, user_id: str, action: str, parameters: Mapping[str, Any], *, now: Optional[int] = None) -> ConsentRecord:
        current = int(time.time() if now is None else now)
        digest = parameters_digest(parameters)
        with self._connect() as db:
            row = db.execute("SELECT * FROM consent_records WHERE consent_id=? AND user_id=?", (consent_id, user_id)).fetchone()
            if not row:
                raise ValueError("Approval request not found")
            record = self._from_row(row)
            if record.status != ConsentStatus.PENDING or current >= record.expires_at:
                db.execute("UPDATE consent_records SET status=? WHERE consent_id=?", (ConsentStatus.EXPIRED.value, consent_id))
                raise ValueError("Approval request expired or already used")
            if record.action != action or not secrets.compare_digest(record.parameters_digest, digest):
                raise ValueError("Approval does not match the proposed action")
            db.execute("UPDATE consent_records SET status=?, approved_at=? WHERE consent_id=?", (ConsentStatus.APPROVED.value, current, consent_id))
            return ConsentRecord(record.consent_id, record.user_id, record.action, record.parameters_digest, record.risk_level, record.created_at, record.expires_at, ConsentStatus.APPROVED, current)

    def validate(self, consent_id: str, user_id: str, action: str, parameters: Mapping[str, Any], *, now: Optional[int] = None) -> bool:
        record = self.get(consent_id)
        return bool(record and record.user_id == user_id and record.action == action and record.parameters_digest == parameters_digest(parameters) and record.is_current(now=now))

    def consume(self, consent_id: str, user_id: str, action: str, parameters: Mapping[str, Any], *, now: Optional[int] = None) -> ConsentRecord:
        record = self.get(consent_id)
        if not record or not self.validate(consent_id, user_id, action, parameters, now=now):
            raise ValueError("Valid exact-action consent is required")
        with self._connect() as db:
            updated = db.execute("UPDATE consent_records SET status=? WHERE consent_id=? AND user_id=? AND status=?", (ConsentStatus.CONSUMED.value, consent_id, user_id, ConsentStatus.APPROVED.value))
            if updated.rowcount != 1:
                raise ValueError("Consent has already been consumed")
        return ConsentRecord(record.consent_id, record.user_id, record.action, record.parameters_digest, record.risk_level, record.created_at, record.expires_at, ConsentStatus.CONSUMED, record.approved_at)

    @staticmethod
    def _from_row(row: sqlite3.Row) -> ConsentRecord:
        return ConsentRecord(row["consent_id"], row["user_id"], row["action"], row["parameters_digest"], RiskLevel(row["risk_level"]), int(row["created_at"]), int(row["expires_at"]), ConsentStatus(row["status"]), row["approved_at"])
