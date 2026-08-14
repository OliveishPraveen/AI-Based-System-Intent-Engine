"""
Safer Alternative Suggester — Owner: Vansh
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Two-phase suggestion system (mirrors NEXUS-AI's tool selection logic):
  Phase 1: Fast lookup in the curated alternatives table (instant, no LLM)
  Phase 2: LLM-generated suggestion for novel dangerous patterns

The curated table is the primary source — LLM is only used when no
table entry exists for the detected pattern.
"""

from __future__ import annotations

from typing import Any, Optional, Tuple

from engine.models import CommandContext, RiskLevel
from engine.parser.command_parser import ParsedCommand

# ─── Curated safer alternatives lookup table ──────────────────────────────────
# key: base_command + pattern hint → (safer_command, explanation)
_ALTERNATIVES_TABLE: dict[str, Tuple[str, str]] = {
    # Deletion
    "rm_rf_root":       ("# ABORT: There is no safe alternative to rm -rf /",
                         "Deleting the root filesystem is unrecoverable."),
    "rm_rf_var_log":    ("sudo journalctl --vacuum-size=500M",
                         "Frees log space safely without removing active log files."),
    "rm_rf_home":       ("trash-put {target}",
                         "Moves files to trash for recovery instead of permanent deletion."),
    # Permissions
    "chmod_777_root":   ("chmod -R 755 {target} && chown -R www-data {target}",
                         "Grants proper web-server permissions without world-write access."),
    # Disk operations
    "dd_raw_device":    ("fallocate -l 10G /tmp/test.img",
                         "Use a loop-back image file for testing instead of a real device."),
    "mkfs_live":        ("# ABORT: Formatting a mounted device will destroy data",
                         "Unmount and verify the device is not in use before formatting."),
    # Pipe-to-shell
    "curl_pipe_sh":     ("curl -o /tmp/script.sh {url} && cat /tmp/script.sh",
                         "Download first, inspect the script, then decide whether to run it."),
    "wget_pipe_sh":     ("wget -O /tmp/script.sh {url} && cat /tmp/script.sh",
                         "Download first, inspect the script, then decide whether to run it."),
    # Fork bomb
    "fork_bomb":        ("# ABORT: Fork bomb detected — will crash the system",
                         "This pattern exhausts all process slots and requires a hard reboot."),
    # Broad glob delete
    "find_root_delete": ("find /var/log -name '*.log' -mtime +30 -delete",
                         "Scope the delete to old log files only, not the entire filesystem."),
}


class SaferAlternativeSuggester:
    """
    Suggests safer alternatives for risky commands.

    Vansh: implement suggest() to:
      1. Check the curated table first (fast path)
      2. If no table entry, call LLM with a focused suggestion prompt
      3. Validate and return the alternative

    The pattern_name from the rule engine verdict is the table lookup key.
    """

    def __init__(self, config: dict[str, Any]) -> None:
        self._config = config

    async def suggest(
        self,
        parsed: ParsedCommand,
        ctx: CommandContext,
        llm_response: Any,  # ParsedLLMResponse
    ) -> Tuple[Optional[str], Optional[str]]:
        """
        Return (safer_command, explanation) or (None, None) if no suggestion.

        Vansh: implement the two-phase lookup here.
        """
        # Phase 1: Check if LLM already provided a suggestion
        if llm_response.safer_alternative:
            return llm_response.safer_alternative, "Suggested by AI analysis."

        # Phase 2: Curated table lookup (use pattern key if available)
        # TODO (Vansh): implement table key resolution from parsed command
        # Example: if parsed.base_command == "rm" and "-rf" in parsed.flags and "/" in parsed.arguments:
        #              return _ALTERNATIVES_TABLE.get("rm_rf_root")

        return None, None

    def get_table_entry(self, key: str, **fmt_kwargs: str) -> Tuple[Optional[str], Optional[str]]:
        """Helper: Get and format a table entry."""
        entry = _ALTERNATIVES_TABLE.get(key)
        if entry is None:
            return None, None
        cmd, explanation = entry
        try:
            cmd = cmd.format(**fmt_kwargs)
        except KeyError:
            pass
        return cmd, explanation
