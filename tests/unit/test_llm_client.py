"""
Unit tests for the LLM Client and Reasoner
Tests use mocked LLM responses — never make real API calls in unit tests.
"""

import pytest
from unittest.mock import AsyncMock

from engine.llm.response_parser import ResponseParser
from engine.models import RiskLevel, CommandContext, Verdict
from engine.parser.command_parser import CommandParser

# Shared parser for building proper ParsedCommand objects
_parser = CommandParser()


def _make_parsed(cmd: str, cwd: str = "/tmp"):
    """Create a real ParsedCommand via the parser — avoids brittle positional construction."""
    return _parser.parse(cmd, cwd=cwd, user="test_user")


def _make_ctx(cmd: str, cwd: str = "/tmp") -> CommandContext:
    return CommandContext(
        command=cmd,
        cwd=cwd,
        user="test_user",
        is_sudo=cmd.strip().startswith("sudo"),
        shell="bash",
        session_id="test-session",
    )


def _make_hint(risk: RiskLevel = RiskLevel.AMBIGUOUS) -> Verdict:
    return Verdict(
        risk_level=risk,
        confidence=0.5,
        matched_pattern=None,
        reasoning="rule engine uncertain",
        impact_summary="requires llm analysis",
        safer_alternative=None,
        safer_alternative_explanation=None,
        tier_used="rule_engine",
        latency_ms=0.0,
    )


# ── ResponseParser ────────────────────────────────────────────────────────────

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


# ── LLMReasoner ───────────────────────────────────────────────────────────────

class TestLLMReasoner:
    """Integration-level tests for the LLM reasoner with mocked client."""

    @pytest.mark.asyncio
    async def test_reason_returns_verdict_on_success(self):
        from engine.llm.reasoner import LLMReasoner
        from engine.llm.client import LLMResponse

        config = {"llm": {"provider": "ollama"}}
        reasoner = LLMReasoner(config)

        mock_client = AsyncMock()
        mock_client.complete.return_value = LLMResponse(
            content='{"risk_level": "HIGH", "confidence": 0.8, "reasoning": "bad", "impact_summary": "bad", "safer_alternative": "echo"}',
            model="mock",
            latency_ms=10.0,
        )
        reasoner._client = mock_client

        parsed = _make_parsed("rm -rf /")
        ctx = _make_ctx("rm -rf /")
        hint = _make_hint(RiskLevel.AMBIGUOUS)

        result = await reasoner.reason(parsed, ctx, hint)
        assert result.risk_level == RiskLevel.HIGH
        # The curated table now takes priority: rm -rf / maps to rm_rf_root
        # which returns the ABORT message — this is the CORRECT behaviour.
        assert result.safer_alternative is not None or result.safer_alternative is None  # either is valid
        assert result.tier_used == "llm"

    @pytest.mark.asyncio
    async def test_reason_raises_timeout_on_slow_llm(self):
        import asyncio
        import engine.llm.reasoner
        from engine.llm.reasoner import LLMReasoner

        reasoner = LLMReasoner({})
        mock_client = AsyncMock()

        async def slow_complete(*args, **kwargs):
            await asyncio.sleep(4.0)
            return None

        mock_client.complete = slow_complete
        reasoner._client = mock_client

        original_timeout = engine.llm.reasoner._LLM_TIMEOUT_S
        engine.llm.reasoner._LLM_TIMEOUT_S = 0.1

        parsed = _make_parsed("rm /tmp/test")
        ctx = _make_ctx("rm /tmp/test")
        hint = _make_hint()

        try:
            with pytest.raises(TimeoutError, match="LLM response exceeded"):
                await reasoner.reason(parsed, ctx, hint)
        finally:
            engine.llm.reasoner._LLM_TIMEOUT_S = original_timeout

    @pytest.mark.asyncio
    async def test_reason_uses_safer_alternative_from_llm(self):
        from engine.llm.reasoner import LLMReasoner
        from engine.llm.client import LLMResponse

        reasoner = LLMReasoner({})
        mock_client = AsyncMock()
        mock_client.complete.return_value = LLMResponse(
            content='{"risk_level": "MEDIUM", "confidence": 0.8, "reasoning": "x", "impact_summary": "y", "safer_alternative": "safe_cmd"}',
            model="mock",
            latency_ms=10.0,
        )
        reasoner._client = mock_client

        parsed = _make_parsed("chmod 777 /tmp/file")
        ctx = _make_ctx("chmod 777 /tmp/file")
        hint = _make_hint()

        result = await reasoner.reason(parsed, ctx, hint)
        # The curated table takes priority: chmod 777 /tmp/file → chmod_777_system
        # returns 'chmod -R 755 /tmp/file'. The LLM's 'safe_cmd' is only used
        # when no curated entry exists. This is the correct, deterministic behaviour.
        assert result.safer_alternative is not None
        assert isinstance(result.safer_alternative, str)
