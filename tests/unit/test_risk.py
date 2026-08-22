"""
Unit tests for Vansh's Risk Scoring Engine
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Tests: SemanticRiskScorer, thresholds
"""

import pytest

from engine.contracts.intent_result import IntentResult, RiskLevel
from engine.risk.semantic_scoring import SemanticRiskScorer
from engine.risk.thresholds import (
    MIN_LLM_CONFIDENCE,
    CONFIRMATION_RISK_LEVELS,
    DESTRUCTIVE_OPERATIONS,
    requires_confirmation,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def make_result(
    risk: RiskLevel = RiskLevel.MEDIUM,
    confidence: float = 0.85,
    intent: str = "list files",
    impact: str = "no side effects",
    reversible: bool = True,
    requires_confirmation: bool = False,
    explanation: str = "safe read-only command",
) -> IntentResult:
    return IntentResult(
        command="ls /tmp",
        risk_level=risk,
        confidence=confidence,
        intent=intent,
        impact=impact,
        reversible=reversible,
        requires_confirmation=requires_confirmation,
        explanation=explanation,
    )


# ── SemanticRiskScorer ────────────────────────────────────────────────────────

class TestSemanticRiskScorer:

    def setup_method(self):
        self.scorer = SemanticRiskScorer()

    def test_safe_command_stays_safe(self):
        r = make_result(risk=RiskLevel.SAFE, confidence=0.99)
        scored = self.scorer.score(r)
        assert scored.risk_level == RiskLevel.SAFE

    def test_low_confidence_escalates_to_low(self):
        """Confidence below MIN_LLM_CONFIDENCE → escalate to at least LOW."""
        r = make_result(risk=RiskLevel.SAFE, confidence=MIN_LLM_CONFIDENCE - 0.01)
        scored = self.scorer.score(r)
        # SAFE should be escalated to at least LOW
        assert scored.risk_level != RiskLevel.SAFE

    def test_irreversible_escalates_to_medium(self):
        """Irreversible operation → escalate to at least MEDIUM."""
        r = make_result(risk=RiskLevel.LOW, reversible=False, confidence=0.9)
        scored = self.scorer.score(r)
        assert scored.risk_level in {RiskLevel.MEDIUM, RiskLevel.HIGH, RiskLevel.CRITICAL}
        assert scored.requires_confirmation is True

    def test_destructive_intent_escalates(self):
        """Semantic text with 'delete' → escalate to at least MEDIUM."""
        r = make_result(
            risk=RiskLevel.LOW,
            intent="delete files permanently",
            impact="permanent deletion of data",
            reversible=True,
            confidence=0.9,
        )
        scored = self.scorer.score(r)
        assert scored.risk_level in {RiskLevel.MEDIUM, RiskLevel.HIGH, RiskLevel.CRITICAL}
        assert scored.reversible is False
        assert scored.requires_confirmation is True

    def test_high_risk_requires_confirmation(self):
        r = make_result(risk=RiskLevel.HIGH, confidence=0.9)
        scored = self.scorer.score(r)
        assert scored.requires_confirmation is True

    def test_critical_risk_requires_confirmation(self):
        r = make_result(risk=RiskLevel.CRITICAL, confidence=1.0)
        scored = self.scorer.score(r)
        assert scored.requires_confirmation is True

    def test_medium_risk_no_auto_confirmation(self):
        """MEDIUM risk does not automatically require confirmation unless irreversible."""
        r = make_result(risk=RiskLevel.MEDIUM, confidence=0.8,
                        reversible=True, requires_confirmation=False)
        scored = self.scorer.score(r)
        # MEDIUM should stay MEDIUM and not be forced to require confirmation
        assert scored.risk_level == RiskLevel.MEDIUM

    def test_escalate_never_lowers_risk(self):
        """Escalation must only raise, never lower the risk level."""
        r = make_result(risk=RiskLevel.CRITICAL, confidence=0.2)  # low confidence
        scored = self.scorer.score(r)
        assert scored.risk_level == RiskLevel.CRITICAL

    def test_all_destructive_keywords_trigger(self):
        """Every keyword in DESTRUCTIVE_OPERATIONS must trigger escalation."""
        for keyword in DESTRUCTIVE_OPERATIONS:
            r = make_result(
                risk=RiskLevel.LOW,
                intent=f"will {keyword} the target",
                impact="some impact",
                reversible=True,
                confidence=0.9,
            )
            scored = self.scorer.score(r)
            assert scored.requires_confirmation is True, \
                f"Keyword '{keyword}' should have triggered confirmation"


# ── Thresholds ────────────────────────────────────────────────────────────────

class TestThresholds:

    def test_min_llm_confidence_is_reasonable(self):
        assert 0.0 < MIN_LLM_CONFIDENCE < 1.0

    def test_confirmation_risk_levels_contains_high_and_critical(self):
        assert RiskLevel.HIGH in CONFIRMATION_RISK_LEVELS
        assert RiskLevel.CRITICAL in CONFIRMATION_RISK_LEVELS

    def test_safe_does_not_require_confirmation(self):
        assert not requires_confirmation(RiskLevel.SAFE)

    def test_low_does_not_require_confirmation(self):
        assert not requires_confirmation(RiskLevel.LOW)

    def test_medium_does_not_require_confirmation(self):
        assert not requires_confirmation(RiskLevel.MEDIUM)

    def test_high_requires_confirmation(self):
        assert requires_confirmation(RiskLevel.HIGH)

    def test_critical_requires_confirmation(self):
        assert requires_confirmation(RiskLevel.CRITICAL)

    def test_destructive_operations_set_non_empty(self):
        assert len(DESTRUCTIVE_OPERATIONS) > 0
        assert "delete" in DESTRUCTIVE_OPERATIONS
        assert "destroy" in DESTRUCTIVE_OPERATIONS
