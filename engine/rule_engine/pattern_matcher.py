"""
Pattern Matcher — Owner: Praveen
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Core pattern matching engine. Receives compiled patterns from PatternLoader
and evaluates them against ParsedCommands.

Design principles:
  - Tier 0 patterns are exact structural checks (fork bomb syntax, dd to /dev/sd*)
    — these should NEVER be AMBIGUOUS; always return CRITICAL
  - Tier 1 patterns use regex + contextual weighting
  - Context boosts: sudo usage, root-level paths (/etc, /boot, /dev), glob patterns
  - Context reduces: /tmp paths, dry-run flags (--dry-run, -n)

Praveen: implement the MatchResult and PatternMatcher class bodies.
Keep patterns in rules/dangerous_patterns.toml — never hardcode strings here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from engine.models import CommandContext, RiskLevel
from engine.parser.command_parser import ParsedCommand


@dataclass
class MatchResult:
    """Result of a pattern match against a ParsedCommand."""
    risk_level: RiskLevel
    confidence: float              # 0.0 to 1.0
    pattern_name: str              # Identifies which pattern fired
    reasoning: str                 # Plain-language explanation
    impact_summary: str            # One-sentence impact for user display
    safer_alternative: Optional[str] = None
    safer_alternative_explanation: Optional[str] = None


class PatternMatcher:
    """
    Evaluates ParsedCommands against the loaded pattern library.

    Praveen implements:
      - check_tier0(parsed)  → Optional[Verdict]  (instant CRITICAL catches)
      - match(parsed, ctx)   → Optional[MatchResult]  (full pattern library scan)
    """

    def __init__(self, patterns: list[dict]) -> None:
        """
        patterns: list of pattern dicts loaded from dangerous_patterns.toml
        Each dict has keys: name, tier, risk_level, regex, commands,
                            reasoning_template, impact_template, safer_alternative
        """
        self._patterns = patterns
        self._compiled = self._compile(patterns)

    def _compile(self, patterns: list[dict]) -> list[dict]:
        """Pre-compile all regex patterns for performance."""
        compiled = []
        for p in patterns:
            try:
                p["_re"] = re.compile(p["regex"], re.IGNORECASE) if p.get("regex") else None
                compiled.append(p)
            except re.error as e:
                # Log bad pattern and skip — don't crash the engine
                import structlog
                structlog.get_logger().error("bad_pattern_regex", name=p.get("name"), error=str(e))
        return compiled

    def check_tier0(self, parsed: ParsedCommand) -> Optional["Verdict"]:
        """
        Fast-path check for Tier 0 CRITICAL patterns.

        Praveen: implement checks for:
          - Fork bombs:   :(){ :|:& };:  /  any variant
          - dd writing to raw device:  dd ... of=/dev/sd* of=/dev/hd*
          - mkfs on a live device
          - Pipe-to-shell execution:  curl|sh, wget|bash, etc.
          - Recursive rm targeting root or near-root:  rm -rf /  rm -rf /*
        """
        # TODO (Praveen): Implement Tier 0 checks
        # Return a Verdict (from engine.models) with risk_level=CRITICAL if matched
        # Return None if no Tier 0 pattern matches
        return None

    def match(self, parsed: ParsedCommand, ctx: CommandContext) -> Optional[MatchResult]:
        """
        Full Tier 1 pattern library scan.

        Praveen: iterate through compiled patterns, apply regex + structural checks,
        compute confidence score with context weighting, return best match.

        Confidence weighting guide:
          Base score from regex match:         0.7
          + is_sudo bonus:                    +0.15
          + root path target (/etc /boot):    +0.10
          + glob pattern in arguments:        +0.08
          - /tmp target (lower risk):         -0.15
          - dry-run flag present:             -0.20
          - user is root (expected):          -0.05
        """
        # TODO (Praveen): Implement full pattern library scan
        # Return the MatchResult with the highest confidence, or None if no match
        return None

    def _is_root_path(self, paths: list[str]) -> bool:
        """Check if any target path is a system-critical location."""
        critical_prefixes = ("/etc", "/boot", "/bin", "/sbin", "/usr/bin",
                             "/lib", "/dev", "/proc", "/sys", "/var/log")
        return any(
            any(p.startswith(prefix) for prefix in critical_prefixes)
            for p in paths
        )

    def _has_dry_run_flag(self, flags: list[str]) -> bool:
        return any(f in flags for f in ("--dry-run", "-n", "--no-act"))
