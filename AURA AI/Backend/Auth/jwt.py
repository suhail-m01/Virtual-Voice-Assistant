"""Small JWT service with strict claim validation.

HS256 is provided as a dependency-free local-development path.  Production
 deployments should configure an asymmetric signer/verifier (RS256/EdDSA) at the
edge or install the approved JWT library; the service exposes the algorithm in
its configuration so deployments can reject the development path.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass
from typing import Any, Mapping, Optional


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


class JWTValidationError(ValueError):
    pass


@dataclass(frozen=True)
class JWTConfig:
    issuer: str
    audience: str
    secret: bytes
    access_ttl_seconds: int = 600
    algorithm: str = "HS256"


class JWTService:
    def __init__(self, config: JWTConfig) -> None:
        if config.algorithm != "HS256":
            raise ValueError("The dependency-free signer supports HS256 only; use a vetted asymmetric adapter in production")
        if len(config.secret) < 32:
            raise ValueError("JWT secret must be at least 32 bytes")
        self.config = config

    @classmethod
    def from_secret(cls, secret: str, issuer: str = "aura-2026", audience: str = "aura-client", ttl_seconds: int = 600) -> "JWTService":
        if not secret:
            raise ValueError("JWT secret is not configured")
        return cls(JWTConfig(issuer, audience, secret.encode("utf-8"), ttl_seconds))

    def issue(self, subject: str, *, session_id: str, role: str, permissions: tuple[str, ...] = (), now: Optional[int] = None) -> str:
        if not subject or not session_id:
            raise ValueError("subject and session_id are required")
        issued = int(time.time() if now is None else now)
        header = {"alg": self.config.algorithm, "typ": "JWT"}
        payload: dict[str, Any] = {
            "iss": self.config.issuer,
            "aud": self.config.audience,
            "sub": subject,
            "sid": session_id,
            "role": role,
            "permissions": list(permissions),
            "iat": issued,
            "exp": issued + self.config.access_ttl_seconds,
            "jti": secrets.token_urlsafe(18),
            "typ": "access",
        }
        encoded_header = _b64(json.dumps(header, separators=(",", ":"), sort_keys=True).encode())
        encoded_payload = _b64(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode())
        signing_input = f"{encoded_header}.{encoded_payload}".encode("ascii")
        signature = hmac.new(self.config.secret, signing_input, hashlib.sha256).digest()
        return f"{encoded_header}.{encoded_payload}.{_b64(signature)}"

    def decode_and_validate(self, token: str, *, now: Optional[int] = None) -> Mapping[str, Any]:
        try:
            header_raw, payload_raw, signature_raw = token.split(".", 2)
            header = json.loads(_unb64(header_raw))
            payload = json.loads(_unb64(payload_raw))
            signature = _unb64(signature_raw)
        except (ValueError, TypeError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise JWTValidationError("Malformed access token") from exc
        if header.get("alg") != self.config.algorithm or header.get("typ") != "JWT":
            raise JWTValidationError("Unsupported token header")
        expected = hmac.new(self.config.secret, f"{header_raw}.{payload_raw}".encode("ascii"), hashlib.sha256).digest()
        if not hmac.compare_digest(signature, expected):
            raise JWTValidationError("Invalid token signature")
        required = ("iss", "aud", "sub", "sid", "jti", "iat", "exp", "typ")
        if any(key not in payload for key in required):
            raise JWTValidationError("Token is missing required claims")
        if payload["iss"] != self.config.issuer or payload["aud"] != self.config.audience:
            raise JWTValidationError("Token issuer or audience is invalid")
        if payload["typ"] != "access":
            raise JWTValidationError("Token type is invalid")
        current = int(time.time() if now is None else now)
        if not isinstance(payload["exp"], int) or current >= payload["exp"]:
            raise JWTValidationError("Access token has expired")
        if not isinstance(payload["iat"], int) or payload["iat"] > current + 30:
            raise JWTValidationError("Access token issued-at time is invalid")
        return payload
