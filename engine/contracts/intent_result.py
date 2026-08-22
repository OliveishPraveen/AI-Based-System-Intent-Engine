from enum import Enum

from pydantic import BaseModel, Field


class RiskLevel(str, Enum):
    SAFE     = "SAFE"
    LOW      = "LOW"
    MEDIUM   = "MEDIUM"
    HIGH     = "HIGH"
    CRITICAL = "CRITICAL"


class IntentResult(BaseModel):
    """
    Final application-level semantic analysis result.

    Produced by the IntentReasoner after receiving, validating,
    and processing the LLM response.
    """

    command: str = Field(min_length=1)

    risk_level: RiskLevel

    confidence: float = Field(ge=0.0, le=1.0)

    intent: str = Field(min_length=1)

    impact: str = Field(min_length=1)

    affected_resources: list[str] = Field(default_factory=list)

    reversible: bool

    requires_confirmation: bool

    explanation: str = Field(min_length=1)
