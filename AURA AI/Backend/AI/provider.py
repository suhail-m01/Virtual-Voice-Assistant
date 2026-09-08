"""Provider-neutral contract for generation, structured output and tool calling."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Iterable, Iterator, Mapping, Optional


class ProviderError(RuntimeError):
    pass


@dataclass(frozen=True)
class ProviderCapabilities:
    supports_tools: bool = False
    supports_vision: bool = False
    supports_structured_output: bool = False
    supports_streaming: bool = False
    local: bool = False


@dataclass(frozen=True)
class ProviderResponse:
    text: str
    provider: str
    model: str = ""
    raw: Any = field(default=None, repr=False)


class AIProvider(ABC):
    name: str
    capabilities: ProviderCapabilities

    @abstractmethod
    def generate(self, prompt: str, *, context: Optional[Iterable[Mapping[str, str]]] = None, model: Optional[str] = None, temperature: float = 0.2) -> ProviderResponse:
        raise NotImplementedError

    def stream(self, prompt: str, *, context: Optional[Iterable[Mapping[str, str]]] = None, model: Optional[str] = None, temperature: float = 0.2) -> Iterator[str]:
        if not self.capabilities.supports_streaming:
            response = self.generate(prompt, context=context, model=model, temperature=temperature)
            yield response.text
            return
        raise NotImplementedError

    def structured_output(self, prompt: str, schema: Mapping[str, Any], *, context: Optional[Iterable[Mapping[str, str]]] = None, model: Optional[str] = None) -> Mapping[str, Any]:
        raise ProviderError(f"Provider {self.name} does not support structured output")

    def tool_calling(self, prompt: str, tools: list[Mapping[str, Any]], *, context: Optional[Iterable[Mapping[str, str]]] = None, model: Optional[str] = None) -> Mapping[str, Any]:
        raise ProviderError(f"Provider {self.name} does not support tool calling")

    def vision(self, prompt: str, image: bytes, *, model: Optional[str] = None) -> ProviderResponse:
        raise ProviderError(f"Provider {self.name} does not support vision")
