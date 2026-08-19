"""
Pattern Matcher — Owner: Praveen (OliveishPraveen)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Core pattern matching engine evaluating ParsedCommands against Tier 0 structural
checks and Tier 1 contextual weighted pattern library with Strategy B (Flag &
Recursion Sensitivity + CWD Path Resolution).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Optional

import structlog

from engine.models import CommandContext, RiskLevel, Verdict
from engine.parser.command_parser import ParsedCommand
from engine.rule_engine.verdict_builder import VerdictBuilder

log = structlog.get_logger()

# Critical filesystem paths that represent core OS infrastructure
_CRITICAL_SYSTEM_PREFIXES = (
    "/etc", "/boot", "/bin", "/sbin", "/usr", "/lib", "/lib64",
    "/dev", "/proc", "/sys", "/var/log", "/root"
)

# Sensitive user credential / security directories
_SENSITIVE_USER_PREFIXES = (
    "/.ssh", "/.gnupg", "/.bash_history", "/.zsh_history",
    "/etc/sudoers", "/etc/shadow", "/etc/gshadow"
)

# Standard benign commands that should pass cleanly without false positives
_SAFE_READONLY_COMMANDS = {
    "ls", "pwd", "whoami", "id", "uname", "df", "free", "ps", "top",
    "git", "node", "python", "python3", "ping", "echo", "which",
    "whereis", "uptime", "cal", "date", "env", "printenv", "hostname"
}

# Safe filesystem locations where scratch/temporary operations are expected
_SAFE_TEMP_PREFIXES = ("/tmp", "/var/tmp", "./tmp", "tmp/")

_SENSITIVE_FILES_PATTERN = re.compile(
    r"(?:/etc/(?:shadow|gshadow|sudoers|master\.passwd)|\.ssh/id_(?:rsa|ed25519|ecdsa|dsa)|/proc/kcore|/dev/(?:mem|kmem))",
    re.IGNORECASE,
)


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
    category: str = "general"


class PatternMatcher:
    """
    Evaluates ParsedCommands against Tier 0 (structural instant CRITICAL)
    and Tier 1 (context-weighted pattern matching).
    """

    def __init__(self, patterns: list[dict[str, Any]]) -> None:
        self._patterns = patterns
        self._compiled = self._compile(patterns)

        # Regex for structural checks
        self._fork_bomb_re = re.compile(
            r"(?::\(\)\s*\{\s*:\s*\||bomb\(\)\s*\{\s*bomb\s*\|\s*bomb\b|\(\)\s*\{\s*:\s*\||\b(\w+)\(\)\s*\{\s*\1\s*\|\s*\1\s*&\s*\}\s*;\s*\1)",
            re.IGNORECASE,
        )
        self._dd_device_re = re.compile(
            r"\bdd\s+.*of=/dev/(?:sd|hd|nvme|vd|xvd|loop|mmcblk)[a-zA-Z0-9_-]*",
            re.IGNORECASE,
        )
        self._mkfs_device_re = re.compile(
            r"\bmkfs(?:\.\w+)?\s+.*?/dev/(?:sd|hd|nvme|vd|xvd|loop|mmcblk)[a-zA-Z0-9_-]*",
            re.IGNORECASE,
        )
        self._pipe_shell_re = re.compile(
            r"\b(?:curl|wget|fetch|cat)\s+.*?\|\s*(?:sudo\s+)?(?:ba|z|k|c|t?c)?sh\b",
            re.IGNORECASE,
        )
        self._redirect_dev_re = re.compile(
            r"(?:>>?|tee)\s+/dev/(?:sd|hd|nvme|vd|xvd)[a-zA-Z0-9_-]*",
            re.IGNORECASE,
        )
        self._sysrq_re = re.compile(
            r"(?:echo|printf)\s+.*?>\s*/proc/sysrq-trigger",
            re.IGNORECASE,
        )

    def _compile(self, patterns: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Pre-compile all regex patterns from the TOML library for fast matching."""
        compiled = []
        for p in patterns:
            p_copy = dict(p)
            regex_str = p.get("regex")
            if regex_str:
                try:
                    p_copy["_re"] = re.compile(regex_str, re.IGNORECASE)
                except re.error as e:
                    log.error("bad_pattern_regex", name=p.get("name"), error=str(e), regex=regex_str)
                    p_copy["_re"] = None
            else:
                p_copy["_re"] = None
            compiled.append(p_copy)
        return compiled

    def check_tier0(self, parsed: ParsedCommand) -> Optional[Verdict]:
        """
        Fast-path check for Tier 0 CRITICAL patterns (< 1ms).
        Returns an immediate 100% confidence CRITICAL Verdict if matched, else None.
        """
        raw = parsed.raw.strip()
        if not raw:
            return None

        # 1. Fork bomb patterns
        if self._fork_bomb_re.search(raw):
            return VerdictBuilder.build_verdict(
                risk_level=RiskLevel.CRITICAL,
                confidence=1.0,
                matched_pattern="fork_bomb",
                reasoning="Fork bomb detected. This pattern recursively creates infinite sub-processes that deplete all system process table slots and freeze the operating system.",
                impact_summary="Will crash your system and make the terminal completely unresponsive. Hard reboot required.",
                safer_alternative=None,
                safer_alternative_explanation="There is no safe version of a fork bomb.",
                tier_used="rule_engine",
            )

        # 2. Recursive deletion targeting root or root glob (rm -rf / or rm -rf /*)
        if self._is_rm_root_tier0(parsed):
            return VerdictBuilder.build_verdict(
                risk_level=RiskLevel.CRITICAL,
                confidence=1.0,
                matched_pattern="rm_rf_root",
                reasoning="Recursive force-deletion targeting the filesystem root (/). This command will permanently erase all system files, binaries, configurations, and installed applications.",
                impact_summary="Will permanently delete your entire operating system. Unrecoverable without full reinstall.",
                safer_alternative=None,
                safer_alternative_explanation="Deleting the root directory is never safe. Abort immediately.",
                tier_used="rule_engine",
            )

        # 3. dd writing directly to raw block device
        if parsed.base_command == "dd" and self._dd_device_re.search(raw):
            device_str = self._extract_device(raw) or "/dev/sda"
            return VerdictBuilder.build_verdict(
                risk_level=RiskLevel.CRITICAL,
                confidence=1.0,
                matched_pattern="dd_raw_device",
                reasoning=f"dd writing directly to raw disk device ({device_str}). Overwrites partition tables, boot records, and stored filesystem data with raw bytes.",
                impact_summary=f"Will destroy all partition structures and data on {device_str}. Unrecoverable.",
                safer_alternative="fallocate -l 10G /tmp/test.img",
                safer_alternative_explanation="Use a loopback file image in /tmp for testing dd operations instead of real disk hardware.",
                tier_used="rule_engine",
            )

        # 4. mkfs on raw block device
        if (parsed.base_command.startswith("mkfs") or "mkfs" in parsed.tokens) and self._mkfs_device_re.search(raw):
            device_str = self._extract_device(raw) or "/dev/sda"
            return VerdictBuilder.build_verdict(
                risk_level=RiskLevel.CRITICAL,
                confidence=1.0,
                matched_pattern="mkfs_device",
                reasoning=f"Filesystem format command ({parsed.base_command}) targeting raw storage partition ({device_str}). Existing filesystem metadata and data blocks will be overwritten.",
                impact_summary=f"Will format and erase all files on {device_str}.",
                safer_alternative=f"lsblk -f {device_str} # Check filesystem usage before formatting",
                safer_alternative_explanation="Verify the partition is unmounted and not in use by your host operating system.",
                tier_used="rule_engine",
            )

        # 5. Pipe to shell execution (curl http://... | sh, wget ... | bash, cat ... | sh)
        if self._is_pipe_to_shell_tier0(parsed):
            url = self._extract_url(raw) or "http://remote-url"
            return VerdictBuilder.build_verdict(
                risk_level=RiskLevel.CRITICAL,
                confidence=1.0,
                matched_pattern="curl_pipe_shell",
                reasoning=f"Pipe-to-shell execution pattern detected. Downloads remote or uninspected script content from {url} and pipes it directly into a shell interpreter for execution.",
                impact_summary="Executes uninspected remote code with your current user privileges.",
                safer_alternative="curl -sSO /tmp/script.sh && cat /tmp/script.sh # Inspect before executing",
                safer_alternative_explanation="Download the script to a temporary file, inspect its contents, and execute only after confirming it is safe.",
                tier_used="rule_engine",
            )

        # 6. Direct redirection to raw disk node (> /dev/sda)
        if self._redirect_dev_re.search(raw):
            device_str = self._extract_device(raw) or "/dev/sda"
            return VerdictBuilder.build_verdict(
                risk_level=RiskLevel.CRITICAL,
                confidence=1.0,
                matched_pattern="redirect_to_device",
                reasoning=f"Writing data directly to {device_str} overwrites disk sectors and corrupts storage partition structures.",
                impact_summary=f"Will corrupt storage partition tables on {device_str}.",
                safer_alternative=None,
                safer_alternative_explanation="Never stream or redirect text into /dev raw storage nodes.",
                tier_used="rule_engine",
            )

        # 7. Proc SysRq trigger write
        if self._sysrq_re.search(raw):
            return VerdictBuilder.build_verdict(
                risk_level=RiskLevel.CRITICAL,
                confidence=1.0,
                matched_pattern="proc_sysrq_trigger",
                reasoning="Writing directly to /proc/sysrq-trigger bypasses normal kernel shutdown handlers to trigger hard reboots, memory dumps, or immediate freezes.",
                impact_summary="Forces an immediate kernel reset without cleanly unmounting disks or closing applications.",
                safer_alternative="sudo systemctl reboot",
                safer_alternative_explanation="Use systemctl reboot to allow services and filesystems to shut down cleanly.",
                tier_used="rule_engine",
            )

        return None

    def match(self, parsed: ParsedCommand, ctx: CommandContext) -> Optional[MatchResult]:
        """
        Scan Tier 1 pattern library with contextual weighting.
        Returns the best MatchResult (highest confidence/severity), or a safe MatchResult
        if the command is identified as benign.
        """
        raw = parsed.raw.strip()
        if not raw:
            return None

        # 1. Fast path: check for benign / safe commands to prevent false positives
        safe_result = self._check_benign_command(parsed, ctx)
        if safe_result is not None:
            return safe_result

        # 2. Iterate compiled patterns and evaluate
        candidates: list[MatchResult] = []

        for p in self._compiled:
            # Skip Tier 0 patterns (handled by check_tier0)
            if p.get("tier") == 0:
                continue

            # Command filter (if specified and non-empty)
            cmd_filter = p.get("commands", [])
            if cmd_filter and parsed.base_command:
                if parsed.base_command not in cmd_filter:
                    # Check if any pipe segment matches
                    if not any(seg.base_command in cmd_filter for seg in parsed.pipe_segments):
                        continue

            # Regex match
            regex = p.get("_re")
            if regex is not None:
                match_obj = regex.search(raw)
                if not match_obj:
                    # Also check resolved relative paths against cwd
                    resolved_args = self._resolve_absolute_paths(parsed.arguments, ctx.cwd)
                    resolved_raw = f"{parsed.base_command} {' '.join(parsed.flags)} {' '.join(resolved_args)}"
                    match_obj = regex.search(resolved_raw)
                    if not match_obj:
                        continue
            else:
                continue

            # Compute context-weighted confidence score
            confidence = self._compute_confidence(p, parsed, ctx)

            # Interpolate templates dynamically
            reasoning = VerdictBuilder.render_template(p.get("reasoning_template", ""), parsed, ctx)
            impact = VerdictBuilder.render_template(p.get("impact_template", ""), parsed, ctx)
            safer_alt = VerdictBuilder.render_template(p.get("safer_alternative", "") or "", parsed, ctx)
            safer_exp = VerdictBuilder.render_template(p.get("safer_explanation", "") or "", parsed, ctx)

            risk_level_str = p.get("risk_level", "HIGH").upper()
            try:
                risk_level = RiskLevel(risk_level_str)
            except ValueError:
                risk_level = RiskLevel.HIGH

            candidates.append(
                MatchResult(
                    risk_level=risk_level,
                    confidence=confidence,
                    pattern_name=p.get("name", "unknown_pattern"),
                    reasoning=reasoning,
                    impact_summary=impact,
                    safer_alternative=safer_alt if safer_alt else None,
                    safer_alternative_explanation=safer_exp if safer_exp else None,
                    category=p.get("category", "general"),
                )
            )

        if not candidates:
            return None

        # Sort by confidence descending, then by risk severity
        severity_rank = {
            RiskLevel.CRITICAL: 5,
            RiskLevel.HIGH: 4,
            RiskLevel.MEDIUM: 3,
            RiskLevel.LOW: 2,
            RiskLevel.SAFE: 1,
            RiskLevel.AMBIGUOUS: 0,
        }
        candidates.sort(
            key=lambda c: (c.confidence, severity_rank.get(c.risk_level, 0)),
            reverse=True,
        )
        return candidates[0]

    def _compute_confidence(
        self,
        pattern: dict[str, Any],
        parsed: ParsedCommand,
        ctx: CommandContext,
    ) -> float:
        """
        Compute confidence score with context weighting:
          Base score:                  0.70
          + is_sudo bonus:            +0.15
          + system path target:       +0.10 ~ +0.15
          + glob pattern in arguments:+0.08
          + subshell / redirect:      +0.05
          - safe path (/tmp target):  -0.20
          - dry-run flag present:     -0.20
          - user is root (expected):  -0.05
        """
        score = 0.70
        resolved_paths = self._resolve_absolute_paths(parsed.arguments, ctx.cwd)

        # Sudo boost
        if parsed.is_sudo or ctx.is_sudo:
            score += 0.15

        # System path boost
        if self._is_root_path(resolved_paths) or self._is_root_path(parsed.target_paths):
            score += 0.12

        # Glob boost
        if parsed.is_glob or any("*" in a or "?" in a for a in parsed.arguments):
            score += 0.08

        # Subshell or redirection boost
        if parsed.has_subshell or parsed.has_redirect:
            score += 0.05

        # Reductions: Safe path target (e.g. /tmp)
        if self._is_safe_temp_path(resolved_paths) and not self._is_root_path(resolved_paths):
            score -= 0.20

        # Dry-run flag reduction
        if self._has_dry_run_flag(parsed):
            score -= 0.20

        # User is already root
        if ctx.user == "root" or parsed.user == "root":
            score -= 0.05

        # Clamp between 0.0 and 1.0
        return max(0.0, min(1.0, round(score, 3)))

    def _check_benign_command(
        self,
        parsed: ParsedCommand,
        ctx: CommandContext,
    ) -> Optional[MatchResult]:
        """
        Fast inspection for safe commands to guarantee zero false positives.
        Strategy B: Differentiates single file vs recursive deletion, and resolves CWD paths.
        """
        base = parsed.base_command.lower()
        raw = parsed.raw.strip()
        resolved_paths = self._resolve_absolute_paths(parsed.arguments, ctx.cwd)

        # Check for dangerous redirects (e.g. echo "" > /dev/sda or > /var/log/syslog)
        if parsed.has_redirect or ">" in raw:
            for prefix in ("/dev/", "/etc/", "/var/log/"):
                if prefix in raw or any(p.startswith(prefix) for p in resolved_paths):
                    return None

        # 1. Read-only standard inspection commands
        if base in _SAFE_READONLY_COMMANDS and not parsed.has_pipe:
            if not _SENSITIVE_FILES_PATTERN.search(raw) and not any(self._is_sensitive_file(p) for p in resolved_paths):
                return MatchResult(
                    risk_level=RiskLevel.SAFE,
                    confidence=0.98,
                    pattern_name="safe_readonly_command",
                    reasoning=f"Standard benign shell utility ({base}) with non-destructive arguments.",
                    impact_summary="Reads non-sensitive system or working directory status.",
                    category="benign",
                )

        # 2. File read utilities (cat, less, more, head, tail, nl) on non-sensitive files
        if base in {"cat", "less", "more", "head", "tail", "nl"} and not parsed.has_pipe:
            if not _SENSITIVE_FILES_PATTERN.search(raw) and not any(self._is_sensitive_file(p) for p in resolved_paths):
                return MatchResult(
                    risk_level=RiskLevel.SAFE,
                    confidence=0.98,
                    pattern_name="safe_file_read",
                    reasoning=f"Reading non-sensitive file content with {base}.",
                    impact_summary="Displays file contents to the terminal.",
                    category="benign",
                )

        # 3. Search utilities: grep, rg, ag, egrep, fgrep
        if base in {"grep", "rg", "ag", "egrep", "fgrep"}:
            return MatchResult(
                risk_level=RiskLevel.SAFE,
                confidence=0.98,
                pattern_name="safe_grep_search",
                reasoning=f"Read-only pattern search with {base}.",
                impact_summary="Searches file contents without modification.",
                category="benign",
            )

        # 4. Service / System status inspection: systemctl status, journalctl
        if base in {"systemctl", "service"}:
            if any(t in ("status", "is-active", "is-enabled", "list-units") for t in parsed.tokens):
                return MatchResult(
                    risk_level=RiskLevel.SAFE,
                    confidence=0.98,
                    pattern_name="safe_service_status",
                    reasoning="Querying systemd service status and runtime metrics.",
                    impact_summary="Inspects service status without altering runtime state.",
                    category="benign",
                )

        if base in {"journalctl", "dmesg"}:
            return MatchResult(
                risk_level=RiskLevel.SAFE,
                confidence=0.98,
                pattern_name="safe_log_inspection",
                reasoning=f"Querying system event logs with {base}.",
                impact_summary="Reads system journal logs without altering records.",
                category="benign",
            )

        # 5. Network fetch / download without piping to shell: curl, wget
        if base in {"curl", "wget", "fetch"} and not parsed.has_pipe:
            return MatchResult(
                risk_level=RiskLevel.SAFE,
                confidence=0.95,
                pattern_name="safe_network_fetch",
                reasoning=f"Network download command ({base}) without pipe-to-shell execution.",
                impact_summary="Fetches web content or downloads target file safely.",
                category="benign",
            )

        # 6. File operation utilities: touch, mkdir, cp, mv, tar, unzip
        if base in {"touch", "mkdir", "cp", "mv", "tar", "unzip"}:
            if self._is_user_or_temp_path(resolved_paths):
                return MatchResult(
                    risk_level=RiskLevel.SAFE,
                    confidence=0.95,
                    pattern_name="safe_file_operation",
                    reasoning=f"Standard file operation ({base}) in user workspace or temporary directory.",
                    impact_summary="Modifies local workspace or temporary files safely.",
                    category="benign",
                )

        # 7. Single-file or scoped deletion (Strategy B): rm without -r / -R on non-critical files
        if base == "rm":
            has_recursive = any(
                "-r" in f or "-R" in f or "r" in f.lstrip("-") or "R" in f.lstrip("-") or f == "--recursive"
                for f in parsed.flags
            )
            # Case 7A: Non-recursive single file deletion in user/temp space (e.g. rm file.txt, rm -f ./doc.pdf)
            if not has_recursive:
                if self._is_user_or_temp_path(resolved_paths) and not any(self._is_sensitive_file(p) for p in resolved_paths):
                    return MatchResult(
                        risk_level=RiskLevel.SAFE,
                        confidence=0.98,
                        pattern_name="safe_single_file_rm",
                        reasoning="Non-recursive deletion targeting a standard file in user workspace.",
                        impact_summary="Deletes specific user file without touching system directories.",
                        category="benign",
                    )

            # Case 7B: Recursive deletion restricted entirely to /tmp or scratch directories
            if all(self._is_safe_temp_path([p]) for p in resolved_paths):
                return MatchResult(
                    risk_level=RiskLevel.SAFE,
                    confidence=0.95,
                    pattern_name="safe_temp_operation",
                    reasoning="File deletion restricted entirely to temporary directory (/tmp).",
                    impact_summary="Modifies temporary scratch files without touching system state.",
                    category="benign",
                )

        # 8. Standard safe chmod on user home or local scripts (e.g. chmod 755 /home/user/script.sh)
        if base == "chmod":
            if resolved_paths:
                first_path = resolved_paths[-1]
                if not self._is_root_path([first_path]) and ("755" in parsed.tokens or "644" in parsed.tokens or "+x" in parsed.tokens):
                    return MatchResult(
                        risk_level=RiskLevel.SAFE,
                        confidence=0.95,
                        pattern_name="safe_permission_change",
                        reasoning="Standard permission assignment (755/644/+x) targeting non-system user file.",
                        impact_summary="Sets standard user permissions without exposing sensitive paths.",
                        category="benign",
                    )

        # 9. User directory ownership (chown user:user /home/user/file)
        if base == "chown":
            if resolved_paths and not self._is_root_path(resolved_paths):
                return MatchResult(
                    risk_level=RiskLevel.SAFE,
                    confidence=0.95,
                    pattern_name="safe_chown_user",
                    reasoning="Setting file ownership for user workspace files.",
                    impact_summary="Updates user file ownership safely.",
                    category="benign",
                )

        # 10. Package managers and container utilities
        if base in {"apt", "apt-get", "dnf", "yum", "pacman", "pip", "npm", "cargo"}:
            if not parsed.has_pipe and not parsed.has_subshell:
                return MatchResult(
                    risk_level=RiskLevel.SAFE,
                    confidence=0.95,
                    pattern_name="safe_package_manager",
                    reasoning=f"Standard package manager command ({base}).",
                    impact_summary="Performs package inspection or standard installation.",
                    category="benign",
                )

        if base in {"docker", "podman"}:
            if any(t in ("ps", "images", "version", "info", "stats", "logs") for t in parsed.tokens):
                return MatchResult(
                    risk_level=RiskLevel.SAFE,
                    confidence=0.98,
                    pattern_name="safe_container_query",
                    reasoning="Querying container runtime status.",
                    impact_summary="Reads container and image inventory.",
                    category="benign",
                )

        # 11. Remote connection utilities without reverse shell (ssh, scp, sftp)
        if base in {"ssh", "scp", "sftp"}:
            return MatchResult(
                risk_level=RiskLevel.SAFE,
                confidence=0.95,
                pattern_name="safe_remote_session",
                reasoning=f"Standard secure remote session with {base}.",
                impact_summary="Connects to remote host over SSH.",
                category="benign",
            )

        # 12. Standard find within /tmp or user directory without system delete
        if base == "find":
            if resolved_paths and (resolved_paths[0].startswith("/tmp") or resolved_paths[0].startswith("/home")):
                if "-delete" not in parsed.tokens and "-exec" not in parsed.tokens:
                    return MatchResult(
                        risk_level=RiskLevel.SAFE,
                        confidence=0.95,
                        pattern_name="safe_find_query",
                        reasoning="Search query scoped to temporary or user home directory without deletion.",
                        impact_summary="Inspects directory tree for matching file patterns.",
                        category="benign",
                    )
                elif resolved_paths[0].startswith("/tmp") and "-delete" in parsed.tokens:
                    return MatchResult(
                        risk_level=RiskLevel.SAFE,
                        confidence=0.92,
                        pattern_name="safe_tmp_cleanup",
                        reasoning="Scoped cleanup of temporary files in /tmp.",
                        impact_summary="Prunes temporary cache files.",
                        category="benign",
                    )

        # 13. Querying shell resource limits: ulimit -a or ulimit without modifying flags
        if base == "ulimit":
            if parsed.tokens == ["ulimit"] or (len(parsed.tokens) == 2 and parsed.tokens[1] in ("-a", "-Sa", "-Ha")):
                return MatchResult(
                    risk_level=RiskLevel.SAFE,
                    confidence=0.98,
                    pattern_name="safe_ulimit_query",
                    reasoning="Querying current shell resource limits with ulimit -a.",
                    impact_summary="Displays configured resource quotas without modifying them.",
                    category="benign",
                )

        return None

    def _is_rm_root_tier0(self, parsed: ParsedCommand) -> bool:
        """Check for rm -rf / or rm -rf /* structural variants."""
        if parsed.base_command != "rm":
            return False

        has_recursive = any(
            "-r" in f or "-R" in f or "r" in f.lstrip("-") or "R" in f.lstrip("-") or f == "--recursive"
            for f in parsed.flags
        )
        if not has_recursive:
            return False

        # Targets / or /*
        for arg in parsed.arguments:
            norm = arg.strip().rstrip("/")
            if norm in {"", "*"} or arg in {"/", "/*", "/--no-preserve-root"}:
                return True

        if "--no-preserve-root" in parsed.tokens and "/" in parsed.arguments:
            return True

        return False

    def _is_pipe_to_shell_tier0(self, parsed: ParsedCommand) -> bool:
        """Check for pipe to shell execution (curl | sh, wget | bash, etc.)."""
        raw = parsed.raw.strip()
        if self._pipe_shell_re.search(raw):
            return True

        if parsed.has_pipe and len(parsed.pipe_segments) >= 2:
            first_cmd = parsed.pipe_segments[0].base_command.lower()
            last_cmd = parsed.pipe_segments[-1].base_command.lower()
            if first_cmd in {"curl", "wget", "fetch", "cat"} and last_cmd in {"sh", "bash", "zsh", "ksh", "csh", "tcsh"}:
                return True

        return False

    def _is_root_path(self, paths: list[str]) -> bool:
        """Check if any target path belongs to critical system hierarchy."""
        for path in paths:
            clean = path.strip()
            if clean in {"/", "/*"} or any(clean.startswith(prefix) for prefix in _CRITICAL_SYSTEM_PREFIXES):
                return True
        return False

    def _is_sensitive_file(self, path: str) -> bool:
        """Check if a path targets sensitive credentials or identity files."""
        clean = path.strip()
        return any(clean.endswith(suffix) or suffix in clean for suffix in _SENSITIVE_USER_PREFIXES)

    def _resolve_absolute_paths(self, paths: list[str], cwd: str) -> list[str]:
        """Resolve relative and tilde arguments against working directory context."""
        resolved: list[str] = []
        clean_cwd = (cwd or "/home/user").rstrip("/")

        for p in paths:
            clean = p.strip()
            if not clean:
                continue
            if clean.startswith("~"):
                resolved.append(clean.replace("~", "/home/user", 1))
            elif clean.startswith("/"):
                resolved.append(clean)
            elif clean.startswith("./"):
                resolved.append(f"{clean_cwd}/{clean[2:]}")
            else:
                resolved.append(f"{clean_cwd}/{clean}")

        return resolved

    def _is_user_or_temp_path(self, paths: list[str]) -> bool:
        """Check if all target paths are in user home, temporary directories, or relative."""
        if not paths:
            return True
        for p in paths:
            clean = p.strip()
            if self._is_root_path([clean]) or self._is_sensitive_file(clean):
                return False
            is_user_or_temp = (
                clean.startswith("/home/")
                or clean.startswith("/tmp")
                or clean.startswith("/var/tmp")
                or clean.startswith("./")
                or clean.startswith("~")
                or not clean.startswith("/")
            )
            if not is_user_or_temp:
                return False
        return True

    def _is_safe_temp_path(self, paths: list[str]) -> bool:
        """Check if all target paths are inside temporary directories."""
        if not paths:
            return False
        return all(
            any(p.strip().startswith(prefix) for prefix in _SAFE_TEMP_PREFIXES)
            for p in paths
        )

    def _has_dry_run_flag(self, parsed: ParsedCommand) -> bool:
        """Check for dry-run or simulation flags."""
        if any(f in parsed.flags for f in ("--dry-run", "--no-act", "--simulate")):
            return True
        if parsed.base_command in {"rsync", "make", "patch", "apt", "apt-get", "dnf"} and "-n" in parsed.flags:
            return True
        return False

    def _extract_device(self, raw: str) -> Optional[str]:
        """Extract block device string like /dev/sda or /dev/nvme0n1."""
        dev_match = re.search(r"/dev/(?:sd|hd|nvme|vd|xvd|loop|mmcblk)[a-zA-Z0-9_-]*", raw)
        return dev_match.group(0) if dev_match else None

    def _extract_url(self, raw: str) -> Optional[str]:
        """Extract URL from command string."""
        url_match = re.search(r"https?://[^\s'\"]+", raw)
        return url_match.group(0) if url_match else None
