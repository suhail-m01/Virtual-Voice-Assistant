"""Capability-aware provider selection."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional

from .provider import AIProvider, ProviderCapabilities, ProviderError, ProviderResponse
from ..Security.privacy import redact_sensitive
from .providers.local import LocalProvider


class ProviderRegistry:
    def __init__(self, providers: Optional[Iterable[AIProvider]] = None) -> None:
        self._providers: dict[str, AIProvider] = {}
        for provider in providers or ():
            self.register(provider)

    def register(self, provider: AIProvider) -> None:
        if not getattr(provider, "name", ""):
            raise ValueError("provider must have a name")
        self._providers[provider.name] = provider

    def get(self, name: str) -> AIProvider:
        try:
            return self._providers[name]
        except KeyError as exc:
            raise ProviderError(f"Provider '{name}' is not configured") from exc

    def select(self, *, capability: Optional[str] = None, preferred: Optional[str] = None, privacy_sensitive: bool = False) -> AIProvider:
        candidates = list(self._providers.values())
        if preferred:
            candidates = [self.get(preferred)]
        if privacy_sensitive:
            local = [item for item in candidates if item.capabilities.local]
            if not local:
                raise ProviderError("No local provider is available for privacy-sensitive work")
            candidates = local
        if capability:
            if not hasattr(ProviderCapabilities(), capability):
                raise ValueError(f"Unknown provider capability: {capability}")
            candidates = [item for item in candidates if bool(getattr(item.capabilities, capability, False))]
        if not candidates:
            raise ProviderError(f"No provider supports capability '{capability}'")
        return candidates[0]

    def names(self) -> tuple[str, ...]:
        return tuple(self._providers)


class ProviderRouter:
    def __init__(self, registry: ProviderRegistry, *, preferred: str = "auto") -> None:
        self.registry = registry
        self.preferred = preferred

    def provider_for(self, *, capability: Optional[str] = None, privacy_sensitive: bool = False) -> AIProvider:
        preferred = None if self.preferred in {"", "auto"} else self.preferred
        return self.registry.select(capability=capability, preferred=preferred, privacy_sensitive=privacy_sensitive)

    @staticmethod
    def _safe_prompt(prompt: str) -> str:
        result = redact_sensitive(prompt)
        if result.redacted:
            raise ProviderError("Privacy filter blocked credential-bearing provider input")
        return result.text

    @staticmethod
    def _safe_context(context):
        if context is None:
            return None
        safe = []
        for item in context:
            content = redact_sensitive(str(item.get("content", "")))
            if content.redacted:
                raise ProviderError("Privacy filter blocked credential-bearing context")
            safe.append({"role": str(item.get("role", "user")), "content": content.text})
        return safe

    def generate(self, prompt: str, *, context=None, privacy_sensitive: bool = False, model: Optional[str] = None) -> ProviderResponse:
        provider = self.provider_for(privacy_sensitive=privacy_sensitive)
        return provider.generate(self._safe_prompt(prompt), context=self._safe_context(context), model=model)

    def structured_output(self, prompt: str, schema, *, context=None, privacy_sensitive: bool = False, model: Optional[str] = None):
        provider = self.provider_for(capability="supports_structured_output", privacy_sensitive=privacy_sensitive)
        return provider.structured_output(self._safe_prompt(prompt), schema, context=self._safe_context(context), model=model)

    def tool_calling(self, prompt: str, tools, *, context=None, privacy_sensitive: bool = False, model: Optional[str] = None):
        provider = self.provider_for(capability="supports_tools", privacy_sensitive=privacy_sensitive)
        return provider.tool_calling(self._safe_prompt(prompt), tools, context=self._safe_context(context), model=model)


def registry_from_settings(settings) -> ProviderRegistry:
    providers: list[AIProvider] = []
    if settings.groq_api_key:
        try:
            from .providers.groq_provider import GroqProvider
            providers.append(GroqProvider(settings.groq_api_key, settings.llm_model or "llama-3.3-70b-versatile"))
        except Exception:
            pass
    if settings.cohere_api_key:
        try:
            from .providers.cohere_provider import CohereProvider
            providers.append(CohereProvider(settings.cohere_api_key, settings.llm_model or "command-r-plus"))
        except Exception:
            pass
    # Local is always registered, but it will state clearly when no model is
    # configured rather than silently sending private context to a cloud model.
    providers.append(LocalProvider())
    return ProviderRegistry(providers)
