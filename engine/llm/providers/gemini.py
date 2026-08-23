"""
Gemini Provider
Google Gemini API provider via the new `google-genai` SDK.
Used as primary when no local GPU, or as fallback to Ollama.

Install: pip3 install google-genai
API Key: export INTENT_GEMINI_API_KEY="your_key_here"
Get key: https://aistudio.google.com/app/apikey
"""

from __future__ import annotations

import asyncio
import os
import time
from typing import Any

from engine.llm.client import BaseLLMClient, LLMResponse


class GeminiClient(BaseLLMClient):
    """Google Gemini API provider using the new google-genai SDK."""

    def __init__(self, config: dict[str, Any]) -> None:
        llm_cfg = config.get("llm", {})
        self._model = llm_cfg.get("gemini_model", "gemini-3.6-flash")
        # API key: env var takes priority (never store keys in config files!)
        self._api_key = (
            os.environ.get("INTENT_GEMINI_API_KEY")
            or llm_cfg.get("gemini_api_key", "")
        )
        self._timeout = llm_cfg.get("timeout_s", 10.0)
        self._client = None

    def _get_client(self) -> Any:
        if self._client is None:
            from google import genai  # type: ignore
            self._client = genai.Client(api_key=self._api_key)
        return self._client

    async def complete(self, prompt: str, system_prompt: str) -> LLMResponse:
        t0 = time.perf_counter()
        client = self._get_client()
        full_prompt = f"{system_prompt}\n\n{prompt}"

        # google-genai SDK is sync — run in executor to avoid blocking event loop
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None,
            lambda: client.models.generate_content(
                model=self._model,
                contents=full_prompt,
                config={
                    "response_mime_type": "application/json",
                    "temperature": 0.1,
                },
            ),
        )
        return LLMResponse(
            content=response.text,
            model=self._model,
            latency_ms=(time.perf_counter() - t0) * 1000,
        )

    async def health_check(self) -> bool:
        return bool(self._api_key)
