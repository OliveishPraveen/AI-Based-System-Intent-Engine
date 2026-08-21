from abc import ABC, abstractmethod

from engine.contracts.rule_result import RuleResult


class RuleEngineAdapter(ABC):
    """
    Interface between Vansh's Alternative Validator
    and Praveen's Rule Engine.
    """

    @abstractmethod
    def analyze(self, command: str) -> RuleResult:
        """
        Analyze a command using the Rule Engine.
        """
        pass