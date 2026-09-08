"""Compatibility adapter for Aura 2024's JSON chat history.

New agent calls should use MemoryRepository.  This adapter exists so existing
Chatbot/RealtimeSearchEngine entry points remain operational during migration.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..Security.privacy import redact_sensitive


class LegacyChatLog:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def read(self) -> list[dict[str, str]]:
        try:
            with self.path.open("r", encoding="utf-8") as handle:
                value = json.load(handle)
            return value if isinstance(value, list) else []
        except (OSError, ValueError):
            return []

    def append(self, role: str, content: str) -> None:
        if role not in {"user", "assistant", "system"}:
            raise ValueError("unsupported role")
        safe = redact_sensitive(content)
        # Never write a raw sensitive credential to the compatibility file.
        history = self.read()
        history.append({"role": role, "content": safe.text})
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(history[-200:], handle, indent=2, ensure_ascii=False)
        temporary.replace(self.path)

    def clear(self) -> None:
        self.path.write_text("[]", encoding="utf-8")
