"""Deterministic privacy filtering used before providers, logs and memory.

A model instruction such as "do not remember this" is not a control boundary.
This module runs in application code and removes high-risk payment credentials
before any downstream component sees the text.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re
from typing import Iterable, Optional


# These patterns intentionally favour false positives over leaking a credential.
# The redactor is not a payment parser and must never be used to validate a PIN.
_PROHIBITED_CREDENTIAL_REQUEST = re.compile(
    r"\b(?:remember|save|store|keep|retain|use|tell)\b[^.\n]{0,120}\b(?:upi\s*pin|atm\s*pin|card\s*pin|cvv|cvc|otp|one[\s-]*time\s*password|bank(?:ing)?\s*password)\b[^.\n]*",
    re.I,
)
_SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("upi_pin", re.compile(r"\b(?:upi\s*pin|pin\s*(?:is|=|:))\s*[:=\-]?\s*\d{4,6}\b", re.I)),
    ("card_pin", re.compile(r"\b(?:card|atm)\s*pin\s*(?:is|=|:)?\s*\d{4,6}\b", re.I)),
    ("cvv", re.compile(r"\b(?:cvv|cvc|security\s*code)\s*(?:is|=|:)?\s*\d{3,4}\b", re.I)),
    ("otp", re.compile(r"\b(?:otp|one[\s-]*time\s*password|verification\s*code)\s*(?:is|=|:)?\s*\d{4,8}\b", re.I)),
    ("bank_password", re.compile(r"\b(?:internet\s*banking|bank(?:ing)?|netbanking)\s*(?:password|passcode)\s*(?:is|=|:)?\s*[^\s,.;]+", re.I)),
    ("password", re.compile(r"\b(?:password|passphrase)\s*(?:is|=|:)\s*[^\s,.;]+", re.I)),
    ("jwt", re.compile(r"\b(?:eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+)\b")),
    ("api_key", re.compile(r"\b(?:sk|rk|api)[_-][A-Za-z0-9_-]{12,}\b", re.I)),
    ("card_number", re.compile(r"\b(?:card(?:\s*number)?|credit\s*card)\s*(?:is|=|:)?\s*\d(?:[ -]?\d){11,18}\b", re.I)),
)


def _replacement(label: str) -> str:
    return f"[REDACTED:{label.upper()}]"


@dataclass(frozen=True)
class RedactionResult:
    text: str
    redacted: bool
    labels: tuple[str, ...]


def redact_sensitive(text: str, *, extra_patterns: Optional[Iterable[tuple[str, re.Pattern[str]]]] = None) -> RedactionResult:
    """Return text with credentials removed and labels for security telemetry.

    Labels contain categories only. They never contain the matched value.
    """
    if not isinstance(text, str):
        raise TypeError("text must be a string")
    patterns = list(_SECRET_PATTERNS)
    if extra_patterns:
        patterns.extend(extra_patterns)
    labels: list[str] = []
    redacted = text
    if _PROHIBITED_CREDENTIAL_REQUEST.search(redacted):
        redacted = _PROHIBITED_CREDENTIAL_REQUEST.sub(_replacement("credential_request"), redacted)
        labels.append("credential_request")
    for label, pattern in patterns:
        redacted, count = pattern.subn(_replacement(label), redacted)
        if count and label not in labels:
            labels.append(label)
    return RedactionResult(redacted, bool(labels), tuple(labels))


def contains_sensitive_credential(text: str) -> bool:
    return redact_sensitive(text).redacted


def privacy_filter(text: str, *, strict: bool = True) -> str:
    """Short alias for call sites that need a safe string only."""
    # Even balanced mode always removes financial credentials. The argument is
    # retained to make call sites explicit and to allow future lower-risk filters.
    return redact_sensitive(text).text


def pseudonymous_user_ref(user_id: str, installation_salt: bytes) -> str:
    """Create a stable, non-reversible reference for the audit ledger."""
    if not user_id:
        raise ValueError("user_id is required")
    return hashlib.sha256(installation_salt + user_id.encode("utf-8")).hexdigest()[:32]


class CredentialLeakError(ValueError):
    """Raised when an operation attempts to persist a raw payment credential."""


def reject_sensitive_credential(text: str) -> None:
    result = redact_sensitive(text)
    if result.redacted:
        raise CredentialLeakError("AURA does not retain payment credentials; remove the credential and try again.")


def safe_metadata(value: object) -> object:
    """Recursively redact strings in structured metadata before storage/logging."""
    if isinstance(value, str):
        return redact_sensitive(value).text
    if isinstance(value, dict):
        output = {}
        blocked_names = ("password", "secret", "token", "pin", "cvv", "cvc", "otp", "api_key", "private_key", "access_key")
        for key, item in value.items():
            key_text = str(key)
            if any(term in key_text.lower() for term in blocked_names):
                output[key_text] = "[REDACTED:SECRET_FIELD]"
            else:
                output[key_text] = safe_metadata(item)
        return output
    if isinstance(value, (list, tuple)):
        return [safe_metadata(item) for item in value]
    return value
