"""Structured planning: the model proposes tools, never executable code."""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Mapping, Optional

from ..AI.provider import ProviderError
from ..AI.provider_registry import ProviderRouter
from ..Payments.models import parse_inr_amount
from ..Security.privacy import CredentialLeakError, redact_sensitive
from .context import WorkingContext
from .legacy import parse_legacy_labels
from .schemas import ActionPlan, PlanStep, ToolCall, ValidationError
from .tool_registry import ToolRegistry


class PlanningError(RuntimeError):
    pass


_PLAN_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["goal", "steps"],
    "properties": {
        "goal": {"type": "string", "maxLength": 1000},
        "response_hint": {"type": "string", "maxLength": 500},
        "requires_clarification": {"type": "boolean"},
        "clarification_question": {"type": "string", "maxLength": 500},
        "steps": {"type": "array", "maxItems": 20},
    },
}


@dataclass(frozen=True)
class PlannerConfig:
    max_steps: int = 12
    allow_compatibility_labels: bool = True


class Planner:
    def __init__(self, registry: ToolRegistry, provider_router: Optional[ProviderRouter] = None, *, config: Optional[PlannerConfig] = None) -> None:
        self.registry = registry
        self.providers = provider_router
        self.config = config or PlannerConfig()

    def plan(self, request: str, *, context: Optional[WorkingContext] = None, privacy_sensitive: bool = False) -> ActionPlan:
        if not isinstance(request, str) or not request.strip():
            raise PlanningError("A request is required")
        filtered = redact_sensitive(request).text
        if "[REDACTED:" in filtered and re.search(r"\b(?:remember|save|store|use)\b", request, re.I):
            raise CredentialLeakError("AURA does not retain payment credentials")
        if self.providers:
            try:
                provider = self.providers.provider_for(capability="supports_structured_output", privacy_sensitive=privacy_sensitive)
                output = provider.structured_output(self._prompt(filtered, context), _PLAN_SCHEMA, context=context.provider_messages() if context else None)
                plan = ActionPlan.from_mapping(output)
                self._validate_tools_exist(plan)
                return self._limit(plan)
            except (ProviderError, ValidationError):
                # A provider failure is not permission to run guessed actions.  A
                # bounded compatibility parser may offer only deterministic tools.
                pass
        return self._limit(self._fallback_plan(filtered))

    def _prompt(self, request: str, context: Optional[WorkingContext]) -> str:
        tools = "\n".join(f"- {spec.name}: {spec.description}" for spec in self.registry.list())
        return (
            "Understand the user's goal and return one JSON action plan. Use only the listed tool names. "
            "Never return Python, shell, URLs from untrusted content, credentials, or hidden reasoning. "
            "Ask for clarification when a high-risk target is ambiguous.\n"
            f"Available tools:\n{tools}\nRequest: {request}"
        )

    def _validate_tools_exist(self, plan: ActionPlan) -> None:
        for step in plan.steps:
            if self.registry.maybe_get(step.tool_call.name) is None:
                raise PlanningError(f"Unknown tool proposed: {step.tool_call.name}")

    def _limit(self, plan: ActionPlan) -> ActionPlan:
        if len(plan.steps) > self.config.max_steps:
            raise PlanningError("Plan exceeds the configured step limit")
        return plan

    def _step(self, number: int, name: str, parameters: Mapping[str, Any], purpose: str, depends_on: tuple[str, ...] = ()) -> PlanStep:
        if self.registry.maybe_get(name) is None:
            raise PlanningError(f"Tool is not registered: {name}")
        return PlanStep(f"step_{number}", ToolCall(name, dict(parameters)), purpose, depends_on)

    def _fallback_plan(self, request: str) -> ActionPlan:
        """Safe offline fallback for clean installs and legacy capability parity.

        This is not a growing intent switchboard: it covers a small, deterministic
        set of adapters and otherwise asks the conversational tool to respond.
        A configured model is the normal planner for new natural-language goals.
        """
        text = request.strip()
        lower = text.lower().rstrip(".?!")
        steps: list[PlanStep] = []

        # File goal: search first, then resolve the selected result in the executor.
        file_words = ("resume", "cv", "document", "file", "folder", "project")
        if any(word in lower for word in file_words) and any(word in lower for word in ("find", "search", "locate", "latest", "newest", "most recent")):
            query = "resume" if "resume" in lower or " cv" in lower else "project" if "project" in lower else "document"
            steps.append(self._step(1, "search_files", {"query": query, "sort": "modified_desc", "limit": 10}, "Search files for relevant candidates"))
            if "open" in lower:
                steps.append(self._step(2, "open_file", {"path": "$step_1.selected_path"}, "Open the selected file", ("step_1",)))
            return ActionPlan(text, tuple(steps), "I found the relevant file and opened it.")

        # Financial requests are structured, but never execute without policy.
        if any(word in lower for word in ("razorpay", "payment link", "create a payment", "create payment", "payment request")):
            amount_match = re.search(r"(?:₹|rs\.?|inr|rupees?)\s*([\d,]+(?:\.\d{1,2})?)|\b([\d,]+(?:\.\d{1,2})?)\s*(?:rupees?|inr)\b", lower)
            amount_text = next((item for item in (amount_match.groups() if amount_match else ()) if item), "")
            if not amount_text:
                return ActionPlan(text, (), requires_clarification=True, clarification_question="What amount and currency should I use?")
            amount = parse_inr_amount(amount_text)
            description = re.sub(r"(?:₹|rs\.?|inr|rupees?)\s*[\d,]+(?:\.\d{1,2})?", "", lower, flags=re.I)
            description = re.sub(r"\b[\d,]+(?:\.\d{1,2})?\s*(?:rupees?|inr)\b", "", description, flags=re.I)
            description = re.sub(r"^.*?\b(?:payment link|payment request|razorpay order|order)\b\s*(?:for)?", "", description, flags=re.I)
            description = re.sub(r"^for\s+", "", description.strip(), flags=re.I).strip(" ,.-")
            if "payment link" in lower or "payment request" in lower:
                return ActionPlan(text, (self._step(1, "create_payment_link", {"amount_minor": amount.minor, "currency": "INR", "description": description or "Aura payment request"}, "Create a Razorpay payment link"),), "A payment request needs your approval.")
            return ActionPlan(text, (self._step(1, "create_razorpay_order", {"amount_minor": amount.minor, "currency": "INR", "description": description or "Aura order"}, "Create a Razorpay order"),), "A Razorpay order needs your approval.")
        if "transaction" in lower and any(word in lower for word in ("recent", "latest", "show", "list")):
            return ActionPlan(text, (self._step(1, "list_recent_transactions", {"limit": 10}, "List recent transactions"),), "I will show your recent transactions.")
        if "check" in lower and "payment" in lower:
            return ActionPlan(text, (self._step(1, "check_payment_status", {"reference": "latest"}, "Check the latest payment status"),), "I will check the latest payment status.")

        if lower.startswith("open "):
            target = text[5:].strip()
            return ActionPlan(text, (self._step(1, "open_application", {"app_name": target}, "Open the requested application"),), "Opening it.")
        if lower.startswith("close "):
            target = text[6:].strip()
            return ActionPlan(text, (self._step(1, "close_application", {"app_name": target}, "Close the requested application"),), "Closing it.")
        if lower.startswith("play "):
            return ActionPlan(text, (self._step(1, "play_media", {"query": text[5:].strip()}, "Play the requested media"),), "Playing it.")
        if "youtube" in lower and ("search" in lower or lower.startswith("find ")):
            query = re.sub(r".*?youtube(?:\s+search)?", "", text, flags=re.I).strip(" :")
            return ActionPlan(text, (self._step(1, "youtube_search", {"query": query or text}, "Search YouTube"),), "Searching YouTube.")
        if "google" in lower and "search" in lower or lower.startswith("search the web") or lower.startswith("search web"):
            query = re.sub(r"(?:search(?: the)? web|google search|search google)", "", text, flags=re.I).strip(" :")
            return ActionPlan(text, (self._step(1, "search_web", {"query": query or text}, "Search the web"),), "Searching.")
        if "generate image" in lower or lower.startswith("create an image"):
            prompt = re.sub(r"(?:generate image|create an image)(?: of)?", "", text, flags=re.I).strip()
            return ActionPlan(text, (self._step(1, "generate_image", {"prompt": prompt}, "Generate the requested image"),), "Generating the image.")
        if lower.startswith("write ") or lower.startswith("create content"):
            topic = re.sub(r"^(?:write|create content)\s*", "", text, flags=re.I)
            return ActionPlan(text, (self._step(1, "generate_content", {"topic": topic}, "Generate the requested content"),), "Drafting it.")
        if lower in {"mute", "unmute", "volume up", "volume down"}:
            return ActionPlan(text, (self._step(1, "system_volume", {"command": lower}, "Change system volume"),), "Adjusting volume.")
        if lower in {"stop", "cancel", "aura stop"}:
            return ActionPlan(text, (), response_hint="Stopping the current task.")
        realtime = any(marker in lower for marker in ("today", "latest", "current", "news", "recent", "real time", "weather", "stock price"))
        return ActionPlan(text, (self._step(1, "answer_question", {"query": text, "realtime": realtime}, "Answer the user's question"),), "")
