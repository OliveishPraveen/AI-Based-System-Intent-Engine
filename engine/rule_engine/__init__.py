"""
Rule Engine Package
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Fast, deterministic Tier 0 and context-weighted Tier 1 command safety classification.

Modules:
  - classifier.py       : Main entry — orchestrates pattern matching & confidence scoring
  - pattern_matcher.py  : Regex + structural pattern matching engine
  - pattern_loader.py   : Loads + validates dangerous_patterns.toml
  - verdict_builder.py  : Dynamic template rendering & verdict construction
  - service.py          : Standalone FastAPI microservice
  - visualizer.py       : Rich CLI inspection & corpus benchmarking
"""

from engine.rule_engine.classifier import RuleEngineClassifier
from engine.rule_engine.pattern_loader import PatternLoader
from engine.rule_engine.pattern_matcher import MatchResult, PatternMatcher
from engine.rule_engine.verdict_builder import VerdictBuilder

__all__ = [
    "RuleEngineClassifier",
    "PatternLoader",
    "PatternMatcher",
    "MatchResult",
    "VerdictBuilder",
]
