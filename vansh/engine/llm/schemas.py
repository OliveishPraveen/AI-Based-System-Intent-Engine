from pydantic import BaseModel, Field

from engine.contracts.intent_result import RiskLevel


class LLMIntentResponse(BaseModel):
    """
    Structured response expected from the LLM.
    """

    risk_level: RiskLevel

    confidence: float = Field(ge=0.0, le=1.0)

    intent: str = Field(min_length=1)

    impact: str = Field(min_length=1)

    affected_resources: list[str] = Field(default_factory=list)

    reversible: bool

    requires_confirmation: bool

    explanation: str = Field(min_length=1)