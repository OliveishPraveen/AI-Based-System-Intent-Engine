"""
Alias Resolver
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Reads shell aliases from the user's environment and resolves them
before the command is sent to the rule engine.

Why this matters:
  - `alias rm='rm -i'` — the rule engine sees "rm -i", not the alias
  - `alias yolo='rm -rf /'` — must be resolved to actual command
  - Without this, aliased dangerous commands would be incorrectly
    classified as the alias name (unknown command → SAFE)

Approach:
  - On daemon startup, read aliases from `bash -i -c alias` or
    `zsh -i -c alias`
  - Cache the alias map in memory
  - Resolver replaces the base command token if it matches an alias
"""

from __future__ import annotations

import re
import subprocess
from typing import Optional

import structlog

log = structlog.get_logger()

# Regex to parse alias output lines:
# bash: alias rm='rm -i'
# zsh:  rm='rm -i'
_ALIAS_RE = re.compile(r"^(?:alias\s+)?([^=]+)='?(.+?)'?$")


class AliasResolver:
    """
    Loads and applies shell alias resolution.

    Usage:
        resolver = AliasResolver()
        resolver.load(shell="zsh")
        expanded = resolver.resolve("yolo /tmp/foo")
    """

    def __init__(self) -> None:
        self._aliases: dict[str, str] = {}

    def load(self, shell: str = "bash") -> None:
        """
        Load aliases from the user's interactive shell.
        Silently skips on any error — alias resolution is best-effort.
        """
        try:
            shell_bin = "zsh" if shell == "zsh" else "bash"
            # Source the user's rc file explicitly — do NOT use -i (interactive mode).
            # -i causes bash/zsh to open /dev/tty directly for terminal control, which
            # sends SIGTTIN to the daemon process group and suspends it.
            rc_file = f"~/.{shell_bin}rc"
            cmd = f". {rc_file} 2>/dev/null; alias 2>/dev/null"
            result = subprocess.run(
                [shell_bin, "-c", cmd],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                text=True,
                timeout=3.0,
            )
            self._aliases = self._parse_alias_output(result.stdout)
            log.info("aliases_loaded", count=len(self._aliases), shell=shell_bin)
        except Exception as e:
            log.warning("alias_load_skipped", reason=str(e))
            self._aliases = {}

    def resolve(self, command: str) -> str:
        """
        Resolve the base command token if it matches a known alias.

        Example:
            alias yolo='rm -rf'
            resolve("yolo /tmp") → "rm -rf /tmp"

        Only the FIRST token is resolved — we don't recursively expand.
        """
        if not self._aliases or not command.strip():
            return command

        tokens = command.strip().split(None, 1)
        base = tokens[0]

        if base in self._aliases:
            expanded = self._aliases[base]
            rest = tokens[1] if len(tokens) > 1 else ""
            resolved = f"{expanded} {rest}".strip()
            if resolved != command:
                log.debug("alias_resolved", original=base, expanded=expanded)
            return resolved

        return command

    def get_aliases(self) -> dict[str, str]:
        """Return the loaded alias map (for debugging)."""
        return dict(self._aliases)

    @staticmethod
    def _parse_alias_output(output: str) -> dict[str, str]:
        """Parse the output of the `alias` builtin command."""
        aliases: dict[str, str] = {}
        for line in output.splitlines():
            line = line.strip()
            m = _ALIAS_RE.match(line)
            if m:
                name = m.group(1).strip()
                value = m.group(2).strip().strip("'\"")
                if name:
                    aliases[name] = value
        return aliases
