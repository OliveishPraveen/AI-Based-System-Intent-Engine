"""
Unit tests for Vansh's Alternatives Engine
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Tests: AlternativeGenerator, AlternativeValidator, contracts
"""

import pytest

from engine.contracts.intent_result import IntentResult, RiskLevel
from engine.contracts.alternative_result import AlternativeResult, AlternativeStatus
from engine.contracts.rule_result import RuleResult, RuleClassification
from engine.alternatives.generator import AlternativeGenerator
from engine.alternatives.validator import AlternativeValidator
from engine.integration.rule_engine import RuleEngineAdapter


# ── Helpers ───────────────────────────────────────────────────────────────────

def make_intent(
    command: str,
    intent: str = "delete files",
    impact: str = "permanently removes files",
    risk: RiskLevel = RiskLevel.HIGH,
    explanation: str = "rm removes files recursively",
    reversible: bool = False,
) -> IntentResult:
    return IntentResult(
        command=command,
        risk_level=risk,
        confidence=0.9,
        intent=intent,
        impact=impact,
        reversible=reversible,
        requires_confirmation=True,
        explanation=explanation,
    )


class StubRuleEngine(RuleEngineAdapter):
    """Test double — always returns SAFE for any command."""
    def analyze(self, command: str) -> RuleResult:
        return RuleResult(
            command=command,
            classification=RuleClassification.SAFE,
            confidence=0.98,
            matched_rules=["safe_stub"],
        )


class DangerousStubRuleEngine(RuleEngineAdapter):
    """Test double — always returns DANGEROUS."""
    def analyze(self, command: str) -> RuleResult:
        return RuleResult(
            command=command,
            classification=RuleClassification.DANGEROUS,
            confidence=0.99,
            matched_rules=["dangerous_stub"],
        )


# ── AlternativeGenerator ──────────────────────────────────────────────────────

class TestAlternativeGenerator:
    """Generator selects a strategy and produces a candidate command."""

    def setup_method(self):
        self.gen = AlternativeGenerator()

    def test_file_deletion_strategy(self):
        result = make_intent("find . -name '*.log' -delete",
                             intent="delete files", impact="deletes files")
        alt = self.gen.generate(result)
        assert alt is not None
        assert alt.strategy == "Inspect before deletion"
        assert alt.candidate_command == "find . -type f -print"
        assert alt.original_command == result.command

    def test_directory_deletion_strategy(self):
        result = make_intent("rm -rf /tmp/old",
                             intent="remove directory", impact="deletes directory")
        alt = self.gen.generate(result)
        assert alt is not None
        assert alt.strategy == "Move to trash"
        assert "gio trash" in alt.candidate_command

    def test_permission_change_strategy(self):
        result = make_intent("chmod -R 777 /var/www",
                             intent="change permissions", impact="modifies permissions")
        alt = self.gen.generate(result)
        assert alt is not None
        assert alt.strategy == "Inspect permissions first"
        assert "ls -la" in alt.candidate_command

    def test_disk_operation_strategy(self):
        result = make_intent("mkfs.ext4 /dev/sdb",
                             intent="format disk", impact="formats the disk partition")
        alt = self.gen.generate(result)
        assert alt is not None
        assert alt.strategy == "Inspect target device"
        assert "lsblk" in alt.candidate_command

    def test_no_strategy_returns_none(self):
        """Commands with no known strategy return None instead of raising."""
        result = make_intent("ssh user@host", intent="connect remotely",
                             impact="opens remote session")
        alt = self.gen.generate(result)
        assert alt is None

    def test_alternative_has_required_fields(self):
        result = make_intent("find /tmp -delete", intent="delete files",
                             impact="deletes files in /tmp")
        alt = self.gen.generate(result)
        assert alt is not None
        assert alt.original_command == result.command
        assert len(alt.candidate_command) > 0
        assert len(alt.strategy) > 0
        assert len(alt.explanation) > 0
        assert alt.status == AlternativeStatus.GENERATED

    def test_intent_propagated(self):
        result = make_intent("rm -rf node_modules",
                             intent="remove directory node_modules",
                             impact="removes directory")
        alt = self.gen.generate(result)
        assert alt is not None
        assert alt.intent == result.intent


# ── AlternativeValidator ──────────────────────────────────────────────────────

class TestAlternativeValidator:
    """Validator stamps VALIDATED/REJECTED based on rule engine feedback."""

    def _make_alt(self, cmd: str) -> AlternativeResult:
        return AlternativeResult(
            original_command="rm -rf /tmp/test",
            candidate_command=cmd,
            intent="delete directory",
            strategy="Move to trash",
            explanation="Use gio trash instead of rm.",
        )

    def test_validates_safe_alternative(self):
        validator = AlternativeValidator(StubRuleEngine())
        alt = self._make_alt("gio trash /tmp/test")
        result = validator.validate(alt)
        assert result.status == AlternativeStatus.VALIDATED

    def test_rejects_dangerous_alternative(self):
        validator = AlternativeValidator(DangerousStubRuleEngine())
        alt = self._make_alt("rm -rf /tmp/test")
        result = validator.validate(alt)
        assert result.status == AlternativeStatus.REJECTED

    def test_original_command_unchanged(self):
        validator = AlternativeValidator(StubRuleEngine())
        alt = self._make_alt("ls /tmp")
        result = validator.validate(alt)
        assert result.original_command == "rm -rf /tmp/test"


# ── Contracts ─────────────────────────────────────────────────────────────────

class TestContracts:
    """Pydantic model validation for all three contract types."""

    def test_intent_result_valid(self):
        r = IntentResult(
            command="ls /tmp",
            risk_level=RiskLevel.SAFE,
            confidence=0.99,
            intent="list directory contents",
            impact="no impact",
            reversible=True,
            requires_confirmation=False,
            explanation="ls is a read-only command.",
        )
        assert r.command == "ls /tmp"
        assert r.risk_level == RiskLevel.SAFE

    def test_intent_result_confidence_bounds(self):
        with pytest.raises(Exception):
            IntentResult(
                command="ls", risk_level=RiskLevel.SAFE,
                confidence=1.5,   # invalid
                intent="x", impact="x", reversible=True,
                requires_confirmation=False, explanation="x",
            )

    def test_rule_result_valid(self):
        r = RuleResult(
            command="rm -rf /",
            classification=RuleClassification.DANGEROUS,
            confidence=1.0,
            matched_rules=["rm_rf_root"],
        )
        assert r.classification == RuleClassification.DANGEROUS
        assert "rm_rf_root" in r.matched_rules

    def test_alternative_result_default_status(self):
        a = AlternativeResult(
            original_command="rm -rf /",
            candidate_command="gio trash /",
            intent="delete root",
            strategy="Move to trash",
            explanation="Use trash.",
        )
        assert a.status == AlternativeStatus.GENERATED

    def test_risk_level_enum_values(self):
        assert RiskLevel.SAFE.value == "SAFE"
        assert RiskLevel.CRITICAL.value == "CRITICAL"
        levels = [RiskLevel.SAFE, RiskLevel.LOW, RiskLevel.MEDIUM,
                  RiskLevel.HIGH, RiskLevel.CRITICAL]
        assert len(levels) == 5
