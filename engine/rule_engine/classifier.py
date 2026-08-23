"""
Rule Engine Classifier
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Main orchestration point for Tier 0 (structural fast-path) and Tier 1 (context-weighted)
rule classification. Returns unified Verdicts according to engine/models.py contract.
"""

from __future__ import annotations

import time
from typing import Any, Optional

import structlog

from engine.models import CommandContext, RiskLevel, Verdict
from engine.parser.command_parser import ParsedCommand
from engine.rule_engine.obfuscation_detector import ObfuscationDetector
from engine.rule_engine.pattern_loader import PatternLoader
from engine.rule_engine.pattern_matcher import PatternMatcher
from engine.rule_engine.verdict_builder import VerdictBuilder

log = structlog.get_logger()

# Confidence below this threshold → escalate to LLM tier
_DEFAULT_AMBIGUOUS_THRESHOLD = 0.55


class RuleEngineClassifier:
    """
    Two-tier rule classifier for Linux shell command risk analysis.
      - Tier 0: Fast structural / semantic checks (fork bombs, rm -rf /, dd to raw disk, etc.)
      - Tier 1: Context-weighted pattern matching against dangerous_patterns.toml
      - Benign fast path: Passes safe commands (ls, df, grep, /tmp ops) with zero false positives.
    """

    def __init__(self, config: Optional[dict[str, Any]] = None) -> None:
        self._config = config or {}
        self._loader = PatternLoader()
        self._matcher: Optional[PatternMatcher] = None
        self._obfuscation_detector = ObfuscationDetector()  # Pre-Tier-0 evasion scanner
        self._ambiguous_threshold: float = float(
            self._config.get("safety", {}).get("ambiguous_threshold", _DEFAULT_AMBIGUOUS_THRESHOLD)
        )

    async def load_patterns(self) -> None:
        """Asynchronously load and compile patterns from the TOML library."""
        patterns = await self._loader.load()
        self._matcher = PatternMatcher(patterns)
        log.info("rule_engine_patterns_loaded", count=len(patterns))

    def load_patterns_sync(self) -> None:
        """Synchronously load and compile patterns."""
        patterns = self._loader.load_sync()
        self._matcher = PatternMatcher(patterns)
        log.info("rule_engine_patterns_loaded_sync", count=len(patterns))

    def reload_patterns(self) -> int:
        """Hot-reload patterns without service restart."""
        patterns = self._loader.reload()
        self._matcher = PatternMatcher(patterns)
        log.info("rule_engine_patterns_reloaded", count=len(patterns))
        return len(patterns)

    async def classify(
        self, parsed: ParsedCommand, ctx: CommandContext
    ) -> Verdict:
        """
        Classify a parsed command against Tier 0 and Tier 1 rule logic.
        """
        if self._matcher is None:
            # Auto-initialize if not loaded yet
            await self.load_patterns()
            if self._matcher is None:
                raise RuntimeError("Failed to initialize PatternMatcher.")

        t0 = time.perf_counter()

        # ── Pre-Tier 0: Obfuscation / Evasion Scan ────────────────────────────
        # Catches eval+base64, hex-decode pipelines, HISTFILE wipes, etc.
        # Must run BEFORE structural checks so encoded payloads don't slip through.
        obfusc_verdict = self._obfuscation_detector.detect(parsed.raw)
        if obfusc_verdict is not None:
            obfusc_verdict.latency_ms = round((time.perf_counter() - t0) * 1000, 2)
            log.info(
                "obfuscation_detected",
                command=parsed.raw[:50],
                pattern=obfusc_verdict.matched_pattern,
                latency_ms=obfusc_verdict.latency_ms,
            )
            return obfusc_verdict

        # ── Tier 0: Fast-Path Immediate CRITICAL Checks (< 1ms) ───────────────
        tier0_verdict = self._matcher.check_tier0(parsed)
        if tier0_verdict is not None:
            tier0_verdict.latency_ms = round((time.perf_counter() - t0) * 1000, 2)
            log.info(
                "tier0_match",
                command=parsed.raw[:50],
                pattern=tier0_verdict.matched_pattern,
                latency_ms=tier0_verdict.latency_ms,
            )
            return tier0_verdict

        # ── Tier 1: Context-Weighted Pattern Matching ─────────────────────────
        match_result = self._matcher.match(parsed, ctx)

        elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)

        # ── Case A: Benign / Safe Command Fast Path ───────────────────────────
        if match_result is not None and match_result.risk_level == RiskLevel.SAFE:
            return VerdictBuilder.build_verdict(
                risk_level=RiskLevel.SAFE,
                confidence=match_result.confidence,
                matched_pattern=match_result.pattern_name,
                reasoning=match_result.reasoning,
                impact_summary=match_result.impact_summary,
                safer_alternative=None,
                safer_alternative_explanation=None,
                tier_used="rule_engine",
                latency_ms=elapsed_ms,
            )

        # ── Case B: Inconclusive / Low-Confidence Match → Escalate to LLM ──────
        if match_result is None or match_result.confidence < self._ambiguous_threshold:
            conf = match_result.confidence if match_result else 0.0
            return VerdictBuilder.build_verdict(
                risk_level=RiskLevel.AMBIGUOUS,
                confidence=conf,
                matched_pattern=match_result.pattern_name if match_result else None,
                reasoning="Command does not match high-confidence static patterns. Escalating to LLM tier for semantic reasoning.",
                impact_summary="Command requires deeper contextual evaluation.",
                safer_alternative=None,
                safer_alternative_explanation=None,
                tier_used="rule_engine",
                latency_ms=elapsed_ms,
            )

        # ── Case C: Confident Tier 1 Match ────────────────────────────────────
        return VerdictBuilder.build_verdict(
            risk_level=match_result.risk_level,
            confidence=match_result.confidence,
            matched_pattern=match_result.pattern_name,
            reasoning=match_result.reasoning,
            impact_summary=match_result.impact_summary,
            safer_alternative=match_result.safer_alternative,
            safer_alternative_explanation=match_result.safer_alternative_explanation,
            tier_used="rule_engine",
            latency_ms=elapsed_ms,
        )
