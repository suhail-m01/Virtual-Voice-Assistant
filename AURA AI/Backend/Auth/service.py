"""SQLite-backed account, session and refresh-token service."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
import secrets
import sqlite3
import threading
import time
import uuid
from typing import Optional, Tuple

from .jwt import JWTService, JWTValidationError
from .models import AuthContext, AuthenticatedSession
from .passwords import PasswordHasher


class AuthenticationError(ValueError):
    """Safe authentication error; callers should not reveal which field failed."""


class AuthService:
    """Authentication boundary with lockout and refresh-token rotation.

    Refresh tokens are opaque, random, hashed at rest, single-use values.  A
    replay of a rotated token revokes its entire session family.
    """

    def __init__(self, database_path: str, jwt_service: JWTService, *, password_hasher: Optional[PasswordHasher] = None, refresh_ttl_seconds: int = 2_592_000) -> None:
        self.database_path = database_path
        self.jwt = jwt_service
        self.passwords = password_hasher or PasswordHasher()
        if refresh_ttl_seconds < 300:
            raise ValueError("refresh token TTL is too short")
        self.refresh_ttl_seconds = refresh_ttl_seconds
        self._lock = threading.RLock()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=10, check_same_thread=False)
        connection.row_factory = sqlite3.Row
        return connection

    def _init_db(self) -> None:
        with self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    user_id TEXT PRIMARY KEY,
                    email TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    role TEXT NOT NULL DEFAULT 'USER',
                    permissions TEXT NOT NULL DEFAULT '',
                    failed_attempts INTEGER NOT NULL DEFAULT 0,
                    locked_until INTEGER,
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS auth_sessions (
                    session_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    expires_at INTEGER NOT NULL,
                    revoked_at INTEGER,
                    FOREIGN KEY(user_id) REFERENCES users(user_id)
                );
                CREATE TABLE IF NOT EXISTS refresh_tokens (
                    token_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    token_hash TEXT NOT NULL UNIQUE,
                    family_id TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    expires_at INTEGER NOT NULL,
                    used_at INTEGER,
                    revoked_at INTEGER,
                    FOREIGN KEY(session_id) REFERENCES auth_sessions(session_id)
                );
                CREATE TABLE IF NOT EXISTS password_reset_tokens (
                    token_hash TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    expires_at INTEGER NOT NULL,
                    used_at INTEGER,
                    FOREIGN KEY(user_id) REFERENCES users(user_id)
                );
                CREATE INDEX IF NOT EXISTS idx_refresh_hash ON refresh_tokens(token_hash);
                CREATE INDEX IF NOT EXISTS idx_sessions_user ON auth_sessions(user_id);
                """
            )

    @staticmethod
    def _normalize_email(email: str) -> str:
        normalized = email.strip().lower()
        if "@" not in normalized or len(normalized) > 320:
            raise AuthenticationError("Invalid credentials")
        return normalized

    @staticmethod
    def _hash_token(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def register(self, email: str, password: str, *, role: str = "USER", permissions: Tuple[str, ...] = ()) -> str:
        normalized = self._normalize_email(email)
        role = role.upper()
        if role not in {"USER", "ADMIN"}:
            raise ValueError("Unsupported role")
        password_hash = self.passwords.hash(password)
        now = int(time.time())
        user_id = str(uuid.uuid4())
        permission_text = ",".join(sorted(set(permissions)))
        with self._lock, self._connect() as db:
            try:
                db.execute(
                    "INSERT INTO users(user_id,email,password_hash,role,permissions,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
                    (user_id, normalized, password_hash, role, permission_text, now, now),
                )
            except sqlite3.IntegrityError as exc:
                raise AuthenticationError("Unable to create account") from exc
        return user_id

    def login(self, email: str, password: str) -> AuthenticatedSession:
        normalized = self._normalize_email(email)
        now = int(time.time())
        with self._lock, self._connect() as db:
            row = db.execute("SELECT * FROM users WHERE email = ?", (normalized,)).fetchone()
            if row is None:
                # Keep the observable response and work path uniform for unknown users.
                raise AuthenticationError("Invalid credentials")
            locked_until = row["locked_until"] or 0
            if locked_until > now:
                raise AuthenticationError("Account temporarily locked")
            valid = self.passwords.verify(row["password_hash"], password)
            if not valid:
                failed = int(row["failed_attempts"]) + 1
                lock_until = None
                if failed >= 5:
                    # Progressive delay: 30 seconds, 60 seconds, then five minutes.
                    lock_until = now + min(300, 30 * (2 ** min(failed - 5, 3)))
                db.execute("UPDATE users SET failed_attempts=?, locked_until=?, updated_at=? WHERE user_id=?", (failed, lock_until, now, row["user_id"]))
                raise AuthenticationError("Invalid credentials")
            db.execute("UPDATE users SET failed_attempts=0, locked_until=NULL, updated_at=? WHERE user_id=?", (now, row["user_id"]))
            permissions = tuple(item for item in row["permissions"].split(",") if item)
            return self._issue_session(db, row["user_id"], row["email"], row["role"], permissions, now)

    def _issue_session(self, db: sqlite3.Connection, user_id: str, email: str, role: str, permissions: Tuple[str, ...], now: int) -> AuthenticatedSession:
        session_id = str(uuid.uuid4())
        session_expiry = now + self.jwt.config.access_ttl_seconds + 86_400
        family_id = str(uuid.uuid4())
        refresh_secret = secrets.token_urlsafe(48)
        refresh_token = f"{family_id}.{refresh_secret}"
        token_id = str(uuid.uuid4())
        db.execute("INSERT INTO auth_sessions(session_id,user_id,created_at,expires_at) VALUES(?,?,?,?)", (session_id, user_id, now, session_expiry))
        db.execute(
            "INSERT INTO refresh_tokens(token_id,session_id,token_hash,family_id,created_at,expires_at) VALUES(?,?,?,?,?,?)",
            (token_id, session_id, self._hash_token(refresh_token), family_id, now, now + self.refresh_ttl_seconds),
        )
        access = self.jwt.issue(user_id, session_id=session_id, role=role, permissions=permissions, now=now)
        return AuthenticatedSession(user_id, email, role, session_id, access, refresh_token, permissions)

    def validate_access(self, access_token: str) -> AuthContext:
        try:
            claims = self.jwt.decode_and_validate(access_token)
        except JWTValidationError as exc:
            raise AuthenticationError("Authentication expired") from exc
        with self._lock, self._connect() as db:
            row = db.execute(
                "SELECT s.revoked_at, s.expires_at, u.role, u.permissions FROM auth_sessions s JOIN users u ON u.user_id=s.user_id WHERE s.session_id=? AND s.user_id=?",
                (claims["sid"], claims["sub"]),
            ).fetchone()
        if row is None or row["revoked_at"] is not None or int(row["expires_at"]) <= int(time.time()):
            raise AuthenticationError("Authentication expired")
        permissions = tuple(item for item in row["permissions"].split(",") if item)
        return AuthContext(str(claims["sub"]), row["role"], permissions, claims["sid"], True)

    def refresh(self, refresh_token: str) -> AuthenticatedSession:
        if not isinstance(refresh_token, str) or len(refresh_token) < 40:
            raise AuthenticationError("Invalid refresh token")
        token_hash = self._hash_token(refresh_token)
        now = int(time.time())
        with self._lock, self._connect() as db:
            row = db.execute(
                "SELECT r.*, s.user_id, s.revoked_at AS session_revoked, u.email, u.role, u.permissions FROM refresh_tokens r JOIN auth_sessions s ON s.session_id=r.session_id JOIN users u ON u.user_id=s.user_id WHERE r.token_hash=?",
                (token_hash,),
            ).fetchone()
            if row is None:
                raise AuthenticationError("Invalid refresh token")
            if row["used_at"] is not None or row["revoked_at"] is not None:
                # Token replay: invalidate the whole family and session.
                db.execute("UPDATE refresh_tokens SET revoked_at=? WHERE family_id=?", (now, row["family_id"]))
                db.execute("UPDATE auth_sessions SET revoked_at=? WHERE session_id=?", (now, row["session_id"]))
                # Commit revocation before returning the security error. A
                # context-manager rollback must never resurrect a replayed family.
                db.commit()
                raise AuthenticationError("Refresh token replay detected")
            if row["session_revoked"] is not None or int(row["expires_at"]) <= now:
                raise AuthenticationError("Refresh token expired")
            db.execute("UPDATE refresh_tokens SET used_at=? WHERE token_id=?", (now, row["token_id"]))
            # Rotation stays in the same family and is single-use.
            next_secret = secrets.token_urlsafe(48)
            next_token = f"{row['family_id']}.{next_secret}"
            next_id = str(uuid.uuid4())
            db.execute(
                "INSERT INTO refresh_tokens(token_id,session_id,token_hash,family_id,created_at,expires_at) VALUES(?,?,?,?,?,?)",
                (next_id, row["session_id"], self._hash_token(next_token), row["family_id"], now, int(row["expires_at"])),
            )
            permissions = tuple(item for item in row["permissions"].split(",") if item)
            access = self.jwt.issue(row["user_id"], session_id=row["session_id"], role=row["role"], permissions=permissions, now=now)
            return AuthenticatedSession(row["user_id"], row["email"], row["role"], row["session_id"], access, next_token, permissions)

    def logout(self, session_id: str) -> None:
        now = int(time.time())
        with self._lock, self._connect() as db:
            db.execute("UPDATE auth_sessions SET revoked_at=? WHERE session_id=?", (now, session_id))
            db.execute("UPDATE refresh_tokens SET revoked_at=? WHERE session_id=? AND revoked_at IS NULL", (now, session_id))

    def change_password(self, context: AuthContext, current_password: str, new_password: str) -> None:
        with self._lock, self._connect() as db:
            row = db.execute("SELECT password_hash FROM users WHERE user_id=?", (context.user_id,)).fetchone()
            if row is None or not self.passwords.verify(row["password_hash"], current_password):
                raise AuthenticationError("Current password is incorrect")
            new_hash = self.passwords.hash(new_password)
            now = int(time.time())
            db.execute("UPDATE users SET password_hash=?, updated_at=? WHERE user_id=?", (new_hash, now, context.user_id))
            db.execute("UPDATE auth_sessions SET revoked_at=? WHERE user_id=? AND session_id != ? AND revoked_at IS NULL", (now, context.user_id, context.session_id or ""))

    def issue_password_reset(self, email: str, *, ttl_seconds: int = 900) -> Optional[str]:
        normalized = self._normalize_email(email)
        now = int(time.time())
        raw = secrets.token_urlsafe(48)
        with self._lock, self._connect() as db:
            row = db.execute("SELECT user_id FROM users WHERE email=?", (normalized,)).fetchone()
            if row is None:
                return None
            db.execute("UPDATE password_reset_tokens SET used_at=? WHERE user_id=? AND used_at IS NULL", (now, row["user_id"]))
            db.execute("INSERT INTO password_reset_tokens(token_hash,user_id,created_at,expires_at) VALUES(?,?,?,?)", (self._hash_token(raw), row["user_id"], now, now + ttl_seconds))
        # The caller hands this to an email/SMS delivery adapter. Never log it.
        return raw

    def reset_password(self, reset_token: str, new_password: str) -> None:
        now = int(time.time())
        with self._lock, self._connect() as db:
            row = db.execute("SELECT * FROM password_reset_tokens WHERE token_hash=?", (self._hash_token(reset_token),)).fetchone()
            if row is None or row["used_at"] is not None or int(row["expires_at"]) <= now:
                raise AuthenticationError("Reset token is invalid or expired")
            password_hash = self.passwords.hash(new_password)
            db.execute("UPDATE users SET password_hash=?, updated_at=? WHERE user_id=?", (password_hash, now, row["user_id"]))
            db.execute("UPDATE password_reset_tokens SET used_at=? WHERE token_hash=?", (now, row["token_hash"]))
            db.execute("UPDATE auth_sessions SET revoked_at=? WHERE user_id=? AND revoked_at IS NULL", (now, row["user_id"]))
