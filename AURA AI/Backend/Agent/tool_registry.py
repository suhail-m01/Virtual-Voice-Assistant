"""Deterministic tool registry and strict parameter validation."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import inspect
from typing import Any, Callable, Mapping, Optional

from ..Security.consent import RiskLevel
from ..Security.privacy import redact_sensitive


class ToolRisk(str, Enum):
    LOW = RiskLevel.LOW.value
    SENSITIVE = RiskLevel.SENSITIVE.value
    FINANCIAL = RiskLevel.FINANCIAL.value
    DESTRUCTIVE = RiskLevel.DESTRUCTIVE.value


class ToolValidationError(ValueError):
    pass


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameter_schema: Mapping[str, Any]
    risk_level: RiskLevel
    required_permission: Optional[str]
    confirmation_required: bool
    timeout_seconds: int
    result_schema: Mapping[str, Any]
    handler: Callable[..., Any]

    def __post_init__(self) -> None:
        # Accept the registry-facing ToolRisk enum while normalizing to the
        # security-layer RiskLevel before policy comparisons.
        if not isinstance(self.risk_level, RiskLevel):
            object.__setattr__(self, "risk_level", RiskLevel(str(getattr(self.risk_level, "value", self.risk_level))))

    def validate_parameters(self, parameters: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(parameters, Mapping):
            raise ToolValidationError(f"Parameters for {self.name} must be an object")
        def contains_credential(value: Any) -> bool:
            if isinstance(value, str):
                return redact_sensitive(value).redacted
            if isinstance(value, Mapping):
                return any(contains_credential(item) for item in value.values())
            if isinstance(value, list):
                return any(contains_credential(item) for item in value)
            return False

        if contains_credential(parameters):
            raise ToolValidationError(f"Sensitive credential input is not accepted by {self.name}")
        properties = self.parameter_schema.get("properties", {})
        required = self.parameter_schema.get("required", [])
        unknown = set(parameters) - set(properties)
        if unknown:
            raise ToolValidationError(f"Unknown parameters for {self.name}: {sorted(unknown)}")
        missing = [item for item in required if item not in parameters]
        if missing:
            raise ToolValidationError(f"Missing parameters for {self.name}: {missing}")
        for key, schema in properties.items():
            if key not in parameters:
                continue
            value = parameters[key]
            kind = schema.get("type")
            valid = {
                "string": isinstance(value, str),
                "integer": isinstance(value, int) and not isinstance(value, bool),
                "number": isinstance(value, (int, float)) and not isinstance(value, bool),
                "boolean": isinstance(value, bool),
                "array": isinstance(value, list),
                "object": isinstance(value, Mapping),
            }.get(kind, True)
            if not valid:
                raise ToolValidationError(f"Parameter {key} for {self.name} has invalid type")
            if isinstance(value, str) and len(value) > int(schema.get("maxLength", 2000)):
                raise ToolValidationError(f"Parameter {key} for {self.name} is too long")
            if "enum" in schema and value not in schema["enum"]:
                raise ToolValidationError(f"Parameter {key} for {self.name} is not allowed")
        return dict(parameters)

    @property
    def permission(self) -> Optional[str]:
        return self.required_permission

    @property
    def requires_confirmation(self) -> bool:
        return self.confirmation_required

    def public_schema(self) -> dict[str, Any]:
        return {"name": self.name, "description": self.description, "parameters": dict(self.parameter_schema)}


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        if not spec.name or spec.name != spec.name.lower() or " " in spec.name:
            raise ValueError("Tool names must be lowercase snake_case")
        if spec.timeout_seconds <= 0 or spec.timeout_seconds > 600:
            raise ValueError("Tool timeout must be between 1 and 600 seconds")
        if spec.name in self._tools:
            raise ValueError(f"Tool already registered: {spec.name}")
        self._tools[spec.name] = spec

    def get(self, name: str) -> ToolSpec:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise ToolValidationError(f"Unknown tool: {name}") from exc

    def maybe_get(self, name: str) -> Optional[ToolSpec]:
        return self._tools.get(name)

    def list(self) -> tuple[ToolSpec, ...]:
        return tuple(self._tools.values())

    def schemas(self) -> list[dict[str, Any]]:
        return [spec.public_schema() for spec in self._tools.values()]

    def validate_call(self, name: str, parameters: Mapping[str, Any]) -> tuple[ToolSpec, dict[str, Any]]:
        spec = self.get(name)
        return spec, spec.validate_parameters(parameters)
