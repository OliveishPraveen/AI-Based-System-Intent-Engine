"""
Integration Adapters
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Abstract interface + concrete implementation that bridges
Vansh's Alternative Engine to Praveen's Rule Engine.
"""
from engine.integration.rule_engine import RuleEngineAdapter
from engine.integration.pattern_matcher_adapter import PatternMatcherAdapter

__all__ = ["RuleEngineAdapter", "PatternMatcherAdapter"]

