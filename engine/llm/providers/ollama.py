"""
Ollama Provider
Local LLM via Ollama HTTP API. Privacy-first default provider.

Requires: ollama running locally (ollama serve)
Default model: llama3.2:3b (fast) or qwen2.5:3b (better reasoning)
"""

from __future__ import annotations

import time
from typing import Any

import httpx

from engine.llm.client import BaseLLMClient, LLMResponse

_OLLAMA_BASE = "http://localhost:11434"


class OllamaClient(BaseLLMClient):
    """Ollama local LLM provider."""

    def __init__(self, config: dict[str, Any]) -> None:
        llm_cfg = config.get("llm", {})
        self._model = llm_cfg.get("model", "llama3.2:3b")
        self._timeout = llm_cfg.get("timeout_s", 3.0)
        self._base_url = llm_cfg.get("ollama_url", _OLLAMA_BASE)

    async def complete(self, prompt: str, system_prompt: str) -> LLMResponse:
        t0 = time.perf_counter()
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.post(
                f"{self._base_url}/api/chat",
                json={
                    "model": self._model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": prompt},
                    ],
                    "stream": False,
                    "keep_alive": -1,
                    "format": "json",
                    "options": {
                        "temperature": 0,        # greedy decoding — fastest
                        "num_predict": 150,      # cap output tokens — responses are short JSON
                        "num_ctx": 2048,         # smaller context window — faster attention
                    },
                },
            )
            resp.raise_for_status()
            data = resp.json()
            content = data["message"]["content"]
        return LLMResponse(
            content=content,
            model=self._model,
            latency_ms=(time.perf_counter() - t0) * 1000,
        )

    async def health_check(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                r = await client.get(f"{self._base_url}/api/tags")
                return r.status_code == 200
        except Exception:
            return False
