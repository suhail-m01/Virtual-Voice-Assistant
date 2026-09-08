"""Razorpay HTTPS integration with explicit test mode and minimal metadata."""
from __future__ import annotations

from dataclasses import dataclass
import base64
import json
import sqlite3
import time
import uuid
from typing import Any, Mapping, Optional

from .models import Money, PaymentIntent, PaymentStatus
from .policy import PaymentPolicy, PaymentLockedError
from .verification import verify_payment_signature, verify_webhook_signature, WebhookReplayGuard


class PaymentServiceError(RuntimeError):
    pass


@dataclass(frozen=True)
class PaymentRecord:
    transaction_id: str
    user_id: str
    amount_minor: int
    currency: str
    description: str
    status: PaymentStatus
    razorpay_order_id: Optional[str] = None
    razorpay_payment_id: Optional[str] = None
    payment_link_id: Optional[str] = None
    approval_reference: Optional[str] = None

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "transaction_id": self.transaction_id,
            "user_id": self.user_id,
            "amount_minor": self.amount_minor,
            "currency": self.currency,
            "description": self.description,
            "status": self.status.value,
            "razorpay_order_id": self.razorpay_order_id,
            "razorpay_payment_id": self.razorpay_payment_id,
            "payment_link_id": self.payment_link_id,
            "approval_reference": self.approval_reference,
        }


class RazorpayHTTPClient:
    def __init__(self, key_id: str, key_secret: str, *, mode: str = "test", timeout: int = 15) -> None:
        if not key_id or not key_secret:
            raise ValueError("Razorpay credentials are not configured")
        self.key_id = key_id
        self.key_secret = key_secret
        self.mode = mode
        self.timeout = timeout
        self.base_url = "https://api.razorpay.com/v1"

    def _request(self, method: str, path: str, payload: Optional[Mapping[str, Any]] = None) -> Mapping[str, Any]:
        try:
            import requests
        except ImportError as exc:  # pragma: no cover
            raise PaymentServiceError("The requests package is required for Razorpay") from exc
        try:
            response = requests.request(method, self.base_url + path, json=payload, auth=(self.key_id, self.key_secret), timeout=self.timeout)
            response.raise_for_status()
            value = response.json()
            return value if isinstance(value, dict) else {}
        except Exception as exc:
            raise PaymentServiceError("Payment service unavailable") from exc

    def create_order(self, intent: PaymentIntent) -> Mapping[str, Any]:
        return self._request("POST", "/orders", {"amount": intent.amount.minor, "currency": intent.amount.currency, "receipt": f"aura_{uuid.uuid4().hex[:24]}", "notes": {"purpose": intent.description[:255]}})

    def create_payment_link(self, intent: PaymentIntent) -> Mapping[str, Any]:
        return self._request("POST", "/payment_links", {"amount": intent.amount.minor, "currency": intent.amount.currency, "description": intent.description[:255], "reference_id": f"aura_{uuid.uuid4().hex[:24]}", "reminder_enable": True})

    def fetch_payment(self, payment_id: str) -> Mapping[str, Any]:
        return self._request("GET", f"/payments/{payment_id}")


class PaymentService:
    """Domain service; clients can inject a fake client for tests."""

    def __init__(self, database_path: str, policy: PaymentPolicy, *, client: Optional[Any] = None, webhook_secret: str = "") -> None:
        self.database_path = database_path
        self.policy = policy
        self.client = client
        self.webhook_secret = webhook_secret
        self.replay_guard = WebhookReplayGuard(database_path)
        with sqlite3.connect(database_path) as db:
            db.execute("""CREATE TABLE IF NOT EXISTS transactions(
                transaction_id TEXT PRIMARY KEY, user_id TEXT NOT NULL,
                razorpay_order_id TEXT, razorpay_payment_id TEXT, payment_link_id TEXT,
                amount_minor INTEGER NOT NULL, currency TEXT NOT NULL, description TEXT NOT NULL,
                status TEXT NOT NULL, approval_reference TEXT, created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL
            )""")
            db.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_txn_order ON transactions(razorpay_order_id) WHERE razorpay_order_id IS NOT NULL")
            db.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_txn_link ON transactions(payment_link_id) WHERE payment_link_id IS NOT NULL")

    def create_order(self, intent: PaymentIntent) -> PaymentRecord:
        self.policy.assert_can_initiate()
        if not self.client:
            raise PaymentServiceError("Razorpay service is not configured")
        response = self.client.create_order(intent)
        order_id = str(response.get("id", ""))
        if not order_id:
            raise PaymentServiceError("Razorpay returned no order reference")
        return self._store(intent, PaymentStatus.CREATED, razorpay_order_id=order_id)

    def create_payment_link(self, intent: PaymentIntent) -> PaymentRecord:
        self.policy.assert_can_initiate()
        if not self.client:
            raise PaymentServiceError("Razorpay service is not configured")
        response = self.client.create_payment_link(intent)
        link_id = str(response.get("id", ""))
        if not link_id:
            raise PaymentServiceError("Razorpay returned no payment-link reference")
        return self._store(intent, PaymentStatus.CREATED, payment_link_id=link_id)

    def _store(self, intent: PaymentIntent, status: PaymentStatus, *, razorpay_order_id: Optional[str] = None, payment_link_id: Optional[str] = None, razorpay_payment_id: Optional[str] = None) -> PaymentRecord:
        now = int(time.time())
        transaction_id = str(uuid.uuid4())
        with sqlite3.connect(self.database_path) as db:
            db.execute("INSERT INTO transactions(transaction_id,user_id,razorpay_order_id,razorpay_payment_id,payment_link_id,amount_minor,currency,description,status,approval_reference,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", (transaction_id, intent.user_id, razorpay_order_id, razorpay_payment_id, payment_link_id, intent.amount.minor, intent.amount.currency, intent.description[:255], status.value, intent.approval_reference, now, now))
        return PaymentRecord(transaction_id, intent.user_id, intent.amount.minor, intent.amount.currency, intent.description, status, razorpay_order_id, razorpay_payment_id, payment_link_id, intent.approval_reference)

    def verify_payment(self, *, transaction_id: str, order_id: str, payment_id: str, signature: str, secret: str) -> PaymentRecord:
        if not verify_payment_signature(order_id, payment_id, signature, secret):
            raise PaymentServiceError("Payment verification failed")
        with sqlite3.connect(self.database_path) as db:
            row = db.execute("SELECT * FROM transactions WHERE transaction_id=? AND razorpay_order_id=?", (transaction_id, order_id)).fetchone()
            if not row:
                raise PaymentServiceError("Transaction not found")
            db.execute("UPDATE transactions SET razorpay_payment_id=?, status=?, updated_at=? WHERE transaction_id=?", (payment_id, PaymentStatus.CAPTURED.value, int(time.time()), transaction_id))
        return self.get(transaction_id)

    def process_webhook(self, *, raw_body: bytes, signature: str, event_id: str, payload: Mapping[str, Any]) -> bool:
        if not verify_webhook_signature(raw_body, signature, self.webhook_secret):
            raise PaymentServiceError("Webhook verification failed")
        if not self.replay_guard.accept_once(event_id):
            return False
        # A production adapter should map Razorpay event types explicitly. Never
        # trust a client-side success flag without this verified webhook/signature.
        entity = payload.get("payload", {}).get("payment", {}).get("entity", {}) if isinstance(payload, Mapping) else {}
        payment_id = entity.get("id") if isinstance(entity, Mapping) else None
        order_id = entity.get("order_id") if isinstance(entity, Mapping) else None
        event_name = str(payload.get("event", ""))
        status = {
            "payment.captured": PaymentStatus.CAPTURED.value,
            "order.paid": PaymentStatus.CAPTURED.value,
            "payment.authorized": PaymentStatus.AUTHORIZED.value,
            "payment.failed": PaymentStatus.FAILED.value,
            "refund.processed": PaymentStatus.REFUNDED.value,
        }.get(event_name, PaymentStatus.PENDING.value)
        with sqlite3.connect(self.database_path) as db:
            if order_id:
                db.execute("UPDATE transactions SET razorpay_payment_id=COALESCE(razorpay_payment_id, ?), status=?, updated_at=? WHERE razorpay_order_id=?", (payment_id, status, int(time.time()), order_id))
        return True

    def get(self, transaction_id: str) -> PaymentRecord:
        with sqlite3.connect(self.database_path) as db:
            row = db.execute("SELECT * FROM transactions WHERE transaction_id=?", (transaction_id,)).fetchone()
        if not row:
            raise PaymentServiceError("Transaction not found")
        return PaymentRecord(row[0], row[1], row[5], row[6], row[7], PaymentStatus(row[8]), row[2], row[3], row[4], row[9])

    def latest_for_user(self, user_id: str) -> Optional[PaymentRecord]:
        with sqlite3.connect(self.database_path) as db:
            row = db.execute("SELECT * FROM transactions WHERE user_id=? ORDER BY created_at DESC LIMIT 1", (user_id,)).fetchone()
        return self._row_to_record(row) if row else None

    def recent_for_user(self, user_id: str, *, limit: int = 10) -> list[PaymentRecord]:
        if not 1 <= limit <= 50:
            raise ValueError("limit out of range")
        with sqlite3.connect(self.database_path) as db:
            rows = db.execute("SELECT * FROM transactions WHERE user_id=? ORDER BY created_at DESC LIMIT ?", (user_id, limit)).fetchall()
        return [self._row_to_record(row) for row in rows]

    @staticmethod
    def _row_to_record(row) -> PaymentRecord:
        return PaymentRecord(row[0], row[1], row[5], row[6], row[7], PaymentStatus(row[8]), row[2], row[3], row[4], row[9])


class RazorpayService(PaymentService):
    """Named facade retained for integrations expecting a Razorpay service."""
    pass
