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

_SYSTEM_PROMPT = """You are a Linux command safety analyzer. Your ONLY job is to analyze
whether a shell command is dangerous and explain the impact clearly.

You MUST respond with valid JSON matching this exact schema:
{
  "risk_level": "SAFE" | "LOW" | "MEDIUM" | "HIGH" | "CRITICAL",
  "confidence": <float 0.0-1.0>,
  "reasoning": "<detailed technical explanation of why this is or isn't dangerous>",
  "impact_summary": "<one sentence plain-English impact for a non-expert user>",
  "safer_alternative": "<safer command string, or null if not applicable>"
}

Rules:
- NEVER suggest running the original command in your safer_alternative
- ALWAYS explain the actual system impact (what files/data/processes are affected)
- confidence must reflect genuine uncertainty — don't fake high confidence
- Do NOT refuse to analyze — always return a risk assessment
- Do NOT return markdown — raw JSON only"""


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
        """Build the user-turn prompt with full command context."""
        flags_str = " ".join(parsed.flags) if parsed.flags else "none"
        args_str = " ".join(parsed.arguments) if parsed.arguments else "none"
        paths_str = ", ".join(parsed.target_paths) if parsed.target_paths else "none"
        pipe_info = f"YES — segments: {[s.base_command for s in parsed.pipe_segments]}" \
                    if parsed.has_pipe else "no"

        return f"""Analyze this Linux shell command for safety risks:

COMMAND: {parsed.raw}

PARSED DETAILS:
- Base command: {parsed.base_command}
- Flags: {flags_str}
- Arguments: {args_str}
- Target paths: {paths_str}
- Uses sudo: {parsed.is_sudo}
- Has pipe: {pipe_info}
- Has redirect: {parsed.has_redirect}
- Has subshell: {parsed.has_subshell}
- Contains glob patterns: {parsed.is_glob} ({', '.join(parsed.glob_patterns) or 'none'})

EXECUTION CONTEXT:
- Current directory: {ctx.cwd}
- User: {ctx.user}
- Shell: {ctx.shell}

RULE ENGINE NOTE: This command was flagged as AMBIGUOUS by the rule engine
with confidence {rule_hint.confidence:.2f}. Reasoning: {rule_hint.reasoning}

Provide your JSON safety assessment:"""

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

