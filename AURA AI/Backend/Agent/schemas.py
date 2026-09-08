"""Strict, provider-independent agent schemas.

This is a small Pydantic-equivalent validation layer so malformed model output is
rejected even when Pydantic is not installed.  All external values are treated as
untrusted.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import json
import re
from typing import Any, Mapping, Optional


class ValidationError(ValueError):
    pass


_NAME = re.compile(r"^[a-z][a-z0-9_]{1,63}$")


def _string(value: Any, field_name: str, *, maximum: int = 2000, required: bool = True) -> str:
    if not isinstance(value, str) or (required and not value.strip()) or len(value) > maximum:
        raise ValidationError(f"{field_name} must be a non-empty string under {maximum} characters")
    return value.strip()


@dataclass(frozen=True)
class ToolCall:
    name: str
    parameters: Mapping[str, Any] = field(default_factory=dict)
    call_id: str = ""

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "ToolCall":
        if not isinstance(value, Mapping):
            raise ValidationError("tool_call must be an object")
        allowed = {"name", "parameters", "arguments", "call_id", "id"}
        unknown = set(value) - allowed
        if unknown:
            raise ValidationError(f"unknown tool_call fields: {sorted(unknown)}")
        name = _string(value.get("name"), "tool name", maximum=64)
        if not _NAME.fullmatch(name):
            raise ValidationError("tool name contains invalid characters")
        parameters = value.get("parameters", value.get("arguments", {}))
        if not isinstance(parameters, Mapping):
            raise ValidationError("tool parameters must be an object")
        return cls(name, dict(parameters), str(value.get("call_id", value.get("id", ""))))


@dataclass(frozen=True)
class PlanStep:
    step_id: str
    tool_call: ToolCall
    purpose: str
    depends_on: tuple[str, ...] = ()

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any], index: int = 0) -> "PlanStep":
        if not isinstance(value, Mapping):
            raise ValidationError("plan step must be an object")
        allowed = {"step_id", "id", "tool", "tool_call", "purpose", "depends_on"}
        unknown = set(value) - allowed
        if unknown:
            raise ValidationError(f"unknown plan step fields: {sorted(unknown)}")
        raw_call = value.get("tool_call", value.get("tool"))
        if isinstance(raw_call, str):
            raw_call = {"name": raw_call, "parameters": {}}
        call = ToolCall.from_mapping(raw_call)
        step_id = _string(value.get("step_id", value.get("id", f"step_{index + 1}")), "step_id", maximum=64)
        purpose = _string(value.get("purpose", f"Execute {call.name}"), "purpose", maximum=300)
        dependencies = value.get("depends_on", ())
        if not isinstance(dependencies, (list, tuple)) or any(not isinstance(item, str) for item in dependencies):
            raise ValidationError("depends_on must be a list of step ids")
        return cls(step_id, call, purpose, tuple(dependencies))


@dataclass(frozen=True)
class ActionPlan:
    goal: str
    steps: tuple[PlanStep, ...]
    response_hint: str = ""
    requires_clarification: bool = False
    clarification_question: str = ""

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "ActionPlan":
        if not isinstance(value, Mapping):
            raise ValidationError("plan must be an object")
        allowed = {"goal", "steps", "response_hint", "requires_clarification", "clarification_question"}
        unknown = set(value) - allowed
        if unknown:
            raise ValidationError(f"unknown plan fields: {sorted(unknown)}")
        goal = _string(value.get("goal"), "goal", maximum=1000)
        raw_steps = value.get("steps", [])
        if not isinstance(raw_steps, list) or len(raw_steps) > 20:
            raise ValidationError("steps must be a list of at most 20 items")
        steps = tuple(PlanStep.from_mapping(step, i) for i, step in enumerate(raw_steps))
        ids = [step.step_id for step in steps]
        if len(ids) != len(set(ids)):
            raise ValidationError("step ids must be unique")
        valid_ids = set(ids)
        for step in steps:
            if any(dep not in valid_ids for dep in step.depends_on):
                raise ValidationError("step dependency is unknown")
            if step.step_id in step.depends_on:
                raise ValidationError("step cannot depend on itself")
        raw_clarify = value.get("requires_clarification", False)
        if not isinstance(raw_clarify, bool):
            raise ValidationError("requires_clarification must be a boolean")
        clarify = raw_clarify
        raw_question = value.get("clarification_question", "")
        if not isinstance(raw_question, str):
            raise ValidationError("clarification_question must be a string")
        question = raw_question
        if clarify and not question.strip():
            raise ValidationError("clarification_question is required")
        return cls(goal, steps, str(value.get("response_hint", ""))[:500], clarify, question[:500])

    @classmethod
    def from_json(cls, raw: str) -> "ActionPlan":
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValidationError("plan is not valid JSON") from exc
        return cls.from_mapping(value)


@dataclass(frozen=True)
class ToolResult:
    tool_name: str
    success: bool
    output: Any = None
    error_code: Optional[str] = None
    user_message: str = ""
    retryable: bool = False


@dataclass(frozen=True)
class AgentTask:
    user_id: str
    text: str
    conversation_id: str = ""
    consent_id: Optional[str] = None
