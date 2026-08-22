"""
PatternMatcherAdapter — Owner: Harshit
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Concrete implementation of Vansh's RuleEngineAdapter interface.
Wraps Praveen's PatternMatcher/Classifier so AlternativeValidator
can synchronously verify that a suggested alternative command is
safe before presenting it to the user.

Mapping:
  engine.models.RiskLevel         →   contracts.rule_result.RuleClassification
  SAFE                            →   SAFE
  LOW / MEDIUM                    →   AMBIGUOUS
  HIGH / CRITICAL / AMBIGUOUS     →   DANGEROUS
"""

from __future__ import annotations

from engine.contracts.rule_result import RuleClassification, RuleResult
from engine.integration.rule_engine import RuleEngineAdapter


class PatternMatcherAdapter(RuleEngineAdapter):
    """
    Synchronous bridge between Vansh's AlternativeValidator
    and Praveen's PatternMatcher rule engine.

    Lazy-initialises the classifier on first call so it can be
    instantiated cheaply without touching the filesystem.
    """

    def __init__(self) -> None:
        self._classifier = None   # lazy init

    def _ensure_loaded(self) -> None:
        if self._classifier is None:
            from engine.rule_engine.classifier import RuleEngineClassifier
            clf = RuleEngineClassifier()
            clf.load_patterns_sync()
            self._classifier = clf

    def analyze(self, command: str) -> RuleResult:
        """
        Analyze a candidate alternative command using the rule engine.
        Returns a RuleResult with SAFE / DANGEROUS / AMBIGUOUS classification.
        """
        self._ensure_loaded()

        from engine.models import RiskLevel
        from engine.parser.command_parser import CommandParser
        from engine.models import CommandContext

        parser = CommandParser()
        ctx = CommandContext(
            command=command,
            cwd="/tmp",           # neutral CWD for alternative validation
            user="validator",
            is_sudo=False,
            shell="zsh",
            session_id="validation",
        )
        parsed = parser.parse(command, cwd="/tmp", user="validator")

        # Use the synchronous pattern matcher directly (no async needed here)
        matcher = self._classifier._matcher  # type: ignore[attr-defined]

        # Tier 0 check
        tier0 = matcher.check_tier0(parsed)
        if tier0 is not None:
            return RuleResult(
                command=command,
                classification=RuleClassification.DANGEROUS,
                confidence=tier0.confidence,
                matched_rules=[tier0.matched_pattern or "tier0"],
                context={"tier": "0", "risk": tier0.risk_level.value},
            )

        # Tier 1 check
        result = matcher.match(parsed, ctx)
        if result is None:
            # No match → ambiguous but lean safe for alternatives
            return RuleResult(
                command=command,
                classification=RuleClassification.AMBIGUOUS,
                confidence=0.4,
                matched_rules=[],
                context={"tier": "1", "note": "no_match"},
            )

        if result.risk_level == RiskLevel.SAFE:
            return RuleResult(
                command=command,
                classification=RuleClassification.SAFE,
                confidence=result.confidence,
                matched_rules=[result.pattern_name],
                context={"tier": "1", "risk": result.risk_level.value},
            )

        if result.risk_level in {RiskLevel.LOW, RiskLevel.MEDIUM}:
            return RuleResult(
                command=command,
                classification=RuleClassification.AMBIGUOUS,
                confidence=result.confidence,
                matched_rules=[result.pattern_name],
                context={"tier": "1", "risk": result.risk_level.value},
            )

        # HIGH / CRITICAL
        return RuleResult(
            command=command,
            classification=RuleClassification.DANGEROUS,
            confidence=result.confidence,
            matched_rules=[result.pattern_name],
            context={"tier": "1", "risk": result.risk_level.value},
        )
