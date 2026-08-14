"""
Response Parser — Owner: Vansh
Parses and validates the LLM's JSON response into a structured object.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Optional

from engine.models import RiskLevel


@dataclass
class ParsedLLMResponse:
    risk_level: RiskLevel
    confidence: float
    reasoning: str
    impact_summary: str
    safer_alternative: Optional[str] = None


class ResponseParser:
    """Parses, validates, and normalizes LLM JSON output."""

    _VALID_LEVELS = {l.value for l in RiskLevel} - {RiskLevel.AMBIGUOUS.value}

    def parse(self, raw_content: str) -> ParsedLLMResponse:
        """
        Parse raw LLM response string into ParsedLLMResponse.
        Raises ValueError if response is malformed or invalid.
        """
        # Strip markdown code fences if present
        content = raw_content.strip()
        if content.startswith("```"):
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]

        try:
            data = json.loads(content)
        except json.JSONDecodeError as e:
            raise ValueError(f"LLM returned invalid JSON: {e}\nRaw: {raw_content[:200]}")

        # Validate risk level
        risk_str = str(data.get("risk_level", "")).upper()
        if risk_str not in self._VALID_LEVELS:
            raise ValueError(f"Invalid risk_level '{risk_str}' from LLM")

        confidence = float(data.get("confidence", 0.5))
        confidence = max(0.0, min(1.0, confidence))

        return ParsedLLMResponse(
            risk_level=RiskLevel(risk_str),
            confidence=confidence,
            reasoning=str(data.get("reasoning", "No reasoning provided")),
            impact_summary=str(data.get("impact_summary", "Impact unknown")),
            safer_alternative=data.get("safer_alternative"),
        )
