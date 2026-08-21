from engine.contracts.alternative_result import (
    AlternativeResult,
    AlternativeStatus,
)
from engine.integration.rule_engine import RuleEngineAdapter


class AlternativeValidator:
    """
    Validates generated alternatives using the Rule Engine.
    """

    def __init__(self, rule_engine: RuleEngineAdapter):
        self.rule_engine = rule_engine

    def validate(
        self,
        alternative: AlternativeResult,
    ) -> AlternativeResult:

        rule_result = self.rule_engine.analyze(
            alternative.candidate_command
        )

        if rule_result.classification.value == "SAFE":
            alternative.status = AlternativeStatus.VALIDATED

        else:
            alternative.status = AlternativeStatus.REJECTED

        return alternative