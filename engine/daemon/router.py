"""
Tier Router
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

The router is the decision-making spine of the daemon. It:
  1. Checks session allowlist / denylist first (instant override)
  2. Parses the incoming command
  3. Sends to Tier 0/1: Rule Engine (Praveen)
  4. If AMBIGUOUS, escalates to Tier 2: LLM Reasoner (Vansh)
  5. Computes should_block from final risk level + config threshold
  6. Returns a unified AnalyzeResponse

MOCK MODE:
  When INTENT_MOCK_MODE=1 (or config mock=true), the router skips
  the real rule engine and LLM and returns a predictable SAFE response.
  This lets the daemon run during Phase 1 before teammates' code lands.
  Remove mock mode invocations once real implementations are integrated.
"""

from __future__ import annotations

import os
import time
from collections import defaultdict, deque
from typing import Any

import structlog

from engine.models import (
    AnalyzeRequest,
    AnalyzeResponse,
    RiskLevel,
    Verdict,
)
from engine.parser.command_parser import CommandParser
from engine.daemon.session import SessionManager
from engine.alternatives.generator import AlternativeGenerator
from engine.alternatives.validator import AlternativeValidator
from engine.integration.pattern_matcher_adapter import PatternMatcherAdapter

log = structlog.get_logger()

# ── Sentinels ──────────────────────────────────────────────────────────────────
_DEFAULT_BLOCK_LEVELS = {RiskLevel.HIGH, RiskLevel.CRITICAL}

_FALLBACK_VERDICT = Verdict(
    risk_level=RiskLevel.LOW,
    confidence=0.0,
    reasoning="LLM tier timed out. Passed through with low-risk assumption.",
    impact_summary="Analysis inconclusive — proceed with caution.",
    tier_used="fallback",
    latency_ms=0.0,
)

_MOCK_SAFE_VERDICT = Verdict(
    risk_level=RiskLevel.SAFE,
    confidence=1.0,
    reasoning="[MOCK MODE] Rule engine and LLM not yet integrated.",
    impact_summary="Mock mode — all commands pass through.",
    tier_used="mock",
    latency_ms=0.0,
)

_ALWAYS_DENY_VERDICT = Verdict(
    risk_level=RiskLevel.CRITICAL,
    confidence=1.0,
    reasoning="This command is on your personal deny list.",
    impact_summary="Blocked by your configuration (always_deny list).",
    tier_used="denylist",
    latency_ms=0.0,
)

_ALWAYS_ALLOW_VERDICT = Verdict(
    risk_level=RiskLevel.SAFE,
    confidence=1.0,
    reasoning="This command is on your personal allow list.",
    impact_summary="Allowed by your configuration (always_allow list).",
    tier_used="allowlist",
    latency_ms=0.0,
)


class _TokenBucket:
    """
    Per-session token bucket rate limiter.
    Allows burst of `capacity` requests; refills at `rate` req/s.
    Uses a sliding window deque for accurate per-second accounting.
    """
    def __init__(self, rate: float = 1000.0, capacity: int = 1000) -> None:
        self._rate = rate
        self._capacity = capacity
        # Maps session_id → deque of timestamps
        self._windows: dict[str, deque] = defaultdict(deque)

    def is_allowed(self, session_id: str) -> bool:
        now = time.monotonic()
        window = self._windows[session_id]
        cutoff = now - 1.0          # 1-second sliding window
        # Evict timestamps older than 1s
        while window and window[0] < cutoff:
            window.popleft()
        if len(window) >= self._capacity:
            return False            # Rate limit exceeded
        window.append(now)
        return True


class IntentRouter:
    """Routes a command through the tier pipeline and returns a final verdict."""

    def __init__(self, config: dict[str, Any]) -> None:
        from engine.parser.alias_resolver import AliasResolver
        self._config = config
        self._alias_resolver = AliasResolver()
        self._parser = CommandParser(alias_resolver=self._alias_resolver)
        self._session = SessionManager(config)
        self._rule_engine = None              # Injected in initialize()
        self._llm_reasoner = None             # Injected in initialize()
        _adapter = PatternMatcherAdapter()    # Vansh: rule engine bridge
        self._alt_generator = AlternativeGenerator()
        self._alt_validator = AlternativeValidator(_adapter)
        self._stats: dict[str, int] = defaultdict(int)
        # Rate limiter: configurable, defaults to 1000 req/s to avoid throttling test suites.
        # Production deployments should set rate_limit_rps in config to a sane per-user limit.
        _rate = float(config.get("daemon", {}).get("rate_limit_rps", 1000.0))
        _cap  = max(500, int(_rate * 1.5))
        self._rate_limiter = _TokenBucket(rate=_rate, capacity=_cap)
        self._block_levels: set[RiskLevel] = _DEFAULT_BLOCK_LEVELS
        self._mock_mode: bool = (
            os.environ.get("INTENT_MOCK_MODE", "0") == "1"
            or config.get("daemon", {}).get("mock", False)
        )

    async def initialize(self) -> None:
        """Load rule engine patterns and warm up LLM client."""
        # Load aliases
        shell = os.environ.get("SHELL", "bash").split("/")[-1]
        self._alias_resolver.load(shell=shell)

        threshold = self._config.get("safety", {}).get("block_threshold", "HIGH")
        self._block_levels = self._levels_at_or_above(RiskLevel(threshold))

        if self._mock_mode:
            log.warning("router_mock_mode_active",
                        note="Set INTENT_MOCK_MODE=0 once rule engine + LLM are integrated")
            return

        # Import lazily so missing deps don't break mock mode
        try:
            from engine.rule_engine.classifier import RuleEngineClassifier
            self._rule_engine = RuleEngineClassifier(self._config)
            await self._rule_engine.load_patterns()
        except Exception as e:
            log.error("rule_engine_init_failed", error=str(e))
            log.warning("falling_back_to_mock_mode")
            self._mock_mode = True
            return

        try:
            from engine.llm.reasoner import LLMReasoner
            self._llm_reasoner = LLMReasoner(self._config)
            await self._llm_reasoner.initialize()
        except Exception as e:
            log.warning("llm_init_failed", error=str(e),
                        note="AMBIGUOUS commands will use fallback verdict")

        log.info("router_initialized",
                 block_threshold=threshold,
                 mock=self._mock_mode)

    async def route(self, request: AnalyzeRequest) -> AnalyzeResponse:
        """Main routing pipeline."""
        ctx = request.context
        t_start = time.perf_counter()

        # ── Rate limiting ─────────────────────────────────────────────────────
        if not self._rate_limiter.is_allowed(ctx.session_id or "default"):
            self._stats["rate_limited"] += 1
            log.warning("rate_limit_exceeded", session=ctx.session_id, command=ctx.command[:40])
            return self._build_response(_FALLBACK_VERDICT, request)

        # ── Mock mode (Phase 1 — before real integrations) ────────────────────
        if self._mock_mode:
            self._stats["mock_passthrough"] += 1
            return self._build_response(_MOCK_SAFE_VERDICT, request)

        # ── Tier 0: Session allowlist / denylist ──────────────────────────────
        if self._session.is_always_denied(ctx.command):
            log.info("denylist_block", command=ctx.command[:60])
            self._stats["denylist_blocks"] += 1
            return self._build_response(_ALWAYS_DENY_VERDICT, request)

        if self._session.is_always_allowed(ctx.command, ctx.session_id):
            log.info("allowlist_pass", command=ctx.command[:60])
            self._stats["allowlist_passes"] += 1
            return self._build_response(_ALWAYS_ALLOW_VERDICT, request)

        # ── Parse ──────────────────────────────────────────────────────────────
        parsed = self._parser.parse(ctx.command, ctx.cwd, ctx.user)

        # ── Pre-segment Full-Raw Scan ──────────────────────────────────────────
        # CRITICAL: Some Tier 0 checks (fork bomb, curl|bash) operate on the full
        # raw command string. When the parser splits `:(){ :|:& };:` or
        # `curl http://x.sh | bash` into chain_segments, each segment loses
        # the structural pattern that makes it dangerous.
        # Fix: classify the FULL un-split parsed command first. If it returns a
        # blockable verdict, short-circuit immediately before segment iteration.
        if self._rule_engine is not None:
            t_pre = time.perf_counter()
            full_verdict = await self._rule_engine.classify(parsed, ctx)
            full_verdict.latency_ms = (time.perf_counter() - t_pre) * 1000
            if full_verdict.risk_level in self._block_levels:
                self._stats[f"tier1_{full_verdict.risk_level.value}"] += 1
                self._enrich_alternative(ctx.command, full_verdict)
                self._log_verdict(ctx.command, full_verdict, t_start)
                return self._build_response(full_verdict, request)

        # ── Tier 1/2: Iterate over segments ───────────────────────────────────
        highest_verdict = _FALLBACK_VERDICT
        highest_risk_val = -1

        segments = parsed.chain_segments if parsed.chain_segments else [parsed]

        for seg in segments:
            if self._rule_engine is None:
                verdict = _FALLBACK_VERDICT
            else:
                t0 = time.perf_counter()
                rule_verdict = await self._rule_engine.classify(seg, ctx)
                rule_verdict.latency_ms = (time.perf_counter() - t0) * 1000
                self._stats[f"tier1_{rule_verdict.risk_level.value}"] += 1

                if rule_verdict.risk_level != RiskLevel.AMBIGUOUS:
                    verdict = rule_verdict
                else:
                    self._stats["llm_escalations"] += 1
                    log.info("escalating_to_llm", command=seg.raw[:60])

                    if self._llm_reasoner is None:
                        self._stats["llm_unavailable"] += 1
                        verdict = _FALLBACK_VERDICT
                    else:
                        try:
                            t1 = time.perf_counter()
                            llm_verdict = await self._llm_reasoner.reason(seg, ctx, rule_verdict)
                            llm_verdict.latency_ms = (time.perf_counter() - t1) * 1000
                            self._stats[f"tier2_{llm_verdict.risk_level.value}"] += 1
                            verdict = llm_verdict
                        except TimeoutError:
                            log.warning("llm_timeout", command=seg.raw[:60])
                            self._stats["llm_timeouts"] += 1
                            verdict = _FALLBACK_VERDICT
                        except Exception as e:
                            log.error("llm_error", error=str(e), command=seg.raw[:60])
                            self._stats["llm_errors"] += 1
                            verdict = _FALLBACK_VERDICT

            # Track highest risk verdict
            risk_val = self._risk_value(verdict.risk_level)
            if risk_val > highest_risk_val:
                highest_risk_val = risk_val
                highest_verdict = verdict

            # Short-circuit if blockable
            if verdict.risk_level in self._block_levels:
                self._enrich_alternative(ctx.command, verdict)
                self._log_verdict(ctx.command, verdict, t_start)
                return self._build_response(verdict, request)

        self._log_verdict(ctx.command, highest_verdict, t_start)
        return self._build_response(highest_verdict, request)

    def _risk_value(self, risk: RiskLevel) -> int:
        order = [RiskLevel.SAFE, RiskLevel.LOW, RiskLevel.MEDIUM, RiskLevel.HIGH, RiskLevel.CRITICAL, RiskLevel.AMBIGUOUS]
        try:
            return order.index(risk)
        except ValueError:
            return -1

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _enrich_alternative(self, command: str, verdict: Verdict) -> None:
        """
        If the verdict has no safer_alternative yet, ask Vansh's
        AlternativeGenerator for a template-based one.
        Silently no-ops on any failure — never crashes the pipeline.
        """
        if verdict.safer_alternative:
            return  # Already populated by LLM reasoner or rule engine
        try:
            from engine.contracts.intent_result import IntentResult
            from engine.contracts.intent_result import RiskLevel as VRiskLevel
            # AMBIGUOUS has no equivalent in Vansh's contract — skip
            if verdict.risk_level.value not in {v.value for v in VRiskLevel}:
                return
            proxy = IntentResult(
                command=command,
                risk_level=VRiskLevel(verdict.risk_level.value),
                confidence=verdict.confidence,
                intent=verdict.reasoning[:80] if verdict.reasoning else "unknown",
                impact=verdict.impact_summary or "unknown impact",
                reversible=False,
                requires_confirmation=True,
                explanation=verdict.reasoning or "no explanation",
            )
            alt = self._alt_generator.generate(proxy)
            if alt:
                    validated = self._alt_validator.validate(alt)
                    # Only surface VALIDATED alternatives to the user
                    if validated.status.value == "VALIDATED":
                        try:
                            verdict.safer_alternative = validated.candidate_command
                            verdict.safer_alternative_explanation = validated.explanation
                        except Exception:
                            object.__setattr__(verdict, "safer_alternative", validated.candidate_command)
                            object.__setattr__(verdict, "safer_alternative_explanation", validated.explanation)
                        self._stats["alternatives_generated"] += 1
        except Exception as e:
            log.debug("alternative_generation_skipped", reason=str(e))

    def _build_response(
        self, verdict: Verdict, request: AnalyzeRequest
    ) -> AnalyzeResponse:
        should_block = (
            verdict.risk_level in self._block_levels
            and not request.dry_run
        )
        return AnalyzeResponse(
            verdict=verdict,
            should_block=should_block,
            session_id=request.context.session_id,
        )

    def _log_verdict(
        self, command: str, verdict: Verdict, t_start: float
    ) -> None:
        total_ms = (time.perf_counter() - t_start) * 1000
        log.info(
            "verdict",
            command=command[:60],
            risk=verdict.risk_level.value,
            confidence=round(verdict.confidence, 2),
            tier=verdict.tier_used,
            total_ms=round(total_ms, 2),
        )

    async def reload_rules(self) -> None:
        """Hot-reload patterns without restarting daemon."""
        if self._rule_engine:
            await self._rule_engine.load_patterns()
            log.info("rules_reloaded")

    def get_stats(self) -> dict[str, int]:
        return dict(self._stats)

    def record_user_action(
        self, session_id: str, command: str, action: str
    ) -> None:
        """Record a user's confirmation action for session tracking."""
        from engine.models import UserAction
        if action == UserAction.ALWAYS_ALLOW:
            self._session.add_session_allow(command, session_id)

    @staticmethod
    def _levels_at_or_above(threshold: RiskLevel) -> set[RiskLevel]:
        order = [
            RiskLevel.SAFE, RiskLevel.LOW, RiskLevel.MEDIUM,
            RiskLevel.HIGH, RiskLevel.CRITICAL,
        ]
        idx = order.index(threshold)
        return set(order[idx:])
