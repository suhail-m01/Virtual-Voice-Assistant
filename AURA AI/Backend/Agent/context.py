"""Bounded user-scoped context selection."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Mapping, Optional

from ..Persistence.memory import MemoryRepository
from ..Security.privacy import redact_sensitive


@dataclass(frozen=True)
class WorkingContext:
    user_id: str
    conversation_id: str = ""
    recent_messages: tuple[Mapping[str, str], ...] = ()
    approved_memories: tuple[str, ...] = ()
    task_facts: Mapping[str, str] = field(default_factory=dict)

    def provider_messages(self, *, max_items: int = 12) -> list[dict[str, str]]:
        messages = []
        for item in self.recent_messages[-max_items:]:
            text = redact_sensitive(str(item.get("content", ""))).text
            messages.append({"role": str(item.get("role", "user")), "content": text})
        if self.approved_memories:
            messages.insert(0, {"role": "system", "content": "User-approved context:\n" + "\n".join(self.approved_memories[:8])})
        return messages


class ContextBuilder:
    def __init__(self, memory: Optional[MemoryRepository] = None) -> None:
        self.memory = memory

    def build(self, user_id: str, *, conversation_id: str = "", recent_messages: Iterable[Mapping[str, str]] = (), task_facts: Optional[Mapping[str, str]] = None) -> WorkingContext:
        approved = tuple(self.memory.approved_context(user_id, limit=8)) if self.memory else ()
        # Do not pass the complete legacy transcript to the provider.
        bounded = tuple({"role": str(item.get("role", "user")), "content": redact_sensitive(str(item.get("content", ""))).text} for item in list(recent_messages)[-12:])
        return WorkingContext(user_id, conversation_id, bounded, approved, dict(task_facts or {}))
