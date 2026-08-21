from engine.contracts.intent_result import (
    IntentResult,
    RiskLevel,
)
from engine.contracts.rule_result import (
    RuleResult,
    RuleClassification,
)
from engine.contracts.alternative_result import (
    AlternativeStatus,
)
from engine.alternatives.generator import AlternativeGenerator
from engine.alternatives.validator import AlternativeValidator
from engine.integration.rule_engine import RuleEngineAdapter


class MockRuleEngine(RuleEngineAdapter):

    def analyze(self, command: str) -> RuleResult:

        return RuleResult(
            command=command,
            classification=RuleClassification.SAFE,
            confidence=0.98,
            matched_rules=[],
            context={
                "shell": "bash",
                "cwd": "/home/vansh/project",
            },
        )


def test_generate_and_validate_alternative():

    intent_result = IntentResult(
        command="find . -type f -delete",
        risk_level=RiskLevel.MEDIUM,
        confidence=0.90,
        intent="Delete all regular files",
        impact="Permanent deletion of files",
        affected_resources=["filesystem"],
        reversible=False,
        requires_confirmation=True,
        explanation="The command deletes files permanently.",
    )

    # Step 1: Generate
    generator = AlternativeGenerator()

    alternative = generator.generate(intent_result)

    assert alternative.status == AlternativeStatus.GENERATED

    # Step 2: Validate
    rule_engine = MockRuleEngine()

    validator = AlternativeValidator(rule_engine)

    validated = validator.validate(alternative)

    # Step 3: Verify
    assert validated.status == AlternativeStatus.VALIDATED

class AmbiguousRuleEngine(RuleEngineAdapter):

    def analyze(self, command: str) -> RuleResult:

        return RuleResult(
            command=command,
            classification=RuleClassification.AMBIGUOUS,
            confidence=0.40,
            matched_rules=[],
            context={
                "shell": "bash",
                "cwd": "/home/vansh/project",
            },
        )

def test_ambiguous_alternative_is_rejected():

    intent_result = IntentResult(
        command="find . -type f -delete",
        risk_level=RiskLevel.MEDIUM,
        confidence=0.90,
        intent="Delete all regular files",
        impact="Permanent deletion of files",
        affected_resources=["filesystem"],
        reversible=False,
        requires_confirmation=True,
        explanation="The command deletes files permanently.",
    )

    generator = AlternativeGenerator()

    alternative = generator.generate(intent_result)

    rule_engine = AmbiguousRuleEngine()

    validator = AlternativeValidator(rule_engine)

    validated = validator.validate(alternative)

    assert validated.status == AlternativeStatus.REJECTED