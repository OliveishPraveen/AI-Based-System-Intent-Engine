"""
Contracts
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Shared Pydantic contracts between the Rule Engine (Praveen),
the LLM Reasoner (Vansh), and the Alternative Generator (Vansh).
"""
from engine.contracts.intent_result import IntentResult, RiskLevel
from engine.contracts.rule_result import RuleResult, RuleClassification
from engine.contracts.alternative_result import AlternativeResult, AlternativeStatus

__all__ = [
    "IntentResult",
    "RiskLevel",
    "RuleResult",
    "RuleClassification",
    "AlternativeResult",
    "AlternativeStatus",
]
