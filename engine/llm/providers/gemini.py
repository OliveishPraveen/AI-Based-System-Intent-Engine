"""
Gemini Provider — Owner: Vansh
Google Gemini API provider. Used as fallback or primary when no local GPU.
"""

from __future__ import annotations

import time
from typing import Any

from engine.llm.client import BaseLLMClient, LLMResponse


class GeminiClient(BaseLLMClient):
    """Google Gemini API provider."""

    def __init__(self, config: dict[str, Any]) -> None:
        llm_cfg = config.get("llm", {})
        self._model = llm_cfg.get("gemini_model", "gemini-2.0-flash")
        self._api_key = llm_cfg.get("gemini_api_key", "")
        self._timeout = llm_cfg.get("timeout_s", 5.0)
        self._client = None

    def _get_client(self) -> Any:
        if self._client is None:
            import google.generativeai as genai  # type: ignore
            genai.configure(api_key=self._api_key)
            self._client = genai.GenerativeModel(
                model_name=self._model,
                generation_config={"response_mime_type": "application/json"},
            )
        return self._client

    async def complete(self, prompt: str, system_prompt: str) -> LLMResponse:
        import asyncio
        t0 = time.perf_counter()
        client = self._get_client()
        full_prompt = f"{system_prompt}\n\n{prompt}"
        # google-generativeai SDK is sync — run in executor
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None, lambda: client.generate_content(full_prompt)
        )
        return LLMResponse(
            content=response.text,
            model=self._model,
            latency_ms=(time.perf_counter() - t0) * 1000,
        )

    async def health_check(self) -> bool:
        return bool(self._api_key)
