"""
LLM Reasoner — Owner: Vansh
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Core LLM-based reasoning for AMBIGUOUS commands that the rule engine
cannot confidently classify. Analogous to NEXUS-AI's planner + reflection phases.

Pipeline:
  1. Build structured prompt from ParsedCommand + context + rule engine hints
  2. Call LLM with strict JSON output schema
  3. Parse + validate response (ResponseParser)
  4. Optional reflection pass: if confidence < 0.7, re-prompt with critique
  5. Invoke Suggester to generate safer alternative
  6. Return final Verdict

Timeout: 3s hard limit. If exceeded, router uses fallback verdict.
"""

from __future__ import annotations

import asyncio
from typing import Any

import structlog

from engine.llm.client import BaseLLMClient, LLMClientFactory
from engine.llm.prompt_builder import PromptBuilder
from engine.llm.response_parser import ResponseParser
from engine.llm.suggester import SaferAlternativeSuggester
from engine.models import CommandContext, RiskLevel, Verdict
from engine.parser.command_parser import ParsedCommand

log = structlog.get_logger()

_LLM_TIMEOUT_S = 3.0  # Hard timeout — never block the user longer than this


class LLMReasoner:
    """
    Tier 2 LLM reasoning engine.

    Vansh: implement the reason() method body following the pipeline above.
    The prompt builder, response parser, and suggester are pre-scaffolded for you.
    """

    def __init__(self, config: dict[str, Any]) -> None:
        self._config = config
        self._client: BaseLLMClient | None = None
        self._prompt_builder = PromptBuilder()
        self._response_parser = ResponseParser()
        self._suggester = SaferAlternativeSuggester(config)

    async def initialize(self) -> None:
        """Create and warm up the LLM client."""
        self._client = await LLMClientFactory.create(self._config)
        log.info("llm_reasoner_initialized")

    async def reason(
        self,
        parsed: ParsedCommand,
        ctx: CommandContext,
        rule_hint: Verdict,
    ) -> Verdict:
        """
        Reason about an AMBIGUOUS command using the LLM.

        Args:
            parsed:     Structured parsed command (from command_parser.py)
            ctx:        Full command context (cwd, user, sudo, shell)
            rule_hint:  The rule engine's AMBIGUOUS verdict (provides partial context)

        Returns:
            Verdict with a definitive risk_level (never AMBIGUOUS)

        Vansh: implement the full reasoning pipeline here.
        See PromptBuilder.build_analysis_prompt() for the prompt structure.
        See ResponseParser.parse() for the expected LLM JSON output format.
        """
        if self._client is None:
            raise RuntimeError("LLM client not initialized")

        # Build prompt
        system_prompt = self._prompt_builder.build_system_prompt()
        user_prompt = self._prompt_builder.build_analysis_prompt(parsed, ctx, rule_hint)

        # Call LLM with hard timeout
        try:
            llm_response = await asyncio.wait_for(
                self._client.complete(user_prompt, system_prompt),
                timeout=_LLM_TIMEOUT_S,
            )
        except asyncio.TimeoutError:
            raise TimeoutError(f"LLM response exceeded {_LLM_TIMEOUT_S}s timeout")

        # Parse response
        parsed_response = self._response_parser.parse(llm_response.content)

        # Generate safer alternative if needed
        safer_alt = None
        safer_explanation = None
        if parsed_response.risk_level not in (RiskLevel.SAFE, RiskLevel.LOW):
            safer_alt, safer_explanation = await self._suggester.suggest(parsed, ctx, parsed_response)

        return Verdict(
            risk_level=parsed_response.risk_level,
            confidence=parsed_response.confidence,
            reasoning=parsed_response.reasoning,
            impact_summary=parsed_response.impact_summary,
            safer_alternative=safer_alt,
            safer_alternative_explanation=safer_explanation,
            tier_used="llm",
            latency_ms=llm_response.latency_ms,
        )
