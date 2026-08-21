from engine.contracts.intent_result import IntentResult, RiskLevel
from engine.risk.semantic_scoring import SemanticRiskScorer


def test_destructive_operation_is_not_reversible():

    result = IntentResult(
        command="find . -type f -delete",
        risk_level=RiskLevel.LOW,
        confidence=0.90,
        intent="Delete all files",
        impact="Permanent deletion of files",
        affected_resources=["filesystem"],
        reversible=True,
        requires_confirmation=False,
        explanation="The command deletes files permanently."
    )

    result = SemanticRiskScorer().score(result)

    assert result.reversible is False
    assert result.requires_confirmation is True
    assert result.risk_level == RiskLevel.MEDIUM


def test_low_confidence_safe_result_is_escalated():

    result = IntentResult(
        command="some-command",
        risk_level=RiskLevel.SAFE,
        confidence=0.30,
        intent="Perform an unknown operation",
        impact="The impact is uncertain",
        affected_resources=[],
        reversible=True,
        requires_confirmation=False,
        explanation="The model is uncertain."
    )

    result = SemanticRiskScorer().score(result)

    assert result.risk_level == RiskLevel.LOW


def test_high_risk_always_requires_confirmation():

    result = IntentResult(
        command="dangerous-command",
        risk_level=RiskLevel.HIGH,
        confidence=0.95,
        intent="Perform a dangerous operation",
        impact="Potential system damage",
        affected_resources=["system"],
        reversible=False,
        requires_confirmation=False,
        explanation="This operation can seriously damage the system."
    )

    result = SemanticRiskScorer().score(result)

    assert result.risk_level == RiskLevel.HIGH
    assert result.requires_confirmation is True


def test_risk_is_never_downgraded():

    result = IntentResult(
        command="critical-command",
        risk_level=RiskLevel.CRITICAL,
        confidence=0.95,
        intent="Destroy critical resources",
        impact="Severe damage",
        affected_resources=["system"],
        reversible=False,
        requires_confirmation=True,
        explanation="Critical destructive operation."
    )

    result = SemanticRiskScorer().score(result)

    assert result.risk_level == RiskLevel.CRITICAL