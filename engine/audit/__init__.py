"""
Audit Logger — Owner: Harshit
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Appends a JSONL entry to ~/.intent_engine/logs/audit.jsonl for
every user decision (EXECUTE / ABORT / USE_SAFER).

Format per line (newline-delimited JSON):
{
  "timestamp":   "2026-08-16T17:38:00+05:30",
  "command":     "rm -rf /",
  "risk_level":  "CRITICAL",
  "confidence":  1.0,
  "pattern":     "rm_rf_root",
  "tier":        "rule_engine",
  "action":      "ABORT",
  "user":        "harshitdv",
  "cwd":         "/home/harshitdv",
  "session_id":  "109a4aff-...",
  "latency_ms":  0.24
}

The log is append-only and never read by the engine itself.
It exists purely as a human-readable security audit trail.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_LOG_DIR  = Path.home() / ".intent_engine" / "logs"
_LOG_FILE = _LOG_DIR / "audit.jsonl"


def log_decision(
    *,
    command:    str,
    risk_level: str,
    confidence: float,
    pattern:    str | None,
    tier:       str,
    action:     str,           # "EXECUTE" | "ABORT" | "USE_SAFER"
    user:       str = "",
    cwd:        str = "",
    session_id: str = "",
    latency_ms: float = 0.0,
) -> None:
    """
    Append one audit entry to audit.jsonl.
    Silently no-ops on any I/O error so it never breaks the shell hook.
    """
    try:
        _LOG_DIR.mkdir(parents=True, exist_ok=True)
        entry: dict[str, Any] = {
            "timestamp":  datetime.now(tz=timezone.utc).astimezone().isoformat(),
            "command":    command,
            "risk_level": risk_level,
            "confidence": round(confidence, 4),
            "pattern":    pattern,
            "tier":       tier,
            "action":     action,
            "user":       user or os.environ.get("USER", ""),
            "cwd":        cwd  or os.getcwd(),
            "session_id": session_id,
            "latency_ms": round(latency_ms, 3),
        }
        with _LOG_FILE.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")
    except Exception:
        pass  # Audit failure must never disrupt the user's terminal


def tail(n: int = 20) -> list[dict[str, Any]]:
    """Return the last n audit entries as dicts (for tests / CLI)."""
    if not _LOG_FILE.exists():
        return []
    lines = _LOG_FILE.read_text(encoding="utf-8").splitlines()
    entries = []
    for line in lines[-n:]:
        line = line.strip()
        if line:
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return entries
