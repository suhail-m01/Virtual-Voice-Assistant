"""Explicit local/offline provider boundary.

This adapter intentionally does not pretend to be an LLM.  A deployment can
replace it with an Ollama/llama.cpp implementation that satisfies the same
interface without changing agent code.
"""
from __future__ import annotations

from typing import Iterable, Mapping, Optional

from ..provider import AIProvider, ProviderCapabilities, ProviderError, ProviderResponse


class LocalProvider(AIProvider):
    name = "local"
    capabilities = ProviderCapabilities(local=True, supports_streaming=False)

    def __init__(self, model: str = "") -> None:
        self.model = model or "local-unconfigured"

    def generate(self, prompt: str, *, context: Optional[Iterable[Mapping[str, str]]] = None, model: Optional[str] = None, temperature: float = 0.2) -> ProviderResponse:
        raise ProviderError("No local model is configured")

    def structured_output(self, prompt: str, schema: Mapping[str, object], *, context: Optional[Iterable[Mapping[str, str]]] = None, model: Optional[str] = None) -> Mapping[str, object]:
        raise ProviderError("No local structured-output model is configured")
