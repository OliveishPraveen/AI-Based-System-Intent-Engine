from engine.contracts.intent_result import IntentResult, RiskLevel

from engine.risk.thresholds import (
    CONFIRMATION_RISK_LEVELS,
    DESTRUCTIVE_OPERATIONS,
    MIN_LLM_CONFIDENCE,
)


RISK_ORDER = {
    RiskLevel.SAFE: 0,
    RiskLevel.LOW: 1,
    RiskLevel.MEDIUM: 2,
    RiskLevel.HIGH: 3,
    RiskLevel.CRITICAL: 4,
}


class SemanticRiskScorer:
    """
    Converts LLM semantic analysis into a safer application-level
    risk decision.
    """

    def score(self, result: IntentResult) -> IntentResult:
        """
        Apply deterministic safety adjustments to an IntentResult.
        """

        risk_level = result.risk_level

        # ---------------------------------------------------------
        # 1. Low-confidence LLM output
        # ---------------------------------------------------------

        if result.confidence < MIN_LLM_CONFIDENCE:
            risk_level = self._escalate(
                risk_level,
                RiskLevel.LOW,
            )

        # ---------------------------------------------------------
        # 2. Irreversible operation
        # ---------------------------------------------------------

        if not result.reversible:
            risk_level = self._escalate(
                risk_level,
                RiskLevel.MEDIUM,
            )

            result.requires_confirmation = True

        # ---------------------------------------------------------
        # 3. Destructive semantic intent
        # ---------------------------------------------------------

        if self._is_destructive(result):

            risk_level = self._escalate(
                risk_level,
                RiskLevel.MEDIUM,
            )

            result.reversible = False
            result.requires_confirmation = True

        # ---------------------------------------------------------
        # 4. High / Critical always require confirmation
        # ---------------------------------------------------------

        if risk_level in CONFIRMATION_RISK_LEVELS:
            result.requires_confirmation = True

        # ---------------------------------------------------------
        # 5. Store final risk
        # ---------------------------------------------------------

        result.risk_level = risk_level

        return result

    def _is_destructive(self, result: IntentResult) -> bool:
        """
        Determine whether the semantic analysis describes
        a destructive operation.
        """

        text = (
            result.intent
            + " "
            + result.impact
            + " "
            + result.explanation
        ).lower()

        return any(
            operation in text
            for operation in DESTRUCTIVE_OPERATIONS
        )

    @staticmethod
    def _escalate(
        current: RiskLevel,
        minimum: RiskLevel,
    ) -> RiskLevel:
        """
        Return whichever risk level is higher.
        """

        if RISK_ORDER[current] >= RISK_ORDER[minimum]:
            return current

        return minimum