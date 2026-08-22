from abc import ABC, abstractmethod

from engine.contracts.rule_result import RuleResult


class RuleEngineAdapter(ABC):
    """
    Abstract interface between Vansh's AlternativeValidator
    and Praveen's PatternMatcher rule engine.
    Implement this in engine/daemon/router.py or wherever
    the PatternMatcher is instantiated.
    """

    @abstractmethod
    def analyze(self, command: str) -> RuleResult:
        """Analyze a command using the Rule Engine."""
        ...
