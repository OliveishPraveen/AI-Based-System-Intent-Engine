"""
Session Manager — Owner: Harshit
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Manages per-session state for a single terminal session:
  - Session-level allowlist (ALWAYS_ALLOW decisions within this session)
  - Persistent personal allowlist (survives terminal close)
  - ALWAYS_DENY list (from config)
  - Per-session command stats

A "session" = one terminal instance identified by session_id (UUID
generated when the shell hook is sourced).
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Optional

import structlog

log = structlog.get_logger()

_ALLOWLIST_PATH = Path.home() / ".intent_engine" / "allowlist.json"


class SessionManager:
    """
    Manages session state, allowlists, and denylists.

    Used by the router to check overrides BEFORE any tier analysis.
    """

    def __init__(self, config: dict[str, Any]) -> None:
        self._config = config
        # In-memory session allowlist: session_id → set of command patterns
        self._session_allowlist: dict[str, set[str]] = defaultdict(set)
        # Persistent personal allowlist: set of base commands user always allows
        self._personal_allowlist: set[str] = set()
        # Always-deny list from config (exact base commands)
        self._always_deny: set[str] = set(
            config.get("safety", {}).get("always_deny", [])
        )
        self._load_personal_allowlist()

    # ── Allowlist checks ──────────────────────────────────────────────────────

    def is_always_allowed(self, command: str, session_id: str) -> bool:
        """
        Return True if this command is in the session or personal allowlist.
        Matches on the base command (first token).
        """
        base = self._base_command(command)
        if base in self._session_allowlist.get(session_id, set()):
            return True
        if base in self._personal_allowlist:
            return True
        # Also check exact matches from config always_allow list
        always_allow = self._config.get("safety", {}).get("always_allow", [])
        return command.strip() in always_allow or base in always_allow

    def is_always_denied(self, command: str) -> bool:
        """Return True if this command's base is in the always-deny list."""
        return self._base_command(command) in self._always_deny

    # ── Recording decisions ───────────────────────────────────────────────────

    def add_session_allow(self, command: str, session_id: str) -> None:
        """Add command base to the in-memory session allowlist."""
        base = self._base_command(command)
        self._session_allowlist[session_id].add(base)
        log.info("session_allow_added", base=base, session=session_id)

    def add_personal_allow(self, command: str) -> None:
        """Add command base to the persistent personal allowlist."""
        base = self._base_command(command)
        self._personal_allowlist.add(base)
        self._save_personal_allowlist()
        log.info("personal_allow_added", base=base)

    # ── Stats ─────────────────────────────────────────────────────────────────

    def clear_session(self, session_id: str) -> None:
        """Remove all session state for a closed terminal session."""
        self._session_allowlist.pop(session_id, None)

    # ── Persistence ───────────────────────────────────────────────────────────

    def _load_personal_allowlist(self) -> None:
        if _ALLOWLIST_PATH.exists():
            try:
                data = json.loads(_ALLOWLIST_PATH.read_text())
                self._personal_allowlist = set(data.get("allowed", []))
                log.info("personal_allowlist_loaded", count=len(self._personal_allowlist))
            except Exception as e:
                log.warning("allowlist_load_failed", error=str(e))

    def _save_personal_allowlist(self) -> None:
        _ALLOWLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
        _ALLOWLIST_PATH.write_text(
            json.dumps({"allowed": sorted(self._personal_allowlist)}, indent=2)
        )

    @staticmethod
    def _base_command(command: str) -> str:
        """Extract the base command (first non-sudo token)."""
        tokens = command.strip().split()
        if not tokens:
            return ""
        if tokens[0] in {"sudo", "su", "doas", "pkexec"} and len(tokens) > 1:
            # Skip sudo flags like -u, -E
            i = 1
            while i < len(tokens) and tokens[i].startswith("-"):
                i += 1
            return tokens[i] if i < len(tokens) else ""
        return tokens[0]
