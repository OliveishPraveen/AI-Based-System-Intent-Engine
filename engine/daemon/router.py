"""
Tier Router — Owner: Harshit
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

The router is the decision-making spine of the daemon. It:
  1. Parses the incoming command (parser module)
  2. Sends it to Tier 0/1: Rule Engine (Praveen's module)
  3. If verdict is AMBIGUOUS, escalates to Tier 2: LLM Reasoner (Vansh's module)
  4. Applies session-level allowlist/denylist overrides
  5. Computes should_block from final risk level + user config thresholds
  6. Returns a unified AnalyzeResponse

This is the ONLY place where tier orchestration logic lives.
"""

from __future__ import annotations

import time
from collections import defaultdict
from typing import Any

import structlog

from engine.models import (
    AnalyzeRequest,
    AnalyzeResponse,
    RiskLevel,
    Verdict,
)
from engine.parser.command_parser import CommandParser
from engine.rule_engine.classifier import RuleEngineClassifier
from engine.llm.reasoner import LLMReasoner

log = structlog.get_logger()

# Risk levels that trigger a blocking prompt (configurable via config.toml)
_DEFAULT_BLOCK_LEVELS = {RiskLevel.HIGH, RiskLevel.CRITICAL}
_AMBIGUOUS_FALLBACK_VERDICT = Verdict(
    risk_level=RiskLevel.LOW,
    confidence=0.0,
    reasoning="LLM tier timed out. Command passed through with a low-risk assumption.",
    impact_summary="Analysis inconclusive — proceed with caution.",
    tier_used="fallback",
    latency_ms=0.0,
)


class IntentRouter:
    """Routes a command through the tier pipeline and returns a final verdict."""

    def __init__(self, config: dict[str, Any]) -> None:
        self._config = config
        self._parser = CommandParser()
        self._rule_engine: RuleEngineClassifier | None = None
        self._llm_reasoner: LLMReasoner | None = None
        self._stats: dict[str, int] = defaultdict(int)
        self._block_levels: set[RiskLevel] = _DEFAULT_BLOCK_LEVELS

    async def initialize(self) -> None:
        """Load rule engine patterns and warm up LLM client."""
        self._rule_engine = RuleEngineClassifier(self._config)
        await self._rule_engine.load_patterns()

        self._llm_reasoner = LLMReasoner(self._config)
        await self._llm_reasoner.initialize()

        # Apply config-level block threshold
        threshold = self._config.get("safety", {}).get("block_threshold", "HIGH")
        self._block_levels = self._levels_at_or_above(RiskLevel(threshold))
        log.info("router_initialized", block_threshold=threshold)

    async def route(self, request: AnalyzeRequest) -> AnalyzeResponse:
        """Main routing pipeline."""
        ctx = request.context
        parsed = self._parser.parse(ctx.command, ctx.cwd, ctx.user)

        # ── Tier 0: Session allowlist / denylist ──────────────────────────────
        # (Implemented in session.py — plugged here in Days 9-10)

        # ── Tier 1: Rule Engine ───────────────────────────────────────────────
        t0 = time.perf_counter()
        rule_verdict = await self._rule_engine.classify(parsed, ctx)
        rule_verdict.latency_ms = (time.perf_counter() - t0) * 1000
        self._stats[f"tier1_{rule_verdict.risk_level}"] += 1

        if rule_verdict.risk_level != RiskLevel.AMBIGUOUS:
            return self._build_response(rule_verdict, request, dry_run=request.dry_run)

        # ── Tier 2: LLM Reasoner (only for AMBIGUOUS) ────────────────────────
        log.info("escalating_to_llm", command=ctx.command[:60])
        self._stats["llm_escalations"] += 1
        try:
            t1 = time.perf_counter()
            llm_verdict = await self._llm_reasoner.reason(parsed, ctx, rule_verdict)
            llm_verdict.latency_ms = (time.perf_counter() - t1) * 1000
            self._stats[f"tier2_{llm_verdict.risk_level}"] += 1
            return self._build_response(llm_verdict, request, dry_run=request.dry_run)
        except TimeoutError:
            log.warning("llm_timeout", command=ctx.command[:60])
            self._stats["llm_timeouts"] += 1
            return self._build_response(
                _AMBIGUOUS_FALLBACK_VERDICT, request, dry_run=request.dry_run
            )

    def _build_response(
        self, verdict: Verdict, request: AnalyzeRequest, dry_run: bool
    ) -> AnalyzeResponse:
        should_block = (
            verdict.risk_level in self._block_levels and not dry_run
        )
        return AnalyzeResponse(
            verdict=verdict,
            should_block=should_block,
            session_id=request.context.session_id,
        )

    async def reload_rules(self) -> None:
        """Hot-reload patterns without restarting daemon."""
        if self._rule_engine:
            await self._rule_engine.load_patterns()
        log.info("rules_reloaded")

    def get_stats(self) -> dict[str, int]:
        return dict(self._stats)

    @staticmethod
    def _levels_at_or_above(threshold: RiskLevel) -> set[RiskLevel]:
        order = [RiskLevel.SAFE, RiskLevel.LOW, RiskLevel.MEDIUM,
                 RiskLevel.HIGH, RiskLevel.CRITICAL]
        idx = order.index(threshold)
        return set(order[idx:])
