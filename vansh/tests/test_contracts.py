from engine.contracts.rule_result import RuleResult, RuleClassification
from engine.contracts.intent_result import IntentResult, RiskLevel
from engine.contracts.alternative_result import AlternativeResult


def test_rule_result():
    result = RuleResult(
        command="find . -type f -delete",
        classification=RuleClassification.AMBIGUOUS,
        confidence=0.42,
        matched_rules=[],
        context={"shell": "bash"}
    )

    assert result.command == "find . -type f -delete"
    assert result.classification == RuleClassification.AMBIGUOUS
    assert result.confidence == 0.42


def test_intent_result():
    result = IntentResult(
        command="find . -type f -delete",
        risk_level=RiskLevel.HIGH,
        confidence=0.91,
        intent="Delete files recursively",
        impact="Potential permanent data loss",
        affected_resources=["filesystem"],
        reversible=False,
        requires_confirmation=True,
        explanation="The command recursively deletes files."
    )

    assert result.risk_level == RiskLevel.HIGH
    assert result.reversible is False
    assert result.requires_confirmation is True


def test_alternative_result():
    result = AlternativeResult(
        original_command="find . -type f -delete",
        candidate_command="find . -type f -print",
        intent="Delete files",
        strategy="Inspect files first",
        explanation="Lists matching files without deleting them."
    )

    assert result.original_command == "find . -type f -delete"
    assert result.candidate_command == "find . -type f -print"