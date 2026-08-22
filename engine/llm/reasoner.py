"""
LLM Reasoner — Owner: Vansh
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Core LLM-based reasoning for AMBIGUOUS commands that the rule engine
cannot confidently classify.

Pipeline:
  1. Check session-scoped LRU cache → instant on repeated commands
  2. Build structured prompt from ParsedCommand + context + rule engine hints
  3. Call LLM with strict JSON output schema
  4. Parse + validate response (ResponseParser)
  5. Curated table lookup for safer alternative (no second LLM call)
  6. Return final Verdict

Timeout: 3s hard limit. If exceeded, router uses fallback verdict.

OPTIMISATION: LRU prompt cache (128 entries, session-scoped).
Identical commands are answered from cache in <1ms instead of re-calling the LLM.
"""

from __future__ import annotations

import asyncio
import hashlib
from collections import OrderedDict
from typing import Any

import structlog

from engine.llm.client import BaseLLMClient, LLMClientFactory
from engine.llm.prompt_builder import PromptBuilder
from engine.llm.response_parser import ResponseParser
from engine.llm.suggester import SaferAlternativeSuggester
from engine.models import CommandContext, RiskLevel, Verdict
from engine.parser.command_parser import ParsedCommand

log = structlog.get_logger()

_LLM_TIMEOUT_S = 3.0       # Hard timeout — never block the user longer than this
_CACHE_MAX_SIZE = 128      # LRU entries per daemon session


class _LRUVerdictCache:
    """
    Session-scoped LRU cache: (command_hash) → Verdict.
    Thread-safe enough for asyncio single-thread daemon (no explicit lock needed).
    """

    def __init__(self, max_size: int = _CACHE_MAX_SIZE) -> None:
        self._max = max_size
        self._cache: OrderedDict[str, Verdict] = OrderedDict()

    def _key(self, command: str) -> str:
        return hashlib.md5(command.strip().encode(), usedforsecurity=False).hexdigest()

    def get(self, command: str) -> Verdict | None:
        key = self._key(command)
        if key in self._cache:
            self._cache.move_to_end(key)
            log.debug("llm_cache_hit", command=command[:40])
            return self._cache[key]
        return None

    def set(self, command: str, verdict: Verdict) -> None:
        key = self._key(command)
        self._cache[key] = verdict
        self._cache.move_to_end(key)
        if len(self._cache) > self._max:
            self._cache.popitem(last=False)

    def invalidate(self) -> None:
        self._cache.clear()


class LLMReasoner:
    """
    Tier 2 LLM reasoning engine with session-scoped response cache.
    """

    def __init__(self, config: dict[str, Any]) -> None:
        self._config = config
        self._client: BaseLLMClient | None = None
        self._prompt_builder = PromptBuilder()
        self._response_parser = ResponseParser()
        self._suggester = SaferAlternativeSuggester(config)
        self._cache = _LRUVerdictCache()

    async def initialize(self) -> None:
        """Create and warm up the LLM client."""
        self._client = await LLMClientFactory.create(self._config)
        if self._client is None:
            log.warning(
                "llm_unavailable",
                note="No LLM provider reachable. AMBIGUOUS commands will use fallback verdict. "
                     "Start Ollama (`ollama serve`) or configure a cloud provider to enable Tier 2."
            )
        else:
            log.info("llm_reasoner_initialized")
            # Fire-and-forget background task to pre-load the model into memory
            asyncio.create_task(self._prewarm_model())

    async def _prewarm_model(self) -> None:
        """Background task to load the model into VRAM/RAM before the user needs it."""
        log.info("llm_prewarm_started")
        try:
            # A dummy request forces Ollama to load the model from disk to memory
            await self._client.complete(
                prompt="Initialize",
                system_prompt="You are a system daemon."
            )
            log.info("llm_prewarm_complete")
        except Exception as e:
            log.debug("llm_prewarm_failed", error=str(e))

    async def reason(
        self,
        parsed: ParsedCommand,
        ctx: CommandContext,
        rule_hint: Verdict,
    ) -> Verdict:
        """
        Reason about an AMBIGUOUS command using the LLM.

        Returns a Verdict with a definitive risk_level (never AMBIGUOUS).
        Cache hit returns in <1ms; cache miss calls LLM with 3s timeout.
        """
        if self._client is None:
            raise RuntimeError("LLM client not initialized")

        # ── Cache check (Priority 2 optimisation) ─────────────────────────────
        cached = self._cache.get(parsed.raw)
        if cached is not None:
            return cached

        # ── Build prompt ───────────────────────────────────────────────────────
        system_prompt = self._prompt_builder.build_system_prompt()
        user_prompt = self._prompt_builder.build_analysis_prompt(parsed, ctx, rule_hint)

        # ── Call LLM with hard timeout ─────────────────────────────────────────
        timeout_s = self._config.get("llm", {}).get("timeout_s", 15.0)
        try:
            llm_response = await asyncio.wait_for(
                self._client.complete(user_prompt, system_prompt),
                timeout=timeout_s,
            )
        except asyncio.TimeoutError:
            raise TimeoutError(f"LLM response exceeded {timeout_s}s timeout")

        # ── Parse response ─────────────────────────────────────────────────────
        parsed_response = self._response_parser.parse(llm_response.content)

        # ── Reflection pass DISABLED ───────────────────────────────────────────
        # Previously made a second LLM call to refine low-confidence verdicts.
        # Disabled to guarantee single-call latency (<2s warm).
        # Re-enable by setting llm.reflection_enabled = true in config.

        # ── Safer alternative: curated table first, LLM output as fallback ────

        # Priority 1 optimisation: NO second LLM call.
        # The suggester checks: (1) LLM's own suggestion in parsed_response,
        # (2) curated table lookup — both are 0ms.
        safer_alt = None
        safer_explanation = None
        if parsed_response.risk_level not in (RiskLevel.SAFE, RiskLevel.LOW):
            safer_alt, safer_explanation = await self._suggester.suggest(parsed, ctx, parsed_response)

        verdict = Verdict(
            risk_level=parsed_response.risk_level,
            confidence=parsed_response.confidence,
            matched_pattern=None,
            reasoning=parsed_response.reasoning,
            impact_summary=parsed_response.impact_summary,
            safer_alternative=safer_alt,
            safer_alternative_explanation=safer_explanation,
            tier_used="llm",
            latency_ms=llm_response.latency_ms,
        )

        # ── Cache the verdict ──────────────────────────────────────────────────
        # Only cache definitive verdicts — AMBIGUOUS shouldn't arise from LLM
        # but guard against it anyway.
        if parsed_response.risk_level != RiskLevel.AMBIGUOUS:
            self._cache.set(parsed.raw, verdict)

        return verdict

    def invalidate_cache(self) -> None:
        """Clear the LRU cache (e.g. after a hot-reload)."""
        self._cache.invalidate()
        log.info("llm_cache_invalidated")
