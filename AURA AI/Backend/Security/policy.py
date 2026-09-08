"""Authentication, authorization, risk and consent gateway."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional

from ..Auth.models import AuthContext
from .consent import ConsentManager, ConsentStatus, RiskLevel, parameters_digest


class PolicyDenied(PermissionError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.user_message = message


@dataclass(frozen=True)
class ToolSecurityContext:
    auth: AuthContext
    payment_lock: Optional[bool] = None
    consent_id: Optional[str] = None


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    requires_consent: bool = False
    reason: str = ""
    consent_id: Optional[str] = None


class PolicyGateway:
    """The only gateway through which protected tools should execute."""

    def __init__(self, consent_manager: ConsentManager, *, payment_lock: bool = True) -> None:
        self.consents = consent_manager
        self.payment_lock = payment_lock

    def evaluate(self, *, tool_name: str, parameters: Mapping[str, Any], risk_level: RiskLevel, required_permission: Optional[str], context: ToolSecurityContext, confirmation_required: bool) -> PolicyDecision:
        if not context.auth.authenticated:
            raise PolicyDenied("AUTHENTICATION_REQUIRED", "Authentication required.")
        if required_permission and not context.auth.has_permission(required_permission):
            raise PolicyDenied("PERMISSION_DENIED", "Permission denied.")
        if risk_level == RiskLevel.FINANCIAL and (self.payment_lock or context.payment_lock is True):
            raise PolicyDenied("PAYMENTS_LOCKED", "Payments are locked.")
        protected = risk_level in {RiskLevel.SENSITIVE, RiskLevel.FINANCIAL, RiskLevel.DESTRUCTIVE}
        if protected and confirmation_required:
            if not context.consent_id:
                return PolicyDecision(False, True, "Fresh approval required.")
            record = self.consents.get(context.consent_id)
            if not record or record.user_id != context.auth.user_id or record.status not in {ConsentStatus.APPROVED}:
                raise PolicyDenied("CONSENT_REQUIRED", "Payment confirmation required." if risk_level == RiskLevel.FINANCIAL else "Approval required.")
            if record.action != tool_name or record.parameters_digest != parameters_digest(parameters) or not record.is_current():
                raise PolicyDenied("CONSENT_MISMATCH", "Approval does not match this action.")
        return PolicyDecision(True, False, "Allowed.", context.consent_id)

    def require_or_create_consent(self, *, tool_name: str, parameters: Mapping[str, Any], risk_level: RiskLevel, context: ToolSecurityContext, confirmation_required: bool, timeout_seconds: int = 120) -> PolicyDecision:
        decision = self.evaluate(tool_name=tool_name, parameters=parameters, risk_level=risk_level, required_permission=None, context=context, confirmation_required=False)
        if confirmation_required and risk_level in {RiskLevel.SENSITIVE, RiskLevel.FINANCIAL, RiskLevel.DESTRUCTIVE} and not context.consent_id:
            record = self.consents.create(context.auth.user_id, tool_name, parameters, risk_level, timeout_seconds=timeout_seconds)
            return PolicyDecision(False, True, "Fresh approval required.", record.consent_id)
        return decision
