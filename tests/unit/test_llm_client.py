"""
Unit tests for the LLM Client and Reasoner — Owner: Vansh
Tests use mocked LLM responses — never make real API calls in unit tests.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from engine.llm.response_parser import ResponseParser
from engine.models import RiskLevel


class TestResponseParser:
    """Test LLM response parsing and validation."""

    parser = ResponseParser()

    def test_valid_high_risk_response(self):
        raw = '''{
            "risk_level": "HIGH",
            "confidence": 0.92,
            "reasoning": "This command deletes active log files.",
            "impact_summary": "Permanently removes all system logs.",
            "safer_alternative": "journalctl --vacuum-size=500M"
        }'''
        result = self.parser.parse(raw)
        assert result.risk_level == RiskLevel.HIGH
        assert result.confidence == 0.92
        assert result.safer_alternative == "journalctl --vacuum-size=500M"

    def test_valid_safe_response(self):
        raw = '''{
            "risk_level": "SAFE",
            "confidence": 0.99,
            "reasoning": "ls is a read-only listing command.",
            "impact_summary": "Lists files without modifying anything.",
            "safer_alternative": null
        }'''
        result = self.parser.parse(raw)
        assert result.risk_level == RiskLevel.SAFE
        assert result.safer_alternative is None

    def test_invalid_json_raises(self):
        with pytest.raises(ValueError, match="invalid JSON"):
            self.parser.parse("not json at all")

    def test_invalid_risk_level_raises(self):
        raw = '{"risk_level": "UNKNOWN", "confidence": 0.5, "reasoning": "x", "impact_summary": "x"}'
        with pytest.raises(ValueError, match="Invalid risk_level"):
            self.parser.parse(raw)

    def test_strips_markdown_fences(self):
        raw = '''```json
{"risk_level": "MEDIUM", "confidence": 0.7, "reasoning": "x", "impact_summary": "y"}
```'''
        result = self.parser.parse(raw)
        assert result.risk_level == RiskLevel.MEDIUM

    def test_confidence_clamped(self):
        raw = '{"risk_level": "LOW", "confidence": 1.5, "reasoning": "x", "impact_summary": "y"}'
        result = self.parser.parse(raw)
        assert result.confidence == 1.0

    def test_ambiguous_not_valid_output(self):
        """LLM must never return AMBIGUOUS — that's only for the rule engine."""
        raw = '{"risk_level": "AMBIGUOUS", "confidence": 0.5, "reasoning": "x", "impact_summary": "y"}'
        with pytest.raises(ValueError):
            self.parser.parse(raw)


class TestLLMReasoner:
    """Integration-level tests for the LLM reasoner with mocked client."""

    @pytest.mark.asyncio
    async def test_reason_returns_verdict_on_success(self):
        """Vansh: implement test that mocks LLM client and verifies Verdict output."""
        pass  # Vansh: implement

    @pytest.mark.asyncio
    async def test_reason_raises_timeout_on_slow_llm(self):
        """Vansh: implement test that verifies TimeoutError is raised when LLM is slow."""
        pass  # Vansh: implement

    @pytest.mark.asyncio
    async def test_reason_uses_safer_alternative_from_llm(self):
        """Vansh: verify that safer_alternative from LLM response is included in Verdict."""
        pass  # Vansh: implement
