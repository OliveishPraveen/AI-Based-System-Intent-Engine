"""
Pattern Matcher — Owner: Praveen (Tier 0/1 baseline implemented by Harshit)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Core pattern matching engine. Evaluates ParsedCommands against:
  - Tier 0: Structural checks (fork bomb, rm -rf /, dd, mkfs, curl|sh)
    → Always CRITICAL, 100% confidence, no scoring needed
  - Tier 1: Regex patterns from dangerous_patterns.toml with context-weighted
    confidence scoring

Praveen: feel free to extend check_tier0() and refine the confidence
scoring in match(). The framework is fully functional — you're adding
patterns and tuning weights.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

import structlog

from engine.models import CommandContext, RiskLevel, Verdict
from engine.parser.command_parser import ParsedCommand

log = structlog.get_logger()


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


# ── Tier 0 structural checks (hardcoded, no regex, no TOML) ──────────────────

_FORK_BOMB_RE = re.compile(
    r":\(\)\s*\{\s*:\s*\|"             # :(){ :|
    r"|\.\(\)\s*\{\s*\.\s*\|"          # .() { .|
    r"|bomb\(\)\s*\{"                   # bomb() {
    r"|(\w)\(\)\s*\{\s*\1\s*\|\s*\1",  # x(){ x|x
    re.IGNORECASE,
)

_CURL_PIPE_SHELL_RE = re.compile(
    r"(?:curl|wget)\s+.*?\|\s*(?:ba)?sh\b"
    r"|(?:curl|wget)\s+.*?\|\s*(?:zsh|fish|dash|ksh)\b",
    re.IGNORECASE,
)

_DD_DEVICE_RE = re.compile(
    r"dd\s+.*of=/dev/(?:sd|hd|nvme|vd|xvd|mmcblk)[a-z0-9]*",
    re.IGNORECASE,
)

_MKFS_DEVICE_RE = re.compile(
    r"mkfs(?:\.\w+)?\s+.*?/dev/(?:sd|hd|nvme|vd|mmcblk)[a-z0-9]*",
    re.IGNORECASE,
)


class PatternMatcher:
    """
    Evaluates ParsedCommands against the loaded pattern library.

    check_tier0(parsed) → Optional[Verdict]    (instant CRITICAL catches)
    match(parsed, ctx)  → Optional[MatchResult] (full pattern library scan)
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
                log.error("bad_pattern_regex", name=p.get("name"), error=str(e))
        return compiled

    # ── Tier 0: Instant CRITICAL checks ───────────────────────────────────────

    def check_tier0(self, parsed: ParsedCommand) -> Optional[Verdict]:
        """
        Fast-path structural checks. These are 100% confidence, always CRITICAL.
        No regex from TOML — these are hardcoded for maximum reliability.
        """
        raw = parsed.raw

        # 1. Fork bomb detection
        if _FORK_BOMB_RE.search(raw):
            return Verdict(
                risk_level=RiskLevel.CRITICAL,
                confidence=1.0,
                matched_pattern="fork_bomb",
                reasoning="Fork bomb detected. This creates recursive processes "
                          "that exhaust all system process slots, requiring a hard reboot.",
                impact_summary="Will crash your system. Requires hard reboot.",
                tier_used="rule_engine",
            )

        # 2. rm -rf targeting root (/ or /*)
        if parsed.base_command == "rm":
            has_recursive = any(
                f in parsed.flags or "-r" in f or "-R" in f
                for f in parsed.flags
            )
            has_force = any("-f" in f for f in parsed.flags)
            targets_root = any(
                arg in ("/", "/*", "/.", "/..")
                or arg.rstrip("/") == ""
                for arg in parsed.arguments
            )
            if has_recursive and targets_root:
                return Verdict(
                    risk_level=RiskLevel.CRITICAL,
                    confidence=1.0,
                    matched_pattern="rm_rf_root",
                    reasoning="Recursive deletion targeting filesystem root. "
                              "This will irreversibly delete ALL files on the system.",
                    impact_summary="Will permanently delete your entire operating system.",
                    tier_used="rule_engine",
                )

        # 3. dd writing to raw block device
        if parsed.base_command == "dd" and _DD_DEVICE_RE.search(raw):
            return Verdict(
                risk_level=RiskLevel.CRITICAL,
                confidence=1.0,
                matched_pattern="dd_raw_device",
                reasoning="dd writing directly to a raw block device. This overwrites "
                          "the partition table and all data without confirmation.",
                impact_summary="Will destroy all data on the target disk.",
                safer_alternative="fallocate -l 10G /tmp/test.img",
                safer_alternative_explanation="Use a loopback image file for testing.",
                tier_used="rule_engine",
            )

        # 4. mkfs on a live device
        if parsed.base_command.startswith("mkfs") and _MKFS_DEVICE_RE.search(raw):
            return Verdict(
                risk_level=RiskLevel.CRITICAL,
                confidence=1.0,
                matched_pattern="mkfs_device",
                reasoning="Filesystem format command targeting a real block device. "
                          "This erases all data on the partition.",
                impact_summary="Will format and erase all data on the target device.",
                tier_used="rule_engine",
            )

        # 5. curl/wget pipe to shell
        if parsed.has_pipe and _CURL_PIPE_SHELL_RE.search(raw):
            return Verdict(
                risk_level=RiskLevel.CRITICAL,
                confidence=1.0,
                matched_pattern="curl_pipe_shell",
                reasoning="Pipe-to-shell execution. Downloads and immediately executes "
                          "remote code without inspection — a primary attack vector.",
                impact_summary="Executes unreviewed remote code with your privileges.",
                safer_alternative="curl -o /tmp/script.sh <url> && cat /tmp/script.sh",
                safer_alternative_explanation="Download first, review, then run.",
                tier_used="rule_engine",
            )

        # 6. Pipe-to-shell via pipe_segments (catches cases where raw regex misses)
        if parsed.has_pipe and len(parsed.pipe_segments) >= 2:
            first_cmd = parsed.pipe_segments[0].base_command
            last_cmd = parsed.pipe_segments[-1].base_command
            if first_cmd in ("curl", "wget") and last_cmd in ("sh", "bash", "zsh", "fish", "dash", "ksh"):
                return Verdict(
                    risk_level=RiskLevel.CRITICAL,
                    confidence=1.0,
                    matched_pattern="curl_pipe_shell",
                    reasoning="Pipe-to-shell execution detected via command structure. "
                              "Downloads and executes remote code without inspection.",
                    impact_summary="Executes unreviewed remote code with your privileges.",
                    safer_alternative="curl -o /tmp/script.sh <url> && cat /tmp/script.sh",
                    safer_alternative_explanation="Download first, review, then run.",
                    tier_used="rule_engine",
                )

        return None

    # ── Tier 1: Full pattern library scan ─────────────────────────────────────

    def match(self, parsed: ParsedCommand, ctx: CommandContext) -> Optional[MatchResult]:
        """
        Scan all compiled Tier 1 patterns against the command.
        Compute confidence with context weighting. Return the highest-confidence match.
        """
        best: Optional[MatchResult] = None
        best_confidence = 0.0

        for p in self._compiled:
            # Skip Tier 0 patterns (handled by check_tier0)
            if p.get("tier") == 0:
                continue

            # Check if the pattern applies to this command
            commands = p.get("commands", [])
            if commands and parsed.base_command not in commands:
                continue

            # Check regex match against the raw command
            regex = p.get("_re")
            if regex and not regex.search(parsed.raw):
                continue

            # ── Compute confidence score ──────────────────────────────────────
            base_score = 0.70
            adjustments = []

            # Boosters
            if parsed.is_sudo:
                base_score += 0.15
                adjustments.append("+0.15 sudo")

            if self._is_root_path(parsed.target_paths):
                base_score += 0.10
                adjustments.append("+0.10 system path")

            if parsed.is_glob:
                base_score += 0.08
                adjustments.append("+0.08 glob pattern")

            # Reducers
            if any(arg.startswith("/tmp") for arg in parsed.target_paths):
                base_score -= 0.15
                adjustments.append("-0.15 /tmp target")

            if self._has_dry_run_flag(parsed.flags):
                base_score -= 0.20
                adjustments.append("-0.20 dry-run flag")

            if ctx.user == "root":
                base_score -= 0.05
                adjustments.append("-0.05 root user")

            # Clamp
            confidence = max(0.0, min(1.0, base_score))

            if confidence > best_confidence:
                best_confidence = confidence
                reasoning = p.get("reasoning_template", "Matched a dangerous pattern.")
                best = MatchResult(
                    risk_level=RiskLevel(p.get("risk_level", "MEDIUM")),
                    confidence=confidence,
                    pattern_name=p["name"],
                    reasoning=reasoning,
                    impact_summary=p.get("impact_template", "Potentially dangerous operation."),
                    safer_alternative=p.get("safer_alternative") or None,
                    safer_alternative_explanation=p.get("safer_explanation") or None,
                )

        return best

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _is_root_path(self, paths: list[str]) -> bool:
        """Check if any target path is a system-critical location."""
        critical_prefixes = (
            "/etc", "/boot", "/bin", "/sbin", "/usr/bin",
            "/lib", "/dev", "/proc", "/sys", "/var/log",
        )
        return any(
            any(p.startswith(prefix) for prefix in critical_prefixes)
            for p in paths
        )

    def _has_dry_run_flag(self, flags: list[str]) -> bool:
        return any(f in flags for f in ("--dry-run", "-n", "--no-act", "--simulate", "--check"))
