"""Provider-neutral conversational compatibility function."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from .AI.provider_registry import ProviderRouter, registry_from_settings
from .config import load_settings
from .Persistence.legacy_chatlog import LegacyChatLog
from .Security.privacy import redact_sensitive


def AnswerModifier(answer: str) -> str:
    return "\n".join(line.strip() for line in str(answer).splitlines() if line.strip())


def _service() -> tuple[ProviderRouter, LegacyChatLog, object]:
    settings = load_settings()
    return ProviderRouter(registry_from_settings(settings), preferred=settings.llm_provider), LegacyChatLog(settings.data_dir / "ChatLog.json"), settings


def ChatBot(Query: str) -> str:
    if not isinstance(Query, str) or not Query.strip():
        return "Please tell me what you need."
    safe = redact_sensitive(Query)
    if safe.redacted:
        return "Aura does not retain payment credentials. Use the secure payment interface instead."
    router, history, settings = _service()
    records = history.read()
    context = records[-12:]
    history.append("user", safe.text)
    try:
        provider = router.provider_for()
        response = provider.generate(safe.text, context=context)
        answer = AnswerModifier(response.text)
    except Exception:
        answer = "I am ready, but an AI provider is not configured yet."
    history.append("assistant", answer)
    return answer


if __name__ == "__main__":
    while True:
        print(ChatBot(input("Enter Your Question: ")))
