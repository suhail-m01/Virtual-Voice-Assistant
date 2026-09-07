"""Aura agent facade: input -> context -> plan -> guarded tools -> response."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import threading
import uuid
from typing import Any, Callable, Mapping, Optional

from ..Auth.models import AuthContext
from ..Security.consent import ConsentManager, ConsentStatus, is_explicit_approval
from ..Security.privacy import CredentialLeakError, redact_sensitive
from .context import ContextBuilder, WorkingContext
from .executor import ExecutionEvent, ExecutionLimits, ExecutionOutcome, ExecutionStatus, Executor
from .planner import Planner, PlanningError
from .schemas import ActionPlan


@dataclass(frozen=True)
class AgentResponse:
    status: ExecutionStatus
    message: str
    plan_goal: str = ""
    consent_id: Optional[str] = None
    events: tuple[ExecutionEvent, ...] = ()
    observations: Mapping[str, Any] = field(default_factory=dict)

    @property
    def awaiting_approval(self) -> bool:
        return self.status == ExecutionStatus.WAITING_APPROVAL


class AuraAgent:
    def __init__(self, planner: Planner, executor: Executor, consent_manager: ConsentManager, *, context_builder: Optional[ContextBuilder] = None, limits: Optional[ExecutionLimits] = None) -> None:
        self.planner = planner
        self.executor = executor
        self.consents = consent_manager
        self.context_builder = context_builder or ContextBuilder()
        self.limits = limits or executor.limits
        self._pending: dict[str, tuple[str, AuthContext, ActionPlan, Mapping[str, Any]]] = {}
        self._cancel_events: dict[str, threading.Event] = {}
        self._lock = threading.RLock()

    async def handle_async(self, text: str, *, auth: AuthContext, conversation_id: str = "", recent_messages=(), on_event: Optional[Callable[[ExecutionEvent], None]] = None) -> AgentResponse:
        if not auth.authenticated:
            return AgentResponse(ExecutionStatus.FAILED, "Authentication required.")
        if not isinstance(text, str) or not text.strip():
            return AgentResponse(ExecutionStatus.NEEDS_CLARIFICATION, "What would you like Aura to do?")
        redaction = redact_sensitive(text)
        if redaction.redacted:
            # Do not pass raw credential-bearing input to planner, provider, logs,
            # or memory. The user gets a concise safety response.
            return AgentResponse(ExecutionStatus.FAILED, "Aura does not retain payment credentials. Use the secure payment screen instead.")

        normalized = text.lower().strip().rstrip(".!?")
        if normalized in {"stop", "aura stop", "stop aura", "cancel", "cancel that"}:
            stopped = self.stop(auth.user_id)
            pending_id = self._pending_for_user(auth.user_id)
            if pending_id:
                self._pending.pop(pending_id, None)
                stopped = True
            return AgentResponse(ExecutionStatus.CANCELLED, "Stopped." if stopped else "There is no active Aura task.")

        # Approval is a separate state machine. It is only interpreted against the
        # exact currently active consent object for this user.
        pending_id = self._pending_for_user(auth.user_id)
        if pending_id:
            record = self.consents.get(pending_id)
            if record and record.status == ConsentStatus.PENDING:
                if is_explicit_approval(text, active_action=record.action):
                    pending = self._pending.get(pending_id)
                    if pending:
                        try:
                            self.consents.approve(pending_id, auth.user_id, record.action, self._first_parameters(pending[2], record.action, pending[3]))
                        except ValueError:
                            return AgentResponse(ExecutionStatus.FAILED, "Approval did not match the proposed action.", consent_id=pending_id)
                        return await self._resume_pending(pending_id, pending, on_event)
                if "cancel" in text.lower() or text.lower().strip() in {"no", "stop", "deny"}:
                    self._pending.pop(pending_id, None)
                    return AgentResponse(ExecutionStatus.CANCELLED, "Cancelled.", consent_id=pending_id)
                return AgentResponse(ExecutionStatus.WAITING_APPROVAL, "Approval required for the active action. Say approve or cancel.", consent_id=pending_id)

        try:
            context = self.context_builder.build(auth.user_id, conversation_id=conversation_id, recent_messages=recent_messages)
            plan = self.planner.plan(text, context=context)
        except CredentialLeakError:
            return AgentResponse(ExecutionStatus.FAILED, "Aura does not retain payment credentials.")
        except PlanningError:
            return AgentResponse(ExecutionStatus.FAILED, "I could not create a safe plan for that request.")

        cancel_event = threading.Event()
        with self._lock:
            self._cancel_events[auth.user_id] = cancel_event
        outcome = await self.executor.execute(plan, auth=auth, cancel_event=cancel_event, on_event=on_event)
        if outcome.status == ExecutionStatus.WAITING_APPROVAL and outcome.consent_id:
            with self._lock:
                self._pending[outcome.consent_id] = (auth.user_id, auth, plan, outcome.observations)
        with self._lock:
            self._cancel_events.pop(auth.user_id, None)
        return AgentResponse(outcome.status, outcome.message, plan.goal, outcome.consent_id, outcome.events, outcome.observations)

    def handle(self, text: str, *, auth: AuthContext, conversation_id: str = "", recent_messages=(), on_event: Optional[Callable[[ExecutionEvent], None]] = None) -> AgentResponse:
        return asyncio.run(self.handle_async(text, auth=auth, conversation_id=conversation_id, recent_messages=recent_messages, on_event=on_event))

    async def _resume_pending(self, consent_id: str, pending: tuple[str, AuthContext, ActionPlan, Mapping[str, Any]], on_event: Optional[Callable[[ExecutionEvent], None]]) -> AgentResponse:
        user_id, auth, plan, _observations = pending
        self._pending.pop(consent_id, None)
        outcome = await self.executor.execute(plan, auth=auth, consent_id=consent_id, cancel_event=threading.Event(), on_event=on_event)
        return AgentResponse(outcome.status, outcome.message, plan.goal, outcome.consent_id, outcome.events, outcome.observations)

    def stop(self, user_id: str) -> bool:
        with self._lock:
            event = self._cancel_events.get(user_id)
            if event:
                event.set()
                return True
            return False

    def pending_consent(self, user_id: str):
        with self._lock:
            consent_id = self._pending_for_user(user_id)
        return self.consents.get(consent_id) if consent_id else None

    def _pending_for_user(self, user_id: str) -> Optional[str]:
        with self._lock:
            for consent_id, value in self._pending.items():
                if value[0] == user_id:
                    return consent_id
        return None

    def _first_parameters(self, plan: ActionPlan, action: str, observations: Optional[Mapping[str, Any]] = None) -> Mapping[str, Any]:
        for step in plan.steps:
            if step.tool_call.name == action:
                return self.executor._resolve(step.tool_call.parameters, observations or {})
        return {}
