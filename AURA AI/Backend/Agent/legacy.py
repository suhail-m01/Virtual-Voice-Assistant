"""Compatibility translation for Aura 2024 command labels.

It is intentionally an adapter at the edge.  New routing is based on structured
plans and tool names; this module only keeps old integrations working while they
are migrated.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable

from .schemas import ActionPlan, PlanStep, ToolCall


@dataclass(frozen=True)
class LegacyCommand:
    label: str
    value: str = ""


def parse_legacy_labels(labels: Iterable[str]) -> ActionPlan:
    steps: list[PlanStep] = []
    general: list[str] = []
    realtime: list[str] = []
    for index, raw in enumerate(labels):
        item = str(raw).strip()
        if not item:
            continue
        label, _, value = item.partition(" ")
        value = value.strip()
        mapping = {
            "open": "open_application",
            "close": "close_application",
            "play": "play_media",
            "system": "system_volume",
            "content": "generate_content",
            "google": "google_search",
            "youtube": "youtube_search",
            "generate": "generate_image",
        }
        if label in {"general", "realtime"}:
            (general if label == "general" else realtime).append(value)
            continue
        if item.startswith("google search "):
            steps.append(PlanStep(f"step_{index + 1}", ToolCall("google_search", {"query": item[len("google search "):].strip()}), "Search Google"))
        elif item.startswith("youtube search "):
            steps.append(PlanStep(f"step_{index + 1}", ToolCall("youtube_search", {"query": item[len("youtube search "):].strip()}), "Search YouTube"))
        elif label in mapping:
            tool = mapping[label]
            parameter = {"app_name": value} if tool in {"open_application", "close_application"} else {"query": value}
            if tool == "system_volume":
                parameter = {"command": value}
            if tool == "generate_content":
                parameter = {"topic": value}
            if tool == "generate_image":
                parameter = {"prompt": value.replace("image", "", 1).strip()}
            if value:
                steps.append(PlanStep(f"step_{index + 1}", ToolCall(tool, parameter), f"Compatibility action: {item}"))
    if general or realtime:
        text = " and ".join(general + realtime)
        steps.append(PlanStep(f"step_{len(steps) + 1}", ToolCall("answer_question", {"query": text, "realtime": bool(realtime)}), "Answer the question"))
    goal = ", ".join(str(item) for item in labels) or "legacy request"
    return ActionPlan(goal, tuple(steps), response_hint="Legacy command adapter")
