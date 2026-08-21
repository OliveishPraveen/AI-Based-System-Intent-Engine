import json

from engine.contracts.intent_result import IntentResult, RiskLevel
from engine.contracts.rule_result import RuleResult
from engine.llm.client import LLMClient
from engine.llm.prompts import build_intent_prompt
from engine.llm.schemas import LLMIntentResponse


class IntentReasoner:
    """
    Semantic reasoning layer for ambiguous Linux commands.
    """

    def __init__(self, client: LLMClient):
        self.client = client

    def analyze(self, rule_result: RuleResult) -> IntentResult:
        """
        Analyze a command using the configured LLM.
        """

        # 1. Build dynamic prompt
        prompt = build_intent_prompt(rule_result)

        # 2. Call LLM
        raw_response = self.client.generate(prompt)

        # 3. Parse JSON
        data = json.loads(raw_response)

        # 4. Validate LLM response
        llm_result = LLMIntentResponse.model_validate(data)

        # 5. Apply basic safety sanity checks
        llm_result = self._apply_sanity_checks(
            rule_result.command,
            llm_result,
        )

        # 6. Convert to application-level IntentResult
        return IntentResult(
            command=rule_result.command,
            risk_level=llm_result.risk_level,
            confidence=llm_result.confidence,
            intent=llm_result.intent,
            impact=llm_result.impact,
            affected_resources=llm_result.affected_resources,
            reversible=llm_result.reversible,
            requires_confirmation=llm_result.requires_confirmation,
            explanation=llm_result.explanation,
        )

    def _apply_sanity_checks(
        self,
        command: str,
        result: LLMIntentResponse,
    ) -> LLMIntentResponse:
        """
        Apply deterministic sanity checks to the LLM response.

        The LLM is not trusted blindly for safety-critical properties.
        """

        destructive_indicators = [
            " -delete",
            "rm ",
            "rm\t",
            "mkfs",
            "dd ",
            "truncate ",
        ]

        command_lower = command.lower()

        is_destructive = any(
            indicator in command_lower
            for indicator in destructive_indicators
        )

        if is_destructive:
            result.reversible = False
            result.requires_confirmation = True

        if result.risk_level in {
            RiskLevel.HIGH,
            RiskLevel.CRITICAL,
        }:
            result.requires_confirmation = True

        return result