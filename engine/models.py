"""
Shared Pydantic models for the Intent Engine API contract.

This is the single source of truth for the interface between:
  - Shell hook  →  Daemon  (AnalyzeRequest)
  - Daemon      →  Hook    (AnalyzeResponse)
  - Rule Engine →  Daemon  (RuleVerdict)
  - LLM Layer   →  Daemon  (LLMVerdict)

All three team members must import from this module — never redefine these models.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class RiskLevel(str, Enum):
    """The canonical risk classification levels used across all engine tiers."""
    SAFE = "SAFE"             # No risk — pass through instantly
    LOW = "LOW"               # Minor risk — warn but allow easily
    MEDIUM = "MEDIUM"         # Moderate risk — prompt with explanation
    HIGH = "HIGH"             # High risk — strong warning + safer alternative
    CRITICAL = "CRITICAL"     # Catastrophic risk — hard block + mandatory confirm
    AMBIGUOUS = "AMBIGUOUS"   # Rule engine uncertain — escalate to LLM tier


class CommandContext(BaseModel):
    """Full context snapshot sent with every command analysis request."""
    command: str = Field(..., description="Raw command string as typed by user")
    cwd: str = Field(..., description="Current working directory at time of command")
    user: str = Field(..., description="Executing username")
    is_sudo: bool = Field(False, description="Whether the command uses sudo/su")
    shell: str = Field("bash", description="Shell in use: bash | zsh | fish")
    session_id: str = Field(..., description="Unique ID for the terminal session")
    terminal: Optional[str] = Field(None, description="Terminal emulator if detectable")


class AnalyzeRequest(BaseModel):
    """Request payload sent from the shell hook to the daemon over the Unix socket."""
    context: CommandContext
    dry_run: bool = Field(False, description="If true, analyze but never block execution")


class Verdict(BaseModel):
    """
    Unified verdict object returned by both the Rule Engine and LLM tier.
    The daemon merges these and returns a single AnalyzeResponse to the hook.
    """
    risk_level: RiskLevel
    confidence: float = Field(
        ..., ge=0.0, le=1.0,
        description="Classifier confidence score (0.0=uncertain, 1.0=certain)"
    )
    matched_pattern: Optional[str] = Field(
        None, description="Name of the rule pattern that fired (rule engine only)"
    )
    reasoning: str = Field(..., description="Plain-language explanation of the risk")
    impact_summary: str = Field(
        ..., description="One-sentence plain-English impact description shown to user"
    )
    safer_alternative: Optional[str] = Field(
        None, description="Safer command to suggest, if one exists"
    )
    safer_alternative_explanation: Optional[str] = Field(
        None, description="Why the alternative is safer"
    )
    tier_used: str = Field(
        ..., description="Which tier produced this verdict: 'rule_engine' | 'llm' | 'fallback'"
    )
    latency_ms: float = Field(0.0, description="Time taken to produce this verdict")


class AnalyzeResponse(BaseModel):
    """Final response from the daemon back to the shell hook."""
    verdict: Verdict
    should_block: bool = Field(
        ..., description="Whether the shell hook should pause and prompt the user"
    )
    session_id: str
    engine_version: str = Field("0.1.0")


class UserAction(str, Enum):
    """The action the user chose at the confirmation prompt."""
    EXECUTE = "EXECUTE"           # Run the original command
    ABORT = "ABORT"               # Cancel execution
    EDIT = "EDIT"                 # Edit command before running (returns to shell)
    USE_SAFER = "USE_SAFER"       # Run the safer alternative instead
    ALWAYS_ALLOW = "ALWAYS_ALLOW" # Add to personal allowlist


class AuditLogEntry(BaseModel):
    """Structured audit log entry written after every analyzed command."""
    timestamp: str
    session_id: str
    user: str
    cwd: str
    command: str
    risk_level: RiskLevel
    verdict_tier: str
    user_action: Optional[UserAction]
    safer_alternative_used: bool = False


# ─── Autocomplete Models (CLI Copilot feature) ────────────────────────────────

class AutocompleteRequest(BaseModel):
    """Partial command buffer sent from the shell hook on every debounce tick."""
    partial: str = Field(..., description="Partial command typed so far")
    cwd: str = Field("", description="Current working directory for context")


class AutocompleteItem(BaseModel):
    """A single completion suggestion."""
    cmd: str = Field(..., description="The complete command to insert")
    desc: str = Field(..., description="Short description (max ~6 words)")


class AutocompleteResponse(BaseModel):
    """Response from the /autocomplete endpoint."""
    completions: list[AutocompleteItem]
    source: str = Field("local", description="'local' | 'cache' | 'llm' — for debugging")
    latency_ms: float = Field(0.0)
