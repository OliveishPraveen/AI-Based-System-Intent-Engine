"""
LLM Client Abstraction — Owner: Vansh
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Abstract base class + provider factory for multi-LLM support.
Vansh has already built this pattern in NEXUS-AI (Gemini/OpenAI wired).

Supported providers (configured via config.toml):
  - "ollama"  → engine.llm.providers.ollama.OllamaClient  (local, private-first)
  - "gemini"  → engine.llm.providers.gemini.GeminiClient  (API, best quality)
  - "openai"  → engine.llm.providers.openai.OpenAIClient  (API, alternative)

Config example:
  [llm]
  provider = "ollama"
  model = "llama3.2:3b"
  timeout_s = 3.0
  fallback_provider = "gemini"
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from typing import Any, Optional


class LLMResponse:
    """Structured response from any LLM provider."""
    def __init__(self, content: str, model: str, latency_ms: float) -> None:
        self.content = content
        self.model = model
        self.latency_ms = latency_ms


class BaseLLMClient(ABC):
    """Abstract base — all providers must implement this interface."""

    @abstractmethod
    async def complete(self, prompt: str, system_prompt: str) -> LLMResponse:
        """Send a prompt and return the LLM response."""
        ...

    @abstractmethod
    async def health_check(self) -> bool:
        """Return True if the provider is reachable and ready."""
        ...


class LLMClientFactory:
    """
    Factory that instantiates the correct LLM client from config.

    Vansh: add new providers by creating a new file in engine/llm/providers/
    and registering it in the _PROVIDERS dict below.
    """

    _PROVIDERS: dict[str, str] = {
        "ollama": "engine.llm.providers.ollama.OllamaClient",
        "gemini": "engine.llm.providers.gemini.GeminiClient",
        "openai": "engine.llm.providers.openai.OpenAIClient",
    }

    @classmethod
    async def create(cls, config: dict[str, Any]) -> BaseLLMClient:
        """Create and return the configured LLM client, with fallback."""
        import importlib

        provider_name = config.get("llm", {}).get("provider", "ollama")
        module_path, class_name = cls._PROVIDERS[provider_name].rsplit(".", 1)
        module = importlib.import_module(module_path)
        client: BaseLLMClient = getattr(module, class_name)(config)

        # Health check — if primary fails, try fallback provider
        if not await client.health_check():
            fallback = config.get("llm", {}).get("fallback_provider")
            if fallback and fallback in cls._PROVIDERS:
                module_path, class_name = cls._PROVIDERS[fallback].rsplit(".", 1)
                module = importlib.import_module(module_path)
                client = getattr(module, class_name)(config)

        return client
