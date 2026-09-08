"""Cohere compatibility adapter for Aura 2024 installations."""
from __future__ import annotations

import json
from typing import Iterable, Mapping, Optional

from ..provider import AIProvider, ProviderCapabilities, ProviderError, ProviderResponse


class CohereProvider(AIProvider):
    name = "cohere"
    capabilities = ProviderCapabilities(supports_tools=False, supports_structured_output=False, supports_streaming=True)

    def __init__(self, api_key: str, default_model: str = "command-r-plus") -> None:
        if not api_key:
            raise ValueError("Cohere API key is required")
        self.api_key = api_key
        self.default_model = default_model

    def _client(self):
        try:
            import cohere
        except ImportError as exc:  # pragma: no cover
            raise ProviderError("Cohere SDK is not installed") from exc
        return cohere.Client(api_key=self.api_key)

    def generate(self, prompt: str, *, context: Optional[Iterable[Mapping[str, str]]] = None, model: Optional[str] = None, temperature: float = 0.2) -> ProviderResponse:
        try:
            history = [{"role": item.get("role", "user"), "message": item.get("content", "")} for item in (context or [])]
            result = self._client().chat(model=model or self.default_model, message=prompt, chat_history=history, temperature=temperature)
            text = getattr(result, "text", "") or ""
            return ProviderResponse(text, self.name, model or self.default_model, result)
        except Exception as exc:
            raise ProviderError("AI provider request failed") from exc

    def stream(self, prompt: str, *, context: Optional[Iterable[Mapping[str, str]]] = None, model: Optional[str] = None, temperature: float = 0.2):
        # Cohere's installed SDK versions expose different stream event shapes;
        # normalize only text events and keep the compatibility path bounded.
        try:
            stream = self._client().chat_stream(model=model or self.default_model, message=prompt, temperature=temperature)
            for event in stream:
                text = getattr(event, "text", None)
                if text:
                    yield text
        except Exception as exc:
            raise ProviderError("AI provider streaming request failed") from exc
