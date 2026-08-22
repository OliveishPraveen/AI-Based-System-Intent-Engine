from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class RuleClassification(str, Enum):
    SAFE      = "SAFE"
    DANGEROUS = "DANGEROUS"
    AMBIGUOUS = "AMBIGUOUS"


class RuleResult(BaseModel):
    """
    Result produced by the deterministic rule engine.

    Input contract between Praveen's rule engine
    and Vansh's Tier-2 reasoning engine.
    """

    command: str = Field(min_length=1)

    classification: RuleClassification

    confidence: float = Field(ge=0.0, le=1.0)

    matched_rules: list[str] = Field(default_factory=list)

    context: dict[str, Any] = Field(default_factory=dict)
