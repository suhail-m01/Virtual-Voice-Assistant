"""Groq adapter; importing the SDK and using the key is deferred until call time."""
from __future__ import annotations

import json
from typing import Iterable, Mapping, Optional

from ..provider import AIProvider, ProviderCapabilities, ProviderError, ProviderResponse


class GroqProvider(AIProvider):
    name = "groq"
    capabilities = ProviderCapabilities(supports_tools=True, supports_vision=False, supports_structured_output=True, supports_streaming=True)

    def __init__(self, api_key: str, default_model: str = "llama-3.3-70b-versatile") -> None:
        if not api_key:
            raise ValueError("Groq API key is required")
        self.api_key = api_key
        self.default_model = default_model

    def _client(self):
        try:
            from groq import Groq
        except ImportError as exc:  # pragma: no cover
            raise ProviderError("Groq SDK is not installed") from exc
        return Groq(api_key=self.api_key)

    @staticmethod
    def _messages(prompt: str, context: Optional[Iterable[Mapping[str, str]]]) -> list[dict[str, str]]:
        messages = [{"role": "system", "content": "You are AURA. Follow the application policy. Do not reveal private reasoning."}]
        if context:
            messages.extend({"role": str(item.get("role", "user")), "content": str(item.get("content", ""))} for item in context)
        messages.append({"role": "user", "content": prompt})
        return messages

    def generate(self, prompt: str, *, context: Optional[Iterable[Mapping[str, str]]] = None, model: Optional[str] = None, temperature: float = 0.2) -> ProviderResponse:
        try:
            result = self._client().chat.completions.create(model=model or self.default_model, messages=self._messages(prompt, context), temperature=temperature, stream=False)
            text = result.choices[0].message.content or ""
            return ProviderResponse(text, self.name, model or self.default_model, result)
        except Exception as exc:
            raise ProviderError("AI provider request failed") from exc

    def stream(self, prompt: str, *, context: Optional[Iterable[Mapping[str, str]]] = None, model: Optional[str] = None, temperature: float = 0.2):
        try:
            result = self._client().chat.completions.create(model=model or self.default_model, messages=self._messages(prompt, context), temperature=temperature, stream=True)
            for chunk in result:
                content = getattr(chunk.choices[0].delta, "content", None)
                if content:
                    yield content
        except Exception as exc:
            raise ProviderError("AI provider streaming request failed") from exc

    def structured_output(self, prompt: str, schema: Mapping[str, object], *, context: Optional[Iterable[Mapping[str, str]]] = None, model: Optional[str] = None) -> Mapping[str, object]:
        instruction = f"Return JSON only. Conform exactly to this schema: {json.dumps(schema, sort_keys=True)}\nRequest: {prompt}"
        response = self.generate(instruction, context=context, model=model, temperature=0)
        try:
            value = json.loads(response.text)
        except json.JSONDecodeError as exc:
            raise ProviderError("Provider returned malformed structured output") from exc
        if not isinstance(value, dict):
            raise ProviderError("Provider structured output must be an object")
        return value

    def tool_calling(self, prompt: str, tools: list[Mapping[str, object]], *, context: Optional[Iterable[Mapping[str, str]]] = None, model: Optional[str] = None) -> Mapping[str, object]:
        try:
            result = self._client().chat.completions.create(model=model or self.default_model, messages=self._messages(prompt, context), tools=[{"type": "function", "function": tool} for tool in tools], tool_choice="auto", temperature=0)
            message = result.choices[0].message
            calls = getattr(message, "tool_calls", None) or []
            return {"content": message.content or "", "tool_calls": [{"name": call.function.name, "arguments": call.function.arguments} for call in calls]}
        except Exception as exc:
            raise ProviderError("Provider tool-calling request failed") from exc
