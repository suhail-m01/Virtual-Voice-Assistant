"""Authentication value objects."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple


@dataclass(frozen=True)
class AuthContext:
    user_id: str
    role: str = "USER"
    permissions: Tuple[str, ...] = ()
    session_id: Optional[str] = None
    authenticated: bool = True

    def has_permission(self, permission: str) -> bool:
        return self.role == "ADMIN" or permission in self.permissions


@dataclass(frozen=True)
class AuthenticatedSession:
    user_id: str
    email: str
    role: str
    session_id: str
    access_token: str
    refresh_token: str
    permissions: Tuple[str, ...]

    @property
    def context(self) -> AuthContext:
        return AuthContext(self.user_id, self.role, self.permissions, self.session_id, True)
