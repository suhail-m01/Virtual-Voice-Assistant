"""Razorpay signature verification and replay protection."""
from __future__ import annotations

import hashlib
import hmac
import sqlite3
import time
from typing import Optional


def _signature(payload: bytes, secret: str) -> str:
    if not secret:
        raise ValueError("verification secret is not configured")
    return hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()


def verify_payment_signature(order_id: str, payment_id: str, signature: str, secret: str) -> bool:
    if not order_id or not payment_id or not signature or not secret:
        return False
    expected = _signature(f"{order_id}|{payment_id}".encode("utf-8"), secret)
    return hmac.compare_digest(expected, signature)


def verify_webhook_signature(raw_body: bytes, signature: str, webhook_secret: str) -> bool:
    if not isinstance(raw_body, bytes) or not signature or not webhook_secret:
        return False
    return hmac.compare_digest(_signature(raw_body, webhook_secret), signature)


class WebhookReplayGuard:
    def __init__(self, database_path: str) -> None:
        self.database_path = database_path
        with sqlite3.connect(database_path) as db:
            db.execute("CREATE TABLE IF NOT EXISTS processed_webhooks(event_id TEXT PRIMARY KEY, received_at INTEGER NOT NULL)")

    def accept_once(self, event_id: str, *, now: Optional[int] = None) -> bool:
        if not event_id or len(event_id) > 200:
            return False
        with sqlite3.connect(self.database_path) as db:
            try:
                db.execute("INSERT INTO processed_webhooks(event_id, received_at) VALUES(?,?)", (event_id, int(time.time() if now is None else now)))
            except sqlite3.IntegrityError:
                return False
        return True
