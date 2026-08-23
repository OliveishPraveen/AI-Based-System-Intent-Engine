"""
Alternatives Engine
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Generates and validates safer command alternatives when the
intent engine classifies a command as HIGH or CRITICAL risk.
"""
from engine.alternatives.generator import AlternativeGenerator
from engine.alternatives.validator import AlternativeValidator

__all__ = ["AlternativeGenerator", "AlternativeValidator"]
