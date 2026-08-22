"""
Prompt Builder — Owner: Vansh
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Assembles structured prompts for the LLM reasoner.
Tightly controls what context the LLM sees — no leaking sensitive data.

Output format: strict JSON schema enforced in system prompt.
"""

from __future__ import annotations

from engine.models import CommandContext, Verdict
from engine.parser.command_parser import ParsedCommand

_SYSTEM_PROMPT = """You analyze Linux commands for safety. Return ONLY valid JSON:
{"risk_level":"SAFE|LOW|MEDIUM|HIGH|CRITICAL","confidence":0.0-1.0,"reasoning":"<why>","impact_summary":"<one line>","safer_alternative":"<cmd or null>"}
Rules: explain actual system impact, never suggest original command as safer, raw JSON only."""


class PromptBuilder:
    """Builds structured prompts for command safety analysis."""

    def build_system_prompt(self) -> str:
        return _SYSTEM_PROMPT

    def build_analysis_prompt(
        self,
        parsed: ParsedCommand,
        ctx: CommandContext,
        rule_hint: Verdict,
    ) -> str:
        """Build a compact user-turn prompt — fewer tokens = faster inference."""
        paths = ", ".join(parsed.target_paths) if parsed.target_paths else "none"
        return (
            f"Command: {parsed.raw}\n"
            f"Base: {parsed.base_command} | sudo: {parsed.is_sudo} | "
            f"paths: {paths} | pipe: {parsed.has_pipe} | cwd: {ctx.cwd}\n"
            f"Rule engine hint: AMBIGUOUS conf={rule_hint.confidence:.2f}\n"
            f"Return JSON assessment:"
        )

    def build_reflection_prompt(
        self,
        parsed: ParsedCommand,
        first_response: object,   # ParsedLLMResponse
    ) -> str:
        """
        Reflection prompt — given the first low-confidence response, ask the LLM
        to critique its own reasoning and produce a more decisive verdict.
        Only called when confidence < reflection_threshold (default 0.65).
        """
        return f"""You previously analyzed this command:

COMMAND: {parsed.raw}

Your initial assessment was:
  risk_level: {getattr(first_response, 'risk_level', 'UNKNOWN')}
  confidence: {getattr(first_response, 'confidence', 0.0):.2f}
  reasoning:  {getattr(first_response, 'reasoning', '')[:300]}

Your confidence was LOW ({getattr(first_response, 'confidence', 0.0):.2f}). Reconsider carefully:
- What is the WORST CASE if this command executes as written?
- Are there filesystem paths, flags, or pipe segments that escalate risk?
- Is this command commonly used maliciously, or is it a legitimate admin task?

Revise your assessment with higher confidence. Return ONLY valid JSON:
{{
  "risk_level": "SAFE" | "LOW" | "MEDIUM" | "HIGH" | "CRITICAL",
  "confidence": <float 0.7-1.0>,
  "reasoning": "<revised technical explanation>",
  "impact_summary": "<one sentence plain-English impact>",
  "safer_alternative": "<safer command or null>"
}}"""

