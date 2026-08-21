from engine.contracts.intent_result import IntentResult, RiskLevel
from engine.contracts.alternative_result import (
    AlternativeResult,
    AlternativeStatus,
)
from engine.alternatives.generator import AlternativeGenerator


def test_alternative_generator_returns_contract():

    intent_result = IntentResult(
        command="find . -type f -delete",
        risk_level=RiskLevel.MEDIUM,
        confidence=0.90,
        intent="Delete all regular files",
        impact="Permanent deletion of files",
        affected_resources=["filesystem"],
        reversible=False,
        requires_confirmation=True,
        explanation="The command deletes files permanently."
    )

    alternative = AlternativeGenerator().generate(intent_result)

    # Correct contract type
    assert isinstance(alternative, AlternativeResult)

    # Original command preserved
    assert alternative.original_command == (
        "find . -type f -delete"
    )

    # Candidate generated
    assert alternative.candidate_command

    # Intent preserved
    assert alternative.intent == intent_result.intent

    # Strategy generated
    assert alternative.strategy

    # Explanation generated
    assert alternative.explanation

    # New alternatives start in GENERATED state
    assert alternative.status == AlternativeStatus.GENERATED