"""Legacy FirstLayerDMM facade backed by the structured Aura planner.

Existing callers still receive the historical labels, but the modern agent uses
Planner/ActionPlan directly and does not route by these strings.
"""
from __future__ import annotations

from typing import Iterable

from .config import load_settings
from .AI.provider_registry import ProviderRouter, registry_from_settings
from .Agent.planner import Planner, PlanningError
from .Tools.builtins import build_default_registry


def _plan_to_legacy(plan) -> list[str]:
    labels: list[str] = []
    for step in plan.steps:
        call = step.tool_call
        params = call.parameters
        if call.name == "answer_question":
            labels.append(("realtime " if params.get("realtime") else "general ") + str(params.get("query", "")).strip())
        elif call.name == "open_application":
            labels.append("open " + str(params.get("app_name", "")))
        elif call.name == "close_application":
            labels.append("close " + str(params.get("app_name", "")))
        elif call.name == "play_media":
            labels.append("play " + str(params.get("query", "")))
        elif call.name == "generate_image":
            labels.append("generate image " + str(params.get("prompt", "")))
        elif call.name == "generate_content":
            labels.append("content " + str(params.get("topic", "")))
        elif call.name in {"google_search", "search_web"}:
            labels.append("google search " + str(params.get("query", "")))
        elif call.name == "youtube_search":
            labels.append("youtube search " + str(params.get("query", "")))
        elif call.name == "system_volume":
            labels.append("system " + str(params.get("command", "")))
    return labels or ["general " + plan.goal]


def FirstLayerDMM(prompt: str = "test") -> list[str]:
    settings = load_settings()
    registry = build_default_registry(settings)
    router = ProviderRouter(registry_from_settings(settings), preferred=settings.llm_provider)
    planner = Planner(registry, router)
    try:
        return _plan_to_legacy(planner.plan(prompt))
    except PlanningError:
        return ["general " + str(prompt).strip()]


if __name__ == "__main__":
    while True:
        print(FirstLayerDMM(input(">>> ")))
