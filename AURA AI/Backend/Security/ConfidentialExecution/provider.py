"""Attestation and secret-release abstraction.

A normal Windows/PyQt process is not a TEE.  The local provider reports that
fact explicitly and fails closed for production secret release.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Mapping, Optional, Protocol


class AttestationStatus(str, Enum):
    UNAVAILABLE = "Unavailable"
    PENDING = "Pending"
    VERIFIED = "Verified"
    FAILED = "Failed"


@dataclass(frozen=True)
class AttestationEvidence:
    mode: str
    status: AttestationStatus
    measurement: Optional[str] = None
    evidence: Optional[bytes] = None
    verifier: Optional[str] = None


class SecretReleaseError(PermissionError):
    pass


class TEEProvider(Protocol):
    def attest(self) -> AttestationEvidence: ...
    def verify_attestation(self, evidence: AttestationEvidence) -> bool: ...
    def release_secret(self, name: str, *, evidence: AttestationEvidence) -> bytes: ...


class ConfidentialExecutionProvider:
    """Base contract for future TDX/SEV-SNP/cloud confidential VM adapters."""
    def attest(self) -> AttestationEvidence:
        raise NotImplementedError

    def verify_attestation(self, evidence: AttestationEvidence) -> bool:
        raise NotImplementedError

    def release_secret(self, name: str, *, evidence: AttestationEvidence) -> bytes:
        raise NotImplementedError


class LocalDevelopmentProvider(ConfidentialExecutionProvider):
    @property
    def mode(self) -> str:
        return "Local Development"

    def attest(self) -> AttestationEvidence:
        return AttestationEvidence(self.mode, AttestationStatus.UNAVAILABLE)

    def verify_attestation(self, evidence: AttestationEvidence) -> bool:
        return False

    def release_secret(self, name: str, *, evidence: AttestationEvidence) -> bytes:
        # Never silently return a local key as if it were attested.
        raise SecretReleaseError("Attestation unavailable; production secret release is blocked")

    def status(self) -> dict[str, str]:
        return {
            "mode": "Local Development",
            "attestation": "Unavailable",
            "secret_protection": "Development",
        }


class AttestedTEEProvider(ConfidentialExecutionProvider):
    """Skeleton for a real verifier; no successful default is permitted."""
    def __init__(self, verifier: object) -> None:
        self.verifier = verifier

    def attest(self) -> AttestationEvidence:
        raise NotImplementedError("Connect a TDX, SEV-SNP or confidential-VM attestation client")

    def verify_attestation(self, evidence: AttestationEvidence) -> bool:
        if evidence.status != AttestationStatus.VERIFIED or not evidence.measurement or not evidence.evidence:
            return False
        return bool(self.verifier.verify(evidence))

    def release_secret(self, name: str, *, evidence: AttestationEvidence) -> bytes:
        if not self.verify_attestation(evidence):
            raise SecretReleaseError("Attestation verification failed; secret release blocked")
        raise NotImplementedError("Bind release to an attestation-gated secret manager")
