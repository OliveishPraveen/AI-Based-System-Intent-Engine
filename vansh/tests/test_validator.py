from engine.contracts.rule_result import (
    RuleResult,
    RuleClassification,
)
from engine.contracts.alternative_result import (
    AlternativeResult,
    AlternativeStatus,
)
from engine.alternatives.validator import AlternativeValidator
from engine.integration.rule_engine import RuleEngineAdapter


class MockRuleEngine(RuleEngineAdapter):

    def __init__(self, classification):
        self.classification = classification

    def analyze(self, command: str) -> RuleResult:
        return RuleResult(
            command=command,
            classification=self.classification,
            confidence=0.95,
            matched_rules=[],
            context={
                "shell": "bash",
                "cwd": "/home/vansh/project",
            },
        )


def create_alternative():
    return AlternativeResult(
        original_command="find . -type f -delete",
        candidate_command="find . -type f -print",
        intent="Delete files",
        strategy="Inspect before deletion",
        explanation="Lists files without deleting them.",
    )


def test_safe_alternative_is_validated():

    engine = MockRuleEngine(
        RuleClassification.SAFE
    )

    validator = AlternativeValidator(engine)

    alternative = create_alternative()

    result = validator.validate(alternative)

    assert result.status == AlternativeStatus.VALIDATED


def test_unsafe_alternative_is_rejected():

    engine = MockRuleEngine(
        RuleClassification.AMBIGUOUS
    )

    validator = AlternativeValidator(engine)

    alternative = create_alternative()

    result = validator.validate(alternative)

    assert result.status == AlternativeStatus.REJECTED