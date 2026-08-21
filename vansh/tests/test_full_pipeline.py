from engine.contracts.rule_result import (
    RuleResult,
    RuleClassification,
)
from engine.contracts.alternative_result import (
    AlternativeStatus,
)
from engine.llm.ollama_client import OllamaClient
from engine.llm.reasoner import IntentReasoner
from engine.risk.semantic_scoring import SemanticRiskScorer
from engine.alternatives.generator import AlternativeGenerator
from engine.alternatives.validator import AlternativeValidator
from engine.integration.rule_engine import RuleEngineAdapter


class MockRuleEngine(RuleEngineAdapter):
    """
    Temporary test adapter.

    This will later be replaced by Praveen's actual
    Rule Engine adapter.
    """

    def analyze(self, command: str) -> RuleResult:

        # For the generated alternative
        # find ... -print should be considered safe.
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


def test_full_intent_engine_pipeline():

    # ---------------------------------------------------------
    # 1. Simulated input from Praveen's Rule Engine
    # ---------------------------------------------------------

    rule_result = RuleResult(
        command="find . -type f -delete",
        classification=RuleClassification.AMBIGUOUS,
        confidence=0.42,
        matched_rules=[],
        context={
            "shell": "bash",
            "cwd": "/home/vansh/project",
        },
    )

    # ---------------------------------------------------------
    # 2. Intent Reasoning
    # ---------------------------------------------------------

    llm_client = OllamaClient()

    reasoner = IntentReasoner(llm_client)

    intent_result = reasoner.analyze(rule_result)

    assert intent_result.command == rule_result.command
    assert intent_result.intent
    assert intent_result.impact
    assert intent_result.explanation

    # ---------------------------------------------------------
    # 3. Semantic Risk Scoring
    # ---------------------------------------------------------

    scorer = SemanticRiskScorer()

    final_intent = scorer.score(intent_result)

    assert final_intent.risk_level
    assert final_intent.requires_confirmation is True

    # ---------------------------------------------------------
    # 4. Generate safer alternative
    # ---------------------------------------------------------

    generator = AlternativeGenerator()

    alternative = generator.generate(final_intent)

    assert alternative.original_command == (
        rule_result.command
    )

    assert alternative.candidate_command

    assert alternative.status == AlternativeStatus.GENERATED

    # ---------------------------------------------------------
    # 5. Validate alternative
    # ---------------------------------------------------------

    rule_engine = MockRuleEngine()

    validator = AlternativeValidator(rule_engine)

    validated = validator.validate(alternative)

    # ---------------------------------------------------------
    # 6. Final result
    # ---------------------------------------------------------

    assert validated.status == AlternativeStatus.VALIDATED

    print("\n==============================")
    print("FULL PIPELINE RESULT")
    print("==============================")

    print("\nOriginal command:")
    print(rule_result.command)

    print("\nIntent:")
    print(final_intent.intent)

    print("\nRisk:")
    print(final_intent.risk_level)

    print("\nImpact:")
    print(final_intent.impact)

    print("\nRequires confirmation:")
    print(final_intent.requires_confirmation)

    print("\nSafer strategy:")
    print(alternative.strategy)

    print("\nAlternative:")
    print(alternative.candidate_command)

    print("\nAlternative status:")
    print(validated.status)