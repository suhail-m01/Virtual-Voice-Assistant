"""User-scoped, privacy-filtered memory repository."""
from __future__ import annotations

from dataclasses import dataclass
import json
import secrets
import time
from typing import Any, Optional

from ..Security.privacy import CredentialLeakError, redact_sensitive
from .database import Database, EncryptedPayloadCodec


@dataclass(frozen=True)
class MemoryItem:
    memory_id: str
    user_id: str
    kind: str
    content: str
    created_at: int
    approved: bool
    conversation_id: Optional[str] = None


class MemoryRepository:
    """Only returns records for the requested user and bounded recent context."""

    def __init__(self, database: Database, codec: EncryptedPayloadCodec) -> None:
        self.database = database
        self.codec = codec

    def add(self, user_id: str, content: str, *, kind: str = "conversation", approved: bool = False, conversation_id: Optional[str] = None) -> MemoryItem:
        if not user_id or not isinstance(content, str) or not content.strip():
            raise ValueError("user_id and content are required")
        redacted = redact_sensitive(content)
        if redacted.redacted:
            # Credentials should not be silently persisted, even after redaction:
            # a user must understand that the input was blocked.
            raise CredentialLeakError("Sensitive credentials are not stored by Aura")
        now = int(time.time())
        memory_id = secrets.token_urlsafe(16)
        ciphertext = self.codec.encrypt(content, associated_data=user_id)
        with self.database.transaction() as db:
            db.execute(
                "INSERT INTO memory_items(memory_id,user_id,conversation_id,kind,content_ciphertext,created_at,approved) VALUES(?,?,?,?,?,?,?)",
                (memory_id, user_id, conversation_id, kind, ciphertext, now, int(approved)),
            )
        return MemoryItem(memory_id, user_id, kind, content, now, approved, conversation_id)

    def recent(self, user_id: str, *, limit: int = 12, include_unapproved: bool = True) -> list[MemoryItem]:
        if limit < 1 or limit > 100:
            raise ValueError("limit out of range")
        where = "user_id=?" if include_unapproved else "user_id=? AND approved=1"
        with self.database.transaction() as db:
            rows = db.execute(f"SELECT * FROM memory_items WHERE {where} ORDER BY created_at DESC LIMIT ?", (user_id, limit)).fetchall()
        items = []
        for row in reversed(rows):
            items.append(MemoryItem(row["memory_id"], row["user_id"], row["kind"], self.codec.decrypt(row["content_ciphertext"], associated_data=user_id), int(row["created_at"]), bool(row["approved"]), row["conversation_id"]))
        return items

    def approved_context(self, user_id: str, *, limit: int = 8) -> list[str]:
        return [item.content for item in self.recent(user_id, limit=limit, include_unapproved=False)]

    def clear(self, user_id: str) -> int:
        with self.database.transaction() as db:
            cursor = db.execute("DELETE FROM memory_items WHERE user_id=?", (user_id,))
            db.execute("DELETE FROM conversations WHERE user_id=?", (user_id,))
            return cursor.rowcount

    def migrate_legacy_chatlog(self, path: str, user_id: str) -> int:
        """One-way, redacting migration for Data/ChatLog.json.

        The legacy file remains untouched for backwards compatibility.  Callers
        may archive/remove it only after the user has reviewed the migration.
        """
        try:
            with open(path, "r", encoding="utf-8") as handle:
                records = json.load(handle)
        except (OSError, ValueError):
            return 0
        count = 0
        for record in records if isinstance(records, list) else []:
            if not isinstance(record, dict) or not isinstance(record.get("content"), str):
                continue
            content = redact_sensitive(record["content"]).text
            if content != record["content"]:
                continue
            self.add(user_id, content, kind="legacy_conversation", approved=False)
            count += 1
        return count
