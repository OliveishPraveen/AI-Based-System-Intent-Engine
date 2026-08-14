"""
Rule Engine Classifier — Owner: Praveen
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Main entry point for Tier 0/1 classification.

Architecture (mirrors Ai_Email_Classifier's hybrid approach):
  - Tier 0: Fast exact/structural matches (fork bombs, known CRITICAL patterns)
  - Tier 1: Pattern matcher against curated dangerous_patterns.toml
  - Confidence scoring based on pattern match quality + context weights
  - Returns AMBIGUOUS only when no pattern matches with confidence >= threshold

Interface contract (defined in engine/models.py — do NOT redefine):
  Input:  ParsedCommand + CommandContext
  Output: Verdict (see models.py)

DO NOT import from engine.llm — that creates a circular dependency.
"""

from __future__ import annotations

import time
from typing import Any

import structlog

from engine.models import CommandContext, RiskLevel, Verdict
from engine.parser.command_parser import ParsedCommand
from engine.rule_engine.pattern_loader import PatternLoader
from engine.rule_engine.pattern_matcher import PatternMatcher

log = structlog.get_logger()

# Confidence below this threshold → escalate to LLM
_AMBIGUOUS_THRESHOLD = 0.55


class RuleEngineClassifier:
    """
    Two-tier rule classifier for known dangerous command patterns.

    Praveen's implementation should:
      1. Load patterns from PatternLoader
      2. Run Tier 0 (exact/structural checks) first — these are instant and certain
      3. Run Tier 1 (pattern matcher) on remaining commands
      4. Compute confidence score considering: pattern match quality, context, sudo usage
      5. Return AMBIGUOUS if confidence < threshold so LLM can handle it

    Test cases are in tests/unit/test_rule_engine.py and tests/fixtures/
    """

    def __init__(self, config: dict[str, Any]) -> None:
        self._config = config
        self._loader = PatternLoader()
        self._matcher: PatternMatcher | None = None

    async def load_patterns(self) -> None:
        """Load and compile patterns from dangerous_patterns.toml."""
        patterns = await self._loader.load()
        self._matcher = PatternMatcher(patterns)
        log.info("rule_engine_patterns_loaded", count=len(patterns))

    async def classify(
        self, parsed: ParsedCommand, ctx: CommandContext
    ) -> Verdict:
        """
        Classify a parsed command.

        Returns a Verdict with risk_level, confidence, reasoning, and
        optional safer_alternative. If risk_level == AMBIGUOUS, the
        router will escalate to the LLM tier.
        """
        if self._matcher is None:
            raise RuntimeError("Patterns not loaded — call load_patterns() first")

        t0 = time.perf_counter()

        # ── Tier 0: Immediate CRITICAL patterns ───────────────────────────────
        # These are 100%-confidence catches — no further analysis needed.
        tier0_verdict = self._matcher.check_tier0(parsed)
        if tier0_verdict is not None:
            tier0_verdict.latency_ms = (time.perf_counter() - t0) * 1000
            return tier0_verdict

        # ── Tier 1: Full pattern library ──────────────────────────────────────
        match_result = self._matcher.match(parsed, ctx)

        if match_result is None or match_result.confidence < _AMBIGUOUS_THRESHOLD:
            # No confident match — escalate to LLM
            return Verdict(
                risk_level=RiskLevel.AMBIGUOUS,
                confidence=match_result.confidence if match_result else 0.0,
                reasoning="No confident rule match. Escalating to LLM tier.",
                impact_summary="Command requires deeper analysis.",
                tier_used="rule_engine",
                latency_ms=(time.perf_counter() - t0) * 1000,
            )

        verdict = Verdict(
            risk_level=match_result.risk_level,
            confidence=match_result.confidence,
            matched_pattern=match_result.pattern_name,
            reasoning=match_result.reasoning,
            impact_summary=match_result.impact_summary,
            safer_alternative=match_result.safer_alternative,
            safer_alternative_explanation=match_result.safer_alternative_explanation,
            tier_used="rule_engine",
            latency_ms=(time.perf_counter() - t0) * 1000,
        )
        return verdict
