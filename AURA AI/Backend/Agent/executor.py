"""Bounded deterministic plan executor with policy and observability."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from enum import Enum
import inspect
import json
import threading
import time
from typing import Any, Callable, Mapping, Optional

from ..Auth.models import AuthContext
from ..Security.audit import AuditLedger
from ..Security.consent import ConsentManager, ConsentStatus, RiskLevel
from ..Security.policy import PolicyDenied, PolicyGateway, ToolSecurityContext
from ..Security.privacy import safe_metadata
from .schemas import ActionPlan, ToolResult
from .tool_registry import ToolRegistry, ToolSpec, ToolValidationError


class ExecutionStatus(str, Enum):
    COMPLETE = "COMPLETE"
    WAITING_APPROVAL = "WAITING_APPROVAL"
    NEEDS_CLARIFICATION = "NEEDS_CLARIFICATION"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"


@dataclass(frozen=True)
class ExecutionLimits:
    max_tool_calls: int = 12
    max_retries: int = 2
    max_planning_iterations: int = 4
    default_timeout_seconds: int = 30


@dataclass(frozen=True)
class ExecutionEvent:
    kind: str
    tool_name: str = ""
    message: str = ""
    status: str = ""
    duration_ms: int = 0


@dataclass(frozen=True)
class ExecutionOutcome:
    status: ExecutionStatus
    message: str
    results: tuple[ToolResult, ...] = ()
    events: tuple[ExecutionEvent, ...] = ()
    consent_id: Optional[str] = None
    observations: Mapping[str, Any] = field(default_factory=dict)


class Executor:
    def __init__(self, registry: ToolRegistry, policy: PolicyGateway, consent_manager: ConsentManager, *, audit: Optional[AuditLedger] = None, limits: Optional[ExecutionLimits] = None) -> None:
        self.registry = registry
        self.policy = policy
        self.consents = consent_manager
        self.audit = audit
        self.limits = limits or ExecutionLimits()

    async def execute(self, plan: ActionPlan, *, auth: AuthContext, consent_id: Optional[str] = None, cancel_event: Optional[threading.Event] = None, on_event: Optional[Callable[[ExecutionEvent], None]] = None) -> ExecutionOutcome:
        events: list[ExecutionEvent] = []
        results: list[ToolResult] = []
        observations: dict[str, Any] = {}
        if plan.requires_clarification:
            return ExecutionOutcome(ExecutionStatus.NEEDS_CLARIFICATION, plan.clarification_question, events=tuple(events))
        if not plan.steps:
            return ExecutionOutcome(ExecutionStatus.COMPLETE, plan.response_hint or "Done.", events=tuple(events))
        if len(plan.steps) > self.limits.max_tool_calls:
            return ExecutionOutcome(ExecutionStatus.FAILED, "The task exceeded Aura's safety limit.", events=tuple(events))

        def emit(event: ExecutionEvent) -> None:
            events.append(event)
            if on_event:
                try:
                    on_event(event)
                except Exception:
                    pass

        # The executor is deliberately sequential. This makes dependencies and
        # approval binding observable and avoids an uncontrolled autonomous loop.
        completed_steps: set[str] = set()
        for step in plan.steps:
            if any(dependency not in completed_steps for dependency in step.depends_on):
                return ExecutionOutcome(ExecutionStatus.FAILED, "The plan contained an unsafe step dependency.", tuple(results), tuple(events), observations=observations)
            if self._cancelled(cancel_event):
                emit(ExecutionEvent("cancelled", message="Task cancelled."))
                return ExecutionOutcome(ExecutionStatus.CANCELLED, "Stopped.", tuple(results), tuple(events), observations=observations)
            try:
                spec, parameters = self.registry.validate_call(step.tool_call.name, self._resolve(step.tool_call.parameters, observations))
            except ToolValidationError as exc:
                self._audit(auth.user_id, "tool_validation", step.tool_call.name, "REJECTED", {"error": str(exc)})
                return ExecutionOutcome(ExecutionStatus.FAILED, "I could not validate that action.", tuple(results), tuple(events), observations=observations)

            # Authentication, permission, payment lock and exact consent are
            # evaluated before every tool, never only at plan creation.
            context = ToolSecurityContext(auth=auth, payment_lock=self.policy.payment_lock, consent_id=consent_id)
            try:
                decision = self.policy.evaluate(
                    tool_name=spec.name,
                    parameters=parameters,
                    risk_level=spec.risk_level,
                    required_permission=spec.required_permission,
                    context=context,
                    confirmation_required=spec.confirmation_required,
                )
            except PolicyDenied as exc:
                self._audit(auth.user_id, "policy_denied", spec.name, "DENIED", {"code": exc.code})
                return ExecutionOutcome(ExecutionStatus.FAILED, exc.user_message, tuple(results), tuple(events), observations=observations)

            if decision.requires_consent:
                record = self.consents.create(auth.user_id, spec.name, parameters, spec.risk_level, timeout_seconds=self._consent_timeout(spec))
                message = self._approval_message(spec, parameters)
                emit(ExecutionEvent("approval_required", spec.name, message, "AWAITING_APPROVAL"))
                self._audit(auth.user_id, "consent_requested", spec.name, "PENDING", {"risk": spec.risk_level.value})
                return ExecutionOutcome(ExecutionStatus.WAITING_APPROVAL, message, tuple(results), tuple(events), record.consent_id, observations)

            started = time.monotonic()
            emit(ExecutionEvent("tool_start", spec.name, step.purpose, "EXECUTING"))
            self._audit(auth.user_id, "tool_start", spec.name, "STARTED", {"risk": spec.risk_level.value})
            result = await self._run_tool(spec, parameters, user_id=auth.user_id, consent_id=consent_id, cancel_event=cancel_event)
            duration = int((time.monotonic() - started) * 1000)
            result = ToolResult(result.tool_name, result.success, result.output, result.error_code, result.user_message, result.retryable)
            emit(ExecutionEvent("tool_complete" if result.success else "tool_failure", spec.name, result.user_message or ("Complete." if result.success else "The tool failed."), "SUCCESS" if result.success else "ERROR", duration))
            results.append(result)
            if result.success:
                observations[step.step_id] = result.output
                if consent_id and spec.confirmation_required and spec.risk_level in {RiskLevel.SENSITIVE, RiskLevel.FINANCIAL, RiskLevel.DESTRUCTIVE}:
                    try:
                        self.consents.consume(consent_id, auth.user_id, spec.name, parameters)
                        consent_id = None
                    except ValueError:
                        return ExecutionOutcome(ExecutionStatus.FAILED, "Approval could not be consumed safely.", tuple(results), tuple(events), observations=observations)
            else:
                self._audit(auth.user_id, "tool_execution", spec.name, "FAILED", {"error_code": result.error_code or "TOOL_FAILED", "duration_ms": duration})
                if result.retryable and self.limits.max_retries:
                    retry = await self._retry(spec, parameters, auth.user_id, consent_id, cancel_event, emit)
                    results.append(retry)
                    if retry.success:
                        observations[step.step_id] = retry.output
                    else:
                        return ExecutionOutcome(ExecutionStatus.FAILED, retry.user_message or "The action could not be completed.", tuple(results), tuple(events), observations=observations)
                else:
                    return ExecutionOutcome(ExecutionStatus.FAILED, result.user_message or "The action could not be completed.", tuple(results), tuple(events), observations=observations)
            self._audit(auth.user_id, "tool_execution", spec.name, "SUCCESS" if result.success else "FAILED", {"duration_ms": duration, "risk": spec.risk_level.value})
            if result.success:
                completed_steps.add(step.step_id)

        return ExecutionOutcome(ExecutionStatus.COMPLETE, plan.response_hint or "Done.", tuple(results), tuple(events), observations=observations)

    async def _retry(self, spec: ToolSpec, parameters: Mapping[str, Any], user_id: str, consent_id: Optional[str], cancel_event: Optional[threading.Event], emit: Callable[[ExecutionEvent], None]) -> ToolResult:
        for attempt in range(1, self.limits.max_retries + 1):
            if self._cancelled(cancel_event):
                return ToolResult(spec.name, False, error_code="CANCELLED", user_message="Stopped.")
            emit(ExecutionEvent("tool_retry", spec.name, f"Retry {attempt}.", "RETRYING"))
            result = await self._run_tool(spec, parameters, user_id=user_id, consent_id=consent_id, cancel_event=cancel_event)
            if result.success:
                return result
        return result

    async def _run_tool(self, spec: ToolSpec, parameters: Mapping[str, Any], *, user_id: str = "", consent_id: Optional[str] = None, cancel_event: Optional[threading.Event]) -> ToolResult:
        if self._cancelled(cancel_event):
            return ToolResult(spec.name, False, error_code="CANCELLED", user_message="Stopped.")
        try:
            call_parameters = dict(parameters)
            # Internal identity is injected by the executor, never selected by
            # the model. Payment handlers use it for user-scoped persistence.
            try:
                signature = inspect.signature(spec.handler)
                if "user_id" in signature.parameters:
                    call_parameters["user_id"] = user_id
                if "approval_reference" in signature.parameters:
                    call_parameters["approval_reference"] = consent_id
            except (TypeError, ValueError):
                pass
            if inspect.iscoroutinefunction(spec.handler):
                value = await asyncio.wait_for(spec.handler(**call_parameters), timeout=spec.timeout_seconds or self.limits.default_timeout_seconds)
            else:
                value = await asyncio.wait_for(asyncio.to_thread(spec.handler, **call_parameters), timeout=spec.timeout_seconds or self.limits.default_timeout_seconds)
            if isinstance(value, ToolResult):
                return ToolResult(value.tool_name, value.success, safe_metadata(value.output), value.error_code, value.user_message, value.retryable)
            return ToolResult(spec.name, True, safe_metadata(value), user_message="Complete.")
        except asyncio.TimeoutError:
            return ToolResult(spec.name, False, error_code="TIMEOUT", user_message="That action timed out.", retryable=True)
        except asyncio.CancelledError:
            return ToolResult(spec.name, False, error_code="CANCELLED", user_message="Stopped.")
        except Exception:
            return ToolResult(spec.name, False, error_code="TOOL_ERROR", user_message="The requested action was unavailable.")

    @staticmethod
    def _resolve(value: Any, observations: Mapping[str, Any]) -> Any:
        if isinstance(value, str) and value.startswith("$"):
            expression = value[1:].split(".")
            current: Any = observations.get(expression[0])
            for key in expression[1:]:
                if isinstance(current, Mapping):
                    current = current.get(key)
                else:
                    current = None
            return current if current is not None else value
        if isinstance(value, Mapping):
            return {key: Executor._resolve(item, observations) for key, item in value.items()}
        if isinstance(value, list):
            return [Executor._resolve(item, observations) for item in value]
        return value

    def _consent_timeout(self, spec: ToolSpec) -> int:
        return 120 if spec.risk_level == RiskLevel.FINANCIAL else 300

    @staticmethod
    def _approval_message(spec: ToolSpec, parameters: Mapping[str, Any]) -> str:
        if spec.risk_level == RiskLevel.FINANCIAL:
            amount = parameters.get("amount_minor")
            currency = parameters.get("currency", "INR")
            description = parameters.get("description", "the requested purpose")
            if isinstance(amount, int):
                amount_text = f"₹{amount / 100:,.2f}"
            else:
                amount_text = "the specified amount"
            return f"You are about to run {spec.name.replace('_', ' ')} for {amount_text} {currency} for {description}. Continue?"
        return f"Approval required for {spec.name.replace('_', ' ')}. Continue?"

    @staticmethod
    def _cancelled(event: Optional[threading.Event]) -> bool:
        return bool(event and event.is_set())

    def _audit(self, user_id: str, action: str, resource: str, outcome: str, metadata: Mapping[str, Any]) -> None:
        if self.audit:
            try:
                self.audit.append(user_id=user_id, action=action, resource_ref=resource, outcome=outcome, metadata=metadata)
            except Exception:
                # Audit failure must not turn into secret-bearing UI output.  A
                # production deployment may choose fail-closed for critical tools.
                pass
