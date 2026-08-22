from engine.contracts.intent_result import RiskLevel


# Minimum confidence required before trusting an LLM risk classification.
MIN_LLM_CONFIDENCE = 0.60

# Risk levels that always require confirmation.
CONFIRMATION_RISK_LEVELS = {
    RiskLevel.HIGH,
    RiskLevel.CRITICAL,
}

# Operations that are inherently destructive (matched against semantic text).
DESTRUCTIVE_OPERATIONS = {
    "delete",
    "remove",
    "format",
    "overwrite",
    "truncate",
    "destroy",
}


def requires_confirmation(risk_level: RiskLevel) -> bool:
    """Determine whether a risk level requires user confirmation."""
    return risk_level in CONFIRMATION_RISK_LEVELS
